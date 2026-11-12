"""B-04 registered ASGI route, real auth dependency and isolated synthetic source checks."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.auth import deps
from app.auth.sessions import SESSION_COOKIE, Session
from app.config import ConfigError, Settings
from app.main import create_app
from app.marketdata.bars_read import get_bars_reader
from selfchecks.b03_shapes import validate
from selfchecks.b04_source import SYNTHETIC_CODE, install_fixture_reader

PATH = f"/api/v1/securities/{SYNTHETIC_CODE}/bars"
QUERY = "?freq=d&adjust=none"


class MemorySessions:
    def __init__(self, sessions: dict[str, Session]) -> None:
        self.sessions = sessions
        self.revoked: list[str] = []
        self.deleted: list[Session] = []

    def get(self, sid: str | None) -> Session | None:
        return self.sessions.get(sid or "")

    def revoke_user(self, uid: str) -> int:
        self.revoked.append(uid)
        return 1

    def delete(self, session: Session) -> None:
        self.deleted.append(session)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    owners = {key: uuid.uuid4() for key in ("a", "b", "p", "blocked", "gone")}
    sessions = MemorySessions(
        {
            key: Session("synthetic", str(owner), "synthetic", "2026-11-02T00:00:00+00:00")
            for key, owner in owners.items()
        }
    )
    records = {
        str(owner): SimpleNamespace(id=owner, status="pending" if key == "blocked" else "approved")
        for key, owner in owners.items()
        if key != "gone"
    }
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=None,
        redis_url=None,
        session_cookie_secure=False,
    )
    app = create_app(settings)
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.begin() as conn:
        conn.execute(text("ATTACH DATABASE ':memory:' AS market"))
        conn.execute(text("CREATE TABLE market.securities (code TEXT PRIMARY KEY, name TEXT)"))
        conn.execute(text("CREATE TABLE market.security_code_history (code TEXT, old_code TEXT)"))
        conn.execute(
            text("INSERT INTO market.securities VALUES (:code, :name)"),
            {"code": SYNTHETIC_CODE, "name": "合成示例股份"},
        )
        conn.execute(
            text("INSERT INTO market.security_code_history VALUES (:code, :old)"),
            {"code": SYNTHETIC_CODE, "old": "999998.BJ"},
        )
    app.dependency_overrides[deps.get_engine] = lambda: engine
    app.dependency_overrides[deps.get_session_store] = lambda: sessions
    monkeypatch.setattr(deps, "load_user", lambda _engine, uid: records.get(uid))
    reader = install_fixture_reader(app, {owners["a"]: "stock", owners["p"]: "pending"})
    client = TestClient(app, raise_server_exceptions=True)
    client.cookies.set(SESSION_COOKIE, "a")
    yield SimpleNamespace(
        app=app,
        client=client,
        owners=owners,
        sessions=sessions,
        reader=reader,
        settings=settings,
    )
    client.close()
    engine.dispose()


def test_b04_registered_http_shape_and_data_times(env: Any) -> None:
    response = env.client.get(PATH + QUERY)
    assert response.status_code == 200
    body = response.json()
    validate("bars", body, set())
    assert [row["t"] for row in body["items"]] == ["2026-11-02", "2026-11-03"]
    assert body["items"][0]["open"] == "10.00"
    assert body["data_as_of"] == "2026-11-02T15:00:00+08:00"
    assert "sources" not in body
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["etag"].startswith('W/"')
    assert PATH.replace(SYNTHETIC_CODE, "{code}") in env.app.openapi()["paths"]


@pytest.mark.parametrize(
    ("sid", "status", "code"),
    [
        (None, 401, "AUTH_REQUIRED"),
        ("expired", 401, "AUTH_REQUIRED"),
        ("gone", 401, "AUTH_REQUIRED"),
        ("blocked", 403, "ACCOUNT_NOT_APPROVED"),
    ],
)
def test_b04_auth_before_parameters_and_reader(
    env: Any,
    monkeypatch: pytest.MonkeyPatch,
    sid: str | None,
    status: int,
    code: str,
) -> None:
    def forbidden_read(*_args: Any) -> None:
        pytest.fail("unauthenticated request reached the bars source")

    monkeypatch.setattr(env.reader, "read", forbidden_read)
    env.client.cookies.clear()
    if sid:
        env.client.cookies.set(SESSION_COOKIE, sid)
    response = env.client.get(PATH + "?freq=bad&limit=0")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-request-id"]
    if sid == "blocked":
        assert env.sessions.revoked == [str(env.owners["blocked"])]
    if sid == "gone":
        assert len(env.sessions.deleted) == 1


@pytest.mark.parametrize("code", ["999997.SH", "999999", "999998.BJ"])
def test_b04_fixture_unknown_security_404(env: Any, code: str) -> None:
    response = env.client.get(PATH.replace(SYNTHETIC_CODE, code) + QUERY)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "?freq=bad",
        "?freq=d&adjust=bad",
        "?freq=1m&adjust=qfq",
        "?freq=d&limit=0",
        "?freq=d&limit=2001",
        "?freq=d&limit=x",
        "?freq=d&limit=-1",
        "?freq=d&limit=1.5",
        "?freq=d&limit=" + "9" * 5000,
        "?freq=d&from=2026-11-03&to=2026-11-02",
        "?freq=d&from=2026-02-30",
        "?freq=d&from=20261102",
        "?freq=d&before=2026-11-03&from=2026-11-02",
        "?freq=d&before=bad",
        "?freq=1m&before=2026-11-03T09:31:00",
        "?freq=d&limit=1&limit=2",
        "?freq=d&freq=w",
    ],
)
def test_b04_invalid_query_400(env: Any, suffix: str) -> None:
    response = env.client.get(PATH + suffix)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.headers["cache-control"] == "private, no-store"


def test_b04_owner_scope_no_fallback_or_spoofed_owner(env: Any) -> None:
    first = env.client.get(PATH + QUERY)
    env.client.cookies.set(SESSION_COOKIE, "b")
    response = env.client.get(
        PATH + QUERY + "&user_id=" + str(env.owners["a"]),
        headers={"If-None-Match": first.headers["etag"]},
    )
    assert response.status_code == 200
    body = response.json()
    validate("bars", body, set())
    assert body["items"] == []
    assert body["data_as_of"] is None
    assert body["data_status"] == "unavailable"
    assert body["gaps"][0]["reason"] == "data_licence_unavailable"
    assert response.headers["etag"] != first.headers["etag"]


def test_b04_pending_preserves_null_without_queue_writes(env: Any) -> None:
    env.client.cookies.set(SESSION_COOKIE, "p")
    for _ in range(2):
        response = env.client.get(PATH + QUERY)
        body = response.json()
        validate("bars", body, set())
        assert response.status_code == 200
        assert body["data_status"] == "pending"
        assert body["items"] == []
        assert body["data_as_of"] is None
        assert body["gaps"][0]["reason"] == "quota_deferred"


def test_b04_pagination_no_duplicates_and_inclusive_dates(env: Any) -> None:
    first = env.client.get(PATH + QUERY + "&limit=1").json()
    assert [row["t"] for row in first["items"]] == ["2026-11-03"]
    assert first["next_before"] == "2026-11-03"
    second = env.client.get(PATH + QUERY + "&limit=1&before=" + first["next_before"]).json()
    assert [row["t"] for row in second["items"]] == ["2026-11-02"]
    assert second["next_before"] is None
    for body in (first, second):
        validate("bars", body, set())
    bounded = env.client.get(PATH + QUERY + "&from=2026-11-02&to=2026-11-02").json()
    assert bounded["items"] == second["items"]
    empty = env.client.get(PATH + QUERY + "&before=2026-11-02").json()
    assert empty["items"] == []
    assert empty["data_as_of"] is None
    assert env.client.get(PATH + QUERY).json()["items"] != first["items"]


def test_b04_etag_304_keeps_private_no_store(env: Any) -> None:
    first = env.client.get(PATH + QUERY)
    cached = env.client.get(PATH + QUERY, headers={"If-None-Match": first.headers["etag"]})
    assert cached.status_code == 304
    assert cached.content == b""
    assert cached.headers["cache-control"] == "private, no-store"
    env.client.cookies.clear()
    denied = env.client.get(PATH + QUERY, headers={"If-None-Match": first.headers["etag"]})
    assert denied.status_code == 401


@pytest.mark.parametrize("query", ["?freq=d", "?freq=w", "?freq=1m", "?freq=d&adjust=hfq"])
def test_b04_unconnected_modes_never_relabel_unadjusted_data(env: Any, query: str) -> None:
    response = env.client.get(PATH + query)
    assert response.status_code == 200
    body = response.json()
    validate("bars", body, set())
    assert body["items"] == []
    assert body["data_as_of"] is None
    assert body["data_status"] == "unavailable"
    assert body["gaps"][0]["reason"] == "no_source"
    assert body["adjust"] == (
        "none" if body["freq"] == "1m" else ("hfq" if "hfq" in query else "qfq")
    )


@pytest.mark.parametrize("mode", ["staging", "production"])
def test_b04_fixture_install_refused_outside_local_test(env: Any, mode: str) -> None:
    env.app.state.settings = env.settings.model_copy(update={"app_env": mode})
    with pytest.raises(ConfigError, match="local/test"):
        install_fixture_reader(env.app, {env.owners["a"]: "stock"})


def test_b04_default_source_only_reads_public_identity(env: Any) -> None:
    del env.app.dependency_overrides[get_bars_reader]
    response = env.client.get(PATH + QUERY)
    assert response.status_code == 200
    body = response.json()
    validate("bars", body, set())
    assert body["name"] == "合成示例股份"
    assert body["items"] == []
    assert body["data_as_of"] is None
    assert body["gaps"][0]["reason"] == "no_source"
    missing = env.client.get(PATH.replace(SYNTHETIC_CODE, "999997.SH") + QUERY)
    assert missing.status_code == 404
    old = env.client.get(PATH.replace(SYNTHETIC_CODE, "999998.BJ") + QUERY)
    assert old.status_code == 404
    assert old.json()["error"]["details"] == {"superseded_by": SYNTHETIC_CODE}
