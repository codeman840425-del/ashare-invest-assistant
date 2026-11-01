"""周 K 聚合（契约 §6.2，v0.2.7）——纯函数，不碰数据库与麦蕊。

由**已复权**的日 K（复权方式与同一请求的日 K 相同，调用方先复权）按自然周（周一到周日，
北京时间；``trade_date`` 本身就是北京时间的交易日）聚合：

1. ``t`` = 该周最后一个**有成交**的交易日；``open`` = 该周第一个有成交日的开盘价；
   ``close`` = ``t`` 当日收盘价；``high``/``low`` 为周内最高/最低；``volume``/``amount`` 求和
   （任一日为 null 则该字段为 null，不猜）；``avg_price`` 恒为 null。
2. ``pre_close`` = 上一根周 K 的 ``close``；第一根取该周首个有成交日的
   日线 ``pre_close``（可为 null）。
3. 麦蕊停牌占位行（``sf=1``，即 ``suspended=True``）不参与聚合；整周停牌或休市不出 bar。
4. ``is_final``：该周**最后一个交易日**（按交易日历，不是按本股是否有成交）已收盘（15:00 北京
   时间），且当日日线已入库（含停牌占位行）；否则 false。交易日历里查不到该周任何交易日时
   保守地给 false。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")
MARKET_CLOSE = time(15, 0)


@dataclass(frozen=True, slots=True)
class DailyBar:
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    pre_close: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    suspended: bool = False  # 麦蕊 sf=1 停牌占位行


@dataclass(frozen=True, slots=True)
class WeeklyBar:
    t: date
    week_start: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    pre_close: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    is_final: bool
    avg_price: None = None


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _sum(vals: Sequence[Decimal | None]) -> Decimal | None:
    if any(v is None for v in vals):
        return None
    return sum((v for v in vals if v is not None), Decimal(0))


def _extreme(vals: Sequence[Decimal | None], *, high: bool) -> Decimal | None:
    present = [v for v in vals if v is not None]
    if not present:
        return None
    return max(present) if high else min(present)


def _is_traded(b: DailyBar) -> bool:
    return not b.suspended and b.close is not None


def aggregate_weekly(
    daily: Iterable[DailyBar],
    *,
    trading_days: Iterable[date],
    now: datetime,
) -> list[WeeklyBar]:
    """日 K → 周 K（按 ``t`` 升序）。``daily`` 中同一日期重复时取最后一条。"""
    if now.tzinfo is None:
        raise ValueError("now 必须带时区")
    now_bj = now.astimezone(BEIJING)
    by_date: dict[date, DailyBar] = {}
    for b in daily:
        by_date[b.trade_date] = b
    stored = set(by_date)

    last_trading_day: dict[date, date] = {}
    for d in trading_days:
        ws = week_start(d)
        if d > last_trading_day.get(ws, date.min):
            last_trading_day[ws] = d

    weeks: dict[date, list[DailyBar]] = {}
    for d in sorted(by_date):
        b = by_date[d]
        if _is_traded(b):
            weeks.setdefault(week_start(d), []).append(b)

    out: list[WeeklyBar] = []
    prev_close: Decimal | None = None
    for ws in sorted(weeks):
        bars = weeks[ws]
        first, last = bars[0], bars[-1]
        ltd = last_trading_day.get(ws)
        closed = ltd is not None and (
            ltd < now_bj.date() or (ltd == now_bj.date() and now_bj.time() >= MARKET_CLOSE)
        )
        out.append(
            WeeklyBar(
                t=last.trade_date,
                week_start=ws,
                open=first.open,
                high=_extreme([b.high for b in bars], high=True),
                low=_extreme([b.low for b in bars], high=False),
                close=last.close,
                pre_close=prev_close if out else first.pre_close,
                volume=_sum([b.volume for b in bars]),
                amount=_sum([b.amount for b in bars]),
                is_final=bool(closed and ltd in stored),
            )
        )
        prev_close = last.close
    return out
