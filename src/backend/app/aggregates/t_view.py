"""/today 持仓行的做 T 视图 t_view（契约 docs/T-A146=1fe3ab9 intraday-bars.md §3.7、§3.8）。

只读 ``market.minute_bars`` 中 source 为 mairui 的行（§3.3、§3.5），不出网、不调用麦蕊。
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, NamedTuple

from sqlalchemy import Connection, func, select

from app.aggregates import models
from app.api.v1.portfolio import (
    INFERRED_SELLABLE,
    SNAPSHOT_TPLUS_CUTOFF,
    _has_ledger,
    snapshot_stale_message,
)
from app.db.tables.accounts import (
    broker_position_snapshot_items,
    broker_position_snapshots,
    trades,
)
from app.db.tables.market import minute_bars
from app.importing.pipeline import live_snapshots
from app.schemas.enums import DataStatus, GapReason, SecurityType

logger = logging.getLogger(__name__)

BEIJING = dt.timezone(dt.timedelta(hours=8))
# 连续竞价时段（§3.7⑤⑥、§3.8 的 N 表）
OPEN = dt.time(9, 30)
MORNING_END = dt.time(11, 30)
AFTERNOON_START = dt.time(13, 0)
CLOSE = dt.time(15, 0)
# §3.8：过去 5 个有成交交易日、每日 240 分钟（T-R58 惯例口径，未经检验）
HISTORY_DAYS = 5
DAY_MINUTES = 240


def minutes_elapsed(as_of: dt.datetime) -> int:
    """按北京时间累计交易分钟，忽略秒；出处 intraday-bars.md §3.8。"""
    local = as_of.astimezone(BEIJING)
    minute = local.hour * 60 + local.minute
    opening = OPEN.hour * 60 + OPEN.minute
    morning_end = MORNING_END.hour * 60 + MORNING_END.minute
    afternoon_start = AFTERNOON_START.hour * 60 + AFTERNOON_START.minute
    closing = CLOSE.hour * 60 + CLOSE.minute
    if minute <= opening:
        return 0
    if minute <= morning_end:
        return minute - opening
    if minute <= afternoon_start:
        return morning_end - opening
    if minute <= closing:
        return morning_end - opening + minute - afternoon_start
    return DAY_MINUTES


def volume_ratio(
    today_volume: Decimal, n: int, history: Sequence[Decimal]
) -> tuple[str | None, str | None]:
    """计算五日每分钟均量的量比及缺口；出处 intraday-bars.md §3.8。"""
    if len(history) < HISTORY_DAYS:
        return None, "历史分时不足 5 个交易日"
    v5 = sum(history[:HISTORY_DAYS], Decimal(0))
    if v5 == 0:
        return None, "历史 5 日无成交"
    if today_volume == 0 or n <= 0:
        return None, "今日无成交"
    # 等价于 (V今 ÷ N) ÷ (V5 ÷ 1200)；合成一次除法，避免中间结果先被截到 28 位影响 HALF_UP 边界
    ratio = today_volume * (HISTORY_DAYS * DAY_MINUTES) / (Decimal(n) * v5)
    return format(ratio.quantize(Decimal("0.01"), ROUND_HALF_UP), "f"), None


def clamp_sellable(
    base_qty: Decimal, sold_today: Decimal, holding_sellable: Decimal | None
) -> tuple[Decimal, bool]:
    """限制可卖量并标记原始数量异常；出处 intraday-bars.md §3.7④。"""
    remaining = base_qty - sold_today
    raw = holding_sellable if holding_sellable is not None else remaining
    return max(Decimal(0), min(remaining, raw)), raw > base_qty or raw < 0


class Bar(NamedTuple):
    ts: dt.datetime
    close: Decimal
    volume: Decimal
    amount: Decimal


@dataclass(frozen=True)
class Thresholds:
    dev_pct: Decimal
    volume_ratio: Decimal
    validated: bool


# §3.7③ 契约不写数值，等 T-R58 复测，未验证不下发也不出信号。
THRESHOLDS: Thresholds | None = None


def build(
    *,
    code: str,
    security_type: SecurityType | None,
    base_qty: Decimal,
    sold_today: Decimal,
    holding_sellable: Decimal | None,
    bars: Sequence[Bar],
    history: Sequence[Decimal],
    now: dt.datetime,
    trading_day: bool,
    scheduled: bool,
    interval_s: int,
    thresholds: Thresholds | None,
    base_source: Literal["ledger", "snapshot"] = "ledger",
    snapshot_as_of: dt.datetime | None = None,
    sellable_known: bool = True,
    previous_open: dt.date | None = None,
    snapshot_at: dt.datetime | None = None,
) -> models.TView:
    local_time = now.astimezone(BEIJING).time()
    if security_type is not SecurityType.STOCK:
        key, message = "t_view.security_type", "不适用：该品种暂不提供做 T 视图。"
    elif base_qty <= 0:
        key, message = "t_view.base_qty", "不适用：昨日无底仓。"
    elif not trading_day:
        key, message = "t_view.session", "今日休市。"
    elif local_time < OPEN:
        key, message = "t_view.session", "开盘后显示。"
    else:
        key, message = "", ""
    if key:
        return models.TView(
            vwap=None,
            dev_pct=None,
            volume_ratio=None,
            base_qty=None,
            sellable_qty=None,
            as_of=None,
            data_status=DataStatus.UNAVAILABLE,
            gaps=[models.Gap(key=key, reason=GapReason.NOT_APPLICABLE, message=message)],
        )

    gaps: list[models.Gap] = []
    snapshot_preopen = (
        snapshot_as_of is not None
        and snapshot_as_of.tzinfo is not None
        and snapshot_as_of.astimezone(BEIJING)
        < dt.datetime.combine(now.astimezone(BEIJING).date(), SNAPSHOT_TPLUS_CUTOFF, BEIJING)
    )
    stale_message = snapshot_stale_message(snapshot_at or snapshot_as_of, previous_open)
    if base_source == "snapshot" and stale_message:
        gaps.append(
            models.Gap(
                key="t_view.base_qty", reason=GapReason.USER_INPUT_MISSING, message=stale_message
            )
        )
    if base_source == "snapshot" and not snapshot_preopen:
        gaps.append(
            models.Gap(
                key="t_view.base_qty",
                reason=GapReason.USER_INPUT_MISSING,
                message="未导入今日成交流水，底仓按持仓快照计，可能含今日买入",
            )
        )
    sellable_qty = None
    clamped = False
    inferred = base_source == "snapshot" and snapshot_preopen and not sellable_known
    if sellable_known or inferred:
        sellable, clamped = clamp_sellable(base_qty, sold_today, holding_sellable)
        sellable_qty = format(sellable.normalize(), "f")
        if inferred:
            gaps.append(
                models.Gap(
                    key="t_view.sellable_qty",
                    reason=GapReason.USER_INPUT_MISSING,
                    message=INFERRED_SELLABLE,
                )
            )
    else:
        gaps.append(
            models.Gap(
                key="t_view.sellable_qty",
                reason=GapReason.USER_INPUT_MISSING,
                message="持仓快照没有可卖数量，无法核实今日可卖，暂不提供可卖数",
            )
        )
    if clamped:
        gaps.append(
            models.Gap(
                key="t_view.sellable_qty",
                reason=GapReason.UPSTREAM_ERROR,
                message="可卖数量与底仓不一致，已按较小值显示",
            )
        )
        logger.warning("t_view_sellable_exceeds_base:%s", code)
    used = [b for b in bars if b.ts <= now]
    if not used:
        gaps.append(
            models.Gap(
                key="t_view",
                reason=GapReason.NOT_YET_PUBLISHED if scheduled else GapReason.NO_SOURCE,
                message="今日分时拉取中" if scheduled else "今日分时数据未取到",
            )
        )
        return models.TView(
            vwap=None,
            dev_pct=None,
            volume_ratio=None,
            base_qty=format(base_qty.normalize(), "f"),
            sellable_qty=sellable_qty,
            as_of=None,
            data_status=DataStatus.PENDING if scheduled else DataStatus.UNAVAILABLE,
            gaps=gaps,
        )

    as_of = used[-1].ts.astimezone(BEIJING)
    vol = sum((b.volume for b in used), Decimal(0))
    amt = sum((b.amount for b in used), Decimal(0))
    vwap = dev = None
    if vol > 0 and amt > 0:
        vwap_exact = amt / vol
        vwap = format(vwap_exact.quantize(Decimal("0.01"), ROUND_HALF_UP), "f")
        dev = format(
            ((used[-1].close - vwap_exact) / vwap_exact * 100).quantize(
                Decimal("0.0001"), ROUND_HALF_UP
            ),
            "f",
        )
    else:
        gaps.append(models.Gap(key="t_view.vwap", reason=GapReason.NO_SOURCE, message="今日无成交"))
    ratio, msg = volume_ratio(vol, minutes_elapsed(as_of), history)
    if msg:
        gaps.append(models.Gap(key="t_view.volume_ratio", reason=GapReason.NO_SOURCE, message=msg))
    data_status = DataStatus.PARTIAL if gaps else DataStatus.FRESH
    if (
        trading_day
        and (OPEN <= local_time < MORNING_END or AFTERNOON_START <= local_time < CLOSE)
        and as_of < now - dt.timedelta(seconds=2 * interval_s)
    ):
        data_status = DataStatus.STALE
    return models.TView(
        vwap=vwap,
        dev_pct=dev,
        volume_ratio=ratio,
        base_qty=format(base_qty.normalize(), "f"),
        sellable_qty=sellable_qty,
        as_of=as_of,
        data_status=data_status,
        gaps=gaps,
        dev_pct_threshold=format(thresholds.dev_pct, "f")
        if thresholds is not None and thresholds.validated
        else None,
        volume_ratio_threshold=format(thresholds.volume_ratio, "f")
        if thresholds is not None and thresholds.validated
        else None,
    )


def today_bars(conn: Connection, code: str, day: dt.date, now: dt.datetime) -> list[Bar]:
    start = dt.datetime.combine(day, dt.time(), BEIJING)
    rows = conn.execute(
        select(minute_bars.c.ts, minute_bars.c.close, minute_bars.c.volume, minute_bars.c.amount)
        .where(
            minute_bars.c.code == code,
            minute_bars.c.source == "mairui",
            minute_bars.c.ts >= start,
            minute_bars.c.ts < start + dt.timedelta(days=1),
            minute_bars.c.ts <= now,
            minute_bars.c.close.is_not(None),
        )
        .order_by(minute_bars.c.ts.asc())
    )
    return [
        Bar(
            ts=row.ts.astimezone(BEIJING),
            close=Decimal(row.close),
            volume=Decimal(row.volume) if row.volume is not None else Decimal(0),
            amount=Decimal(row.amount) if row.amount is not None else Decimal(0),
        )
        for row in rows
    ]


_HISTORY: dict[tuple[str, dt.date], list[Decimal]] = {}


def history_volumes(conn: Connection, code: str, day: dt.date) -> list[Decimal]:
    """§3.8 分母每日算一次并缓存。

    「有成交的交易日」按该日有 mairui 分钟线计，停牌日无分钟线即被跳过。
    """
    if (code, day) in _HISTORY:
        return _HISTORY[code, day]
    for key in list(_HISTORY):
        if key[1] != day:
            del _HISTORY[key]
    date = func.date(func.timezone("Asia/Shanghai", minute_bars.c.ts))
    volumes = conn.execute(
        select(func.sum(minute_bars.c.volume))
        .where(
            minute_bars.c.code == code,
            minute_bars.c.source == "mairui",
            minute_bars.c.ts < dt.datetime.combine(day, dt.time(), BEIJING),
        )
        .group_by(date)
        .order_by(date.desc())
        .limit(HISTORY_DAYS)
    ).scalars()
    result = [Decimal(volume) if volume is not None else Decimal(0) for volume in volumes]
    if len(result) < HISTORY_DAYS or sum(result, Decimal(0)) == 0:
        return result
    _HISTORY[code, day] = result
    return result


class SnapshotBasis(NamedTuple):
    as_of: dt.datetime | None
    sellable_known: dict[str, bool]
    snapshot_at: dt.datetime | None


def snapshot_basis(conn: Connection, account_id: uuid.UUID) -> SnapshotBasis | None:
    """T-A149 §3.8 ④：无流水时返回最新有效快照 as_of 与各代码可卖数是否已知；有流水返回 None。"""
    if _has_ledger(conn, account_id):
        return None
    snap = conn.execute(
        live_snapshots(account_id).order_by(broker_position_snapshots.c.version_no.desc()).limit(1)
    ).first()
    if snap is None:
        return SnapshotBasis(None, {}, None)
    items = conn.execute(
        select(
            broker_position_snapshot_items.c.security_code,
            broker_position_snapshot_items.c.sellable_quantity,
        ).where(broker_position_snapshot_items.c.snapshot_id == snap.id)
    )
    return SnapshotBasis(
        snap.as_of,
        {item.security_code: item.sellable_quantity is not None for item in items},
        snap.as_of or snap.created_at,
    )


def today_trades(
    conn: Connection, account_id: uuid.UUID, day: dt.date
) -> dict[str, tuple[Decimal, Decimal]]:
    rows = conn.execute(
        select(trades.c.security_code, trades.c.side, func.sum(trades.c.quantity))
        .where(
            trades.c.account_id == account_id,
            trades.c.voided_at.is_(None),
            trades.c.trade_date == day,
        )
        .group_by(trades.c.security_code, trades.c.side)
    )
    result: dict[str, tuple[Decimal, Decimal]] = {}
    for code, side, quantity in rows:
        bought, sold = result.get(code, (Decimal(0), Decimal(0)))
        if side == "buy":
            bought = Decimal(quantity)
        elif side == "sell":
            sold = Decimal(quantity)
        result[code] = bought, sold
    return result
