"""Real plan service/SQL/idempotency/HTTP checks in the owned O-CI1 synthetic PG.

Auth context is synthetic. Redis commands are isolated in memory. Positive paths
never replace service.create/revise/project; malformed-output controls inject
only a projection fault after real writes/audit, preserving the real route fn.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import redis
from fastapi import FastAPI
from fastapi.exceptions import ResponseValidationError
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import ValidationError
from sqlalchemy import Connection, Engine, create_engine, event, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import make_url

from app.auth import body_order, deps
from app.common import idempotency
from app.common.errors import Utf8JSONResponse, install_exception_handlers
from app.common.middleware import RequestIdMiddleware
from app.config import Settings, get_settings
from app.db.tables.market import securities
from app.db.tables.research import action_plans, plan_versions
from app.db.tables.users import audit_logs, users
from app.plans import api as plans
from app.plans import service
from app.plans.models import PlanInput


def require(condition: bool, message: str) -> None:
    if not condition:
        pytest.fail(message)


def generic_500(response: Response) -> None:
    require(response.status_code == 500, "malformed service response accepted")
    payload = response.json()
    require(set(payload) == {"error"}, "generic envelope lost")
    error = payload["error"]
    require(error["code"] == "INTERNAL_ERROR", "500 code changed")
    require(error["details"] is None and error["message"] == "服务器内部错误", "500 detail leaked")
    require(
        bool(error["request_id"]) and error["request_id"] == response.headers["X-Request-Id"],
        "request ID lost",
    )
    require("private-response-marker" not in response.text, "invalid projection leaked")


@dataclass
class RedisStorage:
    records: dict[str, str] = field(default_factory=dict)
    sets: int = 0
    gets: int = 0
    deletes: int = 0

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        self.sets += 1
        require(ex == idempotency.TTL_S, "cache TTL argument changed")
        if nx and key in self.records:
            return False
        self.records[key] = value
        return True

    def get(self, key: str) -> str | None:
        self.gets += 1
        return self.records.get(key)

    def delete(self, key: str) -> int:
        self.deletes += 1
        return int(self.records.pop(key, None) is not None)


@dataclass
class RealPlans:
    engine: Engine
    cache: RedisStorage
    owner: uuid.UUID
    other: uuid.UUID
    plan_id: uuid.UUID
    commits: int = 0
    baseline: tuple[int, int, int] = (0, 0, 0)

    def body(self, revise: bool, *, code: str = "600000.SH") -> dict[str, object]:
        body: dict[str, object] = {
            "security_code": code,
            "action": "hold",
            "rationale": "synthetic real-service plan",
        }
        if revise:
            body.update(base_version_no=1, change_reason="synthetic revision")
        return body

    def path(self, revise: bool) -> str:
        return f"/api/v1/plans/{self.plan_id}/versions" if revise else "/api/v1/plans"

    def counts(self) -> tuple[int, int, int]:
        owners = [self.owner, self.other]
        with self.engine.connect() as conn:
            heads = conn.execute(
                select(func.count())
                .select_from(action_plans)
                .where(action_plans.c.user_id.in_(owners))
            ).scalar_one()
            versions = conn.execute(
                select(func.count())
                .select_from(
                    plan_versions.join(action_plans, plan_versions.c.plan_id == action_plans.c.id)
                )
                .where(action_plans.c.user_id.in_(owners))
            ).scalar_one()
            audits = conn.execute(
                select(func.count())
                .select_from(audit_logs)
                .where(
                    audit_logs.c.actor_id.in_(owners),
                    audit_logs.c.action.in_(["plan.created", "plan.revised"]),
                )
            ).scalar_one()
        return int(heads), int(versions), int(audits)

    def delta(self) -> tuple[int, int, int]:
        return tuple(
            current - original
            for current, original in zip(self.counts(), self.baseline, strict=True)
        )


@pytest.fixture
def real_plans(request: pytest.FixtureRequest) -> Iterator[tuple[RealPlans, TestClient]]:
    raw = os.environ.get("OCI1_MIGRATIONS_URL")
    if not raw:
        pytest.fail("explicit synthetic PG URL required")
    parsed = make_url(raw)
    require(
        parsed.host == "127.0.0.1"
        and parsed.port == 55481
        and parsed.database == "oci1_20261111_migrations",
        "refuse non-O-CI1 database",
    )
    engine = create_engine(raw)
    owner, other = uuid.uuid4(), uuid.uuid4()
    state = RealPlans(engine, RedisStorage(), owner, other, uuid.uuid4())
    with engine.begin() as conn:
        for identifier in (owner, other):
            conn.execute(
                insert(users).values(
                    id=identifier,
                    username="oci1_" + identifier.hex[:20],
                    password_hash=identifier.hex,
                    role="user",
                    status="approved",
                )
            )
        for code in ("600000.SH", "600001.SH"):
            conn.execute(
                pg_insert(securities)
                .values(code=code, type="stock", name="synthetic", exchange="SH")
                .on_conflict_do_nothing(index_elements=["code"])
            )
    revise = bool(
        getattr(request.node, "callspec", SimpleNamespace(params={})).params.get("revise", False)
    )
    if revise:
        with engine.begin() as conn:
            created = service.create(conn, owner, PlanInput.model_validate(state.body(False)))
        state.plan_id = uuid.UUID(created["id"])
    state.baseline = state.counts()

    def committed(_conn: Connection) -> None:
        state.commits += 1

    event.listen(engine, "commit", committed)
    rds = Mock(spec=redis.Redis)
    rds.set.side_effect = state.cache.set
    rds.get.side_effect = state.cache.get
    rds.delete.side_effect = state.cache.delete
    settings = Settings(app_env="test", database_url=None, redis_url=None, _env_file=None)
    app = FastAPI(default_response_class=Utf8JSONResponse)
    install_exception_handlers(app)
    body_order.install(app)
    app.add_middleware(RequestIdMiddleware)
    app.state.settings = settings
    app.include_router(plans.router, prefix="/api/v1")
    app.dependency_overrides[deps.current_auth] = lambda: SimpleNamespace(user_id=state.owner)
    app.dependency_overrides[deps.get_engine] = lambda: engine
    app.dependency_overrides[deps.get_redis] = lambda: rds
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield state, client
    finally:
        engine.dispose()


@pytest.mark.parametrize("revise", [False, True])
def test_real_service_create_revision_cache_and_conflict(
    real_plans: tuple[RealPlans, TestClient], revise: bool
) -> None:
    state, client = real_plans
    headers = {"Idempotency-Key": "synthetic-key"}
    first = client.post(state.path(revise), json=state.body(revise), headers=headers)
    require(first.status_code == 201, "real service first request failed")
    if not revise:
        state.plan_id = uuid.UUID(first.json()["id"])
    replay = client.post(state.path(revise), json=state.body(revise), headers=headers)
    require(
        replay.status_code == 201 and replay.json() == first.json(), "real replay shape differs"
    )
    require(state.commits == 1, "real replay committed twice")
    require(state.delta() == ((0, 1, 1) if revise else (1, 1, 1)), "real SQL/audit duplicated")
    require(state.cache.sets == 3 and state.cache.gets == 1, "real wrapper cache counts changed")
    changed = {**state.body(revise), "rationale": "different synthetic rationale"}
    conflict = client.post(state.path(revise), json=changed, headers=headers)
    require(
        conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT",
        "real conflict mapping changed",
    )
    require(state.commits == 1 and state.delta()[1:] == (1, 1), "conflict produced side effects")


def test_real_user_and_create_revision_scope_isolation(
    real_plans: tuple[RealPlans, TestClient],
) -> None:
    state, client = real_plans
    first_owner = state.owner
    headers = {"Idempotency-Key": "synthetic-key"}
    created = client.post(state.path(False), json=state.body(False), headers=headers)
    require(created.status_code == 201, "first real creation failed")
    first_id = uuid.UUID(created.json()["id"])
    state.plan_id = first_id
    revised = client.post(state.path(True), json=state.body(True), headers=headers)
    require(
        revised.status_code == 201 and revised.json()["current_version_no"] == 2,
        "create/revise cache scope collided",
    )
    state.owner = state.other
    state.other = first_owner
    second = client.post(state.path(False), json=state.body(False), headers=headers)
    require(
        second.status_code == 201 and second.json()["id"] != str(first_id),
        "users shared plan/cache",
    )
    require(state.commits == 3 and state.delta() == (2, 3, 3), "scope/user SQL identity failed")
    require(len(state.cache.records) == 3, "scope/user cache keys collided")


@pytest.mark.parametrize("revise", [False, True])
def test_real_service_app_error_releases_key_without_commit(
    real_plans: tuple[RealPlans, TestClient], revise: bool
) -> None:
    state, client = real_plans
    body = state.body(revise)
    if revise:
        body["base_version_no"] = 99
    else:
        body["security_code"] = "999999.SH"
    response = client.post(
        state.path(revise), json=body, headers={"Idempotency-Key": "synthetic-key"}
    )
    expected_status, expected_code = (
        (409, "VERSION_CONFLICT") if revise else (400, "VALIDATION_ERROR")
    )
    require(
        response.status_code == expected_status
        and response.json()["error"]["code"] == expected_code,
        "real AppError mapping changed",
    )
    require(state.commits == 0 and state.delta() == (0, 0, 0), "real failed transaction committed")
    require(
        not state.cache.records and state.cache.deletes == 1, "real fn failure retained reservation"
    )


@pytest.mark.parametrize("revise", [False, True])
@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        "private-response-marker",
        {7: "private-response-marker"},
        {"missing": "private-response-marker"},
    ],
)
def test_real_writes_survive_late_projection_validation(
    real_plans: tuple[RealPlans, TestClient],
    revise: bool,
    bad: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state, client = real_plans
    # Fault injection only: the service still validates, locks, writes versions and audits.
    monkeypatch.setattr(service, "project", lambda *_args, **_kwargs: bad)
    headers = {"Idempotency-Key": "synthetic-key"}
    for index in range(2):
        response = client.post(state.path(revise), json=state.body(revise), headers=headers)
        generic_500(response)
        if index == 0:
            layer = (
                ResponseValidationError
                if isinstance(bad, dict) and all(isinstance(key, str) for key in bad)
                else ValidationError
            )
            require(
                any(
                    record.exc_info and isinstance(record.exc_info[1], layer)
                    for record in caplog.records
                ),
                "wrong real rejection layer",
            )
    require(state.commits == 1, "late validation retroactively rolled back or re-executed fn")
    require(
        state.delta() == ((0, 1, 1) if revise else (1, 1, 1)),
        "late validation SQL/audit state changed",
    )
    require(len(state.cache.records) == 1, "late validation cache missing")
    cached = json.loads(next(iter(state.cache.records.values())))
    require(
        cached["s"] == 201 and cached["b"] == json.loads(json.dumps(bad)),
        "actual bad cache changed",
    )
