"""健康检查（契约 §7.10，v0.2）。

- ``GET /health/live``：存活检查，恒 200 ``{"status": "ok"}``，不访问任何依赖。
- ``GET /health/ready``：就绪检查 ``{status, db, redis, ingest, checked_at, version}``：

  - db 与 redis 都为 ``ok`` → 200；此时 ingest 非 ``ok`` 则 ``status="degraded"``，否则 ``"ok"``；
  - db 或 redis 为 ``error`` → 503，``status="down"``；
  - 响应体不用 §2 错误外壳（503 也返回健康结构），不含错误细节（异常类型只写日志）；
  - 每个依赖检查超时 ``HEALTH_CHECK_TIMEOUT_S``（默认 1 秒），db 与 redis 并行。
- ``GET /health``：``/health/ready`` 的别名。

ingest 判定顺序（契约 §7.10）：Redis 不可用 → ``unknown``；``ingest:paused`` 存在 → ``paused``；
心跳缺失、JSON 无法解析、缺 ``ts`` 或 ``now - ts > INGEST_STALE_AFTER_S`` → ``stale``；否则 ``ok``。
键名与阈值：环境变量 > ``config/ingest.yaml`` 的 ``heartbeat`` 段（见 :mod:`app.config`）。
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import time
from typing import Annotated, Literal

import psycopg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.config import Settings, get_settings
from app.schemas.enums import ComponentHealth, HealthStatus, IngestHealth
from app.version import APP_VERSION

router = APIRouter(tags=["meta"])
logger = logging.getLogger("app.health")

#: 契约 §1：服务端时间统一输出 +08:00
BEIJING = dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")


class LiveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


class ReadyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: HealthStatus
    db: ComponentHealth
    redis: ComponentHealth
    ingest: IngestHealth
    checked_at: dt.datetime
    version: str


def _psycopg_dsn(url: str) -> str:
    """SQLAlchemy 风格 ``postgresql+psycopg://`` → libpq 可识别的 ``postgresql://``。"""
    scheme, sep, rest = url.partition("://")
    if sep and "+" in scheme:
        scheme = scheme.split("+", 1)[0]
    return f"{scheme}{sep}{rest}"


_warned_unset: set[str] = set()


def _warn_unset_once(name: str) -> None:
    """未配置的依赖只告警一次，避免探测刷屏（评审 S6）。"""
    if name not in _warned_unset:
        _warned_unset.add(name)
        logger.warning("health: %s 未设置，该依赖按 error 处理", name)


async def check_db(settings: Settings) -> ComponentHealth:
    if settings.database_url is None:
        _warn_unset_once("DATABASE_URL")
        return ComponentHealth.ERROR
    dsn = _psycopg_dsn(settings.database_url.get_secret_value())
    timeout = settings.health_check_timeout_s
    try:
        async with asyncio.timeout(timeout):
            conn = await psycopg.AsyncConnection.connect(dsn, connect_timeout=max(1, int(timeout)))
            async with conn:
                cur = await conn.execute("SELECT 1")
                row = await cur.fetchone()
        return ComponentHealth.OK if row == (1,) else ComponentHealth.ERROR
    except Exception as exc:  # noqa: BLE001 - 健康检查只关心成败；异常类型写日志，不含 DSN
        logger.warning("health: db check failed (%s)", type(exc).__name__)
        return ComponentHealth.ERROR


def parse_heartbeat_ts(raw: bytes | str | None) -> int | None:
    """心跳 JSON 的 ``ts``（Unix 秒，整数）；缺失或无法解析返回 ``None``。

    契约 §7.10：值为 JSON 对象，api 只依赖 ``ts``。布尔、浮点、字符串形式的 ts 都视为无法解析。
    """
    if raw is None:
        return None
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    ts = payload.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, int):
        return None
    return ts


def ingest_state(
    *, paused: bool, heartbeat: bytes | str | None, stale_after_s: int, now: float
) -> IngestHealth:
    if paused:
        return IngestHealth.PAUSED
    ts = parse_heartbeat_ts(heartbeat)
    if ts is None or now - ts > stale_after_s:
        return IngestHealth.STALE
    return IngestHealth.OK


async def check_redis_and_ingest(settings: Settings) -> tuple[ComponentHealth, IngestHealth]:
    """一次连接内完成 PING 与 ingest 键读取；Redis 不可用时 ingest 为 ``unknown``。"""
    if not settings.redis_url:
        _warn_unset_once("REDIS_URL")
        return ComponentHealth.ERROR, IngestHealth.UNKNOWN
    timeout = settings.health_check_timeout_s
    client = aioredis.Redis.from_url(
        settings.redis_url, socket_connect_timeout=timeout, socket_timeout=timeout
    )
    try:
        async with asyncio.timeout(timeout):
            await client.ping()
            async with client.pipeline(transaction=False) as pipe:
                pipe.exists(settings.ingest_paused_key)
                pipe.get(settings.ingest_heartbeat_key)
                paused, heartbeat = await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("health: redis check failed (%s)", type(exc).__name__)
        return ComponentHealth.ERROR, IngestHealth.UNKNOWN
    finally:
        await client.aclose()

    state = ingest_state(
        paused=bool(paused),
        heartbeat=heartbeat,
        stale_after_s=settings.ingest_stale_after_s,
        now=time.time(),
    )
    return ComponentHealth.OK, state


def overall_status(db: ComponentHealth, rds: ComponentHealth, ingest: IngestHealth) -> HealthStatus:
    if db is not ComponentHealth.OK or rds is not ComponentHealth.OK:
        return HealthStatus.DOWN
    if ingest is not IngestHealth.OK:
        return HealthStatus.DEGRADED
    return HealthStatus.OK


@router.get("/health/live", response_model=LiveResponse, summary="存活检查（不访问依赖）")
async def health_live() -> LiveResponse:
    return LiveResponse(status="ok")


async def _ready(settings: Settings) -> JSONResponse:
    db, (rds, ingest) = await asyncio.gather(check_db(settings), check_redis_and_ingest(settings))
    status = overall_status(db, rds, ingest)
    body = ReadyResponse(
        status=status,
        db=db,
        redis=rds,
        ingest=ingest,
        checked_at=dt.datetime.now(BEIJING).replace(microsecond=0),
        version=APP_VERSION,
    )
    return JSONResponse(
        body.model_dump(mode="json"),
        status_code=503 if status is HealthStatus.DOWN else 200,
    )


_READY_DOC: dict[int | str, dict[str, object]] = {
    503: {"model": ReadyResponse, "description": "db 或 redis 不可用（status=down，非错误外壳）"}
}


@router.get(
    "/health/ready",
    response_model=ReadyResponse,
    responses=_READY_DOC,
    summary="就绪检查",
)
async def health_ready(settings: Annotated[Settings, Depends(get_settings)]) -> JSONResponse:
    return await _ready(settings)


@router.get(
    "/health",
    response_model=ReadyResponse,
    responses=_READY_DOC,
    summary="就绪检查（/health/ready 的别名）",
)
async def health_alias(settings: Annotated[Settings, Depends(get_settings)]) -> JSONResponse:
    return await _ready(settings)
