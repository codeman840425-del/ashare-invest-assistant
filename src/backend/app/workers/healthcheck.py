"""容器健康检查：``python -m app.workers.healthcheck <worker|beat|ingest|signal-rt>``。

存活文件在 ``3 × 15`` 秒内更新过 → 退出码 0，否则 1。
"""

from __future__ import annotations

import sys
import time

from app.workers.runner import ALIVE_INTERVAL_S, alive_file

NAMES = ("worker", "beat", "ingest", "signal-rt")


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in NAMES:
        print(f"用法：python -m app.workers.healthcheck {{{'|'.join(NAMES)}}}", file=sys.stderr)
        return 2
    try:
        age = time.time() - alive_file(argv[0]).stat().st_mtime
    except FileNotFoundError:
        return 1
    return 0 if age <= 3 * ALIVE_INTERVAL_S else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
