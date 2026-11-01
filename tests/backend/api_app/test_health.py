"""健康检查：契约 v0.2.2 §7.10 / §9（与 v0.2 相同）+ T-B01 报告 §6 建议 6。

期望：
- ``GET /health/live`` → 200 ``{status:"ok"}``，不访问任何依赖；
- ``GET /health/ready`` → ``{status, db, redis, ingest, checked_at, version}``；db 或 redis 为 error → 503 + ``down``；
  只有 ingest 非 ok → 200 + ``degraded``；``/health`` 为别名；响应不用错误外壳；
- ingest 判定顺序：Redis 不可用 → unknown；``ingest:paused`` 存在 → paused；
  心跳（JSON ``{ts,…}``）缺失/无法解析/``now-ts>120`` → stale；否则 ok。

T-B01 现状只有 ``GET /health``（恒 200、心跳为纯数字、Redis 挂时 ingest=stale）。
凡 v0.2 行为未实现的用例在**运行时检测**后 ``pytest.xfail``，原因写明“T-B01 v0.2 修订”。
新后端（main a42bce7）用 ``ping`` + ``pipeline(transaction=False)`` 读 Redis，``FakeRedis`` 两种方式都支持。
依赖探测一律打桩（``stub_health``）或用假的 Redis 客户端 / 本机关闭端口，不连真实服务。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest

pytestmark = [pytest.mark.unit]

LIVE = "/api/v1/health/live"
READY = "/api/v1/health/ready"
ALIAS = "/api/v1/health"
READY_KEYS = {"status", "db", "redis", "ingest", "checked_at", "version"}
TODO = "T-B01 v0.2 修订未完成（契约 v0.2 §7.10）"


def _get_or_xfail(client, path: str):
    resp = client.get(path)
    if resp.status_code == 404:
        pytest.xfail(f"{TODO}：{path} 未实现")
    return resp


def _assert_ready(resp, http: int, status: str, db: str, redis: str, ingest: str) -> dict[str, Any]:
    body = resp.json()
    if "checked_at" not in body:
        pytest.xfail(f"{TODO}：响应缺 checked_at/version")
    assert set(body) == READY_KEYS
    assert "error" not in body
    assert (resp.status_code, body["status"], body["db"], body["redis"], body["ingest"]) == (http, status, db, redis, ingest)
    assert isinstance(body["version"], str) and body["version"]
    assert body["checked_at"].endswith("+08:00")  # 契约 §1：服务端统一输出 +08:00
    return body


@pytest.fixture
def client(make_client):
    return make_client()


# ---------------- /health/live ----------------
def test_live_ok_without_dependencies(client, backend, monkeypatch):
    async def explode(settings: Any) -> Any:
        raise AssertionError("/health/live 不得访问依赖")

    for name in ("check_db", "check_redis_and_ingest"):
        if hasattr(backend.health, name):
            monkeypatch.setattr(backend.health, name, explode)
    resp = _get_or_xfail(client, LIVE)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------- /health/ready 状态矩阵（打桩） ----------------
@pytest.mark.parametrize(
    ("db", "redis", "ingest", "http", "status"),
    [
        ("ok", "ok", "ok", 200, "ok"),
        ("ok", "ok", "stale", 200, "degraded"),
        ("ok", "ok", "paused", 200, "degraded"),
        ("error", "ok", "ok", 503, "down"),
        ("ok", "error", "unknown", 503, "down"),
        ("error", "error", "unknown", 503, "down"),
    ],
)
def test_ready_matrix(client, stub_health, db, redis, ingest, http, status):
    stub_health(db=db, redis=redis, ingest=ingest)
    resp = _get_or_xfail(client, READY)
    _assert_ready(resp, http, status, db, redis, ingest)


def test_alias_same_as_ready(client, stub_health):
    stub_health(db="error", redis="ok", ingest="ok")
    resp = client.get(ALIAS)
    _assert_ready(resp, 503, "down", "error", "ok", "ok")


def test_ready_no_auth_and_no_envelope_on_503(client, stub_health):
    stub_health(db="error", redis="error", ingest="unknown")
    resp = _get_or_xfail(client, READY)
    body = resp.json()
    assert "error" not in body
    assert "X-Request-Id" in resp.headers


# ---------------- 现状 /health（v0.2 下为别名，同样适用） ----------------
def test_health_shape_any_version(client, stub_health):
    stub_health()
    resp = client.get(ALIAS)
    assert resp.status_code == 200
    body = resp.json()
    assert {"status", "db", "redis", "ingest"} <= set(body) <= READY_KEYS
    assert body["status"] == "ok"


def test_health_dead_dependencies_real_probes(client):
    """不打桩：DATABASE_URL/REDIS_URL 指向本机关闭端口，真实探测应快速给出 error，且不泄露细节。"""
    t0 = time.perf_counter()
    resp = client.get(ALIAS)
    elapsed = time.perf_counter() - t0
    body = resp.json()
    assert body["db"] == "error" and body["redis"] == "error"
    assert body["ingest"] in {"stale", "unknown"}
    assert body["status"] in {"degraded", "down"}
    assert elapsed < 3.0
    for leak in ("127.0.0.1", "postgresql", "redis://", "Error", "refused"):
        assert leak not in resp.text


def test_health_missing_urls(make_client):
    resp = make_client(database_url=None, redis_url=None).get(ALIAS)
    body = resp.json()
    assert body["db"] == "error" and body["redis"] == "error"


def test_health_checks_time_out_in_parallel(backend, make_client, monkeypatch):
    """依赖“挂住”时：每个检查有超时且并行（T-B01 §6 建议 6：不超过约 2s）。"""
    import psycopg

    async def hang_connect(*a: Any, **k: Any) -> Any:
        await asyncio.sleep(10)

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", hang_connect)
    monkeypatch.setattr(backend.health.aioredis.Redis, "from_url", classmethod(lambda cls, *a, **k: FakeRedis(hang=True)))
    client = make_client(health_check_timeout_s=0.5)
    t0 = time.perf_counter()
    body = client.get(ALIAS).json()
    elapsed = time.perf_counter() - t0
    assert body["db"] == "error" and body["redis"] == "error"
    assert elapsed < 2.0, f"健康检查耗时 {elapsed:.2f}s"


# ---------------- ingest 心跳判定（假 Redis，走真实判定逻辑） ----------------
class FakeRedis:
    def __init__(self, store: dict[str, bytes] | None = None, *, down: bool = False, hang: bool = False) -> None:
        self.store = store or {}
        self.down = down
        self.hang = hang

    async def ping(self) -> bool:
        if self.hang:
            await asyncio.sleep(10)
        if self.down:
            raise ConnectionError("fake redis down")
        return True

    async def exists(self, *keys: str) -> int:
        return sum(1 for k in keys if k in self.store)

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def mget(self, *keys: Any) -> list[bytes | None]:
        flat = keys[0] if len(keys) == 1 and isinstance(keys[0], list | tuple) else keys
        return [self.store.get(k) for k in flat]

    def pipeline(self, transaction: bool = True) -> FakePipeline:
        return FakePipeline(self)

    async def aclose(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> FakeRedis:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


class FakePipeline:
    """redis.asyncio 管道的最小替身：exists/get 排队，execute 按顺序返回结果。"""

    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.ops: list[tuple[str, tuple[Any, ...]]] = []

    def exists(self, *keys: str) -> FakePipeline:
        self.ops.append(("exists", keys))
        return self

    def get(self, key: str) -> FakePipeline:
        self.ops.append(("get", (key,)))
        return self

    async def execute(self) -> list[Any]:
        if self.redis.hang:
            await asyncio.sleep(10)
        if self.redis.down:
            raise ConnectionError("fake redis down")
        out = [await getattr(self.redis, op)(*args) for op, args in self.ops]
        self.ops.clear()
        return out

    async def __aenter__(self) -> FakePipeline:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


@pytest.fixture
def with_fake_redis(backend, monkeypatch):
    async def db_ok(settings: Any) -> Any:
        return getattr(backend.health, "ComponentHealth", str)("ok")

    if hasattr(backend.health, "check_db"):
        monkeypatch.setattr(backend.health, "check_db", db_ok)

    def _install(fake: FakeRedis) -> None:
        monkeypatch.setattr(backend.health.aioredis.Redis, "from_url", classmethod(lambda cls, *a, **k: fake))

    return _install


def _hb(ts: float) -> bytes:
    return json.dumps({"ts": int(ts), "instance_id": "test-ingest-1", "leader": True, "version": "test",
                       "budget_used_last_minute": 0, "queue_depth": {"p0": 0, "p1": 0, "p2": 0}}).encode()


def _ingest(client) -> tuple[int, dict[str, Any]]:
    resp = client.get(ALIAS)
    return resp.status_code, resp.json()


def test_heartbeat_json_fresh_is_ok(client, with_fake_redis):
    with_fake_redis(FakeRedis({"ingest:heartbeat": _hb(time.time() - 5)}))
    _, body = _ingest(client)
    if body["ingest"] == "stale":
        pytest.xfail(f"{TODO}：心跳仍按纯数字解析，未支持 JSON {{ts,…}}")
    assert body["ingest"] == "ok"


@pytest.mark.parametrize(
    "value",
    [None, b"not-json", b"{}", b'{"ts": "abc"}'],
    ids=["missing", "garbage", "no_ts", "ts_not_number"],
)
def test_heartbeat_missing_or_unparseable_is_stale(client, with_fake_redis, value):
    store = {} if value is None else {"ingest:heartbeat": value}
    with_fake_redis(FakeRedis(store))
    _, body = _ingest(client)
    assert body["ingest"] == "stale"
    assert body["redis"] == "ok"


def test_heartbeat_older_than_120s_is_stale(client, with_fake_redis):
    with_fake_redis(FakeRedis({"ingest:heartbeat": _hb(time.time() - 121)}))
    assert _ingest(client)[1]["ingest"] == "stale"


def test_paused_takes_precedence(client, with_fake_redis):
    paused = json.dumps({"by": "admin-test", "at": "2026-11-01T10:00:00+08:00", "reason": "test"}).encode()
    with_fake_redis(FakeRedis({"ingest:paused": paused, "ingest:heartbeat": _hb(time.time())}))
    code, body = _ingest(client)
    assert body["ingest"] == "paused"
    assert body["status"] == "degraded"
    assert code == 200


def test_paused_with_stale_heartbeat_still_paused(client, with_fake_redis):
    with_fake_redis(FakeRedis({"ingest:paused": b"{}"}))
    assert _ingest(client)[1]["ingest"] == "paused"


def test_redis_down_ingest_unknown_and_503(client, with_fake_redis):
    with_fake_redis(FakeRedis(down=True))
    code, body = _ingest(client)
    assert body["redis"] == "error"
    if body["ingest"] == "stale" or code == 200:
        pytest.xfail(f"{TODO}：Redis 不可用时应 ingest=unknown、503 down（现状 stale、200 degraded）")
    assert (code, body["status"], body["ingest"]) == (503, "down", "unknown")


def test_custom_keys_and_threshold_from_settings(make_client, with_fake_redis):
    """键名与阈值可配置（INGEST_HEARTBEAT_KEY / INGEST_PAUSED_KEY / INGEST_STALE_AFTER_S）。"""
    client = make_client(ingest_heartbeat_key="hb:test", ingest_paused_key="paused:test", ingest_stale_after_s=10)
    with_fake_redis(FakeRedis({"ingest:paused": b"{}", "hb:test": _hb(time.time() - 30)}))
    assert _ingest(client)[1]["ingest"] == "stale"
