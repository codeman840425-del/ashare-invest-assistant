#!/usr/bin/env python3
"""T-O67：在 CI 内置 PG 上准备 A2–A31 所需的模板库名（不打印 DSN/口令）。

正式用例硬编码从 ``o61_tmp_0030`` 克隆 ``tt51_tpl``（不可改 tests/）。
本脚本把已 migrate 的源库复制为该名字，仅用于本次一次性服务。
"""

from __future__ import annotations

import os
import sys

import psycopg


def _req(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        print(f"::error title=tt50-template::{name} 未设置", file=sys.stderr)
        sys.exit(1)
    return v


def main() -> int:
    host, port, user = _req("PGHOST"), _req("PGPORT"), _req("PGUSER")
    password = _req("PGPASSWORD")
    src = os.environ.get("AIA_TT50_SOURCE_DB", "aia")
    tpl_src = "o61_tmp_0030"
    selfcheck = os.environ.get("AIA_SELFCHECK_DB", "o67_selfcheck")

    # 不把完整连接串写进异常消息
    conn = psycopg.connect(
        host=host, port=port, user=user, password=password, dbname="postgres", autocommit=True
    )
    try:
        def exists(name: str) -> bool:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
                return cur.fetchone() is not None

        def term(name: str) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (name,),
                )

        if not exists(src):
            print("::error title=tt50-template::源库不存在，须先 alembic upgrade head", file=sys.stderr)
            return 1

        from psycopg import sql

        if not exists(tpl_src):
            term(src)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                        sql.Identifier(tpl_src), sql.Identifier(src)
                    )
                )

        if not exists(selfcheck):
            term(tpl_src)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                        sql.Identifier(selfcheck), sql.Identifier(tpl_src)
                    )
                )
    finally:
        conn.close()
    print("tt50-template: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
