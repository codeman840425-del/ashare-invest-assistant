"""测试库容器示例（T-T01）：PostgreSQL 16 + TimescaleDB、Redis 7。

Docker 不可用时整个模块 skip（见 backend/conftest.py）。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_postgres_is_16_with_timescaledb(pg_conn) -> None:  # type: ignore[no-untyped-def]
    with pg_conn.cursor() as cur:
        cur.execute("show server_version_num")
        (version_num,) = cur.fetchone()
        assert int(version_num) // 10000 == 16

        cur.execute("create extension if not exists timescaledb")
        cur.execute("select extversion from pg_extension where extname = 'timescaledb'")
        row = cur.fetchone()
        assert row is not None and row[0].startswith("2.")


def test_hypertable_roundtrip_is_rolled_back(pg_conn) -> None:  # type: ignore[no-untyped-def]
    """演示：用例内建表写数，fixture 结束时回滚，不污染其他用例。"""
    with pg_conn.cursor() as cur:
        cur.execute("create extension if not exists timescaledb")
        cur.execute(
            "create table t_quote_demo (ts timestamptz not null, security_code text not null, price numeric(12,3))"
        )
        cur.execute("select create_hypertable('t_quote_demo', 'ts')")
        cur.execute(
            "insert into t_quote_demo values ('2026-11-02 09:31:00+08', '600000.SH', 10.250)"
        )
        cur.execute("select count(*), max(price)::text from t_quote_demo")
        assert cur.fetchone() == (1, "10.250")


def test_table_from_previous_case_is_gone(pg_conn) -> None:  # type: ignore[no-untyped-def]
    with pg_conn.cursor() as cur:
        cur.execute("select to_regclass('public.t_quote_demo')")
        assert cur.fetchone() == (None,)


def test_redis_ping(redis_url: str) -> None:
    import redis

    client = redis.Redis.from_url(redis_url)
    try:
        assert client.ping() is True
        client.set("aia:test:key", "1", ex=5)
        assert client.get("aia:test:key") == b"1"
    finally:
        client.close()
