"""``GET /health``（契约 §7.10）：不需要登录、不含细节。

响应：``{status: "ok"|"degraded", db, redis, ingest: "ok"|"stale"|"paused"}``。
- 契约只给出 ``db: "ok"``、``redis: "ok"``，未定义失败取值；本实现失败时为 ``"error"``，
  并令 ``status="degraded"``（见 reports/T-B01.md「契约问题」）。
- HTTP 状态恒为 200（降级仍可服务）；只要进程能响应，容器健康检查即通过。
- 各依赖检查有超时（``HEALTH_CHECK_TIMEOUT_S``），并行执行；错误详情只写日志，不进响应。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Annotated, Literal

import psycopg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.config import Settings, get_settings

router = APIRouter(tags=["meta"])
logger = logging.getLogger("app.health")

DepState = Literal["ok", "error"]
IngestState = Literal["ok", "stale", "paused"]


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    db: DepState
    redis: DepState
    ingest: IngestState


def _psycopg_dsn(url: str) -> str:
    """SQLAlchemy 风格 ``postgresql+psycopg://`` → libpq 可识别的 ``postgresql://``。"""
    scheme, sep, rest = url.partition("://")
    if sep and "+" in scheme:
        scheme = scheme.split("+", 1)[0]
    return f"{scheme}{sep}{rest}"


async def check_db(settings: Settings) -> DepState:
    if settings.database_url is None:
        logger.warning("health: DATABASE_URL 未设置")
        return "error"
    dsn = _psycopg_dsn(settings.database_url.get_secret_value())
    timeout = settings.health_check_timeout_s
    try:
        async with asyncio.timeout(timeout):
            conn = await psycopg.AsyncConnection.connect(dsn, connect_timeout=max(1, int(timeout)))
            async with conn:
                cur = await conn.execute("SELECT 1")
                row = await cur.fetchone()
        return "ok" if row == (1,) else "error"
    except Exception as exc:  # noqa: BLE001 - 健康检查只关心成败；异常类型写日志，不含 DSN
        logger.warning("health: db check failed (%s)", type(exc).__name__)
        return "error"


def _parse_heartbeat(raw: bytes | str | None) -> float | None:
    if raw is None:
        return None
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    try:
        return float(text)
    except ValueError:
        return None


async def check_redis_and_ingest(settings: Settings) -> tuple[DepState, IngestState]:
    """一次连接内完成 PING 与 ingest 心跳读取。

    ingest 心跳约定（临时，待 T-B04a 落地时对齐）：
    - ``INGEST_PAUSED_KEY`` 存在 → ``paused``；
    - ``INGEST_HEARTBEAT_KEY`` 为 Unix 秒时间戳，距今 ≤ ``INGEST_STALE_AFTER_S`` → ``ok``；
    - 其余（缺失、无法解析、过旧、Redis 不可用）→ ``stale``。
    """
    if not settings.redis_url:
        logger.warning("health: REDIS_URL 未设置")
        return "error", "stale"
    timeout = settings.health_check_timeout_s
    client = aioredis.Redis.from_url(
        settings.redis_url, socket_connect_timeout=timeout, socket_timeout=timeout
    )
    try:
        async with asyncio.timeout(timeout * 2):
            await client.ping()
            paused = await client.exists(settings.ingest_paused_key)
            heartbeat = await client.get(settings.ingest_heartbeat_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("health: redis check failed (%s)", type(exc).__name__)
        return "error", "stale"
    finally:
        await client.aclose()

    if paused:
        return "ok", "paused"
    ts = _parse_heartbeat(heartbeat)
    if ts is not None and 0 <= time.time() - ts <= settings.ingest_stale_after_s:
        return "ok", "ok"
    return "ok", "stale"


@router.get("/health", response_model=HealthResponse, summary="健康检查")
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    db, (rds, ingest) = await asyncio.gather(check_db(settings), check_redis_and_ingest(settings))
    status: Literal["ok", "degraded"] = (
        "ok" if (db, rds, ingest) == ("ok", "ok", "ok") else "degraded"
    )
    return HealthResponse(status=status, db=db, redis=rds, ingest=ingest)
