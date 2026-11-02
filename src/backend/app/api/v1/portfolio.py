"""持仓汇总（契约 v0.2.9 §7.2 ``GET /portfolio?account_id=``；T-B46，v0.2.9 #1–#3 由 T-B48 同步）。

口径：
- 账户有流水（期初持仓 / 未作废成交）→ 用重放得到的 ``holdings``；没有流水 → 用最新有效持仓快照。
- 现价只取持仓快照的 ``last_price_ref``（本接口不读日线，不触发取数），``data_status=stale``。
- 可转债（问题 63 / U3 已定，v0.2.9 #1–#3）：``security_type=null``（不在证券主数据中），
  ``market_value``、``pnl``、``pnl_pct`` 为 ``null``（不是 0），按成本计入总资产与仓位并标
  ``estimated=true``，顶层 ``data_status=partial``。
  其他缺现价的持仓（未导入持仓快照）同样按成本估算、
  ``estimated=true``，但 ``security_type`` 仍为主数据类型。
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
from app.db.tables.market import securities
from app.domain.portfolio import MONEY_DP, instrument_kind
from app.importing.pipeline import last_cash_balance, live_snapshots
from app.schemas.enums import DataStatus, GapReason, SecurityType

router = APIRouter(tags=["portfolio"])

BEIJING: Final = dt.timezone(dt.timedelta(hours=8))
PCT_DP: Final = Decimal("0.01")
PRICE_DP: Final = Decimal("0.0001")
ZERO: Final = Decimal(0)


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
    cost_price: str | None
    market_value: str | None
    pnl: str | None
    pnl_pct: str | None
    weight_pct: str | None
    security_type: SecurityType | None
    estimated: bool


class Portfolio(BaseModel):
    cash: str | None
    total_assets: str | None
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


def _s(v: Decimal | None, q: Decimal = MONEY_DP) -> str | None:
    return None if v is None else format(v.quantize(q), "f")


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


def _account(conn: Connection, account_id: uuid.UUID, today: dt.date) -> _Acc:
    acc = _Acc()
    snap = conn.execute(
        live_snapshots(account_id).order_by(broker_position_snapshots.c.version_no.desc()).limit(1)
    ).first()
    items: dict[str, Any] = {}
    snap_day: dt.date | None = None
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
        for code, i in items.items():
            if i.quantity is None or Decimal(i.quantity) <= 0:
                continue
            qty = Decimal(i.quantity)
            p = _Pos(qty=qty)
            if i.broker_cost_price is None:
                p.cost_known = False
            else:
                p.cost_total = Decimal(i.broker_cost_price) * qty
            if snap_day == today and i.sellable_quantity is not None:
                p.sellable = min(qty, Decimal(i.sellable_quantity))
            else:
                p.sellable = qty
            acc.positions[code] = p
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
    cash: Decimal | None = ZERO if account_ids else None
    cash_missing = False
    for aid in account_ids:
        acc = _account(conn, aid, today)
        if acc.cash is None:
            cash_missing = True
        elif cash is not None:
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
    if cash_missing:
        cash = None
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

    gaps: list[dict[str, str]] = []
    rows: list[dict[str, Any]] = []
    total_value = ZERO
    no_price = cb = unknown = no_cost = False
    price_times: list[dt.datetime] = []
    for code in sorted(merged):
        p = merged[code]
        kind = instrument_kind(code, types.get(code))
        cost_price = (p.cost_total / p.qty) if p.cost_known and p.qty else None
        # v0.2.9 #1：不在证券主数据中（可转债或其他）→ 无行情、按成本估算
        stype = types.get(code)
        price = None if stype is None else p.price
        mv = pnl = pnl_pct = None
        estimated = False
        if price is not None:
            mv = price * p.qty
            value: Decimal | None = mv
            if p.price_at is not None:
                price_times.append(p.price_at)
            if cost_price is not None:
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
            value = p.cost_total if p.cost_known else None
        if value is None:
            no_cost = True
        else:
            total_value += value
        rows.append(
            {
                "security_code": code,
                "name": names.get(code, code),
                "qty": format(p.qty.normalize(), "f"),
                "sellable_qty": format(p.sellable.normalize(), "f"),
                "cost_price": _s(cost_price, PRICE_DP),
                "market_value": _s(mv),
                "pnl": _s(pnl),
                "pnl_pct": _s(pnl_pct, PCT_DP),
                "weight_pct": None,
                "security_type": stype,
                "estimated": estimated,
                "_value": value,
            }
        )
    total = None if cash is None or no_cost else cash + total_value
    for r in rows:
        v = r.pop("_value")
        if total is not None and total > 0 and v is not None:
            r["weight_pct"] = _s(v / total * 100, PCT_DP)
    if cash is None:
        gaps.append(
            {
                "key": "cash",
                "reason": GapReason.USER_INPUT_MISSING.value,
                "message": "未导入现金余额，无法计算总资产与仓位比例",
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
                "reason": GapReason.USER_INPUT_MISSING.value,
                "message": "部分持仓没有现价（未导入持仓快照），仓位按成本估算",
            }
        )
    if no_cost:
        gaps.append(
            {
                "key": "positions.cost",
                "reason": GapReason.USER_INPUT_MISSING.value,
                "message": "部分持仓缺少成本，无法估算总资产",
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
    if gaps:
        status = DataStatus.PARTIAL
    elif price_times:
        status = DataStatus.STALE
    else:
        status = DataStatus.FRESH
    as_of = (
        min(price_times).astimezone(BEIJING)
        if price_times
        else _ledger_as_of(conn, account_ids) or dt.datetime.combine(today, dt.time(), BEIJING)
    )
    return {
        "cash": _s(cash),
        "total_assets": _s(total),
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
