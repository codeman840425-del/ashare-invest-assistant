"""beat → worker 的定时任务（T-B49）：beat 按间隔把任务放进 Redis 队列，worker 取出执行。

项目里没有 Celery；沿用 ``app.workers.runner.run(name, tick, interval_s)`` 的占位框架：

- **beat**（``python -m app.workers.beat``，单副本）每轮对 :func:`schedule` 里每个任务做
  ``SET beat:due:<task> <ts> NX EX <interval>``：设置成功（上一次排程已超过间隔，或首次启动）才
  ``LPUSH`` 一条任务到 :data:`QUEUE_KEY`。到期键放在 Redis 里，beat 重启不会立刻重排，
  也不会因多副本而重复排程。
- **worker**（``python -m app.workers.worker``）每轮最多取 :data:`MAX_JOBS_PER_TICK` 条
  （``RPOP``，先进先出）并执行；未知任务名只记日志后丢弃。任务执行失败只记异常类型，不重试
  （下一次排程会再跑；清理类任务幂等）。
- 队列元素是 JSON ``{"task": <名称>, "enqueued_at": <unix 秒>}``，不含任何用户数据或密钥。

当前任务：

- ``licences.purge_expired_cooldowns``：调用 :func:`app.licences.service.purge_expired_cooldowns`
  删除已到期的证书冷却记录（review-a8e055b M1；取代 deploy 的 cooldown-purge 服务）。间隔
  ``Settings.cooldown_purge_interval_s``（``COOLDOWN_PURGE_INTERVAL_S``，默认 3600，最小 60）。
- ``imports.purge_uncommitted_rows``：调用
  :func:`app.importing.pipeline.purge_uncommitted_import_rows` 删除 discarded / failed 批次残留的
  预览行（架构师裁定，T-live-83a031c §8）。间隔 ``Settings.import_rows_purge_interval_s``
  （``IMPORT_ROWS_PURGE_INTERVAL_S``，默认 3600，最小 60）。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Final

import redis
from sqlalchemy import Engine

from app.config import Settings
from app.db.engine import engine_for

log = logging.getLogger("app.workers.jobs")

QUEUE_KEY: Final = "jobs:worker"
DUE_PREFIX: Final = "beat:due:"
MAX_JOBS_PER_TICK: Final = 20
#: beat / worker 的轮询间隔（秒）；任务真正的间隔由 SCHEDULE 决定
TICK_S: Final = 15

PURGE_COOLDOWNS: Final = "licences.purge_expired_cooldowns"
PURGE_IMPORT_ROWS: Final = "imports.purge_uncommitted_rows"

Task = Callable[[Settings], int]


def _redis(settings: Settings) -> redis.Redis:
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL 未设置")
    t = settings.health_check_timeout_s
    return redis.Redis.from_url(settings.redis_url, socket_connect_timeout=t, socket_timeout=t)


_engines: dict[str, Engine] = {}


def _engine(settings: Settings) -> Engine:
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL 未设置")
    url = settings.database_url.get_secret_value()
    eng = _engines.get(url)
    if eng is None:
        eng = _engines[url] = engine_for(url)
    return eng


def purge_expired_cooldowns_task(settings: Settings) -> int:
    from app.licences.service import purge_expired_cooldowns

    with _engine(settings).begin() as conn:
        return purge_expired_cooldowns(conn)


def purge_import_rows_task(settings: Settings) -> int:
    from app.importing.pipeline import purge_uncommitted_import_rows

    with _engine(settings).begin() as conn:
        return purge_uncommitted_import_rows(conn)


#: 任务名 → 实现
TASKS: Final[dict[str, Task]] = {
    PURGE_COOLDOWNS: purge_expired_cooldowns_task,
    PURGE_IMPORT_ROWS: purge_import_rows_task,
}


def schedule(settings: Settings) -> dict[str, int]:
    """任务名 → 间隔秒数（beat 排程表；间隔来自配置）。"""
    return {
        PURGE_COOLDOWNS: settings.cooldown_purge_interval_s,
        PURGE_IMPORT_ROWS: settings.import_rows_purge_interval_s,
    }


def beat_tick(settings: Settings, client: redis.Redis | None = None) -> list[str]:
    """排程到期的任务，返回本轮放进队列的任务名。"""
    r = client or _redis(settings)
    now = int(time.time())
    queued: list[str] = []
    try:
        for task, interval in schedule(settings).items():
            if r.set(DUE_PREFIX + task, now, nx=True, ex=interval):
                r.lpush(QUEUE_KEY, json.dumps({"task": task, "enqueued_at": now}))
                queued.append(task)
                log.info("beat 排程 %s（间隔 %ss）", task, interval)
    finally:
        if client is None:
            r.close()
    return queued


def worker_tick(settings: Settings, client: redis.Redis | None = None) -> list[tuple[str, str]]:
    """执行队列里的任务，返回 ``[(任务名, ok / failed / unknown / bad_payload)]``。"""
    r = client or _redis(settings)
    done: list[tuple[str, str]] = []
    try:
        for _ in range(MAX_JOBS_PER_TICK):
            raw = r.rpop(QUEUE_KEY)
            if raw is None:
                break
            try:
                task = str(json.loads(raw)["task"])  # type: ignore[arg-type]
            except (ValueError, KeyError, TypeError):
                log.warning("worker 丢弃无法解析的任务")
                done.append(("", "bad_payload"))
                continue
            fn = TASKS.get(task)
            if fn is None:
                log.warning("worker 丢弃未知任务 %s", task[:64])
                done.append((task[:64], "unknown"))
                continue
            try:
                n = fn(settings)
            except Exception as exc:  # noqa: BLE001  只记类型，不输出连接串或参数
                log.warning("worker 任务 %s 失败：%s", task, type(exc).__name__)
                done.append((task, "failed"))
                continue
            log.info("worker 任务 %s 完成：%s", task, n)
            done.append((task, "ok"))
    finally:
        if client is None:
            r.close()
    return done
