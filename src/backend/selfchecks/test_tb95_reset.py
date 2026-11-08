# ruff: noqa: S101, ANN401
"""T-A52 N1-N10; explicitly provisioned disposable PG, synthetic sessions, no provider IO."""

from __future__ import annotations

import datetime as dt
import os
import socket
import threading
import uuid
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError

from app.auth.deps import get_engine, get_session_store
from app.auth.sessions import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, Session
from app.config import Settings
from app.db.tables.strategy import risk_control_settings as rows
from app.db.tables.strategy import risk_control_settings_history as history
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
    client = TestClient(app)
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
    engine, client, owner, stranger, _ = env
    before = counts(engine, owner)
    client.cookies.clear()
    assert client.delete(URL + "/position_cap").json()["error"]["code"] == "AUTH_REQUIRED"
    assert client.delete(URL + "/nope").status_code == 404
    client.cookies.set(SESSION_COOKIE, str(owner))
    assert client.delete(URL + "/position_cap").json()["error"]["code"] == "CSRF_FAILED"
    client.cookies.set(CSRF_COOKIE, "synthetic-csrf")
    client.headers[CSRF_HEADER] = "wrong-synthetic"
    assert client.delete(URL + "/position_cap").status_code == 403
    client.headers[CSRF_HEADER] = "synthetic-csrf"
    for path in (
        "/position_cap?scope=system",
        "/position_cap?scope=user",
        "/position_cap?user_id=" + str(stranger),
        "/position_cap/system",
        "/nope",
    ):
        assert client.delete(URL + path).status_code == 404
    for body in ({"scope": "system"}, {"user_id": str(stranger)}, {}, None):
        response = client.request(
            "DELETE",
            URL + "/position_cap",
            content="null" if body is None else __import__("json").dumps(body),
        )
        assert response.status_code == 404
    assert client.request("DELETE", URL + "/position_cap", content="{invalid").status_code == 404
    with engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == owner).values(status="pending"))
    response = client.delete(URL + "/position_cap")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_APPROVED"
    assert counts(engine, owner) == before


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


def test_n8_concurrent_put_delete_are_serial_and_atomic(env: Any) -> None:
    engine, client, owner, _, settings = env
    assert client.put(URL, json=patch()).status_code == 200
    barrier = threading.Barrier(2)

    def write(clear: bool) -> Any:
        with engine.begin() as conn:
            barrier.wait(timeout=5)
            if clear:
                return store.reset(
                    conn,
                    owner,
                    "user",
                    settings.business.risk_controls,
                    "position_cap",
                    dt.datetime.now(dt.UTC),
                )
            return store.save(
                conn,
                owner,
                "user",
                settings.business.risk_controls,
                patch("30"),
                dt.datetime.now(dt.UTC),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(write, clear) for clear in (False, True)]
        results = [future.result(timeout=10) for future in futures]
    assert all(len(result) == 6 for result in results)
    result = client.get(URL).json()[1]
    assert (result["source"], result["params"]["single_position_max_pct"]) in {
        ("system", "20"),
        ("user", "30"),
    }
    assert counts(engine, owner) == (3, 3)


def test_migration_roundtrip_preserves_fk_and_append_only(env: Any) -> None:
    engine, client, owner, _, _ = env
    assert client.put(URL, json=patch()).status_code == 200
    assert client.delete(URL + "/position_cap").status_code == 200
    before = counts(engine, owner)
    cfg = migration_config()
    command.downgrade(cfg, "0027")
    with engine.connect() as conn:
        assert not conn.execute(
            text(
                "select exists(select 1 from information_schema.columns "
                "where table_schema='app' and table_name='risk_control_settings' "
                "and column_name='override_active')"
            )
        ).scalar_one()
    command.upgrade(cfg, "head")
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
