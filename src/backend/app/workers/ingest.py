"""行情采集 ingest 入口（占位）：``python -m app.workers.ingest``。

按契约写 Redis 心跳；replay 或管理员暂停时不调麦蕊。T-B99 的 live 接线复用本循环：
本人验证意图需独立的一次性验证回执、设置开关、有效本人证书及共享门禁；名单沿用三次回执。
名单与验证逐次发送前重读全局暂停，且共用单出口互斥、证书稳定标识预算与持久停机；等待时续心跳。
心跳键由 ``INGEST_HEARTBEAT_KEY`` 覆盖（与 /health/ready 使用同一设置）。

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


#: T-B49（T-O11 裁定）：ingest 不得持有 APP_MASTER_KEY；发现即拒绝启动（同样退出码 78）
MASTER_KEY_ENV = "APP_MASTER_KEY"
MASTER_KEY_MESSAGE = (
    "ingest 拒绝启动：发现 APP_MASTER_KEY。主密钥只给 api / worker，ingest 不得派生任何 HMAC / "
    "签名密钥；请从 ingest 的 environment / secrets 中删除它"
)


def master_key_present(environ: Mapping[str, str] | None = None) -> bool:
    """环境里是否有非空 ``APP_MASTER_KEY``。只返回布尔值。"""
    env = os.environ if environ is None else environ
    return bool(env.get(MASTER_KEY_ENV, "").strip())


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
        from app.db.engine import engine_for
        from app.ingest.daily_lists import tick
        from app.ingest.live import sync_halts
        from app.ingest.verification import tick as verify_tick

        # Live verification uses owned intents and its settings gate; daily lists
        # additionally require the operator receipt. Replay keeps both paths closed.
        def heartbeat_wait(seconds: float) -> None:
            import time

            remaining = seconds
            while remaining > 0:
                client.set(settings.ingest_heartbeat_key, heartbeat_payload(), ex=hb.ttl_s)
                duration = min(1, remaining)
                time.sleep(duration)
                remaining -= duration

        if settings.database_url is not None:
            engine = engine_for(settings.database_url.get_secret_value())
            try:
                shared_root = os.environ.get("MAIRUI_SHARED_STATE_DIR")
                if shared_root:
                    from pathlib import Path

                    sync_halts(engine, settings, client, Path(shared_root))
                if (
                    os.environ.get("MAIRUI_MODE", "replay") == "live"
                    and not client.exists(settings.ingest_paused_key)
                ):
                    verify_tick(engine, client, settings)
                    tick(engine, client, pause=heartbeat_wait, settings=settings)
            finally:
                engine.dispose()
    finally:
        client.close()


def main() -> int:
    if legacy_licence_present():
        # 在读取配置、建立任何连接之前退出；消息不含变量值
        print(LEGACY_LICENCE_MESSAGE, file=sys.stderr)
        return EXIT_LEGACY_LICENCE
    if master_key_present():
        print(MASTER_KEY_MESSAGE, file=sys.stderr)
        return EXIT_LEGACY_LICENCE

    from app.config import get_settings

    # 主密钥若来自其他配置来源（secret 文件等），Settings 校验同样拒绝（SERVICE_NAME=ingest）
    interval = get_settings().business.ingest.heartbeat.interval_s
    return run("ingest", tick=write_heartbeat, interval_s=interval)


if __name__ == "__main__":
    sys.exit(main())
