"""异步任务 worker 入口（占位）：``python -m app.workers.worker``。"""

from __future__ import annotations

import sys

from app.workers.runner import run

if __name__ == "__main__":
    sys.exit(run("worker"))
