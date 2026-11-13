# ruff: noqa: S101, E501
"""T-B134：t_view 取数的连库自检（合成分钟线，不用真实样本，不出网、不调用麦蕊）。

契约：``git show 1fe3ab9:docs/contracts/intraday-bars.md`` §3.3、§3.5（today 只用 mairui）、§3.8（过去 5 个有成交交易日、停牌顺延、分母每日一次缓存）。
隔离 PG：只在 o61-pg 127.0.0.1:55461 自建临时库 ``o61_tmp_b133_*``（复用 T-B133 的建删辅助），用后 DROP；不 down -v。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.engine import Engine

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
    rows.append(_row("600001", dt.date(2026, 10, 30), 9, 31, 7, "tdx_local"))  # 只进复测，不进分母
    rows.append(_row("600001", TODAY, 9, 31, 999, "mairui"))  # 当日不进分母
    with db.begin() as conn:
        conn.execute(insert(minute_bars), rows)
    with db.connect() as conn:
        got = tv.history_volumes(conn, "600001", TODAY)
    # 取 11-09、11-06、11-04、11-03、11-02，跳过 11-05
    assert got == [Decimal(1200), Decimal(1000), Decimal(600), Decimal(400), Decimal(200)]


def test_t_view_history_cached_once_per_day(db: Engine) -> None:
    # T-B134b：按 T-A149 ⑥ 只缓存非空结果，故首次即给满 5 日，再改历史验证当天不刷新
    tv._HISTORY.clear()
    with db.begin() as conn:
        conn.execute(
            insert(minute_bars), [_row("600002", d, 10, 0, 50, "mairui") for d in PAST[1:]]
        )
    with db.connect() as conn:
        first = tv.history_volumes(conn, "600002", TODAY)
        conn.execute(insert(minute_bars), [_row("600002", PAST[-1], 10, 1, 50, "mairui")])
        conn.commit()
        assert tv.history_volumes(conn, "600002", TODAY) == first == [Decimal(50)] * 5
        tv._HISTORY.clear()
        assert tv.history_volumes(conn, "600002", TODAY)[0] == Decimal(100)


def test_t_view_volume_ratio_null_not_cached(db: Engine) -> None:
    # T-A149 ⑥：首次历史不足（量比为空）不缓存，同日补齐后下次请求得到非空量比
    tv._HISTORY.clear()
    with db.begin() as conn:
        conn.execute(
            insert(minute_bars), [_row("600005", d, 10, 0, 240, "mairui") for d in PAST[:3]]
        )
    with db.connect() as conn:
        first = tv.history_volumes(conn, "600005", TODAY)
        assert tv.volume_ratio(Decimal(240), 1, first) == (None, "历史分时不足 5 个交易日")
        conn.execute(
            insert(minute_bars), [_row("600005", d, 10, 0, 240, "mairui") for d in PAST[3:]]
        )
        conn.commit()
        again = tv.history_volumes(conn, "600005", TODAY)
    assert len(again) == 5
    assert tv.volume_ratio(Decimal(240), 1, again) == ("240.00", None)


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
