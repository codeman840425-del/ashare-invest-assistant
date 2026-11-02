"""仓库内后端自检的公共部分（T-B46-x / T-B49 起）。

只连本机隔离的 PostgreSQL / Redis（``DATABASE_URL`` / ``REDIS_URL``，主机必须是 127.0.0.1 或
localhost），``APP_ENV`` 必须是 local/test；不访问外网、不调用任何行情接口，环境里有
``MAIRUI_LICENCE`` 直接拒绝运行。会 ``FLUSHDB`` 隔离 Redis，**不要并发运行多个自检**。

运行（目录 ``src/backend``）::

    env -u MAIRUI_LICENCE PYTHONPATH=$PWD .venv/bin/python selfchecks/tb49.py

输出逐条 ``PASS`` / ``FAIL``，最后一行 ``N passed, M failed``；有 FAIL 时退出码 1。
"""

from __future__ import annotations

import os
import sys
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Engine, create_engine, text

if os.environ.get("MAIRUI_LICENCE"):
    sys.exit("自检拒绝运行：环境里有 MAIRUI_LICENCE（请 env -u MAIRUI_LICENCE）")
if os.environ.get("APP_ENV", "local") not in {"local", "test"}:
    sys.exit("自检只能在 APP_ENV=local/test 运行")

DB: str = os.environ.get("DATABASE_URL", "")
RURL: str = os.environ.get("REDIS_URL", "")
for _name, _url in (("DATABASE_URL", DB), ("REDIS_URL", RURL)):
    if urlsplit(_url).hostname not in {"127.0.0.1", "localhost"}:
        sys.exit(f"自检只连本机隔离实例：{_name} 主机必须是 127.0.0.1/localhost")

_results: list[tuple[bool, str]] = []


def check(ok: object, name: str) -> None:
    _results.append((bool(ok), name))
    print(("PASS " if ok else "FAIL ") + name, flush=True)


def finish() -> None:
    bad = sum(1 for ok, _ in _results if not ok)
    print(f"{len(_results) - bad} passed, {bad} failed")
    sys.exit(1 if bad else 0)


_engine: Engine | None = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(DB)
    return _engine


def q(sql: str, **params: Any) -> Any:  # noqa: ANN401
    with engine().begin() as conn:
        return conn.execute(text(sql), params)


def err_code(resp: Any) -> str | None:  # noqa: ANN401
    try:
        return str(resp.json()["error"]["code"])
    except Exception:  # noqa: BLE001
        return None
