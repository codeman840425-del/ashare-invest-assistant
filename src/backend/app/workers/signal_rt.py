"""盘中实时信号 signal-rt 入口（占位）：``python -m app.workers.signal_rt``。"""

from __future__ import annotations

import sys

from app.workers.runner import run

if __name__ == "__main__":
    sys.exit(run("signal-rt"))
