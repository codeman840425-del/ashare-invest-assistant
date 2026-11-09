# ruff: noqa: S101, ANN401
"""T-B94: disposable local PG only; synthetic users, in-memory sessions, no provider IO."""

from __future__ import annotations

import datetime as dt
import os
import socket
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, insert, select, text, update

from app.aggregates.calendar import seed_calendar
from app.auth.deps import get_engine, get_session_store
from app.auth.sessions import SESSION_COOKIE, Session
from app.config import Settings
from app.db.tables.licences import user_data_licences
from app.db.tables.market import (
    master_runs,
    master_snapshots,
    securities,
    security_code_history,
    security_reconciliation_diffs,
    security_search_terms,
    trading_calendar,
)
from app.db.tables.users import account_reviews, audit_logs, login_attempts, users
from app.db.tables.vendor import master_vendor_batches
from app.main import create_app
from app.reference_files import CalendarReference, load_reference_file

DSN = "postgresql+psycopg://postgres@127.0.0.1:55494/tb94_test"
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch) -> Any:
    if os.environ.get("TB94_ISOLATED_DATABASE_URL") != DSN:
        pytest.skip("requires disposable T-B94 database on dedicated port 55494")
    original = socket.socket.connect
    original_pair = socket.socketpair
    local = threading.local()

    def socketpair(*args: Any, **kwargs: Any) -> Any:
        # Windows asyncio's own self-pipe is a loopback socketpair, not provider IO.
        local.self_pipe = True
        try:
            return original_pair(*args, **kwargs)
        finally:
            local.self_pipe = False

    def connect(sock: Any, address: Any) -> Any:
        assert address[:2] == ("127.0.0.1", 55494) or (
            getattr(local, "self_pipe", False) and address[0] == "127.0.0.1"
        ), "T-B94 denies non-test network"
        return original(sock, address)

    monkeypatch.setattr(socket, "socketpair", socketpair)
    monkeypatch.setattr(socket.socket, "connect", connect)
    engine = create_engine(DSN)
    with engine.connect() as conn:
        assert conn.execute(text("select current_database()")).scalar_one() == "tb94_test"
        assert conn.execute(text("select version_num from alembic_version")).scalar_one() == "0027"
    prefix = "b94_" + uuid.uuid4().hex[:8]
    ids = [uuid.uuid4() for _ in range(4)]
    now = dt.datetime.now(dt.UTC)
    with engine.begin() as conn:
        for index, ident in enumerate(ids):
            conn.execute(
                insert(users).values(
                    id=ident,
                    username=f"{prefix}_{index}",
                    display_name=f"合成用户{index}",
                    role="admin" if index == 0 else "user",
                    status="approved",
                    password_hash=uuid.uuid4().hex,
                    created_at=now,
                )
            )
    sessions = {
        str(ident): Session("synthetic", str(ident), "synthetic-csrf", now.isoformat())
        for ident in ids
    }
    store = SimpleNamespace(get=lambda sid: sessions.get(sid), revoke_user=lambda uid: None)
    settings = Settings(_env_file=None, app_env="test", session_cookie_secure=False)
    app = create_app(settings)
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_session_store] = lambda: store
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, str(ids[0]))
    yield engine, client, ids, prefix, settings
    client.close()
    engine.dispose()


def test_calendar_empty_then_seed_recovers_three_routes_idempotently(
    isolated: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import aggregates
    from app.cli.calendar_seed import main

    engine, client, _, _, _ = isolated
    instant = dt.datetime(2026, 11, 9, 2, tzinfo=dt.UTC)
    monkeypatch.setattr(
        aggregates,
        "dt",
        SimpleNamespace(
            datetime=SimpleNamespace(now=lambda tz: instant),
            UTC=dt.UTC,
        ),
    )
    monkeypatch.setenv("DATABASE_URL", DSN)
    seed = load_reference_file(ROOT / "config", "trading_calendar.json")
    assert isinstance(seed, CalendarReference)
    assert (ROOT / "config/trading_calendar.json").read_bytes() == (
        ROOT / "docs/strategies/calendar/trading_calendar_2026.json"
    ).read_bytes()
    with engine.begin() as conn:
        conn.execute(delete(trading_calendar))
    routes = ("/terminal", "/today", "/market/overview")
    for route in routes:
        response = client.get("/api/v1" + route)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "CALENDAR_NOT_COVERED"
    with engine.begin() as conn:
        assert seed_calendar(conn, seed) == 365
        assert seed_calendar(conn, seed) == 0
    assert main(["--config-dir", str(ROOT / "config"), "--apply"]) == 0
    assert main(["--config-dir", str(ROOT / "config"), "--apply"]) == 0
    for route in routes:
        response = client.get("/api/v1" + route)
        assert response.status_code == 200, response.text
        assert response.json()["trade_date"]
        # Actual market data remains honestly unavailable; calendar seed is not data ingestion.
        assert response.json()["data_status"] in {"partial", "unavailable"}


def test_admin_list_fields_filters_cursor_and_sensitive_projection(isolated: Any) -> None:
    engine, client, ids, prefix, settings = isolated
    now = dt.datetime.now(dt.UTC)
    with engine.begin() as conn:
        for ident in ids:
            conn.execute(
                insert(audit_logs).values(
                    actor_id=ident,
                    actor_role="user",
                    action="auth.register",
                    target_type="user",
                    target_id=str(ident),
                    ip_hash=prefix + "-synthetic-shared-hash",
                    at=now,
                )
            )
        conn.execute(
            insert(account_reviews).values(
                user_id=ids[1],
                action="approve",
                reason="合成审批原因",
                admin_id=ids[0],
            )
        )
        conn.execute(
            insert(login_attempts).values(
                user_id=ids[1],
                success=True,
                at=now,
            )
        )
    response = client.get("/api/v1/admin/users", params={"q": prefix, "limit": 2})
    assert response.status_code == 200, response.text
    first = response.json()
    second = client.get(
        "/api/v1/admin/users",
        params={
            "q": prefix,
            "limit": 2,
            "cursor": first["next_cursor"],
        },
    ).json()
    items = first["items"] + second["items"]
    assert {item["id"] for item in items} == {str(ident) for ident in ids}
    assert len(items) == 4
    assert second["next_cursor"] is None
    item = next(item for item in items if item["id"] == str(ids[1]))
    assert item["review_reason"] == "合成审批原因"
    assert item["last_login_at"] is not None
    assert item["register_ip_region"] is None
    assert item["same_ip_registrations"] == 4
    assert item["same_ip_flag"] == (settings.business.auth.admin.same_ip_highlight_threshold < 4)
    assert set(item) == {
        "id",
        "username",
        "display_name",
        "status",
        "role",
        "apply_note",
        "created_at",
        "register_ip_region",
        "same_ip_registrations",
        "same_ip_flag",
        "review_reason",
        "reviewed_at",
        "last_login_at",
    }
    assert "synthetic-shared-hash" not in response.text
    assert client.get("/api/v1/admin/users", params={"status": "bogus"}).status_code == 400
    assert (
        client.get(
            "/api/v1/admin/users",
            params={
                "q": prefix + "x",
                "cursor": first["next_cursor"],
            },
        ).json()["error"]["code"]
        == "INVALID_CURSOR"
    )
    with engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == ids[1]).values(status="pending"))
    filtered = client.get("/api/v1/admin/users", params={"q": prefix, "status": "pending"}).json()
    assert [item["id"] for item in filtered["items"]] == [str(ids[1])]
    assert client.get("/api/v1/admin/users", params={"q": prefix + "%"}).json()["items"] == []


def seed_master(engine: Any) -> int:
    from sqlalchemy.dialects.postgresql import insert as upsert

    with engine.begin() as conn:
        snapshots = []
        for source, day in [("sse_list", 7), ("szse_list", 6), ("bse_list", 5)]:
            snapshots.append(
                conn.execute(
                    insert(master_snapshots)
                    .values(
                        source=source,
                        url="https://example.invalid/synthetic",
                        fetched_at=dt.datetime.now(dt.UTC),
                        trade_date=dt.date(2026, 11, day),
                        row_count=2,
                        sha256=uuid.uuid4().hex * 2,
                        parse_status="ok",
                    )
                    .returning(master_snapshots.c.id)
                ).scalar_one()
            )
        run = conn.execute(
            insert(master_runs)
            .values(
                trigger="bootstrap",
                status="ok",
                finished_at=dt.datetime.now(dt.UTC),
                snapshot_ids=snapshots,
                stats={
                    "sources": {
                        source: {"status": "ok"} for source in ("sse_list", "szse_list", "bse_list")
                    }
                },
            )
            .returning(master_runs.c.id)
        ).scalar_one()
        for code, name, kind, status in [
            ("600091.SH", "合成甲", "stock", "listed"),
            ("600092.SH", "合成甲乙", "stock", "missing_from_list"),
            ("600093.SH", "合成退", "stock", "delisted"),
            ("920094.BJ", "合成乙", "stock", "listed"),
            ("510094.SH", "合成基金", "etf", "listed"),
            ("000094.SH", "合成指数", "index", "listed"),
        ]:
            stmt = upsert(securities).values(
                code=code,
                name=name,
                type=kind,
                exchange=code[-2:],
                listing_status=status,
                master_source="exchange",
                board="main" if kind == "stock" and code[-2:] == "SH" else None,
            )
            conn.execute(stmt.on_conflict_do_nothing(index_elements=[securities.c.code]))
            conn.execute(delete(security_search_terms).where(security_search_terms.c.code == code))
            conn.execute(
                insert(security_search_terms).values(
                    code=code,
                    term_kind="name",
                    term=name,
                    source_name=name,
                    generator_version=1,
                )
            )
        for code, kind, term, source in [
            ("600091.SH", "name_initials", "HCJ", "合成甲"),
            ("600091.SH", "former_name", "旧合成", "旧合成"),
            ("600091.SH", "former_initials", "JHC", "旧合成"),
            ("920094.BJ", "former_code", "830094", "830094.BJ"),
        ]:
            conn.execute(
                insert(security_search_terms).values(
                    code=code,
                    term_kind=kind,
                    term=term,
                    source_name=source,
                    generator_version=1,
                )
            )
        stmt = upsert(security_code_history).values(
            code="920094.BJ",
            old_code="830094.BJ",
            valid_from=dt.date(2026, 1, 1),
            source="bse_code_map",
        )
        conn.execute(stmt.on_conflict_do_nothing())
    return run


def test_search_contract_normalization_terms_filters_alias_etag(isolated: Any) -> None:
    engine, client, ids, _, _ = isolated
    seed_master(engine)
    route = "/api/v1/securities/search"
    for query in ("600091", "600091.SH", "SH600091", "sh600091", " ｓｈ ６０００９１ "):
        response = client.get(route, params={"q": query})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["master_as_of"] == "2026-11-05"
        assert data["items"][0]["security_code"] == "600091.SH"
        assert data["items"][0]["match_kind"] == "code_exact"
        assert data["items"][0]["quote_missing"] is None
    for query, kind, matched in [
        ("合成甲", "name_exact", None),
        ("hcj", "initials_exact", "合成甲"),
        ("hc", "initials_prefix", "合成甲"),
        ("jhc", "former_name", "旧合成"),
        ("旧合成", "former_name", "旧合成"),
        ("830094", "former_code", "830094.BJ"),
    ]:
        items = client.get(route, params={"q": query}).json()["items"]
        assert items[0]["match_kind"] == kind
        assert items[0]["matched_text"] == matched
        assert len({item["security_code"] for item in items}) == len(items)
    response = client.get(route, params={"q": "合成"})
    items = response.json()["items"]
    assert {item["security_code"] for item in items} == {
        "600091.SH",
        "600092.SH",
        "920094.BJ",
        "510094.SH",
    }
    assert all(item["listing_status"] != "delisted" for item in items)
    assert (
        client.get(
            route,
            params={"q": "合成"},
            headers={
                "If-None-Match": response.headers["ETag"],
            },
        ).status_code
        == 304
    )
    assert response.headers["Cache-Control"] == "private, no-store"
    alias = client.get("/api/v1/securities", params={"q": "合成"}).json()
    assert alias == [
        {"security_code": item["security_code"], "name": item["name"]} for item in items
    ]
    assert len(client.get(route, params={"q": "合成", "limit": 1}).json()["items"]) == 1
    assert client.get(route, params={"q": "600093", "include_delisted": "true"}).json()["items"]
    index = client.get(route, params={"q": "000094.SH", "types": "index"}).json()["items"][0]
    assert index["board"] is None
    assert client.get(route, params={"q": "%"}).json()["items"] == []
    for params in (
        {"q": " "},
        {"q": "x" * 21},
        {"q": "a", "types": "unknown"},
        {"q": "a", "limit": 51},
        {"q": "a", "include_delisted": "bogus"},
        {},
    ):
        failure = client.get(route, params=params)
        assert failure.status_code == 400
        assert failure.json()["error"]["code"] == "VALIDATION_ERROR"
        assert failure.headers["Cache-Control"] == "private, no-store"
    client.cookies.clear()
    assert client.get(route, params={"q": "合成"}).status_code == 401
    client.cookies.set(SESSION_COOKIE, str(ids[1]))
    with engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == ids[1]).values(status="pending"))
    assert client.get(route, params={"q": "合成"}).status_code == 403


@pytest.mark.parametrize(
    "missing_sources",
    [
        ("sse_list", "szse_list", "bse_list"),
        ("bse_list",),
    ],
)
def test_search_missing_bootstrap_returns_500_without_fabricated_date(
    isolated: Any, missing_sources: tuple[str, ...]
) -> None:
    engine, client, _, _, _ = isolated
    seed_master(engine)
    with engine.begin() as conn:
        previous = conn.execute(
            select(master_snapshots.c.id, master_snapshots.c.parse_status).where(
                master_snapshots.c.source.in_(missing_sources)
            )
        ).all()
        conn.execute(
            update(master_snapshots)
            .where(master_snapshots.c.source.in_(missing_sources))
            .values(parse_status="failed")
        )
    try:
        response = client.get("/api/v1/securities/search", params={"q": "600091"})
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "master_as_of" not in response.json()
        assert response.headers["Cache-Control"] == "private, no-store"
    finally:
        with engine.begin() as conn:
            for row in previous:
                conn.execute(
                    update(master_snapshots)
                    .where(master_snapshots.c.id == row.id)
                    .values(parse_status=row.parse_status)
                )


def test_search_rejected_snapshot_preserves_previous_successful_date(isolated: Any) -> None:
    engine, client, _, _, _ = isolated
    seed_master(engine)
    with engine.begin() as conn:
        rejected = conn.execute(
            insert(master_snapshots)
            .values(
                source="bse_list",
                url="https://example.invalid/rejected",
                fetched_at=dt.datetime.now(dt.UTC),
                trade_date=dt.date(2026, 11, 8),
                row_count=0,
                sha256=uuid.uuid4().hex * 2,
                parse_status="rejected",
                reject_reason="empty",
            )
            .returning(master_snapshots.c.id)
        ).scalar_one()
        conn.execute(
            insert(master_runs).values(
                trigger="manual",
                status="partial",
                finished_at=dt.datetime.now(dt.UTC),
                snapshot_ids=[rejected],
                stats={"sources": {"bse_list": {"status": "rejected"}}},
            )
        )
    response = client.get("/api/v1/securities/search", params={"q": "600091"})
    assert response.status_code == 200
    assert response.json()["master_as_of"] == "2026-11-05"


def test_search_quote_missing_uses_own_successful_reconciliation(isolated: Any) -> None:
    engine, client, ids, _, _ = isolated
    run = seed_master(engine)
    licence_id = uuid.uuid4()
    now = dt.datetime.now(dt.UTC)
    with engine.begin() as conn:
        conn.execute(
            insert(user_data_licences).values(
                id=licence_id,
                user_id=ids[0],
                ciphertext=b"synthetic",
                licence_hmac=uuid.uuid4().bytes * 2,
                seal_key_version=1,
                tier="other",
                status="active",
            )
        )
        conn.execute(
            insert(master_vendor_batches).values(
                master_run_id=run,
                source_licence_id=licence_id,
                status="reconciled",
                attempt=1,
                requested_at=now,
                deadline_at=now + dt.timedelta(hours=1),
                fetched_at=now,
                reconciled_at=now,
            )
        )
        conn.execute(
            insert(security_reconciliation_diffs).values(
                kind="quote_missing",
                source="mairui_lists",
                security_code="600091.SH",
                source_licence_id=licence_id,
                first_seen_on=now.date(),
                last_seen_on=now.date(),
                seen_days=1,
                status="open",
            )
        )
    route = "/api/v1/securities/search"
    items = client.get(route, params={"q": "合成"}).json()["items"]
    result = {item["security_code"]: item["quote_missing"] for item in items}
    assert result["600091.SH"] is True
    assert result["600092.SH"] is False
    assert result["510094.SH"] is None
    client.cookies.set(SESSION_COOKIE, str(ids[1]))
    assert all(
        item["quote_missing"] is None
        for item in client.get(
            route,
            params={"q": "合成"},
        ).json()["items"]
    )
    client.cookies.set(SESSION_COOKIE, str(ids[0]))
    with engine.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == licence_id)
            .values(status="paused_by_admin")
        )
    assert all(
        item["quote_missing"] is None
        for item in client.get(
            route,
            params={"q": "合成"},
        ).json()["items"]
    )


def test_admin_list_denies_anonymous_regular_and_disabled_admin(isolated: Any) -> None:
    engine, client, ids, _, _ = isolated
    client.cookies.clear()
    assert client.get("/api/v1/admin/users").status_code == 404
    client.cookies.set(SESSION_COOKIE, str(ids[1]))
    assert client.get("/api/v1/admin/users", params={"status": "bogus"}).status_code == 404
    client.cookies.set(SESSION_COOKIE, str(ids[0]))
    with engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == ids[0]).values(status="disabled"))
    assert client.get("/api/v1/admin/users").status_code == 404
    with engine.connect() as conn:
        assert (
            conn.execute(select(users.c.status).where(users.c.id == ids[0])).scalar_one()
            == "disabled"
        )
