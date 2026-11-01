"""定时调度 beat 入口（占位）：``python -m app.workers.beat``。"""

from __future__ import annotations

import sys

from app.workers.runner import run

if __name__ == "__main__":
    sys.exit(run("beat"))
