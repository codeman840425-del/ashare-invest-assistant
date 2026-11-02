"""异步任务 worker 入口：``python -m app.workers.worker``。

执行 beat 放进 Redis 队列的任务（:mod:`app.workers.jobs`，T-B49）。
"""

from __future__ import annotations

import sys

from app.config import Settings
from app.workers.jobs import TICK_S, worker_tick
from app.workers.runner import run


def _tick(settings: Settings) -> None:
    worker_tick(settings)


if __name__ == "__main__":
    sys.exit(run("worker", tick=_tick, interval_s=TICK_S))
