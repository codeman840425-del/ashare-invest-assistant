# ruff: noqa: S101, ANN401
"""T-A52 N1-N10; explicitly provisioned disposable PG, synthetic sessions, no provider IO."""

from __future__ import annotations

import datetime as dt
import os
import socket
import threading
import time
import uuid
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError

from app.auth.deps import get_engine, get_session_store
from app.auth.sessions import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, Session
from app.config import Settings
from app.db.migration_check import MigrationLineageError
from app.db.tables.accounts import accounts
from app.db.tables.strategy import risk_control_settings as rows
from app.db.tables.strategy import risk_control_settings_history as history
from app.db.tables.strategy import strategies, strategy_instances, strategy_versions
from app.db.tables.users import audit_logs, user_profiles, users
from app.main import create_app
from app.risk import settings as store
from app.suggestions.risk import effective_config

DSN = "postgresql+psycopg://postgres@127.0.0.1:55495/tb95_test"
ROOT = Path(__file__).resolve().parents[3]
URL = "/api/v1/risk-controls"


def migration_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
    cfg.cmd_opts = Namespace(x=["url=" + DSN])
    return cfg


@pytest.fixture(scope="module")
def database() -> Any:
    if os.environ.get("TB95_ISOLATED_DATABASE_URL") != DSN:
        pytest.skip("requires dedicated disposable T-B95 PostgreSQL on port 55495")
    engine = create_engine(DSN, hide_parameters=True)
    with engine.connect() as conn:
        assert conn.execute(text("select current_database()")).scalar_one() == "tb95_test"
    cfg = migration_config()
    assert ScriptDirectory.from_config(cfg).get_heads() == ["0028"]
    command.upgrade(cfg, "0027")
    marker = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            insert(users).values(
                id=marker,
                username="migration_" + marker.hex[:12],
                password_hash=uuid.uuid4().hex,
                status="approved",
                role="user",
            )
        )
        conn.execute(
            text(
                "insert into app.risk_control_settings(scope,user_id,control,enabled,params) "
                "values ('user',:owner,'position_cap',true,'{\"single_position_max_pct\":\"25\"}')"
            ),
            {"owner": marker},
        )
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(
            select(rows.c.override_active).where(rows.c.user_id == marker)
        ).scalar_one()
    # All overrides are active here: this is the only safe semantic roundtrip.
    command.downgrade(cfg, "0027")
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(
            select(rows.c.override_active).where(rows.c.user_id == marker)
        ).scalar_one()
    yield engine
    engine.dispose()


@pytest.fixture
def env(database: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    original, original_pair = socket.socket.connect, socket.socketpair
    local = threading.local()

    def pair(*args: Any, **kwargs: Any) -> Any:
        local.self_pipe = True
        try:
            return original_pair(*args, **kwargs)
        finally:
            local.self_pipe = False

    def connect(sock: Any, address: Any) -> Any:
        assert address[:2] == ("127.0.0.1", 55495) or (
            getattr(local, "self_pipe", False) and address[0] == "127.0.0.1"
        ), "T-B95 forbids non-test network"
        return original(sock, address)

    monkeypatch.setattr(socket, "socketpair", pair)
    monkeypatch.setattr(socket.socket, "connect", connect)
    ids = [uuid.uuid4(), uuid.uuid4()]
    now = dt.datetime.now(dt.UTC)
    with database.begin() as conn:
        for ident in ids:
            conn.execute(
                insert(users).values(
                    id=ident,
                    username="b95_" + ident.hex[:12],
                    display_name="纯合成用户",
                    password_hash=uuid.uuid4().hex,
                    role="user",
                    status="approved",
                )
            )
    sessions = {
        str(ident): Session("synthetic", str(ident), "synthetic-csrf", now.isoformat())
        for ident in ids
    }
    session_store = SimpleNamespace(
        get=lambda sid: sessions.get(sid),
        revoke_user=lambda uid: None,
    )
    settings = Settings(_env_file=None, app_env="test", session_cookie_secure=False)
    app = create_app(settings)
    app.dependency_overrides[get_engine] = lambda: database
    app.dependency_overrides[get_session_store] = lambda: session_store
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set(SESSION_COOKIE, str(ids[0]))
    client.cookies.set(CSRF_COOKIE, "synthetic-csrf")
    client.headers[CSRF_HEADER] = "synthetic-csrf"
    yield database, client, ids[0], ids[1], settings
    client.close()


def patch(value: str = "25") -> list[dict[str, Any]]:
    return [
        {"control": "position_cap", "enabled": True, "params": {"single_position_max_pct": value}}
    ]


def counts(engine: Any, owner: uuid.UUID) -> tuple[int, int]:
    with engine.connect() as conn:
        return (
            conn.execute(
                select(func.count()).select_from(history).where(history.c.user_id == owner)
            ).scalar_one(),
            conn.execute(
                select(func.count()).select_from(audit_logs).where(audit_logs.c.actor_id == owner)
            ).scalar_one(),
        )


def test_n1_n2_n3_n5_n6_n7_authentication_shape_and_no_side_effects(env: Any) -> None:
    engine, client, owner, stranger, settings = env
    with engine.begin() as conn:
        for ident, value in ((owner, "25"), (stranger, "35")):
            store.save(
                conn,
                ident,
                "user",
                settings.business.risk_controls,
                patch(value),
                dt.datetime.now(dt.UTC),
            )
        system_id = conn.execute(
            insert(rows)
            .values(
                scope="system",
                control="position_cap",
                enabled=True,
                params={"single_position_max_pct": "40"},
            )
            .returning(rows.c.id)
        ).scalar_one()

    def snapshot() -> Any:
        with engine.connect() as conn:
            return tuple(
                conn.execute(select(table).order_by(table.c.id)).all()
                for table in (rows, history, audit_logs)
            )

    before = snapshot()

    def rejected(response: Any, status: int, code: str) -> None:
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert snapshot() == before

    try:
        client.cookies.clear()
        rejected(client.delete(URL + "/position_cap"), 401, "AUTH_REQUIRED")
        rejected(client.delete(URL + "/nope"), 404, "NOT_FOUND")
        client.cookies.set(SESSION_COOKIE, str(owner))
        rejected(client.delete(URL + "/position_cap"), 403, "CSRF_FAILED")
        client.cookies.set(CSRF_COOKIE, "synthetic-csrf")
        client.headers[CSRF_HEADER] = "wrong-synthetic"
        rejected(client.delete(URL + "/position_cap"), 403, "CSRF_FAILED")
        client.headers[CSRF_HEADER] = "synthetic-csrf"
        for path in (
            "/position_cap?scope=system",
            "/position_cap?scope=user",
            "/position_cap?user_id=" + str(stranger),
            "/position_cap/system",
            "/nope",
        ):
            rejected(client.delete(URL + path), 404, "NOT_FOUND")
        for body in ({"scope": "system"}, {"user_id": str(stranger)}, {}, None):
            rejected(
                client.request(
                    "DELETE",
                    URL + "/position_cap",
                    content="null" if body is None else __import__("json").dumps(body),
                ),
                404,
                "NOT_FOUND",
            )
        rejected(
            client.request("DELETE", URL + "/position_cap", content="{invalid"), 404, "NOT_FOUND"
        )
        with engine.begin() as conn:
            conn.execute(update(users).where(users.c.id == owner).values(status="pending"))
        rejected(client.delete(URL + "/position_cap"), 403, "ACCOUNT_NOT_APPROVED")
    finally:
        with engine.begin() as conn:
            conn.execute(rows.delete().where(rows.c.id == system_id))


def test_n4_n9_n10_reset_inheritance_reactivation_and_audit(env: Any) -> None:
    engine, client, owner, stranger, settings = env
    baseline = client.get(URL).json()
    assert client.delete(URL + "/position_cap").json() == baseline
    assert counts(engine, owner) == (0, 0)
    assert client.put(URL, json=patch()).status_code == 200
    # A different user's override is not a target of this endpoint.
    with engine.begin() as conn:
        store.save(
            conn,
            stranger,
            "user",
            settings.business.risk_controls,
            patch("35"),
            dt.datetime.now(dt.UTC),
        )
    first = client.delete(URL + "/position_cap")
    assert first.status_code == 200
    assert len(first.json()) == 6
    assert first.json() == baseline
    assert first.json()[1]["source"] == "system"
    assert client.get(URL).json() == baseline
    with engine.connect() as conn:
        own = conn.execute(select(rows).where(rows.c.user_id == owner)).one()
        assert own.override_active is False
        assert (
            effective_config(
                conn, owner, settings.business.risk_controls
            ).rc2_position_cap.single_position_max_pct
            == 20
        )
        assert (
            effective_config(
                conn, stranger, settings.business.risk_controls
            ).rc2_position_cap.single_position_max_pct
            == 35
        )
        cleared = conn.execute(
            select(history).where(history.c.user_id == owner, history.c.enabled.is_(None))
        ).one()
        audit = conn.execute(
            select(audit_logs).where(
                audit_logs.c.actor_id == owner, audit_logs.c.action == "risk_control.reset"
            )
        ).one()
        assert cleared.setting_id == own.id
        assert cleared.params is None
        assert cleared.changed_by == owner
        assert audit.actor_id == own.user_id
        assert audit.target_id == str(own.id)
        assert audit.detail == {
            "control": "position_cap",
            "history_id": str(cleared.id),
            "had_override": True,
        }
    before = counts(engine, owner)
    assert client.delete(URL + "/position_cap").json() == baseline
    assert counts(engine, owner) == before
    # Even writing the previous retained value must reactivate, not take PUT's same-value shortcut.
    assert client.put(URL, json=patch()).json()[1]["source"] == "user"
    with engine.connect() as conn:
        assert conn.execute(
            select(rows.c.override_active).where(rows.c.user_id == owner)
        ).scalar_one()
    assert client.delete(URL + "/position_cap").status_code == 200
    assert counts(engine, owner) == (4, 4)


def test_n4_n9_system_profile_and_other_controls_are_preserved(env: Any) -> None:
    engine, client, owner, _, settings = env
    now = dt.datetime.now(dt.UTC)
    with engine.begin() as conn:
        system_id = conn.execute(
            insert(rows)
            .values(
                scope="system",
                control="sector_concentration",
                enabled=True,
                params={"sw_l1_max_pct": "45", "concept_max_pct": "55"},
            )
            .returning(rows.c.id)
        ).scalar_one()
        conn.execute(
            insert(user_profiles).values(user_id=owner, version_no=1, max_single_position_pct=17)
        )
        store.save(conn, owner, "user", settings.business.risk_controls, patch(), now)
        store.save(
            conn,
            owner,
            "user",
            settings.business.risk_controls,
            [
                {
                    "control": "sector_concentration",
                    "enabled": True,
                    "params": {"sw_l1_max_pct": "60", "concept_max_pct": "70"},
                }
            ],
            now,
        )
    try:
        before = client.get(URL).json()
        reset = client.delete(URL + "/position_cap").json()
        assert reset[1]["params"]["single_position_max_pct"] == "17"
        assert reset[1]["source"] == "user"
        assert [row for row in reset if row["control"] != "position_cap"] == [
            row for row in before if row["control"] != "position_cap"
        ]
        sector = client.delete(URL + "/sector_concentration").json()[3]
        assert sector["params"] == {"sw_l1_max_pct": "45", "concept_max_pct": "55"}
        assert sector["source"] == "system"
        with engine.connect() as conn:
            assert conn.execute(
                select(rows.c.override_active).where(rows.c.id == system_id)
            ).scalar_one()
            assert (
                effective_config(
                    conn, owner, settings.business.risk_controls
                ).rc2_position_cap.single_position_max_pct
                == 17
            )
    finally:
        # Only the dedicated test's synthetic system fixture is removed, never the API's user reset.
        with engine.begin() as conn:
            conn.execute(rows.delete().where(rows.c.id == system_id))


@pytest.mark.parametrize("holder_clears", [False, True])
def test_n8_advisory_lock_competition_both_orders(env: Any, holder_clears: bool) -> None:
    engine, client, owner, _, settings = env
    assert client.put(URL, json=patch()).status_code == 200
    attempting = threading.Event()
    waiter_pids = []

    def observe(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
    ) -> None:
        if (
            "pg_advisory_xact_lock" in statement
            and threading.current_thread() is not threading.main_thread()
        ):
            waiter_pids.append(cursor.connection.info.backend_pid)
            attempting.set()

    def request() -> Any:
        return (
            client.put(URL, json=patch("30"))
            if holder_clears
            else client.delete(URL + "/position_cap")
        )

    with engine.connect() as holder:
        transaction = holder.begin()
        if holder_clears:
            store.reset(
                holder,
                owner,
                "user",
                settings.business.risk_controls,
                "position_cap",
                dt.datetime.now(dt.UTC),
            )
        else:
            store.save(
                holder,
                owner,
                "user",
                settings.business.risk_controls,
                patch("30"),
                dt.datetime.now(dt.UTC),
            )
        event.listen(engine, "before_cursor_execute", observe)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(request)
                try:
                    assert attempting.wait(timeout=5)
                    deadline = time.monotonic() + 5
                    with engine.connect() as inspector:
                        while time.monotonic() < deadline:
                            waiting = inspector.execute(
                                text(
                                    "SELECT EXISTS (SELECT 1 FROM pg_locks "
                                    "WHERE pid=:pid AND locktype='advisory' AND NOT granted)"
                                ),
                                {"pid": waiter_pids[0]},
                            ).scalar_one()
                            if waiting:
                                break
                            time.sleep(0.01)
                        assert waiting, "request must actually wait for the owner advisory lock"
                    assert not future.done()
                    assert counts(engine, owner) == (1, 1)
                finally:
                    transaction.commit()
                response = future.result(timeout=10)
                assert response.status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", observe)
            if transaction.is_active:
                transaction.rollback()
    result = client.get(URL).json()[1]
    assert (result["source"], result["params"]["single_position_max_pct"]) == (
        ("user", "30") if holder_clears else ("system", "20")
    )
    assert counts(engine, owner) == (3, 3)


def test_migration_refuses_cleared_override_loss_and_preserves_fk(env: Any) -> None:
    engine, client, owner, _, _ = env
    assert client.put(URL, json=patch()).status_code == 200
    assert client.delete(URL + "/position_cap").status_code == 200
    before = counts(engine, owner)
    cfg = migration_config()
    baseline = client.get(URL).json()
    with pytest.raises(MigrationLineageError, match="UNSAFE_DOWNGRADE_0028"):
        command.downgrade(cfg, "0027")
    assert client.get(URL).json() == baseline
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
            == "0028"
        )
        assert (
            conn.execute(select(rows.c.override_active).where(rows.c.user_id == owner)).scalar_one()
            is False
        )
    cfg.output_buffer = StringIO()
    with pytest.raises(MigrationLineageError, match="offline SQL"):
        command.downgrade(cfg, "0028:0027", sql=True)
    assert "DROP COLUMN" not in cfg.output_buffer.getvalue()
    assert counts(engine, owner) == before
    with engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "select count(*) from pg_constraint "
                    "where conrelid='app.risk_control_settings_history'::regclass and contype='f'"
                )
            ).scalar_one()
            >= 2
        )
    for operation in (
        history.update().where(history.c.user_id == owner).values(enabled=True),
        history.delete().where(history.c.user_id == owner),
    ):
        with pytest.raises(DBAPIError), engine.begin() as conn:
            conn.execute(operation)


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
@pytest.mark.parametrize("sqlstate", ["40001", "40P01", "23514"])
def test_request_conflicts_rollback_without_masking_other_db_errors(
    env: Any, monkeypatch: pytest.MonkeyPatch, method: str, sqlstate: str
) -> None:
    engine, client, owner, _, _ = env
    assert client.put(URL, json=patch()).status_code == 200
    baseline, before = client.get(URL).json(), counts(engine, owner)
    name = "save" if method == "PUT" else "reset"
    original = getattr(store, name)

    def fail_after_write(*args: Any, **kwargs: Any) -> Any:
        original(*args, **kwargs)
        # Actual PostgreSQL failure after setting/history/audit writes.
        args[0].execute(
            text(
                "DO $$ BEGIN RAISE EXCEPTION 'synthetic database failure' "
                "USING ERRCODE='" + sqlstate + "'; END $$"
            )
        )

    monkeypatch.setattr(store, name, fail_after_write)

    def request() -> Any:
        return (
            client.put(URL, json=patch("30"))
            if method == "PUT"
            else client.delete(URL + "/position_cap")
        )

    response = request()
    conflict = sqlstate in {"40001", "40P01"}
    assert response.status_code == (409 if conflict else 500)
    assert response.json()["error"]["code"] == ("CONFLICT" if conflict else "INTERNAL_ERROR")
    assert "synthetic database failure" not in response.text
    assert sqlstate not in response.text
    assert client.get(URL).json() == baseline
    assert counts(engine, owner) == before
    monkeypatch.setattr(store, name, original)
    assert request().status_code == 200
    assert counts(engine, owner) == (before[0] + 1, before[1] + 1)


@pytest.mark.parametrize("inheritance", ["file", "system", "profile"])
@pytest.mark.parametrize("inherited_stop_enabled", [True, False])
def test_reset_then_create_request_freezes_effective_controls(
    env: Any, inheritance: str, inherited_stop_enabled: bool
) -> None:
    engine, client, owner, stranger, settings = env
    account_id = str(uuid.uuid4())
    strategy_id, version_id = uuid.uuid4(), uuid.uuid4()
    system_ids = []
    with engine.begin() as conn:
        conn.execute(
            insert(accounts).values(id=uuid.UUID(account_id), user_id=owner, name="synthetic-b98")
        )
        conn.execute(
            insert(strategies).values(
                id=strategy_id,
                key="b98_" + strategy_id.hex,
                name="Synthetic risk snapshot",
                horizons=["swing"],
            )
        )
        conn.execute(
            insert(strategy_versions).values(
                id=version_id,
                strategy_id=strategy_id,
                version_no=1,
                lifecycle="published",
                config_hash="synthetic-b98",
                config={"horizons": ["swing"]},
            )
        )
        if inheritance == "system":
            system_ids.append(
                conn.execute(
                    insert(rows)
                    .values(
                        scope="system",
                        control="position_cap",
                        enabled=True,
                        params={"single_position_max_pct": "40"},
                    )
                    .returning(rows.c.id)
                ).scalar_one()
            )
        if inheritance == "profile":
            conn.execute(
                insert(user_profiles).values(
                    user_id=owner, version_no=1, max_single_position_pct=17
                )
            )
        if not inherited_stop_enabled:
            system_ids.append(
                conn.execute(
                    insert(rows)
                    .values(scope="system", control="stop_take", enabled=False, params={})
                    .returning(rows.c.id)
                ).scalar_one()
            )
        store.save(
            conn,
            stranger,
            "user",
            settings.business.risk_controls,
            patch("35"),
            dt.datetime.now(dt.UTC),
        )

    body = {
        "strategy_version_id": str(version_id),
        "account_id": account_id,
        "scope": "account",
        "horizon": "swing",
    }

    def create_and_check(position: str, stop_enabled: bool) -> tuple[str, Any]:
        response = client.post("/api/v1/strategy-instances", json=body)
        assert response.status_code == 201, response.text
        identifier = response.json()["id"]
        current = client.get(URL)
        assert current.status_code == 200
        expected = {
            item["control"]: {"enabled": item["enabled"], "params": item["params"]}
            for item in current.json()
        }
        with engine.connect() as conn:
            snapshot = conn.execute(
                select(strategy_instances.c.risk_settings_snapshot).where(
                    strategy_instances.c.id == uuid.UUID(identifier)
                )
            ).scalar_one()
        # Canonicalize decimals only, matching the GET contract rather than the implementation.
        assert store.canonical(snapshot["controls"]) == expected
        assert expected["position_cap"]["params"]["single_position_max_pct"] == position
        assert expected["stop_take"]["enabled"] is stop_enabled
        assert any("RC1" in message for message in response.json()["warnings"]) is (
            not stop_enabled
        )
        assert client.get(f"/api/v1/strategy-instances/{identifier}").status_code == 200
        return identifier, snapshot

    try:
        inherited = client.get(URL).json()
        changes = [
            {"control": item["control"], "enabled": not item["enabled"], "params": item["params"]}
            for item in inherited
        ]
        # GET also exposes the read-only horizon map; PUT accepts its documented fields only.
        changes[4]["params"] = {
            key: value
            for key, value in changes[4]["params"].items()
            if key != "sim_fail_horizon_by_horizon"
        }
        changes[1]["params"] = {"single_position_max_pct": "25"}
        write_response = client.put(URL, json=changes)
        assert write_response.status_code == 200, write_response.text
        prior_id, prior_snapshot = create_and_check("25", not inherited_stop_enabled)
        for item in inherited:
            assert client.delete(URL + "/" + item["control"]).status_code == 200
        expected_position = {"file": "20", "system": "40", "profile": "17"}[inheritance]
        new_id, _ = create_and_check(expected_position, inherited_stop_enabled)
        with engine.connect() as conn:
            assert (
                conn.execute(
                    select(strategy_instances.c.risk_settings_snapshot).where(
                        strategy_instances.c.id == uuid.UUID(prior_id)
                    )
                ).scalar_one()
                == prior_snapshot
            )
            assert (
                conn.execute(select(rows.c.override_active).where(rows.c.user_id == owner))
                .scalars()
                .all()
                == [False] * 6
            )
            assert (
                effective_config(
                    conn, stranger, settings.business.risk_controls
                ).rc2_position_cap.single_position_max_pct
                == 35
            )
        write_response = client.put(URL, json=changes)
        assert write_response.status_code == 200, write_response.text
        create_and_check("25", not inherited_stop_enabled)
        client.cookies.set(SESSION_COOKIE, str(stranger))
        denied = client.post("/api/v1/strategy-instances", json=body)
        assert denied.status_code == 404
        assert denied.json()["error"]["code"] == "NOT_FOUND"
        assert client.get(f"/api/v1/strategy-instances/{new_id}").status_code == 404
    finally:
        with engine.begin() as conn:
            if system_ids:
                conn.execute(rows.delete().where(rows.c.id.in_(system_ids)))
