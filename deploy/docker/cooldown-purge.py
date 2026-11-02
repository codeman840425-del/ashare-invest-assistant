"""定时清理到期的证书冷却记录（T-B10 部署项 / T-B03f 后续）：周期调用后端自己的
``app.licences.service.purge_expired_cooldowns``，不复制业务判定。

为什么在 deploy 里：beat 仍是占位（src/backend/app/workers/beat.py），改它属于后端；在 beat 落地定时任务前，
由 compose 服务 cooldown-purge（只读挂载本文件）以 aia_api 连库调用——aia_api 本来就在证书 PUT/DELETE 时
执行同一函数（cleanup-on-access），没有新增任何权限；不挂任何 secret，不用属主连接。

环境变量：
  DATABASE_URL                       必须（compose 里是 aia_api 连接串）
  AIA_COOLDOWN_PURGE_INTERVAL_S      间隔秒数，默认 3600，最小 60
  AIA_COOLDOWN_PURGE_ONCE=1          只跑一次并以 0/1 退出（演练、手动补跑）
  AIA_COOLDOWN_PURGE_HEARTBEAT       心跳文件，默认 /tmp/cooldown-purge.ok；成功一次就更新 mtime，
                                     健康检查要求它不早于 2×间隔+60 秒
日志不含连接串：异常只打印类型名。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path


def _log(**kw: object) -> None:
    kw = {"ts": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "job": "cooldown-purge", **kw}
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def run_once(engine, heartbeat: Path) -> bool:
    from app.licences.service import purge_expired_cooldowns

    try:
        with engine.begin() as conn:
            n = purge_expired_cooldowns(conn)
    except Exception as exc:  # noqa: BLE001 —— 只记类型，绝不打印连接串
        _log(level="error", error=type(exc).__name__)
        return False
    heartbeat.touch()
    _log(level="info", purged=n)
    return True


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        _log(level="error", error="DATABASE_URL 未设置")
        return 2
    interval = max(60, int(os.environ.get("AIA_COOLDOWN_PURGE_INTERVAL_S", "3600")))
    heartbeat = Path(os.environ.get("AIA_COOLDOWN_PURGE_HEARTBEAT", "/tmp/cooldown-purge.ok"))
    import sqlalchemy as sa

    engine = sa.create_engine(url, pool_pre_ping=True, pool_size=1, max_overflow=0)
    if os.environ.get("AIA_COOLDOWN_PURGE_ONCE") == "1":
        return 0 if run_once(engine, heartbeat) else 1
    _log(level="info", msg="started", interval_s=interval)
    while True:
        run_once(engine, heartbeat)
        time.sleep(interval)


def healthcheck() -> int:
    interval = max(60, int(os.environ.get("AIA_COOLDOWN_PURGE_INTERVAL_S", "3600")))
    hb = Path(os.environ.get("AIA_COOLDOWN_PURGE_HEARTBEAT", "/tmp/cooldown-purge.ok"))
    try:
        age = time.time() - hb.stat().st_mtime
    except FileNotFoundError:
        return 1
    return 0 if age <= 2 * interval + 60 else 1


if __name__ == "__main__":
    sys.exit(healthcheck() if sys.argv[1:] == ["health"] else main())
