"""Only owned Unix PG/Redis, fake sessions; actual worker and HTTP read chain."""

# ruff: noqa: S101,S108,ANN401
from __future__ import annotations

import datetime as dt
import secrets
import socket
from pathlib import Path
from typing import Any

import pytest
import redis
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, text, update

from app.config import Settings
from app.db.tables.accounts import accounts
from app.db.tables.market import trading_calendar
from app.db.tables.strategy import strategy_instances, strategy_versions
from app.db.tables.users import users
from app.feedback.worker import TASK
from app.main import create_app
from app.workers import jobs
from selfchecks import test_p2n08_pause as shared
from selfchecks.test_p2n08_pause import env as env
from selfchecks.test_p2n08_pause import pg as pg

SOCKET = "/tmp/p2n08-s3-owned/pg"
REDIS = "unix:///tmp/p2n08-s3-owned/redis/redis.sock?db=0"


@pytest.fixture(autouse=True)
def confined(monkeypatch: Any) -> None:
    monkeypatch.setattr(shared, "SOCKET", SOCKET)
    original = socket.socket.connect

    def guarded(sock: socket.socket, address: Any) -> Any:
        assert sock.family == socket.AF_UNIX
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture
def http(env: Any, tmp_path: Path) -> Any:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr(env[1].url.render_as_string(hide_password=False)),
        redis_url=REDIS,
        app_env="test",
        session_cookie_secure=False,
        app_master_key=SecretStr(secrets.token_urlsafe(32)),
        import_storage_path=tmp_path,
    )
    clients = [TestClient(create_app(settings)), TestClient(create_app(settings))]
    password = secrets.token_urlsafe(24) + "7a"
    for uid, client in zip((env[2], env[3]), clients, strict=True):
        with env[1].begin() as c:
            c.execute(
                update(users)
                .where(users.c.id == uid)
                .values(password_hash=PasswordHasher().hash(password))
            )
            username = c.execute(select(users.c.username).where(users.c.id == uid)).scalar_one()
        response = client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    try:
        yield settings, clients[0], clients[1]
    finally:
        for client in clients:
            client.close()
        jobs._engine(settings).dispose()


def deliver(settings: Settings, r: Any) -> None:
    jobs._push(r, TASK)
    assert (TASK, "ok") in jobs.worker_tick(settings, r)


@pytest.mark.parametrize(("case", "expected"), shared.cases("-092"))
def test_real_beat_redis_expiry_http_and_golden092(
    env: Any, http: Any, monkeypatch: Any, case: Any, expected: Any
) -> None:
    settings, client, stranger = http
    assert shared.apply(env, shared.receipt(env, shared.BASE, 2), shared.BASE).changed is False
    point = shared.BASE + dt.timedelta(hours=1)
    assert shared.apply(env, shared.receipt(env, point, 3), point).changed
    until = shared.state(env).paused_until
    with env[0].begin() as c:
        c.execute(
            update(strategy_versions)
            .where(strategy_versions.c.id == env[5])
            .values(lifecycle=case["lifecycle"])
        )
        if not case["calendar_available"]:
            c.execute(trading_calendar.delete())
    with env[1].connect() as c:
        assert c.execute(text("SELECT current_user")).scalar_one() == "aia_api"
        assert (
            c.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")).scalar_one()
            is False
        )
    clock = [until - dt.timedelta(microseconds=1)]
    monkeypatch.setattr(jobs, "_now", lambda: clock[0])
    original = jobs.schedule(settings)
    assert TASK in original
    monkeypatch.setattr(jobs, "schedule", lambda _: {TASK: original[TASK]})
    r = redis.Redis.from_url(REDIS)
    path = f"/api/v1/strategy-instances/{env[6]}"
    try:
        r.delete(jobs.QUEUE_KEY, jobs.DUE_PREFIX + TASK)
        assert jobs.beat_tick(settings, r) == [TASK]
        assert (TASK, "ok") in jobs.worker_tick(settings, r)
        assert client.get(path).json()["status"] == "paused"
        for operand in shared.OPERANDS[:2]:
            clock[0] = until - dt.timedelta(microseconds=abs(operand["delta"]) + 1)
            deliver(settings, r)
            assert shared.state(env).status == "paused"
        clock[0] = dt.datetime.fromisoformat(case["now"])
        deliver(settings, r)
        response = client.get(path)
        assert response.status_code == 200
        value = response.json()
        assert value["status"] == expected["status"]
        assert value["pause_reason_code"] == expected["reason"]
        assert (
            dt.datetime.fromisoformat(value["paused_until"]) if value["paused_until"] else None
        ) == (
            dt.datetime.fromisoformat(expected["paused_until"])
            if expected["paused_until"]
            else None
        )
        assert client.get("/api/v1/notifications/unread-count").json()["count"] == int(
            expected["blocked_notification_required"]
        )
        assert stranger.get(path).status_code == 404
        assert stranger.get("/api/v1/notifications/unread-count").json()["count"] == 0
        before = shared.counts(env)
        deliver(settings, r)
        assert client.get(path).json() == value
        assert shared.counts(env) == before
        assert shared.state(env).status == expected["status"]
        with env[1].connect() as c:
            assert (
                c.execute(
                    select(strategy_versions.c.lifecycle).where(strategy_versions.c.id == env[5])
                ).scalar_one()
                == case["lifecycle"]
            )
        with TestClient(client.app) as anonymous:
            assert anonymous.get(path).status_code == 401
    finally:
        r.delete(jobs.QUEUE_KEY, jobs.DUE_PREFIX + TASK)
        r.close()


def test_worker_preserves_manual_pause_and_rechecks_account_and_user(
    env: Any, http: Any, monkeypatch: Any
) -> None:
    settings, client, _ = http
    shared.apply(env, shared.receipt(env, shared.BASE, 2), shared.BASE)
    point = shared.BASE + dt.timedelta(hours=1)
    assert shared.apply(env, shared.receipt(env, point, 3), point).changed
    until = shared.state(env).paused_until
    path = f"/api/v1/strategy-instances/{env[6]}"
    assert client.post(path + "/resume").status_code == 200
    assert client.post(path + "/pause").status_code == 200
    assert client.get(path).json()["paused_by"] == "user"
    monkeypatch.setattr(jobs, "_now", lambda: until)
    r = redis.Redis.from_url(REDIS)
    try:
        before = shared.counts(env)
        deliver(settings, r)
        assert shared.state(env).paused_by == "user"
        assert shared.counts(env) == before
        # Synthetic corruption/revocation must not turn a foreign/revoked account
        # into a runnable owned instance; no actual account is changed.
        with env[0].begin() as c:
            c.execute(
                update(strategy_instances)
                .where(strategy_instances.c.id == env[6])
                .values(
                    paused_by="system", pause_reason_code="LOSS_STREAK_PAUSE", paused_until=until
                )
            )
            c.execute(update(accounts).where(accounts.c.id == env[4]).values(user_id=env[3]))
        deliver(settings, r)
        assert shared.state(env).status == "paused"
        assert shared.counts(env) == before
        with env[0].begin() as c:
            c.execute(update(accounts).where(accounts.c.id == env[4]).values(user_id=env[2]))
            c.execute(update(users).where(users.c.id == env[2]).values(status="pending"))
        deliver(settings, r)
        assert shared.state(env).status == "paused"
        assert shared.counts(env) == before
        with env[0].begin() as c:
            c.execute(update(users).where(users.c.id == env[2]).values(status="approved"))
            c.execute(update(accounts).where(accounts.c.id == env[4]).values(archived_at=until))
        deliver(settings, r)
        assert shared.state(env).status == "paused"
        assert shared.counts(env) == before
    finally:
        r.delete(jobs.QUEUE_KEY, jobs.DUE_PREFIX + TASK)
        r.close()
