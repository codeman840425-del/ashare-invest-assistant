"""持仓重放、摊薄成本与对账（契约 v0.2.8 §7.2 ``/portfolio``、``/reconciliation``；plan §3.5A、
第 9 节问题 19 / 63；T-B46）。纯函数，不读库。

摊薄成本（与通达信一致，问题 19）：每只证券维护“持仓成本合计”，
``成本合计 -= 每笔流水的带符号现金发生额``（买入为负、卖出回款为正、现金红利为正、
股息红利税补缴等 ``other`` 按发生额符号），送转股只加数量；摊薄成本价 = 成本合计 ÷ 持股数，
对外 4 位小数。持股数回到 0 时，成本合计结转为已实现盈亏并清零。

对账容差（plan 3.5A）：``|我方 − 券商| > max(0.01 元, 0.1% × 券商成本价)`` 记 ``cost_differs``，
等于容差不记。

可转债（问题 63，已定）：按 ``import_as_is`` 导入后，持仓保留原代码；展示标注“可转债·无行情”，
现价、市值为 null（前端显示“—”）；总仓位与集中度按成本估算并标注“估算”；
**不跑策略、不出信号、不进入风控止损计算**。ETF 照常进入持仓，但同样不跑策略（v0.2.8）。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from app.marketdata.security_types import is_convertible_bond

COST_DP: Final = Decimal("0.0001")
MONEY_DP: Final = Decimal("0.01")
COST_TOL_ABS: Final = Decimal("0.01")
COST_TOL_PCT: Final = Decimal("0.001")
CASH_TOL: Final = Decimal("0.005")

#: 改变持股数量的账户事件（数量取绝对值后按方向计）
QTY_IN_EVENTS: Final = frozenset({"bonus_share", "ipo_allot", "rights", "transfer_in"})
QTY_OUT_EVENTS: Final = frozenset({"transfer_out"})

NOTES: Final[dict[str, str]] = {
    "cost_differs": (
        "我方摊薄成本与券商成本价不一致：可能缺少红利入账、股息红利税补缴或费用流水，"
        "或券商成本口径不同"
    ),
    "quantity_mismatch": "持仓数量不一致：可能缺少成交、送转股、新股入账或转托管流水",
    "missing_in_broker": "我方有持仓、券商快照中没有：可能缺少卖出或转出流水，或快照不完整",
    "missing_in_ours": "券商快照中有、我方没有：可能缺少买入、新股入账或期初持仓",
    "cash_gap": "资金余额与券商快照不一致：可能缺少资金流水（如银证转账、利息）或交割单不完整",
    "cash_chain_break": "交割单资金余额链不连续：可能漏导了部分交割单",
}
ACTIONS: Final[dict[str, str]] = {
    "cost_differs": "补导红利、税费流水后重新对账",
    "quantity_mismatch": "补导缺失的成交或事件流水",
    "missing_in_broker": "补导卖出/转出流水，或确认快照完整",
    "missing_in_ours": "补导买入流水或录入期初持仓",
    "cash_gap": "补导资金流水后重新对账",
    "cash_chain_break": "补导缺失日期的交割单",
}


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """一条重放流水。``cash`` 为带符号现金发生额（流入为正），``qty`` 为带符号数量变动。"""

    day: dt.date
    time: str
    order: int
    code: str
    qty: Decimal
    cash: Decimal
    at: dt.datetime | None = None


@dataclass(slots=True)
class Lot:
    qty: Decimal = Decimal(0)
    cost_total: Decimal = Decimal(0)
    realized: Decimal = Decimal(0)
    last_at: dt.datetime | None = None
    last_day: dt.date | None = None

    @property
    def avg_cost(self) -> Decimal | None:
        if self.qty <= 0:
            return None
        return self.cost_total / self.qty


@dataclass(frozen=True, slots=True)
class ReconItem:
    kind: str
    security_code: str | None
    ours: str | None
    broker: str | None
    diff: str | None
    note: str
    actions: tuple[str, ...] = field(default=())


def q4(value: Decimal) -> Decimal:
    return value.quantize(COST_DP, rounding=ROUND_HALF_UP)


def q2(value: Decimal) -> Decimal:
    return value.quantize(MONEY_DP, rounding=ROUND_HALF_UP)


def trade_cash(
    side: str, amount: Decimal, fees: Decimal | None, net_amount: Decimal | None
) -> Decimal:
    """成交的带符号现金发生额：优先用券商的发生金额，否则按 金额 ± 费用 推算。"""
    if net_amount is not None:
        return net_amount
    f = fees or Decimal(0)
    return -(amount + f) if side == "buy" else amount - f


def event_qty(kind: str, qty: Decimal | None) -> Decimal:
    if qty is None:
        return Decimal(0)
    if kind in QTY_IN_EVENTS:
        return abs(qty)
    if kind in QTY_OUT_EVENTS:
        return -abs(qty)
    return Decimal(0)


def replay(entries: Iterable[LedgerEntry]) -> dict[str, Lot]:
    """按 (日期, 时间, 顺序) 重放，得到每只证券的数量、摊薄成本合计与已实现盈亏。"""
    lots: dict[str, Lot] = {}
    for e in sorted(entries, key=lambda x: (x.day, x.time, x.order)):
        lot = lots.setdefault(e.code, Lot())
        lot.qty += e.qty
        lot.cost_total -= e.cash
        if e.qty != 0:
            lot.last_day = e.day
            if e.at is not None:
                lot.last_at = e.at
        if lot.qty <= 0:
            # 清仓：成本合计结转为已实现盈亏（负成本 = 盈利）
            lot.realized -= lot.cost_total
            lot.cost_total = Decimal(0)
            lot.qty = Decimal(0)
    return lots


def cost_tolerance(broker_cost: Decimal) -> Decimal:
    return max(COST_TOL_ABS, abs(broker_cost) * COST_TOL_PCT)


def _s(value: Decimal | None, dp: Decimal | None = None) -> str | None:
    if value is None:
        return None
    v = value.quantize(dp, rounding=ROUND_HALF_UP) if dp is not None else value
    return format(v.normalize() if dp is None else v, "f")


def reconcile(
    ours: Mapping[str, Lot],
    broker: Mapping[str, tuple[Decimal, Decimal | None]],
    *,
    ours_cash: Decimal | None,
    broker_cash: Decimal | None,
    chain_breaks: int = 0,
) -> list[ReconItem]:
    """我方重放结果 vs 券商快照（``broker``：代码 → (数量, 成本价)）。"""
    items: list[ReconItem] = []
    codes = sorted({c for c, lot in ours.items() if lot.qty > 0} | set(broker))
    for code in codes:
        lot = ours.get(code)
        oq = lot.qty if lot is not None else Decimal(0)
        bq, bcost = broker.get(code, (Decimal(0), None))
        if oq > 0 and code not in broker:
            items.append(_item("missing_in_broker", code, _s(oq), None, _s(oq)))
            continue
        if oq <= 0 and bq > 0:
            items.append(_item("missing_in_ours", code, None, _s(bq), _s(-bq)))
            continue
        if oq != bq:
            items.append(_item("quantity_mismatch", code, _s(oq), _s(bq), _s(oq - bq)))
            continue
        avg = lot.avg_cost if lot is not None else None
        if avg is None or bcost is None:
            continue
        mine = q4(avg)
        if abs(mine - bcost) > cost_tolerance(bcost):
            items.append(
                _item(
                    "cost_differs",
                    code,
                    _s(mine, COST_DP),
                    _s(bcost, COST_DP),
                    _s(mine - bcost, COST_DP),
                )
            )
    if ours_cash is not None and broker_cash is not None:
        gap = broker_cash - ours_cash
        if abs(gap) > CASH_TOL:
            items.append(
                _item(
                    "cash_gap",
                    None,
                    _s(ours_cash, MONEY_DP),
                    _s(broker_cash, MONEY_DP),
                    _s(gap, MONEY_DP),
                )
            )
    if chain_breaks:
        items.append(_item("cash_chain_break", None, None, None, str(chain_breaks)))
    return items


def _item(
    kind: str, code: str | None, ours: str | None, broker: str | None, diff: str | None
) -> ReconItem:
    return ReconItem(kind, code, ours, broker, diff, NOTES[kind], (ACTIONS[kind],))


# ---------------------------------------------------------------------------
# 展示分类（问题 63）
# ---------------------------------------------------------------------------

INSTRUMENT_KINDS: Final = ("stock", "cdr", "etf", "convertible_bond", "unknown")
# 是否跑策略统一走 app.strategy.eligibility.is_strategy_eligible（ETF/可转债/未知 → 否）


def instrument_kind(code: str, security_type: str | None) -> str:
    """持仓的展示分类：主数据有 → 其 ``type``；没有且在可转债代码段 → ``convertible_bond``。"""
    if security_type in {"stock", "cdr", "etf"}:
        return security_type
    if security_type is None and is_convertible_bond(code.split(".")[0]):
        return "convertible_bond"
    return "unknown"
