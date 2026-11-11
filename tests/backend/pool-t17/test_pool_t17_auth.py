"""Pool T-17: real auth/owner gates; synthetic memory storage, no external DB.

A01/A02/A03/A08 are HTTP auth evidence. A04 covers portfolio accounts only.
A05 checks real account SQL scope, not portfolio aggregation. A06/A07 and
candidate/report ownership await their own storage adapters. No auth override.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1 import accounts as account_api
from app.api.v1 import admin, aggregates, auth, portfolio, securities
from app.auth import deps
from app.auth.sessions import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, Session
from app.common.errors import install_exception_handlers
from app.config import Settings, get_settings
from app.db.tables.accounts import accounts
from app.db.tables.users import users
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, create_engine, event, insert
from sqlalchemy.pool import StaticPool


class MemorySessions:
    """Only synthetic in-memory handles; no Redis TTL simulation claim."""

    def __init__(self, identities):
        self.records = {
            name: Session(name, str(uid), "pool-synthetic-csrf", "2026-11-11T00:00:00Z")
            for name, uid in identities.items()
        }
        self.deleted = []
        self.revoked = []

    def get(self, handle):
        return self.records.get(handle)

    def delete(self, session):
        self.deleted.append(session.user_id)
        self.records = {k: v for k, v in self.records.items() if v != session}

    def revoke_user(self, uid):
        self.revoked.append(uid)
        before = len(self.records)
        self.records = {k: v for k, v in self.records.items() if v.user_id != uid}
        return before - len(self.records)


@pytest.fixture
def harness(monkeypatch):
    # Copy column storage types only: no PostgreSQL DDL/check/default emulation.
    # Queries, UUID binding, owner predicates and filtering remain production SQL.
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.begin() as conn:
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS app")
    memory = MetaData()
    tables = {}
    for source in (users, accounts):
        tables[source.name] = Table(
            source.name,
            memory,
            *(Column(c.name, c.type, nullable=True) for c in source.columns),
            schema="app",
        )
    memory.create_all(engine)
    ids = {
        k: uuid.uuid4()
        for k in (
            "a",
            "b",
            "pending",
            "rejected",
            "disabled",
            "gone",
            "deleted",
            "admin",
        )
    }
    account_ids = {k: uuid.uuid4() for k in ("a", "b", "archived")}
    now = dt.datetime(2026, 11, 11, tzinfo=dt.UTC)
    with engine.begin() as conn:
        for name, uid in ids.items():
            if name == "gone":
                continue
            conn.execute(
                insert(tables["users"]).values(
                    id=uid,
                    username="pool_" + name,
                    password_hash="synthetic-unused",
                    status=name
                    if name in {"pending", "rejected", "disabled"}
                    else "approved",
                    role="admin" if name == "admin" else "user",
                    deleted_at=now if name == "deleted" else None,
                    created_at=now,
                )
            )
        for name, aid in account_ids.items():
            conn.execute(
                insert(tables["accounts"]).values(
                    id=aid,
                    user_id=ids["b"] if name == "b" else ids["a"],
                    name="pool_" + name,
                    created_at=now,
                    archived_at=now if name == "archived" else None,
                )
            )
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def observe(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    sessions = MemorySessions(ids)
    settings = Settings(
        _env_file=None, app_env="test", database_url=None, redis_url=None
    )
    app = FastAPI()
    app.state.settings = settings
    install_exception_handlers(app)
    for router in (aggregates.router, securities.router, portfolio.router, auth.router):
        app.include_router(router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.dependency_overrides.update(
        {
            deps.get_engine: lambda: engine,
            deps.get_session_store: lambda: sessions,
            get_settings: lambda: settings,
            # A sentinel resource: any actual Redis operation fails immediately.
            deps.get_redis: lambda: object(),
        }
    )
    reached = []

    def forbidden(*_args, **_kwargs):
        reached.append("producer")
        pytest.fail("denied request reached a data producer")

    monkeypatch.setattr(aggregates, "market_clock", forbidden)
    monkeypatch.setattr(securities, "profile", forbidden)
    monkeypatch.setattr(portfolio, "build_portfolio", forbidden)
    monkeypatch.setattr(admin.ingest_status, "build", forbidden)
    monkeypatch.setattr(auth.service, "audit", forbidden)
    client = TestClient(app)
    try:
        yield SimpleNamespace(
            app=app,
            client=client,
            sessions=sessions,
            ids=ids,
            accounts=account_ids,
            engine=engine,
            statements=statements,
            reached=reached,
        )
    finally:
        client.close()
        engine.dispose()


def select_user(h, name):
    h.client.cookies.clear()
    if name is not None:
        h.client.cookies.set(SESSION_COOKIE, name)


def assert_error(response, status, code):
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


READS = ("/market/overview", "/securities/999999.SH", "/portfolio")


@pytest.mark.parametrize("path", READS)
@pytest.mark.parametrize("identity", [None, "expired", "gone", "deleted"])
def test_pool_t17_missing_session_or_user(harness, path, identity):
    h = harness
    select_user(h, identity)
    response = h.client.get("/api/v1" + path)
    assert_error(response, 401, "AUTH_REQUIRED")
    assert h.reached == []
    assert h.sessions.deleted == (
        [str(h.ids[identity])] if identity in {"gone", "deleted"} else []
    )
    assert h.sessions.revoked == []
    # Unknown handles represent store-rejected sessions, not Redis TTL proof.
    assert len(h.statements) == (1 if identity in {"gone", "deleted"} else 0)


@pytest.mark.parametrize("path", READS)
@pytest.mark.parametrize("identity", ["pending", "rejected", "disabled"])
def test_pool_t17_unapproved_revokes(harness, path, identity):
    h = harness
    select_user(h, identity)
    response = h.client.get("/api/v1" + path)
    assert_error(response, 403, "ACCOUNT_NOT_APPROVED")
    assert response.json()["error"]["details"]["status"] == identity
    assert h.sessions.revoked == [str(h.ids[identity])]
    assert identity not in h.sessions.records
    assert h.sessions.deleted == []
    assert h.reached == []
    assert_error(h.client.get("/api/v1" + path), 401, "AUTH_REQUIRED")


@pytest.mark.parametrize(
    "identity", [None, "expired", "a", "pending", "rejected", "disabled", "gone"]
)
def test_pool_t17_admin_hides_denied(harness, identity):
    select_user(harness, identity)
    assert_error(harness.client.get("/api/v1/admin/ingest/status"), 404, "NOT_FOUND")
    assert harness.reached == []
    assert harness.sessions.deleted == harness.sessions.revoked == []


@pytest.mark.parametrize("csrf", ["missing", "header-only", "cookie-only", "mismatch"])
def test_pool_t17_logout_requires_csrf(harness, csrf):
    h = harness
    select_user(h, "a")
    headers = {}
    if csrf in {"header-only", "mismatch"}:
        headers[CSRF_HEADER] = "pool-synthetic-csrf"
    if csrf in {"cookie-only", "mismatch"}:
        h.client.cookies.set(
            CSRF_COOKIE, "wrong" if csrf == "mismatch" else "pool-synthetic-csrf"
        )
    assert_error(
        h.client.post("/api/v1/auth/logout", headers=headers), 403, "CSRF_FAILED"
    )
    assert h.sessions.deleted == h.sessions.revoked == []
    assert "a" in h.sessions.records
    assert h.reached == []


@pytest.mark.parametrize("target", ["b", "missing", "archived"])
def test_pool_t17_portfolio_owner_rejects(harness, target):
    h = harness
    select_user(h, "a")
    aid = uuid.uuid4() if target == "missing" else h.accounts[target]
    response = h.client.get(
        "/api/v1/portfolio", params={"account_id": str(aid), "user_id": str(h.ids["b"])}
    )
    assert_error(response, 404, "NOT_FOUND")
    assert h.reached == []
    assert h.sessions.deleted == h.sessions.revoked == []
    sql = h.statements[-1]
    assert "accounts.id =" in sql and "accounts.user_id =" in sql
    assert "accounts.archived_at IS NULL" in sql


@pytest.mark.parametrize("owner", ["a", "b"])
def test_pool_t17_real_owner_query_positive(harness, owner):
    h = harness
    user = deps.load_user(h.engine, str(h.ids[owner]))
    context = deps.AuthContext(user, h.sessions.records[owner])
    with h.engine.connect() as conn:
        row = account_api.owned_account(conn, context, h.accounts[owner])
        assert row.id == h.accounts[owner] and row.user_id == h.ids[owner]
        assert account_api.user_account_ids(conn, context) == [h.accounts[owner]]
    assert h.reached == []


def test_pool_t17_logout_valid_csrf_reaches_audit(harness):
    h = harness
    select_user(h, "a")
    h.client.cookies.set(CSRF_COOKIE, "pool-synthetic-csrf")
    with pytest.raises(pytest.fail.Exception, match="data producer"):
        h.client.post(
            "/api/v1/auth/logout", headers={CSRF_HEADER: "pool-synthetic-csrf"}
        )
    assert h.sessions.deleted == [str(h.ids["a"])]
    assert "a" not in h.sessions.records
    assert h.reached == ["producer"]


def test_pool_t17_real_auth_and_admin_positive(harness):
    # Positive controls stop at the producer sentinel, proving both real auth
    # dependencies can admit approved users rather than every request being denied.
    select_user(harness, "a")
    with pytest.raises(pytest.fail.Exception, match="data producer"):
        harness.client.get("/api/v1/securities/999999.SH")
    select_user(harness, "admin")
    with pytest.raises(pytest.fail.Exception, match="data producer"):
        harness.client.get("/api/v1/admin/ingest/status")
    assert harness.reached == ["producer", "producer"]
    assert deps.current_auth not in harness.app.dependency_overrides
    assert deps.current_admin not in harness.app.dependency_overrides
