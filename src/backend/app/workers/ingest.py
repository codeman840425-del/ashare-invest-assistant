"""行情采集 ingest 入口（占位）：``python -m app.workers.ingest``。

占位实现**不发任何外部请求**（不调用麦蕊，不读取 licence），只按契约 v0.2 §7.10 每
``ingest.yaml`` 的 ``heartbeat.interval_s``（默认 15 秒）写一次 Redis 心跳：
``SET <heartbeat.key> <json> EX <heartbeat.ttl_s>``，JSON 为
``{"ts", "instance_id", "leader", "version", "budget_used_last_minute", "queue_depth"}``。
键名可由环境变量 ``INGEST_HEARTBEAT_KEY`` 覆盖（与 /health/ready 读取同一个设置）。
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time

import redis

from app.config import Settings
from app.version import APP_VERSION
from app.workers.runner import run

INSTANCE_ID = f"{socket.gethostname()}:{os.getpid()}"


def heartbeat_payload(now: float | None = None) -> str:
    return json.dumps(
        {
            "ts": int(time.time() if now is None else now),
            "instance_id": INSTANCE_ID,
            "leader": True,
            "version": APP_VERSION,
            "budget_used_last_minute": 0,
            "queue_depth": {"p0": 0, "p1": 0, "p2": 0},
        },
        separators=(",", ":"),
    )


def write_heartbeat(settings: Settings) -> None:
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL 未设置")
    hb = settings.business.ingest.heartbeat
    timeout = settings.health_check_timeout_s
    client = redis.Redis.from_url(
        settings.redis_url, socket_connect_timeout=timeout, socket_timeout=timeout
    )
    try:
        client.set(settings.ingest_heartbeat_key, heartbeat_payload(), ex=hb.ttl_s)
    finally:
        client.close()


def main() -> int:
    from app.config import get_settings

    interval = get_settings().business.ingest.heartbeat.interval_s
    return run("ingest", tick=write_heartbeat, interval_s=interval)


if __name__ == "__main__":
    sys.exit(main())
