"""定时调度 beat 入口：``python -m app.workers.beat``（单副本）。

按 :func:`app.workers.jobs.schedule` 的间隔把任务放进 Redis 队列，由 worker 执行（T-B49）；
证券主数据按北京时间钟点排程并处理延迟重试（:func:`app.workers.jobs.beat_slots`，T-B52）。
"""

from __future__ import annotations

import sys

from app.config import Settings
from app.workers.jobs import TICK_S, beat_slots, beat_tick
from app.workers.runner import run


def _tick(settings: Settings) -> None:
    beat_tick(settings)
    beat_slots(settings)


if __name__ == "__main__":
    sys.exit(run("beat", tick=_tick, interval_s=TICK_S))
