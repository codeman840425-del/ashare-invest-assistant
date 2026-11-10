"""持仓汇总（契约 v0.2.9 §7.2 ``GET /portfolio?account_id=``；T-B46，T-B46-47 裁定 R6 与
契约 #31 由 T-B49 / T-B46-x 落实）。

口径：
- 账户有流水（期初持仓 / 未作废成交）→ 用重放得到的 ``holdings``；没有流水 → 用最新有效持仓快照。
- 现价来源依次为（R6 ②）：① 库内该证券最近一个交易日的日线收盘价（``market.daily_bars``，
  ``adj_type=none``；只读已有数据，不触发取数）；② 最近一次持仓快照的 ``last_price_ref``；
  ③ 都没有 → 该行按成本估算，``estimated=true``，``market_value``、``pnl``、``pnl_pct`` 为 null。
- 不在证券主数据中（``security_type=null``，主要是可转债）：无行情，同样按成本估算、
  ``estimated=true``（问题 63 / U3、v0.2.9 #1–#3）。
- 不为 null（R6 ③）：``cash``、``total_assets``、``qty``、``sellable_qty``、``cost_price``、
  ``weight_pct``。没有现金记录 → ``cash="0.00"``，并列
  ``{key:"cash", reason:"user_input_missing"}``。
- 顶层没有 ``estimated``（#31 ①）。``data_status``（#31 ②）：任一行 ``estimated=true``，或除
  ``exposure.sector`` 以外的任一缺口（含 ``cash``）→ ``partial``；否则有现价 → ``stale``，
  一行现价都没有（含无持仓）→ ``fresh``。行业数据未接入时 ``exposure.sector=[]``，
  ``gaps`` 列 ``exposure.sector``（``no_source``），这一项不单独降为 ``partial``（R6 ④）。
- 估算行的缺口按原因各列一项（#31 ③）：``positions.convertible_bond`` /
  ``positions.unknown_security`` / ``positions.price``，``reason`` 均为 ``no_source``。
- ETF 正常列入持仓；本接口不跑策略、不出信号、不做风控止损计算。
- ``sellable_qty``：一律 T+1 = 持仓 − 当日（北京时间）买入；快照为当日的取快照可卖数。
- 不传 ``account_id`` 时合并本人全部未归档账户（同代码合并数量与成本）。
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated, Any, Final

from fastapi import APIRouter, Header, Response
from pydantic import BaseModel
from sqlalchemy import Connection, func, select

from app.api.v1.accounts import owned_account, user_account_ids
from app.api.v1.imports import ETAG_RESPONSES, etag_response
from app.api.v1.trades import names_from_imports
from app.auth.deps import AuthDep, EngineDep
from app.db.tables.accounts import (
    broker_position_snapshot_items,
    broker_position_snapshots,
    holdings,
    opening_positions,
    trades,
)
from app.db.tables.market import daily_bars, securities, trading_calendar
from app.domain.portfolio import MONEY_DP, instrument_kind
from app.importing.pipeline import last_cash_balance, live_snapshots
from app.schemas.enums import BarAdjust, DataStatus, GapReason, SecurityType

router = APIRouter(tags=["portfolio"])

BEIJING: Final = dt.timezone(dt.timedelta(hours=8))
PCT_DP: Final = Decimal("0.01")
PRICE_DP: Final = Decimal("0.0001")
ZERO: Final = Decimal(0)
#: 日线收盘价的时点（北京时间收盘）
CLOSE_TIME: Final = dt.time(15, 0)
# intraday-bars §3.8 T-B134c: call-auction start, independent of minute-bar opening.
SNAPSHOT_TPLUS_CUTOFF: Final = dt.time(9, 15)
INFERRED_SELLABLE: Final = "可卖数按开盘前持仓快照推算（T+1），未扣今日卖出和冻结、限售股份"
UNKNOWN_SELLABLE: Final = "当日持仓快照没有可卖数量，无法核实今日可卖，可卖暂按 0 计"


class Gap(BaseModel):
    key: str
    reason: GapReason
    message: str


class SectorExposure(BaseModel):
    name: str
    pct: str


class Exposure(BaseModel):
    sector: list[SectorExposure]


class Position(BaseModel):
    security_code: str
    name: str
    qty: str
    sellable_qty: str
    cost_price: str
    market_value: str | None
    pnl: str | None
    pnl_pct: str | None
    weight_pct: str
    security_type: SecurityType | None
    estimated: bool


class Portfolio(BaseModel):
    cash: str
    total_assets: str
    positions: list[Position]
    exposure: Exposure
    data_status: DataStatus
    data_as_of: dt.datetime
    gaps: list[Gap]


@dataclass
class _Pos:
    qty: Decimal = ZERO
    cost_total: Decimal = ZERO
    sellable: Decimal = ZERO
    cost_known: bool = True
    price: Decimal | None = None
    price_at: dt.datetime | None = None


@dataclass
class _Acc:
    cash: Decimal | None = None
    positions: dict[str, _Pos] = field(default_factory=dict)
    price_at: dt.datetime | None = None
    gaps: list[dict[str, str]] = field(default_factory=list)


def _s(v: Decimal | None, q: Decimal = MONEY_DP) -> str | None:
    return None if v is None else format(v.quantize(q), "f")


def _n(v: Decimal, q: Decimal = MONEY_DP) -> str:
    return format(v.quantize(q), "f")


def latest_daily_close(
    conn: Connection, codes: set[str], today: dt.date
) -> dict[str, tuple[Decimal, dt.datetime]]:
    """库内各证券最近一个交易日（≤ 今天，北京时间）的不复权日线收盘价与其时点（当日 15:00）。

    只读 ``market.daily_bars`` 已有数据，不触发任何取数（R6 ②-1）。
    """
    if not codes:
        return {}
    rows = conn.execute(
        select(daily_bars.c.code, daily_bars.c.trade_date, daily_bars.c.close)
        .where(
            daily_bars.c.code.in_(sorted(codes)),
            daily_bars.c.adj_type == BarAdjust.NONE.value,
            daily_bars.c.close.is_not(None),
            daily_bars.c.trade_date <= today,
        )
        .order_by(daily_bars.c.code, daily_bars.c.trade_date.desc())
        .distinct(daily_bars.c.code)
    ).all()
    return {
        code: (Decimal(close), dt.datetime.combine(d, CLOSE_TIME, BEIJING))
        for code, d, close in rows
    }


def latest_close_at(conn: Connection, now: dt.datetime) -> dt.datetime:
    """最近一个**已收盘**交易日的收盘时点（北京时间 15:00）。

    T-B49 / review-6670b10 m1：现价时点不早于它即为 FRESH（今日收盘后的今日收盘价不算过期）。
    交易日历覆盖该日期时按 ``market.trading_calendar``；不覆盖时退回周一至周五（与导入预览一致）。
    今天是交易日但未到 15:00 时，最近已收盘的是上一交易日。
    """
    now = now.astimezone(BEIJING)
    lo, hi = conn.execute(
        select(func.min(trading_calendar.c.date), func.max(trading_calendar.c.date))
    ).one()
    d = now.date() if now.time() >= CLOSE_TIME else now.date() - dt.timedelta(days=1)
    start = d - dt.timedelta(days=40)
    opened: set[dt.date] = set()
    if lo is not None and hi is not None:
        opened = set(
            conn.execute(
                select(trading_calendar.c.date).where(
                    trading_calendar.c.is_open,
                    trading_calendar.c.date.between(start, d),
                )
            ).scalars()
        )
    while d >= start:
        covered = lo is not None and hi is not None and lo <= d <= hi
        if (d in opened) if covered else d.weekday() < 5:
            break
        d -= dt.timedelta(days=1)
    return dt.datetime.combine(d, CLOSE_TIME, BEIJING)


def _has_ledger(conn: Connection, account_id: uuid.UUID) -> bool:
    t = conn.execute(
        select(func.count())
        .select_from(trades)
        .where(trades.c.account_id == account_id, trades.c.voided_at.is_(None))
    ).scalar_one()
    o = conn.execute(
        select(func.count())
        .select_from(opening_positions)
        .where(opening_positions.c.account_id == account_id)
    ).scalar_one()
    return bool(t or o)


def previous_open_day(conn: Connection, today: dt.date) -> dt.date | None:
    """Strictly previous opening day; missing calendar coverage has no weekday fallback."""
    previous: dt.date | None = conn.execute(
        select(func.max(trading_calendar.c.date)).where(
            trading_calendar.c.date < today, trading_calendar.c.is_open.is_(True)
        )
    ).scalar_one()
    if previous is None:
        return None
    covered = conn.execute(
        select(func.count())
        .select_from(trading_calendar)
        .where(trading_calendar.c.date >= previous, trading_calendar.c.date < today)
    ).scalar_one()
    return previous if covered == (today - previous).days else None


def snapshot_stale_message(
    snapshot_at: dt.datetime | None,
    previous_open: dt.date | None,
) -> str | None:
    if snapshot_at is None or snapshot_at.tzinfo is None:
        return None
    day = snapshot_at.astimezone(BEIJING).date()
    if previous_open is not None and day >= previous_open:
        return None
    return f"持仓快照停在 {day.isoformat()}，早于上一交易日，之后的买卖未反映，持仓与可卖可能已变"


def _account(conn: Connection, account_id: uuid.UUID, today: dt.date) -> _Acc:
    acc = _Acc()
    snap = conn.execute(
        live_snapshots(account_id).order_by(broker_position_snapshots.c.version_no.desc()).limit(1)
    ).first()
    items: dict[str, Any] = {}
    snap_day: dt.date | None = None
    snap_at: dt.datetime | None = None
    if snap is not None:
        items = {
            i.security_code: i
            for i in conn.execute(
                select(broker_position_snapshot_items).where(
                    broker_position_snapshot_items.c.snapshot_id == snap.id
                )
            ).all()
        }
        snap_at = snap.as_of or snap.created_at
        snap_day = snap_at.astimezone(BEIJING).date()
        acc.price_at = snap_at
    ledger = _has_ledger(conn, account_id)
    if ledger:
        buys_today: dict[str, Decimal] = {
            code: Decimal(q)
            for code, q in conn.execute(
                select(trades.c.security_code, func.sum(trades.c.quantity))
                .where(
                    trades.c.account_id == account_id,
                    trades.c.voided_at.is_(None),
                    trades.c.side == "buy",
                    trades.c.trade_date == today,
                )
                .group_by(trades.c.security_code)
            ).all()
        }
        for h in conn.execute(
            select(holdings).where(holdings.c.account_id == account_id, holdings.c.quantity > 0)
        ).all():
            qty = Decimal(h.quantity)
            p = _Pos(qty=qty)
            if h.avg_cost is None:
                p.cost_known = False
            else:
                p.cost_total = Decimal(h.avg_cost) * qty
            item = items.get(h.security_code)
            if item is not None and snap_day == today and item.sellable_quantity is not None:
                p.sellable = min(qty, Decimal(item.sellable_quantity))
            else:
                p.sellable = max(ZERO, qty - buys_today.get(h.security_code, ZERO))
            acc.positions[h.security_code] = p
        last_trade_day = conn.execute(
            select(func.max(trades.c.trade_date)).where(
                trades.c.account_id == account_id, trades.c.voided_at.is_(None)
            )
        ).scalar()
        if (
            snap is not None
            and snap.cash_balance is not None
            and (last_trade_day is None or (snap_day is not None and snap_day >= last_trade_day))
        ):
            acc.cash = Decimal(snap.cash_balance)
        else:
            acc.cash = last_cash_balance(conn, account_id)
    elif snap is not None:
        missing_sellable: set[str] = set()
        stale_message = snapshot_stale_message(snap_at, previous_open_day(conn, today))
        if stale_message:
            acc.gaps.append(
                {
                    "key": "positions.snapshot",
                    "reason": "user_input_missing",
                    "message": stale_message,
                }
            )
        for code, i in items.items():
            if i.quantity is None or Decimal(i.quantity) <= 0:
                continue
            qty = Decimal(i.quantity)
            p = _Pos(qty=qty)
            if i.broker_cost_price is None:
                p.cost_known = False
            else:
                p.cost_total = Decimal(i.broker_cost_price) * qty
            if i.sellable_quantity is None:
                preopen = snap_at is not None and snap_at.astimezone(BEIJING) < (
                    dt.datetime.combine(today, SNAPSHOT_TPLUS_CUTOFF, BEIJING)
                )
                p.sellable = qty if preopen else ZERO
                missing_sellable.add(INFERRED_SELLABLE if preopen else UNKNOWN_SELLABLE)
            elif snap_day == today:
                p.sellable = min(qty, Decimal(i.sellable_quantity))
            else:
                p.sellable = qty
            acc.positions[code] = p
        acc.gaps.extend(
            {"key": "positions.sellable_qty", "reason": "user_input_missing", "message": message}
            for message in sorted(missing_sellable)
        )
        acc.cash = None if snap.cash_balance is None else Decimal(snap.cash_balance)
    for code, p in acc.positions.items():
        item = items.get(code)
        if item is not None and item.last_price_ref is not None:
            p.price = Decimal(item.last_price_ref)
            p.price_at = acc.price_at
    return acc


def _ledger_as_of(conn: Connection, account_ids: list[uuid.UUID]) -> dt.datetime | None:
    """无现价时 ``data_as_of`` = 本人持仓数据最后一次变化（保证 ETag 稳定）。"""
    if not account_ids:
        return None
    marks = [
        conn.execute(
            select(func.max(holdings.c.rebuilt_at)).where(holdings.c.account_id.in_(account_ids))
        ).scalar(),
        conn.execute(
            select(func.max(func.greatest(trades.c.created_at, trades.c.voided_at))).where(
                trades.c.account_id.in_(account_ids)
            )
        ).scalar(),
        conn.execute(
            select(func.max(broker_position_snapshots.c.created_at)).where(
                broker_position_snapshots.c.account_id.in_(account_ids)
            )
        ).scalar(),
    ]
    got = [m for m in marks if m is not None]
    return max(got).astimezone(BEIJING) if got else None


def build_portfolio(conn: Connection, account_ids: list[uuid.UUID]) -> dict[str, Any]:
    now = dt.datetime.now(BEIJING)
    today = now.date()
    merged: dict[str, _Pos] = {}
    gaps: list[dict[str, str]] = []
    cash = ZERO
    # R6 ③：没有现金记录（无账户，或任一账户既无快照现金也无流水现金）→ 按 0 计并列缺口
    cash_missing = not account_ids
    for aid in account_ids:
        acc = _account(conn, aid, today)
        for item in acc.gaps:
            if item not in gaps:
                gaps.append(item)
        if acc.cash is None:
            cash_missing = True
        else:
            cash += acc.cash
        for code, p in acc.positions.items():
            m = merged.setdefault(code, _Pos())
            m.qty += p.qty
            m.cost_total += p.cost_total
            m.sellable += p.sellable
            m.cost_known = m.cost_known and p.cost_known
            if p.price is not None and (
                m.price_at is None or (p.price_at and p.price_at > m.price_at)
            ):
                m.price, m.price_at = p.price, p.price_at
    codes = set(merged)
    types: dict[str, str] = {}
    names: dict[str, str] = {}
    if codes:
        for code, name, typ in conn.execute(
            select(securities.c.code, securities.c.name, securities.c.type).where(
                securities.c.code.in_(codes)
            )
        ).all():
            types[code] = typ
            if name:
                names[code] = name
        for code, name in names_from_imports(conn, account_ids, codes - names.keys()).items():
            names.setdefault(code, name)
    # R6 ②-1：日线收盘价优先于快照参考价（只对主数据中的证券；不在主数据中的行不取行情）
    for code, (close, at) in latest_daily_close(conn, set(types) & codes, today).items():
        merged[code].price, merged[code].price_at = close, at

    rows: list[dict[str, Any]] = []
    total_value = ZERO
    no_price = cb = unknown = no_cost = False
    price_times: list[dt.datetime] = []
    for code in sorted(merged):
        p = merged[code]
        kind = instrument_kind(code, types.get(code))
        # R6 ③ cost_price 不为 null；成本缺失（防御：导入要求成本价必填）按 0 输出并列缺口
        cost_price = (p.cost_total / p.qty) if p.cost_known and p.qty else ZERO
        if not p.cost_known:
            no_cost = True
        # v0.2.9 #1：不在证券主数据中（可转债或其他）→ 无行情、按成本估算
        stype = types.get(code)
        price = None if stype is None else p.price
        mv = pnl = pnl_pct = None
        estimated = False
        if price is not None:
            mv = price * p.qty
            value = mv
            if p.price_at is not None:
                price_times.append(p.price_at)
            if p.cost_known:
                pnl = mv - p.cost_total
                pnl_pct = (pnl / p.cost_total * 100) if p.cost_total else None
        else:
            estimated = True
            if kind == "convertible_bond":
                cb = True
            elif stype is None:
                unknown = True
            else:
                no_price = True
            value = p.cost_total
        total_value += value
        rows.append(
            {
                "security_code": code,
                "name": names.get(code, code),
                "qty": format(p.qty.normalize(), "f"),
                "sellable_qty": format(p.sellable.normalize(), "f"),
                "cost_price": _n(cost_price, PRICE_DP),
                "market_value": _s(mv),
                "pnl": _s(pnl),
                "pnl_pct": _s(pnl_pct, PCT_DP),
                "weight_pct": "0.00",
                "security_type": stype,
                "estimated": estimated,
                "_value": value,
            }
        )
    total = cash + total_value
    for r in rows:
        v = r.pop("_value")
        if total > 0:
            r["weight_pct"] = _n(v / total * 100, PCT_DP)
    if cash_missing:
        gaps.append(
            {
                "key": "cash",
                "reason": GapReason.USER_INPUT_MISSING.value,
                "message": "未导入现金余额，现金按 0 计，总资产与仓位比例偏差",
            }
        )
    if cb:
        gaps.append(
            {
                "key": "positions.convertible_bond",
                "reason": GapReason.NO_SOURCE.value,
                "message": "可转债·无行情：现价与市值不展示，仓位按成本估算",
            }
        )
    if unknown:
        gaps.append(
            {
                "key": "positions.unknown_security",
                "reason": GapReason.NO_SOURCE.value,
                "message": "部分持仓不在证券主数据中·无行情：现价与市值不展示，仓位按成本估算",
            }
        )
    if no_price:
        gaps.append(
            {
                "key": "positions.price",
                "reason": GapReason.NO_SOURCE.value,
                "message": "部分持仓既无日线收盘价也无持仓快照参考价，仓位按成本估算",
            }
        )
    if no_cost:
        gaps.append(
            {
                "key": "positions.cost",
                "reason": GapReason.USER_INPUT_MISSING.value,
                "message": "部分持仓缺少成本，成本价按 0 输出",
            }
        )
    if rows:
        gaps.append(
            {
                "key": "exposure.sector",
                "reason": GapReason.NO_SOURCE.value,
                "message": "暂无行业分类数据，行业暴露不展示",
            }
        )
    # #31 ②：exposure.sector 缺口不单独降级；估算行（cb / unknown / no_price）都已列缺口
    if any(g["key"] != "exposure.sector" for g in gaps) or any(r["estimated"] for r in rows):
        status = DataStatus.PARTIAL
    elif price_times and min(price_times) < latest_close_at(conn, now):
        status = DataStatus.STALE
    else:
        status = DataStatus.FRESH
    as_of = (
        min(price_times).astimezone(BEIJING)
        if price_times
        else _ledger_as_of(conn, account_ids) or dt.datetime.combine(today, dt.time(), BEIJING)
    )
    return {
        "cash": _n(cash),
        "total_assets": _n(total),
        "positions": rows,
        "exposure": {"sector": []},
        "data_status": status.value,
        "data_as_of": as_of.isoformat(),
        "gaps": gaps,
    }


@router.get("/portfolio", response_model=Portfolio, responses=ETAG_RESPONSES)
def get_portfolio(
    auth: AuthDep,
    engine: EngineDep,
    account_id: uuid.UUID | None = None,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    with engine.connect() as conn:
        if account_id is not None:
            owned_account(conn, auth, account_id)
            ids = [account_id]
        else:
            ids = user_account_ids(conn, auth)
        content = build_portfolio(conn, ids)
    content = Portfolio.model_validate(content).model_dump(mode="json")
    return etag_response(content, if_none_match)
