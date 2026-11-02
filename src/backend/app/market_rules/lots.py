"""申报数量（整手 / 零股 / 单笔上限）与 ETF 当日回转判定（T-B47-R10）。

依据 ``docs/strategies/market_rules_T-R10.md`` §1.3 / §2.2 / §3 与契约 v0.2.9 #14
（``POST /plan-drafts/{id}/confirm`` 的 ``chosen_qty`` 整手校验）。
全部为纯函数，不访问数据库与网络；
规则数值只读 ``MarketRuleSegment``（按草案 ``market_rule_version_id`` / 成交日取段），段缺失时用
与 2023/2026 两段相同的内置默认值。

记号：``q`` = 单笔申报数量，``A`` = 可卖数量（``sellable_qty``；T+1 下当日买入不可卖）。

- 买入（主板 / 创业板 / ETF，含科创板 ETF）：``q ≥ buy_lot`` 且 ``q % buy_lot == 0``；
- 买入（科创板股票 / CDR）：``q ≥ star_min_buy`` 且 ``(q - star_min_buy) % star_step == 0``；
- 北交所：``q ≥ bse_min_buy``、按 ``bse_step`` 递增（【未核实】，V1 不扫描北交所）；
- 卖出：``q ≤ A``，且 ``q == A``（零股连同全部余量一次卖出）或满足该板块的申报单位：
  科创板股票/CDR ``A ≥ 200`` 时 ``200 ≤ q`` 且按 1 股递增，``A < 200`` 时只能 ``q == A``；
  其他 ``q % buy_lot == 0``（“整手连带零股”未核实，V1 不允许）；
- 单笔上限（买卖都适用）：全市场 ``max_order_qty``；科创板股票/CDR 限价 / 市价 / 盘后分别
  ``star_max_limit_order`` / ``star_max_market_order`` / ``star_max_after_hours``；
  创业板股票限价 / 市价 ``chinext_max_limit_order`` / ``chinext_max_market_order``。
  例外：一次性卖出全部零股（``q == A`` 且 ``A`` 不足一个申报单位）不受下限约束。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from app.config_files import Lot, MarketRuleSegment, T0RoundTrip

Side = Literal["buy", "sell"]
OrderType = Literal["limit", "market", "after_hours"]

_DEFAULT_LOT = Lot(buy_lot=100, star_min_buy=200, star_step=1, bse_min_buy=100, bse_step=1)
_DEFAULT_T0 = T0RoundTrip()
#: 科创板第六章只覆盖“股票、存托凭证”（沪 6.1）；科创板 ETF 按 3.3.8（100 份整数倍）
_STAR_CH6_TYPES = frozenset({"stock", "cdr"})


@dataclass(frozen=True)
class LotSpec:
    """某证券的申报单位。

    ``min_buy`` 起买量、``step`` 递增单位、``odd_lot`` 零股阈值、``max_qty`` 单笔上限。
    """

    min_buy: int
    step: int
    odd_lot: int
    max_qty: int


def normalize_board(board: str | None) -> str:
    """``main``/``main_board``/缺失 → ``main_board``；其余原样（star/chinext/bse）。"""
    if board in (None, "", "main"):
        return "main_board"
    return board


def lot_spec(
    seg: MarketRuleSegment | None,
    *,
    board: str | None,
    security_type: str | None,
    order_type: OrderType = "limit",
) -> LotSpec:
    lot = seg.lot if seg is not None else _DEFAULT_LOT
    b = normalize_board(board)
    if b == "star" and (security_type is None or security_type in _STAR_CH6_TYPES):
        cap = {
            "limit": lot.star_max_limit_order,
            "market": lot.star_max_market_order,
            "after_hours": lot.star_max_after_hours,
        }[order_type]
        return LotSpec(lot.star_min_buy, lot.star_step, lot.star_odd_lot_threshold, cap)
    if b == "bse":
        return LotSpec(lot.bse_min_buy, lot.bse_step, lot.bse_min_buy, lot.max_order_qty)
    cap = lot.max_order_qty
    if b == "chinext" and security_type != "etf":
        cap = {
            "limit": lot.chinext_max_limit_order,
            "market": lot.chinext_max_market_order,
            "after_hours": lot.max_order_qty,
        }[order_type]
    return LotSpec(lot.buy_lot, lot.buy_lot, lot.buy_lot, cap)


def qty_range_lot(
    seg: MarketRuleSegment | None, *, board: str | None, security_type: str | None
) -> tuple[int, int]:
    """契约 #14 ``qty_range``：``(min, lot)`` = (起买量, 买入递增单位)。

    主板/创业板/ETF ``(100, 100)``，科创板股票/CDR ``(200, 1)``。
    """
    s = lot_spec(seg, board=board, security_type=security_type)
    return s.min_buy, s.step


def _on_grid(q: Decimal, spec: LotSpec) -> bool:
    return q >= spec.min_buy and (q - spec.min_buy) % spec.step == 0


def buy_qty_on_grid(
    seg: MarketRuleSegment | None, *, board: str | None, security_type: str | None, qty: Decimal
) -> bool:
    """买入数量是否落在申报单位网格上（不看单笔上限：导入的成交行可能是多笔委托合并）。"""
    spec = lot_spec(seg, board=board, security_type=security_type)
    return qty == qty.to_integral_value() and _on_grid(qty, spec)


def check_qty(
    seg: MarketRuleSegment | None,
    *,
    board: str | None,
    security_type: str | None,
    side: Side,
    qty: Decimal,
    sellable_qty: Decimal | None = None,
    order_type: OrderType = "limit",
) -> dict[str, Any] | None:
    """合规 → ``None``；否则返回契约 ``400 VALIDATION_ERROR`` 的 ``details``：
    ``{field: "chosen_qty", issue: "lot_rule", min_buy, step}``（超单笔上限时另带 ``max_qty``）。

    ``sellable_qty`` 为 ``None``（卖出时未知可卖数量）只校验正整数与单笔上限，零股不判。
    """
    spec = lot_spec(seg, board=board, security_type=security_type, order_type=order_type)
    details: dict[str, Any] = {
        "field": "chosen_qty",
        "issue": "lot_rule",
        "min_buy": str(spec.min_buy),
        "step": str(spec.step),
    }
    if qty <= 0 or qty != qty.to_integral_value():
        return details
    if side == "buy":
        ok = _on_grid(qty, spec)
    else:
        if sellable_qty is None:
            ok = True
        elif qty > sellable_qty:
            return details
        elif qty == sellable_qty:
            ok = True  # 零股连同全部余量一次卖出；整手全卖同样合规
        elif sellable_qty < spec.odd_lot:
            ok = False  # 余额不足一个申报单位：只能一次性全部卖出
        else:
            ok = _on_grid(qty, spec)
    if not ok:
        return details
    odd_all = side == "sell" and sellable_qty is not None and qty == sellable_qty
    if qty > spec.max_qty and not (odd_all and qty < spec.odd_lot):
        return details | {"max_qty": str(spec.max_qty)}
    return None


def clamp_draft_qty(
    seg: MarketRuleSegment | None,
    *,
    board: str | None,
    security_type: str | None,
    qty: int,
    order_type: OrderType = "limit",
) -> tuple[int, dict[str, Any] | None]:
    """计划草案数量按单笔申报上限截断（T-T25 裁定 / plan 2.13，与 50 万股风险警示上限同一做法）。

    ``qty`` 不超过该证券、该委托类型的单笔上限 → ``(qty, None)``；超过 → 截断到上限以内最大的
    合规申报数量（落在 ``min_buy + k·step`` 网格上），并返回提示
    ``{code: "qty_capped_order_limit", original_qty, max_qty}``（数量为字符串，同契约 decimal）。
    """
    spec = lot_spec(seg, board=board, security_type=security_type, order_type=order_type)
    if qty <= spec.max_qty:
        return qty, None
    capped = spec.min_buy + (spec.max_qty - spec.min_buy) // spec.step * spec.step
    notice = {
        "code": "qty_capped_order_limit",
        "original_qty": str(qty),
        "max_qty": str(spec.max_qty),
    }
    return capped, notice


# ---------------------------------------------------------------------------
# ETF 当日回转（沪/深 3.1.5；T-R10 §3）
# ---------------------------------------------------------------------------

#: 证券主数据 ``etf_category`` 的取值（T-R10 §3.2；字段待数据负责人补充）
ETF_CATEGORIES = ("stock", "bond", "money", "gold", "commodity_futures", "cross_border", "other")


def fund_t_plus(
    seg: MarketRuleSegment | None,
    *,
    security_type: str | None,
    etf_category: str | None = None,
    is_cross_border: bool | None = None,
    constituents_t0: bool | None = None,
    is_lof: bool = False,
    t0_override: bool | None = None,
) -> int:
    """返回 0（当日回转）或该段的 ``t_plus``。

    - 非 ETF/LOF（股票、CDR 等）→ ``seg.t_plus``；
    - ``t0_override`` 非空（人工覆盖，须带来源与日期）优先；
    - 类别属于 ``t0_round_trip.fund_categories`` → 0；跨境类在
      ``cross_border_requires_t0_constituents`` 时还要求 ``constituents_t0 is True``；
    - 类别缺失 / 未知 / 跨境但成份是否 T+0 未知 → ``unknown_category_default_t_plus``（1）。
    - **闸门**（T-O11 裁定 / 契约 #29 ②，T-B49）：``t0_round_trip.data_source`` 为 null 或空串
      （ETF 类别数据源未接入）时，所有 ETF/LOF 一律按 T+1
      （``unknown_category_default_t_plus``），不论传入的类别或人工覆盖。
    """
    base = seg.t_plus if seg is not None else 1
    if security_type != "etf" and not is_lof:
        return base
    t0 = seg.t0_round_trip if seg is not None else _DEFAULT_T0
    if not (t0.data_source or "").strip():  # null 或空串（plan 2.13 / T-T19 要点）
        return max(base, t0.unknown_category_default_t_plus)
    if t0_override is not None:
        return 0 if t0_override else base
    cross = bool(is_cross_border) or etf_category == "cross_border"
    if cross:
        key = "cross_border_lof" if is_lof else "cross_border_etf"
        if key not in t0.fund_categories:
            return base
        if t0.cross_border_requires_t0_constituents and constituents_t0 is not True:
            return t0.unknown_category_default_t_plus if constituents_t0 is None else base
        return 0
    if is_lof or etf_category is None or etf_category not in ETF_CATEGORIES:
        return t0.unknown_category_default_t_plus if etf_category is None else base
    if f"{etf_category}_etf" in t0.fund_categories:
        return 0
    return base
