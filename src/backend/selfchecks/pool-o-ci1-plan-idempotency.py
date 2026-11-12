"""Actual plan routes/idempotency with synthetic SQLite writes and stateful Redis commands.

No real account, PostgreSQL, Redis server, auth/CSRF claim, or network collection.
"""

from __future__ import annotations

import datetime as dt
import json
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
from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.pool import StaticPool

from app.auth import body_order, deps
from app.common import idempotency
from app.common.errors import AppError, ErrorCode, Utf8JSONResponse, install_exception_handlers
from app.common.middleware import RequestIdMiddleware
from app.config import Settings, get_settings
from app.plans import api as plans
from app.plans.models import PlanInput, VersionInput


def require(condition: bool, message: str) -> None:
    if not condition:
        pytest.fail(message)


def require_generic_500(response: Response) -> None:
    require(response.status_code == 500, "invalid response must be HTTP 500")
    payload = response.json()
    require(set(payload) == {"error"}, "500 envelope must be generic")
    error = payload["error"]
    require(error["code"] == "INTERNAL_ERROR", "500 code changed")
    require(error["message"] == "服务器内部错误" and error["details"] is None, "500 detail leaked")
    require(bool(error["request_id"]), "500 missing request ID")
    require(error["request_id"] == response.headers["X-Request-Id"], "request ID mismatch")
    require("private-response-marker" not in response.text, "invalid body leaked")


@dataclass
class MemoryRedis:
    records: dict[str, str] = field(default_factory=dict)
    ttl: list[int | None] = field(default_factory=list)
    unavailable: bool = False
    set_calls: int = 0
    get_calls: int = 0
    delete_calls: int = 0

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        self.set_calls += 1
        if self.unavailable:
            raise redis.ConnectionError("synthetic Redis unavailable")
        self.ttl.append(ex)
        if nx and key in self.records:
            return False
        self.records[key] = value
        return True

    def get(self, key: str) -> str | None:
        self.get_calls += 1
        return self.records.get(key)

    def delete(self, key: str) -> int:
        self.delete_calls += 1
        return int(self.records.pop(key, None) is not None)


@dataclass
class Harness:
    engine: Engine
    cache: MemoryRedis
    owner: uuid.UUID
    plan_id: uuid.UUID
    mode: str = "valid"
    producer_calls: int = 0
    commits: int = 0
    error_code: ErrorCode = ErrorCode.VERSION_CONFLICT
    invalid_reply: object = None

    def body(self, revise: bool) -> dict[str, object]:
        result: dict[str, object] = {
            "security_code": "600000.SH",
            "action": "hold",
            "rationale": "synthetic plan",
        }
        if revise:
            result.update(base_version_no=1, change_reason="synthetic revision")
        return result

    def response(self) -> dict[str, object]:
        stamp = dt.datetime(2026, 11, 11, tzinfo=dt.UTC)
        return {
            "id": str(self.plan_id),
            "security_code": "600000.SH",
            "name": "synthetic",
            "account_id": None,
            "origin": "manual",
            "status": "active",
            "action": "hold",
            "current_version_no": 1,
            "plan_draft_id": None,
            "candidate_id": None,
            "triggered_at": None,
            "created_at": stamp,
            "updated_at": stamp,
            "current_version": {
                "plan_id": str(self.plan_id),
                "version_no": 1,
                "action": "hold",
                "qty": None,
                "price": None,
                "size_pct_of_assets": None,
                "max_loss_amount": None,
                "stops": None,
                "rationale": "synthetic plan",
                "risks": None,
                "review_date": dt.date(2026, 11, 12),
                "conditions": [],
                "change_reason": None,
                "checklist_answers": [],
                "snapshot_id": None,
                "created_at": stamp,
            },
            "version_count": 1,
            "pending_triggers": [],
            "evidence": [],
        }

    def produce(self, conn: Connection, *_args: object) -> object:
        self.producer_calls += 1
        conn.execute(text("INSERT INTO synthetic_writes DEFAULT VALUES"))
        if self.mode == "business_error":
            raise AppError(self.error_code)
        if self.mode == "runtime_error":
            raise RuntimeError("synthetic producer failure")
        if self.mode == "invalid_object":
            return self.invalid_reply
        return self.response()

    def writes(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(text("SELECT count(*) FROM synthetic_writes")).scalar_one())

    def path(self, revise: bool) -> str:
        return f"/api/v1/plans/{self.plan_id}/versions" if revise else "/api/v1/plans"

    def cache_key(self, revise: bool) -> str:
        scope = f"plans:{self.plan_id}:versions" if revise else "plans:create"
        return idempotency._k(user_id=self.owner, scope=scope, key="synthetic-key")

    def preload(self, revise: bool, *, status: int, body: object) -> None:
        model = VersionInput if revise else PlanInput
        payload = model.model_validate(self.body(revise)).model_dump(mode="json")
        self.cache.records[self.cache_key(revise)] = json.dumps(
            {"h": idempotency.body_hash(payload), "s": status, "b": body}
        )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Harness, TestClient]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE synthetic_writes(id INTEGER PRIMARY KEY)"))
    state = Harness(engine, MemoryRedis(), uuid.uuid4(), uuid.uuid4())

    def committed(_conn: Connection) -> None:
        state.commits += 1

    event.listen(engine, "commit", committed)
    rds = Mock(spec=redis.Redis)
    rds.set.side_effect = state.cache.set
    rds.get.side_effect = state.cache.get
    rds.delete.side_effect = state.cache.delete
    monkeypatch.setattr(plans.s, "create", state.produce)
    monkeypatch.setattr(plans.s, "revise", state.produce)
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
def test_first_create_or_revision_then_cache_replay(
    harness: tuple[Harness, TestClient], revise: bool
) -> None:
    state, client = harness
    for _ in range(2):
        response = client.post(
            state.path(revise),
            json=state.body(revise),
            headers={"Idempotency-Key": "synthetic-key"},
        )
        require(response.status_code == 201, "valid response must remain HTTP 201")
        require(response.json()["current_version"]["qty"] is None, "nullable shape changed")
        require(response.json()["current_version"]["conditions"] == [], "nested shape changed")
    require(state.producer_calls == 1, "cache replay executed producer twice")
    require(state.writes() == 1 and state.commits == 1, "cache replay committed another write")
    require(
        state.cache.set_calls == 3 and state.cache.get_calls == 1, "cache command counts changed"
    )
    require(state.cache.delete_calls == 0, "valid replay deleted reservation")
    require(response.json()["current_version"]["review_date"] == "2026-11-12", "date changed")
    require(response.json()["created_at"] == "2026-11-11T00:00:00Z", "datetime changed")
    require(
        bool(state.cache.ttl) and all(value == idempotency.TTL_S for value in state.cache.ttl),
        "TTL changed",
    )


@pytest.mark.parametrize("revise", [False, True])
def test_no_key_executes_each_request(harness: tuple[Harness, TestClient], revise: bool) -> None:
    state, client = harness
    for _ in range(2):
        response = client.post(state.path(revise), json=state.body(revise))
        require(response.status_code == 201, "unkeyed result changed")
    require(state.writes() == 2, "unkeyed requests were unexpectedly deduplicated")
    require(not state.cache.records, "unkeyed request wrote cache")


@pytest.mark.parametrize("revise", [False, True])
def test_same_key_different_body_conflicts_before_second_write(
    harness: tuple[Harness, TestClient], revise: bool
) -> None:
    state, client = harness
    headers = {"Idempotency-Key": "synthetic-key"}
    first = client.post(state.path(revise), json=state.body(revise), headers=headers)
    require(first.status_code == 201, "first request failed")
    changed = {**state.body(revise), "rationale": "changed synthetic rationale"}
    response = client.post(state.path(revise), json=changed, headers=headers)
    require(response.status_code == 409, "conflict status changed")
    require(response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT", "conflict mapping changed")
    require(state.writes() == 1 and state.producer_calls == 1, "conflict ran producer")


@pytest.mark.parametrize("revise", [False, True])
@pytest.mark.parametrize(
    ("mode", "error_code", "status"),
    [
        ("business_error", ErrorCode.VALIDATION_ERROR, 400),
        ("business_error", ErrorCode.NOT_FOUND, 404),
        ("business_error", ErrorCode.VERSION_CONFLICT, 409),
        ("business_error", ErrorCode.UPSTREAM_UNAVAILABLE, 503),
        ("runtime_error", ErrorCode.INTERNAL_ERROR, 500),
    ],
)
def test_producer_failure_rolls_back_and_releases_reservation(
    harness: tuple[Harness, TestClient], revise: bool, mode: str, error_code: ErrorCode, status: int
) -> None:
    state, client = harness
    state.mode = mode
    state.error_code = error_code
    headers = {"Idempotency-Key": "synthetic-key"}
    response = client.post(state.path(revise), json=state.body(revise), headers=headers)
    require(response.status_code == status, "producer failure status changed")
    if mode == "business_error":
        require(response.json()["error"]["code"] == error_code.value, "business mapping changed")
    else:
        require_generic_500(response)
    require(
        state.commits == 0 and state.cache.delete_calls == 1,
        "failed producer committed or retained key",
    )
    require("synthetic producer failure" not in response.text, "internal failure leaked")
    require(
        state.writes() == 0 and not state.cache.records,
        "failed producer retained write or reservation",
    )
    state.mode = "valid"
    retried = client.post(state.path(revise), json=state.body(revise), headers=headers)
    require(retried.status_code == 201 and state.writes() == 1, "released key cannot retry")


@pytest.mark.parametrize("revise", [False, True])
@pytest.mark.parametrize(
    "invalid_reply",
    [
        None,
        [],
        "private-response-marker",
        {7: "private-response-marker"},
        {"missing": "private-response-marker"},
    ],
)
def test_response_validation_occurs_after_committed_producer_and_cache(
    harness: tuple[Harness, TestClient],
    revise: bool,
    invalid_reply: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state, client = harness
    state.mode = "invalid_object"
    state.invalid_reply = invalid_reply
    for index in range(2):
        response = client.post(
            state.path(revise),
            json=state.body(revise),
            headers={"Idempotency-Key": "synthetic-key"},
        )
        require_generic_500(response)
        if index == 0:
            expected = (
                ResponseValidationError
                if isinstance(invalid_reply, dict)
                and all(isinstance(key, str) for key in invalid_reply)
                else ValidationError
            )
            require(
                any(
                    record.exc_info and isinstance(record.exc_info[1], expected)
                    for record in caplog.records
                ),
                "wrong response rejection layer",
            )
    require(
        state.writes() == 1 and state.commits == 1 and state.producer_calls == 1,
        "validation must remain after commit and before cache replay",
    )
    cached = json.loads(state.cache.records[state.cache_key(revise)])
    expected_cached = json.loads(json.dumps(invalid_reply, default=str))
    require(
        cached["s"] == 201 and cached["b"] == expected_cached,
        "post-commit malformed reply state changed",
    )


@pytest.mark.parametrize("revise", [False, True])
def test_preexisting_malformed_cached_body_fails_without_producer(
    harness: tuple[Harness, TestClient], revise: bool
) -> None:
    state, client = harness
    state.preload(revise, status=201, body=None)
    response = client.post(
        state.path(revise), json=state.body(revise), headers={"Idempotency-Key": "synthetic-key"}
    )
    require_generic_500(response)
    require(state.writes() == 0 and state.producer_calls == 0, "malformed cache invoked producer")


@pytest.mark.parametrize("revise", [False, True])
def test_in_progress_reservation_remains_409(
    harness: tuple[Harness, TestClient], revise: bool
) -> None:
    state, client = harness
    state.preload(revise, status=0, body=None)
    response = client.post(
        state.path(revise), json=state.body(revise), headers={"Idempotency-Key": "synthetic-key"}
    )
    require(response.status_code == 409, "in-progress reservation status changed")
    require(response.json()["error"]["details"]["in_progress"] is True, "in-progress detail lost")
    require(state.writes() == 0, "in-progress reservation wrote")


@pytest.mark.parametrize("revise", [False, True])
def test_redis_failure_maps_503_without_producer(
    harness: tuple[Harness, TestClient], revise: bool
) -> None:
    state, client = harness
    state.cache.unavailable = True
    response = client.post(
        state.path(revise), json=state.body(revise), headers={"Idempotency-Key": "synthetic-key"}
    )
    require(response.status_code == 503, "Redis failure status changed")
    require(
        response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE", "Redis failure mapping changed"
    )
    require(state.writes() == 0 and state.producer_calls == 0, "Redis failure wrote")


@pytest.mark.parametrize("revise", [False, True])
def test_request_validation_precedes_idempotency_side_effects(
    harness: tuple[Harness, TestClient], revise: bool
) -> None:
    state, client = harness
    invalid = {**state.body(revise), "rationale": ""}
    response = client.post(
        state.path(revise), json=invalid, headers={"Idempotency-Key": "synthetic-key"}
    )
    require(response.status_code == 400, "input validation mapping changed")
    require(response.json()["error"]["code"] == "VALIDATION_ERROR", "input error code changed")
    require(state.writes() == 0 and not state.cache.records, "invalid input touched DB/cache")


@pytest.mark.parametrize("revise", [False, True])
def test_same_key_is_isolated_by_user(harness: tuple[Harness, TestClient], revise: bool) -> None:
    state, client = harness
    first_owner = state.owner
    headers = {"Idempotency-Key": "synthetic-key"}
    for owner in (first_owner, uuid.uuid4(), first_owner):
        state.owner = owner
        response = client.post(state.path(revise), json=state.body(revise), headers=headers)
        require(response.status_code == 201, "user-separated request failed")
    require(state.producer_calls == 2 and state.commits == 2, "users shared callback/cache result")
    require(state.writes() == 2 and len(state.cache.records) == 2, "user cache namespaces merged")


def test_same_key_is_isolated_by_create_revision_scope_and_identifier(
    harness: tuple[Harness, TestClient],
) -> None:
    state, client = harness
    headers = {"Idempotency-Key": "synthetic-key"}
    for revise in (False, True, False, True):
        response = client.post(state.path(revise), json=state.body(revise), headers=headers)
        require(response.status_code == 201, "scope-separated request failed")
    require(state.producer_calls == 2 and state.commits == 2, "create and revise shared cache")
    state.plan_id = uuid.uuid4()
    response = client.post(state.path(True), json=state.body(True), headers=headers)
    require(response.status_code == 201, "second revision identifier failed")
    require(state.writes() == 3 and len(state.cache.records) == 3, "revision IDs shared cache")
