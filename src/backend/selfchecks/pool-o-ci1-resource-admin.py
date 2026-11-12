"""Chief17:15 narrow gate: resource templates and existing admin schema contract.

Execute only in a separately assigned exclusive window. No real G7 operation:
admin POST tests keep real authentication/reauthentication and replace service leaves.
"""

from __future__ import annotations

import json
import os
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import redis
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Connection, Engine, create_engine, insert, select, text
from sqlalchemy.engine import make_url

from app.api.v1 import promotions
from app.auth.passwords import policy_for
from app.auth.sessions import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, Session, SessionStore
from app.common.resource_routes import install_static_resources
from app.config import Settings
from app.db.tables.strategy import (
    strategies,
    strategy_instance_events,
    strategy_instances,
    strategy_versions,
)
from app.db.tables.users import users
from app.main import create_app

METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT")
HTTP_SCHEMA_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def need(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def error(response: Response, status: int, code: str) -> None:
    need(response.status_code == status, f"Expected {status}/{code}, got {response.status_code}")
    payload = response.json()
    need(set(payload) == {"error"}, "Unexpected error envelope")
    need(payload["error"]["code"] == code, "Unexpected error code")
    need(
        payload["error"]["request_id"] == response.headers.get("X-Request-Id"),
        "Request ID mismatch",
    )


def methods(response: Response, allowed: set[str]) -> None:
    error(response, 405, "METHOD_NOT_ALLOWED")
    need(set(response.headers["Allow"].split(", ")) == allowed, "Wrong resource Allow")
    need(
        response.json()["error"]["details"] == {"allowed": sorted(allowed)},
        "Wrong resource details",
    )


@dataclass
class Rig:
    settings: Settings
    engine: Engine
    store: SessionStore
    sessions: dict[str, tuple[str, Session]] = field(repr=False)
    owner: uuid.UUID
    admin: uuid.UUID
    instance: uuid.UUID
    admin_password: str = field(repr=False)


@pytest.fixture(scope="module")
def rig() -> Iterator[Rig]:
    need(
        os.environ.get("OCI1_RESOURCE_GATE_AUTHORIZED") == "1",
        "Explicit exclusive gate window required",
    )
    raw = os.environ.get("OCI1_RESOURCE_DATABASE_URL", "")
    parsed = make_url(raw)
    need(
        parsed.host in {"127.0.0.1", "oci1-pg"} and parsed.port in {55481, 5432},
        "Refuse unrelated database endpoint",
    )
    need(
        parsed.database in {"oci1_20261111_linux_gate_before", "oci1_20261111_linux_gate_after"},
        "Fresh gate database required",
    )
    cache_url = os.environ.get("OCI1_RESOURCE_REDIS_URL", "")
    cache_parts = urlsplit(cache_url)
    need(
        cache_parts.hostname in {"127.0.0.1", "oci1-redis"}
        and cache_parts.port in {56381, 6379}
        and cache_parts.path == "/15",
        "Refuse unrelated Redis namespace",
    )
    settings = Settings(app_env="test", database_url=raw, redis_url=cache_url, _env_file=None)
    engine = create_engine(raw)
    owner, stranger, admin, strategy, version, instance = (uuid.uuid4() for _ in range(6))
    password = secrets.token_urlsafe(24)
    password_hash = policy_for(settings.business.auth).hash(password)
    with engine.begin() as conn:
        need(
            conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
            == "0034",
            "Unexpected gate migration head",
        )
        for uid, role in ((owner, "user"), (stranger, "user"), (admin, "admin")):
            conn.execute(
                insert(users).values(
                    id=uid,
                    username="oci1_ra_" + uid.hex[:12],
                    password_hash=password_hash if role == "admin" else uid.hex,
                    role=role,
                    status="approved",
                )
            )
        conn.execute(
            insert(strategies).values(
                id=strategy,
                key="oci1_ra_" + strategy.hex,
                name="Synthetic route component",
                horizons=["swing"],
            )
        )
        conn.execute(
            insert(strategy_versions).values(
                id=version,
                strategy_id=strategy,
                version_no=1,
                config={},
                config_hash=version.hex,
                lifecycle="published",
            )
        )
        conn.execute(
            insert(strategy_instances).values(
                id=instance,
                user_id=owner,
                strategy_version_id=version,
                scope="watch_group",
                horizon="swing",
                origin="user",
                status="active",
            )
        )
    cache = redis.Redis.from_url(cache_url)
    store = SessionStore(cache, idle_ttl_s=120, absolute_ttl_s=300)
    sessions = {
        name: store.create(str(uid), origin="password_login")
        for name, uid in (("owner", owner), ("stranger", stranger), ("admin", admin))
    }
    yield Rig(settings, engine, store, sessions, owner, admin, instance, password)
    for _, session in sessions.values():
        store.delete(session)
    cache.close()
    engine.dispose()


@pytest.fixture
def client(rig: Rig) -> Iterator[TestClient]:
    with TestClient(create_app(rig.settings)) as result:
        yield result


def authenticate(client: TestClient, rig: Rig, actor: str, *, csrf: bool = True) -> None:
    sid, session = rig.sessions[actor]
    client.cookies.set(SESSION_COOKIE, sid)
    if csrf:
        client.cookies.set(CSRF_COOKIE, session.csrf_token)
        client.headers[CSRF_HEADER] = session.csrf_token


@pytest.mark.parametrize("authenticated", [False, True])
def test_events_post_selects_specific_resource_before_auth(
    client: TestClient, rig: Rig, authenticated: bool
) -> None:
    if authenticated:
        authenticate(client, rig, "owner")
    methods(client.post(f"/api/v1/strategy-instances/{rig.instance}/events"), {"GET"})


def test_events_allow_and_actual_uuid_owner_validation(client: TestClient, rig: Rig) -> None:
    path = f"/api/v1/strategy-instances/{rig.instance}/events"
    methods(client.options(path), {"GET"})
    authenticate(client, rig, "owner")
    response = client.get(path)
    need(
        response.status_code == 200 and isinstance(response.json()["items"], list),
        "Actual events handler did not run",
    )
    error(client.get("/api/v1/strategy-instances/not-a-uuid/events"), 400, "VALIDATION_ERROR")
    authenticate(client, rig, "stranger")
    error(client.get(path), 404, "NOT_FOUND")


def test_actual_action_and_unknown_action_are_preserved(client: TestClient, rig: Rig) -> None:
    authenticate(client, rig, "owner")
    response = client.post(f"/api/v1/strategy-instances/{rig.instance}/pause")
    need(
        response.status_code == 200 and response.json()["status"] == "paused",
        "Actual pause action was intercepted",
    )
    error(
        client.post(f"/api/v1/strategy-instances/{rig.instance}/not-an-action"),
        400,
        "VALIDATION_ERROR",
    )
    with rig.engine.connect() as conn:
        need(
            conn.execute(
                select(strategy_instances.c.status).where(strategy_instances.c.id == rig.instance)
            ).scalar_one()
            == "paused",
            "Real action state missing",
        )
        need(
            conn.execute(
                select(strategy_instance_events.c.kind).where(
                    strategy_instance_events.c.instance_id == rig.instance
                )
            )
            .scalars()
            .all()
            == ["paused"],
            "Real action event count changed",
        )


def test_parameter_scope_converter_endpoint_and_method_union() -> None:
    app = create_app(Settings(app_env="test", database_url=None, redis_url=None, _env_file=None))
    router = APIRouter()
    seen: list[tuple[str, uuid.UUID, bool]] = []

    @router.post("/probe/{owner_id:uuid}/{action}")
    def action(owner_id: uuid.UUID, action: str) -> dict[str, str]:
        return {"route": "action", "owner": str(owner_id), "action": action}

    @router.get("/probe/{owner_id:uuid}/events")
    def get_events(owner_id: uuid.UUID, request: Request) -> dict[str, str]:
        seen.append(("get", owner_id, request.scope["path_params"]["owner_id"] == owner_id))
        need(request.scope["endpoint"] is get_events, "GET endpoint identity lost")
        return {"owner": str(owner_id)}

    @router.put("/probe/{owner_id:uuid}/events")
    def put_events(owner_id: uuid.UUID, request: Request) -> dict[str, str]:
        seen.append(("put", owner_id, request.scope["path_params"]["owner_id"] == owner_id))
        need(request.scope["endpoint"] is put_events, "PUT endpoint identity lost")
        return {"owner": str(owner_id)}

    nested = APIRouter()
    nested.include_router(router, prefix="/nested")
    app.include_router(nested, prefix="/api/v1")
    install_static_resources(app)
    owner = uuid.uuid4()
    with TestClient(app) as probe:
        path = f"/api/v1/nested/probe/{owner}/events"
        methods(probe.post(path), {"GET", "PUT"})
        need(probe.get(path).json() == {"owner": str(owner)}, "GET UUID path parameters lost")
        need(probe.put(path).json() == {"owner": str(owner)}, "PUT UUID path parameters lost")
        need(
            seen == [("get", owner, True), ("put", owner, True)],
            "Actual endpoint or converter changed",
        )
        need(
            probe.post(f"/api/v1/nested/probe/{owner}/pause").json()["action"] == "pause",
            "Legal generic action lost",
        )


ADMIN_PATHS = (
    "/api/v1/admin/promotions",
    "/api/v1/admin/promotions/00000000-0000-4000-8000-000000000101/decision",
    "/api/v1/admin/strategies/00000000-0000-4000-8000-000000000102/versions/00000000-0000-4000-8000-000000000103/lifecycle",
)


@pytest.mark.parametrize("actor", ["anonymous", "stranger"])
@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_non_admin_all_methods_hidden_without_allow(
    client: TestClient, rig: Rig, actor: str, method: str, path: str
) -> None:
    if actor != "anonymous":
        authenticate(client, rig, actor, csrf=False)
    response = client.request(method, path)
    need(
        response.status_code == 404 and "allow" not in response.headers, "Admin existence disclosed"
    )
    if method != "HEAD":
        error(response, 404, "NOT_FOUND")


def test_all_admin_paths_absent_from_public_openapi(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")
    need(response.status_code == 200, "Public schema unavailable")
    need(
        not any(path.startswith("/api/v1/admin/") for path in response.json()["paths"]),
        "Admin path in public schema",
    )


def test_original_113_operations_map_exactly_to_three_authorized_removals(
    client: TestClient,
) -> None:
    frozen = Path(os.environ.get("OCI1_FROZEN_OPERATIONS", ""))
    need(frozen.is_file(), "Frozen original operation map required")
    data = json.loads(frozen.read_text(encoding="utf-8"))
    original = {(row["method"], row["path"]) for row in data["original_operations"]}
    removed = {(row["method"], row["path"]) for row in data["authorized_removals"]}
    schema = client.get("/api/v1/openapi.json").json()
    current = {
        (method.upper(), path)
        for path, operation in schema["paths"].items()
        for method in operation
        if method in HTTP_SCHEMA_METHODS
    }
    need(len(original) == 113 and len(removed) == 3, "Frozen operation map altered")
    need(
        original - current == removed and current - original == set(),
        "Operations changed outside authorized admin registration",
    )
    need(len(current) == 110, "Unexpected public operation count")


def test_admin_original_get_registration_still_executes(client: TestClient, rig: Rig) -> None:
    authenticate(client, rig, "admin")
    response = client.get("/api/v1/admin/promotions")
    need(response.status_code == 200 and "items" in response.json(), "Admin GET route disabled")


@pytest.mark.parametrize("operation", ["decision", "lifecycle"])
def test_admin_post_keeps_handler_and_real_reauthentication(
    client: TestClient, rig: Rig, operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    authenticate(client, rig, "admin")
    calls: list[tuple[object, ...]] = []

    def leaf(conn: Connection, actor: uuid.UUID, *args: object) -> dict[str, str]:
        need(
            isinstance(conn, Connection) and actor == rig.admin,
            "Actual reauthentication or actor lost",
        )
        calls.append(args)
        return {"route_witness": operation}

    if operation == "decision":
        monkeypatch.setattr(promotions.service, "decide", leaf)
        response = client.post(
            ADMIN_PATHS[1],
            json={
                "decision": "changes_requested",
                "comment": "synthetic routing witness",
                "ack_warn_gates": [],
                "password": rig.admin_password,
            },
        )
    else:
        monkeypatch.setattr(promotions.service, "change_lifecycle", leaf)
        response = client.post(
            ADMIN_PATHS[2],
            json={
                "to": "draft",
                "reason": "synthetic routing witness",
                "password": rig.admin_password,
            },
        )
    need(
        response.status_code == 200
        and response.json() == {"route_witness": operation}
        and len(calls) == 1,
        "Original admin POST route or real reauthentication disabled",
    )
