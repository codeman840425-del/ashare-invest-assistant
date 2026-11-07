"""占位进程的公共运行框架：配置校验、日志、存活文件、信号处理与优雅退出。"""

from __future__ import annotations

import logging
import os
import signal
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import FrameType

from app.common.logging import configure_logging
from app.config import Settings, get_settings

#: 每轮回调：返回 None；抛异常时记日志并继续（不让占位进程因一次失败退出）
Tick = Callable[[Settings], None]

ALIVE_INTERVAL_S = 15


def alive_file(name: str) -> Path:
    """存活文件路径（容器内本地文件；healthcheck 检查其修改时间）。"""
    base = os.environ.get("AIA_ALIVE_DIR") or tempfile.gettempdir()
    return Path(base) / f"aia-{name}.alive"


def run(name: str, tick: Tick | None = None, interval_s: float = ALIVE_INTERVAL_S) -> int:
    """常驻运行直到收到 SIGTERM / SIGINT；返回进程退出码。"""
    settings = get_settings()  # 与 api 相同：配置有未知键 / 缺文件时直接失败
    from app.db.migration_check import check_startup

    check_startup(settings)
    configure_logging(settings.log_level)
    log = logging.getLogger(f"app.workers.{name}")
    stop = threading.Event()

    def _on_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("收到信号 %s，准备退出", signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    path = alive_file(name)
    log.info("%s 启动（占位实现）pid=%s env=%s", name, os.getpid(), settings.app_env)
    while not stop.is_set():
        if tick is not None:
            try:
                tick(settings)
            except Exception as exc:  # noqa: BLE001  占位进程不因单次失败退出
                log.warning("%s 本轮执行失败：%s", name, type(exc).__name__)
        path.write_text(str(int(time.time())), encoding="ascii")
        log.info("%s 存活", name)
        stop.wait(interval_s)
    path.unlink(missing_ok=True)
    log.info("%s 已退出", name)
    return 0
