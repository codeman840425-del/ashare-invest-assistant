"""A18 static-resource dispatch: real auth/CSRF/owner, task-only PG and Redis."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
import redis
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, create_engine, insert

from app.auth.sessions import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, Session, SessionStore
from app.common import errors
from app.common.resource_routes import StaticResourceRoute, install_static_resources
from app.config import Settings
from app.db.tables.realtime import suggestion_threads, suggestions
from app.db.tables.users import users
from app.main import create_app


def need(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def envelope(response: Response, status: int, code: str) -> dict[str, object]:
    need(response.status_code == status, f"Unexpected status for {code}: {response.status_code}")
    payload = response.json()
    need(set(payload) == {"error"}, "Unexpected envelope root")
    body: dict[str, object] = payload["error"]
    need(set(body) == {"code", "message", "details", "request_id"}, "Unexpected envelope keys")
    need(body["code"] == code, "Unexpected error code")
    need(body["request_id"] == response.headers.get("X-Request-Id"), "Request ID mismatch")
    return body


def only_methods(response: Response, methods: set[str]) -> None:
    body = envelope(response, 405, "METHOD_NOT_ALLOWED")
    need(set(response.headers["allow"].split(", ")) == methods, "Allow does not match resource")
    need(body["details"] == {"allowed": sorted(methods)}, "Envelope methods differ from Allow")


@dataclass
class Rig:
    app: FastAPI
    engine: Engine
    store: SessionStore
    sessions: list[tuple[str, Session]]
    suggestion: uuid.UUID


@pytest.fixture(scope="module")
def rig() -> Iterator[Rig]:
    dsn = "postgresql+psycopg://aia:ci-only@127.0.0.1:55481/oci1_20261111_contract"
    engine = create_engine(dsn)
    owner, other, suggestion, thread = (uuid.uuid4() for _ in range(4))
    with engine.begin() as conn:
        for uid in (owner, other):
            conn.execute(
                insert(users).values(
                    id=uid,
                    username="oci1_route_" + uid.hex[:12],
                    password_hash=uuid.uuid4().hex,
                    status="approved",
                    role="user",
                )
            )
        conn.execute(
            insert(suggestion_threads).values(id=thread, user_id=owner, security_code="600000.SH")
        )
        conn.execute(
            insert(suggestions).values(
                id=suggestion,
                thread_id=thread,
                user_id=owner,
                security_code="600000.SH",
                seq_no=1,
                origin="manual_refresh",
                data_status="fresh",
                holding_context={"suggestion_view": {"security_code": "600000.SH"}},
                created_at=dt.datetime.now(dt.UTC),
            )
        )
    cache = redis.Redis.from_url("redis://127.0.0.1:56381/14")
    store = SessionStore(cache, idle_ttl_s=120, absolute_ttl_s=300)
    sessions = [store.create(str(uid)) for uid in (owner, other)]
    settings = Settings(
        app_env="test", database_url=dsn, redis_url="redis://127.0.0.1:56381/14", _env_file=None
    )
    app = create_app(settings)
    yield Rig(app, engine, store, sessions, suggestion)
    for _, session in sessions:
        store.delete(session)
    cache.close()
    engine.dispose()


@pytest.fixture
def client(rig: Rig) -> Iterator[TestClient]:
    with TestClient(rig.app) as result:
        yield result


@pytest.mark.parametrize("method", ["GET", "OPTIONS", "PUT", "HEAD"])
def test_refresh_reserved_resource_rejects_dynamic_fallthrough(
    client: TestClient, method: str
) -> None:
    response = client.request(method, "/api/v1/suggestions/refresh")
    if method == "HEAD":
        need(
            response.status_code == 405 and response.headers["allow"] == "POST",
            "HEAD must not be implicit",
        )
    else:
        only_methods(response, {"POST"})


@pytest.mark.parametrize("path", ["evaluation", "events"])
@pytest.mark.parametrize("method", ["DELETE", "OPTIONS", "POST"])
def test_risk_static_resource_does_not_advertise_dynamic_delete(
    client: TestClient, path: str, method: str
) -> None:
    only_methods(client.request(method, "/api/v1/risk-controls/" + path), {"GET"})


def test_auth_then_csrf_then_body_uses_real_dependencies(client: TestClient, rig: Rig) -> None:
    envelope(
        client.post(
            "/api/v1/suggestions/refresh",
            content=b"{bad",
            headers={"Content-Type": "application/json"},
        ),
        401,
        "AUTH_REQUIRED",
    )
    sid, session = rig.sessions[0]
    client.cookies.set(SESSION_COOKIE, sid)
    envelope(
        client.post(
            "/api/v1/suggestions/refresh",
            content=b"{bad",
            headers={"Content-Type": "application/json"},
        ),
        403,
        "CSRF_FAILED",
    )
    client.cookies.set(CSRF_COOKIE, session.csrf_token)
    envelope(
        client.post(
            "/api/v1/suggestions/refresh",
            content=b"{bad",
            headers={"Content-Type": "application/json", CSRF_HEADER: session.csrf_token},
        ),
        400,
        "VALIDATION_ERROR",
    )


@pytest.mark.parametrize("method", ["GET", "PUT", "TRACE", "OPTIONS"])
def test_admin_wrong_method_hidden_without_allow(client: TestClient, method: str) -> None:
    response = client.request(method, "/api/v1/admin/promotions")
    envelope(response, 404, "NOT_FOUND")
    need("allow" not in response.headers, "Hidden admin resource disclosed Allow")


@pytest.mark.parametrize(
    "path", ["/api/v1/suggestions/refresh", "/api/v1/admin/promotions", "/api/v1/not-a-route"]
)
def test_global_413_precedes_routing_and_auth(client: TestClient, rig: Rig, path: str) -> None:
    response = client.post(
        path,
        content=b"x",
        headers={
            "Content-Length": str(rig.app.state.settings.business.imports.max_request_bytes + 1)
        },
    )
    envelope(response, 413, "PAYLOAD_TOO_LARGE")


def test_same_static_resource_get_put_union_and_no_implicit_head(client: TestClient) -> None:
    only_methods(client.delete("/api/v1/me/profile"), {"GET", "PUT"})
    response = client.head("/api/v1/health/live")
    need(response.status_code == 405 and response.headers["allow"] == "GET", "Implicit HEAD added")
    envelope(client.get("/api/v1/not-a-route"), 404, "NOT_FOUND")


def test_real_uuid_owner_cross_owner_and_invalid_uuid(client: TestClient, rig: Rig) -> None:
    client.cookies.set(SESSION_COOKIE, rig.sessions[0][0])
    own = client.get("/api/v1/suggestions/" + str(rig.suggestion))
    need(
        own.status_code == 200 and own.json()["id"] == str(rig.suggestion),
        "Real owned UUID detail was not dispatched",
    )
    envelope(client.get("/api/v1/suggestions/not-a-reserved-resource"), 400, "VALIDATION_ERROR")
    client.cookies.set(SESSION_COOKIE, rig.sessions[1][0])
    envelope(client.get("/api/v1/suggestions/" + str(rig.suggestion)), 404, "NOT_FOUND")


def test_real_dispatch_static_before_dynamic_even_when_registered_last(rig: Rig) -> None:
    app = create_app(Settings(app_env="test", database_url=None, redis_url=None, _env_file=None))
    router = APIRouter()
    calls: list[str] = []

    @router.get("/dispatch/{identifier}")
    def dynamic(identifier: str) -> dict[str, str]:
        calls.append("dynamic")
        return {"identifier": identifier}

    @router.get("/dispatch/fixed")
    def static_get() -> dict[str, str]:
        calls.append("static-get")
        return {"kind": "static-get"}

    @router.put("/dispatch/fixed")
    def static_put() -> dict[str, str]:
        calls.append("static-put")
        return {"kind": "static-put"}

    nested = APIRouter()
    nested.include_router(router, prefix="/nested")
    app.include_router(nested, prefix="/api/v1")
    install_static_resources(app)
    with TestClient(app) as client:
        need(
            client.get("/api/v1/nested/dispatch/fixed").json() == {"kind": "static-get"},
            "Dynamic GET shadowed static resource",
        )
        need(
            client.put("/api/v1/nested/dispatch/fixed").json() == {"kind": "static-put"},
            "Static PUT dispatch failed",
        )
        only_methods(client.options("/api/v1/nested/dispatch/fixed"), {"GET", "PUT"})
        need(calls == ["static-get", "static-put"], "Unsupported method executed endpoint")
        schema = app.openapi()["paths"]["/api/v1/nested/dispatch/fixed"]
        need(set(schema) == {"get", "put"}, "OpenAPI methods were fabricated")


def test_allow_only_negative_control_still_exposes_wrong_get_dispatch(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(
        Settings(
            app_env="test",
            database_url="postgresql://aia:ci-only@127.0.0.1:55481/oci1_20261111_contract",
            redis_url="redis://127.0.0.1:56381/14",
            _env_file=None,
        )
    )
    app.router.routes[:] = [
        route for route in app.router.routes if not isinstance(route, StaticResourceRoute)
    ]
    monkeypatch.setattr(errors, "_allowed_methods", lambda _request: ["POST"])
    with TestClient(app) as client:
        only_methods(client.options("/api/v1/suggestions/refresh"), {"POST"})
        envelope(client.get("/api/v1/suggestions/refresh"), 401, "AUTH_REQUIRED")
        # Correct Allow alone leaves the original wrong dynamic GET dispatch observable.
