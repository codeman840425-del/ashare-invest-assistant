# ruff: noqa: S101, E501
"""T-B135 M3：生产 ``DbDeps.recommended_daily_until`` 连库自检（合成日历，不用真实样本）。

依据：reports/T-A147.md §五 M3；``git show 1fe3ab9:docs/contracts/daily-bars-tdx.md`` §3.4。
隔离 PG：仅在 o61-pg 127.0.0.1:55461 自建临时库 ``o61_tmp_b135_*``，用后 DROP DATABASE。
不连接、不删除其他库；不起实例、不 down -v；不出网、不调用麦蕊。
"""

from __future__ import annotations

import contextlib
import datetime as dt
import re
import uuid
from collections.abc import Iterator

import pytest
from psycopg import sql
from sqlalchemy import create_engine, delete, insert
from sqlalchemy.engine import URL, Engine

from app.cli import tdx_import
from app.db.tables.market import trading_calendar
from app.ingest.tdx_local import BEIJING
from selfchecks.test_tb127_daily_bars import _admin, _require_o61, _upgrade, _url

_SAFE_TMP = re.compile(r"^o61_tmp_b135_[a-z0-9]+$")
CLOSED = frozenset({dt.date(2023, 11, 10)})


@contextlib.contextmanager
def _temp_db() -> Iterator[URL]:
    _require_o61()
    name = "o61_tmp_b135_" + uuid.uuid4().hex[:10]
    assert _SAFE_TMP.fullmatch(name)
    with _admin() as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield _url(name)
    finally:
        assert _SAFE_TMP.fullmatch(name)
        with _admin() as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with _temp_db() as url:
        _upgrade(url, "head")
        eng = create_engine(url)
        start, end = dt.date(2023, 1, 1), dt.date(2028, 3, 31)
        rows = [
            {"date": d, "is_open": d.weekday() < 5 and d not in CLOSED}
            for d in (start + dt.timedelta(n) for n in range((end - start).days + 1))
        ]
        with eng.begin() as conn:
            conn.execute(insert(trading_calendar), rows)
        try:
            yield eng
        finally:
            eng.dispose()


def _d(engine: Engine, now: dt.datetime) -> dt.date | None:
    with engine.connect() as conn:
        try:
            return tdx_import.DbDeps(conn).recommended_daily_until(now)
        finally:
            conn.rollback()


def test_m3_db_start_closed_previous_open(engine: Engine) -> None:
    # 20:00 ≥ 17:45 → trade_date=2026-11-10；起点 2023-11-10 休市 → 第一个开市日 11-13，D=2023-11-09。
    assert _d(engine, dt.datetime(2026, 11, 10, 20, 0, tzinfo=BEIJING)) == dt.date(2023, 11, 9)


def test_m3_db_before_cutoff_uses_previous_trade_date(engine: Engine) -> None:
    # 10:00 < 17:45 → trade_date=2026-11-09；起点 2023-11-09 开市 → D=2023-11-09。
    assert _d(engine, dt.datetime(2026, 11, 10, 10, 0, tzinfo=BEIJING)) == dt.date(2023, 11, 9)
    # 2026-11-12 20:00 → 起点 2023-11-12（周日）→ 第一个开市日 11-13，D=2023-11-09（11-10 休市）。
    assert _d(engine, dt.datetime(2026, 11, 12, 20, 0, tzinfo=BEIJING)) == dt.date(2023, 11, 9)


def test_m3_db_feb29(engine: Engine) -> None:
    # 2028-02-29 20:00 → 起点 2025-02-28（day=28 回退）开市 → D=2025-02-28。
    assert _d(engine, dt.datetime(2028, 2, 29, 20, 0, tzinfo=BEIJING)) == dt.date(2025, 2, 28)
    # 2027-03-01 20:00 → 起点 2024-03-01（周五开市）→ D=2024-03-01。
    assert _d(engine, dt.datetime(2027, 3, 1, 20, 0, tzinfo=BEIJING)) == dt.date(2024, 3, 1)


def test_m3_db_calendar_gap_unknown(engine: Engine) -> None:
    gap = dt.date(2024, 6, 3)
    with engine.begin() as conn:
        conn.execute(delete(trading_calendar).where(trading_calendar.c.date == gap))
    try:
        assert _d(engine, dt.datetime(2026, 11, 10, 20, 0, tzinfo=BEIJING)) is None
    finally:
        with engine.begin() as conn:
            conn.execute(insert(trading_calendar).values(date=gap, is_open=True))
