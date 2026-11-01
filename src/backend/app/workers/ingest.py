"""行情采集 ingest 入口（占位）：``python -m app.workers.ingest``。

占位实现**不发任何外部请求**（不调用麦蕊，不读取 licence），只按契约 v0.2 §7.10 每
``ingest.yaml`` 的 ``heartbeat.interval_s``（默认 15 秒）写一次 Redis 心跳：
``SET <heartbeat.key> <json> EX <heartbeat.ttl_s>``，JSON 为
``{"ts", "instance_id", "leader", "version", "budget_used_last_minute", "queue_depth"}``。
键名可由环境变量 ``INGEST_HEARTBEAT_KEY`` 覆盖（与 /health/ready 读取同一个设置）。

T-A07（plan §2.1B 第 7 点、契约 v0.2.6）：生产与预发**不再使用**全站 ``MAIRUI_LICENCE``，
每位用户的证书以 HPKE 密文存库。``ingest`` 发现环境变量 ``MAIRUI_LICENCE`` 非空即**拒绝启动**
（退出码 78 = EX_CONFIG），且不输出它的值、长度或任何片段。只有本机实测脚本（``probes/``，
不属于本服务）可以在用户本人电脑的 shell 中临时设置它。
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from collections.abc import Mapping

import redis

from app.config import Settings
from app.version import APP_VERSION
from app.workers.runner import run

INSTANCE_ID = f"{socket.gethostname()}:{os.getpid()}"

#: 已废弃的全站证书变量（T-A07）；只判断是否非空，从不读取或输出它的值
LEGACY_LICENCE_ENV = "MAIRUI_LICENCE"
#: sysexits.h EX_CONFIG
EXIT_LEGACY_LICENCE = 78
LEGACY_LICENCE_MESSAGE = (
    "ingest 拒绝启动：环境变量 MAIRUI_LICENCE 非空。T-A07 起每位用户的麦蕊证书加密存库"
    "（plan §2.1B），生产与预发不再使用全站证书；请从 compose / env 文件中删除该变量"
)


def legacy_licence_present(environ: Mapping[str, str] | None = None) -> bool:
    """``MAIRUI_LICENCE`` 是否非空（去首尾空白后）。只返回布尔值。"""
    env = os.environ if environ is None else environ
    return bool(env.get(LEGACY_LICENCE_ENV, "").strip())


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
    if legacy_licence_present():
        # 在读取配置、建立任何连接之前退出；消息不含变量值
        print(LEGACY_LICENCE_MESSAGE, file=sys.stderr)
        return EXIT_LEGACY_LICENCE

    from app.config import get_settings

    interval = get_settings().business.ingest.heartbeat.interval_s
    return run("ingest", tick=write_heartbeat, interval_s=interval)


if __name__ == "__main__":
    sys.exit(main())
