"""Reusable B-05 in-memory auth/identity environment and explicitly installed fixture port."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.auth import deps
from app.auth.sessions import SESSION_COOKIE, Session
from app.common.errors import AppError, ErrorCode
from app.config import ConfigError, Settings
from app.main import create_app
from selfchecks.b03_shapes import validate

STOCK = "999999.SH"
ETF = "510300.SH"
INDEX = "000001.SH"
OLD = "999998.BJ"
Transform = Callable[[dict[str, Any], Any], dict[str, Any]]


class MemorySessions:
    def __init__(self, owners: dict[str, uuid.UUID]) -> None:
        self.sessions = {
            key: Session("synthetic", str(uid), "synthetic", "2026-11-02T00:00:00+00:00")
            for key, uid in owners.items()
        }
        self.revoked: list[str] = []
        self.deleted: list[Session] = []

    def get(self, sid: str | None) -> Session | None:
        return self.sessions.get(sid or "")

    def revoke_user(self, uid: str) -> int:
        self.revoked.append(uid)
        return 1

    def delete(self, session: Session) -> None:
        self.deleted.append(session)


class FixtureReader:
    def __init__(self, resource: str, owner: uuid.UUID, transform: Transform) -> None:
        self.resource = resource
        self.owner = owner
        self.transform = transform
        path = Path(__file__).parent / "fixtures/b03" / (resource + ".json")
        self.bundle = json.loads(path.read_text(encoding="utf-8"))
        for scenario in self.bundle.values():
            validate(resource, scenario["response"], set())

    def read(self, owner: uuid.UUID, code: str, query: Any) -> dict[str, Any]:
        case = {STOCK: "stock", ETF: "etf", INDEX: "index"}.get(code)
        if case is None:
            raise AppError(ErrorCode.NOT_FOUND)
        if case == "index" and "index" not in self.bundle:
            case = "licence_unavailable"
        if case == "stock" and owner != self.owner:
            case = "licence_unavailable"
        result = self.transform(deepcopy(self.bundle[case]["response"]), query)
        validate(self.resource, result, set())
        return result


def install_fixture_reader(
    app: FastAPI,
    dependency: Callable[..., Any],
    reader: FixtureReader,
) -> None:
    if app.state.settings.app_env not in {"local", "test"}:
        raise ConfigError("synthetic subresources are restricted to explicit local/test selfchecks")
    app.dependency_overrides[dependency] = lambda: reader


def empty_window(body: dict[str, Any]) -> dict[str, Any]:
    if not body["items"]:
        body["data_as_of"] = None
        body["sources"] = []
        if body["data_status"] not in {"pending", "unavailable"}:
            body["data_status"] = "unavailable"
            body["gaps"] = [{"key": "window", "reason": "no_source", "message": "合成区间无数据"}]
    return body


@contextmanager
def environment(
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
    dependency: Callable[..., Any],
    transform: Transform,
) -> Iterator[Any]:
    owners = {key: uuid.uuid4() for key in ("a", "b", "blocked", "gone")}
    sessions = MemorySessions(owners)
    users = {
        str(uid): SimpleNamespace(id=uid, status="pending" if key == "blocked" else "approved")
        for key, uid in owners.items()
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
        conn.execute(
            text("CREATE TABLE market.securities (code TEXT PRIMARY KEY, name TEXT, type TEXT)")
        )
        conn.execute(text("CREATE TABLE market.security_code_history (code TEXT, old_code TEXT)"))
        for code, name, kind in (
            (STOCK, "合成股份", "stock"),
            (ETF, "合成ETF", "etf"),
            (INDEX, "合成指数", "index"),
        ):
            conn.execute(
                text("INSERT INTO market.securities VALUES (:c, :n, :t)"),
                {"c": code, "n": name, "t": kind},
            )
        conn.execute(
            text("INSERT INTO market.security_code_history VALUES (:c, :o)"), {"c": STOCK, "o": OLD}
        )
    app.dependency_overrides[deps.get_engine] = lambda: engine
    app.dependency_overrides[deps.get_session_store] = lambda: sessions
    monkeypatch.setattr(deps, "load_user", lambda _engine, uid: users.get(uid))
    reader = FixtureReader(resource, owners["a"], transform)
    install_fixture_reader(app, dependency, reader)
    client = TestClient(app, raise_server_exceptions=True)
    client.cookies.set(SESSION_COOKIE, "a")
    try:
        yield SimpleNamespace(
            app=app,
            client=client,
            reader=reader,
            owners=owners,
            sessions=sessions,
            settings=settings,
            dependency=dependency,
            resource=resource,
            path=f"/api/v1/securities/{STOCK}/{resource}",
        )
    finally:
        client.close()
        engine.dispose()


def check_access(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    original = env.reader.read

    def forbidden(*_args: Any) -> None:
        pytest.fail("denied request reached the fixture reader")

    monkeypatch.setattr(env.reader, "read", forbidden)
    for sid, status, code in (
        (None, 401, "AUTH_REQUIRED"),
        ("expired", 401, "AUTH_REQUIRED"),
        ("gone", 401, "AUTH_REQUIRED"),
        ("blocked", 403, "ACCOUNT_NOT_APPROVED"),
    ):
        env.client.cookies.clear()
        if sid:
            env.client.cookies.set(SESSION_COOKIE, sid)
        response = env.client.get(env.path + "?limit=0")
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert response.headers["cache-control"] == "private, no-store"
    assert env.sessions.revoked == [str(env.owners["blocked"])]
    assert len(env.sessions.deleted) == 1
    monkeypatch.setattr(env.reader, "read", original)


def check_scope(env: Any) -> None:
    first = env.client.get(env.path)
    assert first.status_code == 200
    validate(env.resource, first.json(), set())
    assert first.json()["items"]
    cached = env.client.get(env.path, headers={"If-None-Match": first.headers["etag"]})
    assert cached.status_code == 304
    assert cached.headers["cache-control"] == "private, no-store"
    env.client.cookies.set(SESSION_COOKIE, "b")
    other = env.client.get(
        env.path + "?user_id=" + str(env.owners["a"]),
        headers={"If-None-Match": first.headers["etag"]},
    )
    assert other.status_code == 200
    assert other.json()["items"] == []
    assert other.json()["data_as_of"] is None
    assert other.json()["gaps"][0]["reason"] == "data_licence_unavailable"
    assert other.headers["etag"] != first.headers["etag"]


def check_defaults(env: Any) -> None:
    del env.app.dependency_overrides[env.dependency]
    for code, reason in ((STOCK, "no_source"), (ETF, "not_applicable"), (INDEX, "no_source")):
        result = env.client.get(env.path.replace(STOCK, code))
        assert result.status_code == 200
        body = result.json()
        assert body["items"] == []
        assert body["sources"] == []
        assert body["data_as_of"] is None
        assert body["gaps"][0]["reason"] == reason
    missing = env.client.get(env.path.replace(STOCK, "999997.SH"))
    assert missing.status_code == 404
    old = env.client.get(env.path.replace(STOCK, OLD))
    assert old.status_code == 404
    assert old.json()["error"]["details"] == {"superseded_by": STOCK}


def check_guard(env: Any, mode: str) -> None:
    env.app.state.settings = env.settings.model_copy(update={"app_env": mode})
    with pytest.raises(ConfigError, match="local/test"):
        install_fixture_reader(env.app, env.dependency, env.reader)
