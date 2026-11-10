# ruff: noqa: S101, E501
"""T-T78：T-B134 t_view 正式契约连库用例（合成分钟线）。

覆盖 11+6+2 中的两例：
- test_t_view_volume_ratio_skips_suspended_days（§3.8）
- test_t_view_ignores_tdx_local（§5.1 M4 / §3.3）

只在 o61-pg 127.0.0.1:55461 自建临时库 ``o61_tmp_b133_*``
（复用 T-B133 的 temp_db 与 T-B127 的 _upgrade），用后 DROP；不 down -v。
不调用麦蕊，不用真实样本。禁止 DROP tt51_tpl / o61_tmp_0030 / o61_tmp_0029。
"""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.engine import Engine

_BACKEND = Path(__file__).resolve().parents[3] / "src" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.aggregates import t_view as tv
from app.db.tables.market import minute_bars
from selfchecks.test_tb127_daily_bars import _upgrade
from selfchecks.test_tb133_tdx_db import temp_db

BJ = dt.timezone(dt.timedelta(hours=8))
TODAY = dt.date(2026, 11, 10)
# 过去 6 个开市日（11-02 至 11-09，跳过周末）；11-05 停牌、没有分钟线
PAST = [dt.date(2026, 11, d) for d in (2, 3, 4, 5, 6, 9)]


@pytest.fixture(scope="module")
def db() -> Iterator[Engine]:
    with temp_db() as url:
        _upgrade(url, "head")
        engine = create_engine(url)
        try:
            yield engine
        finally:
            engine.dispose()


def _row(code: str, day: dt.date, hh: int, mm: int, vol: int, source: str) -> dict[str, object]:
    return {
        "code": code,
        "ts": dt.datetime.combine(day, dt.time(hh, mm), BJ),
        "open": 10,
        "high": 10,
        "low": 10,
        "close": 10,
        "volume": vol,
        "amount": vol * 10,
        "source": source,
    }


def test_t_view_volume_ratio_skips_suspended_days(db: Engine) -> None:
    tv._HISTORY.clear()
    rows = []
    for i, day in enumerate(PAST):
        if day == dt.date(2026, 11, 5):
            continue  # 停牌：无分钟线，向前顺延
        rows += [
            _row("600001", day, 9, 31, 100 * (i + 1), "mairui"),
            _row("600001", day, 15, 0, 100 * (i + 1), "mairui"),
        ]
    rows.append(_row("600001", dt.date(2026, 10, 30), 9, 31, 7, "tdx_local"))  # 窗口外，不进分母
    # 窗口内同日 tdx_local 也不进分母（避免只靠更早日期无法证明来源过滤）
    rows.append(_row("600001", dt.date(2026, 11, 9), 10, 0, 999, "tdx_local"))
    rows.append(_row("600001", TODAY, 9, 31, 999, "mairui"))  # 当日不进分母
    with db.begin() as conn:
        conn.execute(insert(minute_bars), rows)
    with db.connect() as conn:
        got = tv.history_volumes(conn, "600001", TODAY)
    # 取 11-09、11-06、11-04、11-03、11-02，跳过 11-05
    assert got == [Decimal(1200), Decimal(1000), Decimal(600), Decimal(400), Decimal(200)]


def test_t_view_ignores_tdx_local(db: Engine) -> None:
    with db.begin() as conn:
        conn.execute(
            insert(minute_bars),
            [
                _row("600003", TODAY, 9, 31, 100, "tdx_local"),
                _row("600004", TODAY, 9, 31, 100, "mairui"),
                _row("600004", TODAY, 9, 33, 100, "mairui"),
            ],
        )
    now = dt.datetime.combine(TODAY, dt.time(9, 32, 30), BJ)
    with db.connect() as conn:
        assert tv.today_bars(conn, "600003", TODAY, now) == []
        got = tv.today_bars(conn, "600004", TODAY, now)
    assert [b.ts for b in got] == [
        dt.datetime.combine(TODAY, dt.time(9, 31), BJ)
    ]  # 晚于 now 的不计
