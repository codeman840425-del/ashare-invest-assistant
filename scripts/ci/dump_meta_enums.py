#!/usr/bin/env python3
"""在进程内调用后端 ``GET /api/v1/meta/enums``，把响应写到文件（契约对照用）。

必须用后端虚拟环境的解释器、在 src/backend 目录下运行：
    cd src/backend && uv run --frozen python ../../scripts/ci/dump_meta_enums.py OUT.json
不连接数据库、Redis 或任何外部服务。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def main() -> int:
    out = Path(sys.argv[1])
    sys.path.insert(0, str(Path.cwd()))
    from app.config import Settings
    from app.main import create_app

    # Export static route data before CI migrations; never inherit database/Redis access.
    settings = Settings(app_env="test", database_url=None, redis_url=None, _env_file=None)
    with TestClient(create_app(settings)) as client:
        prefix = client.app.openapi_url.rsplit("/", 1)[0]  # type: ignore[attr-defined]
        resp = client.get(f"{prefix}/meta/enums")
    if resp.status_code != 200:
        print(f"::error title=meta-enums::GET {prefix}/meta/enums -> {resp.status_code}")
        return 1
    out.write_text(json.dumps(resp.json(), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已写入 {out}（{len(resp.content)} 字节）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
