"""T-T19 测试要点（T-T25 裁定，docs 46538a6 plan 2.13「交易单位」行 / §6.1 market_rules，契约 §7.7 lot_rule）。

依据 ``docs/strategies/market_rules_T-R10.md``，数值读配置目录（AIA_CONFIG_DIR 优先，否则仓库 config/）里的
``market_rules.yaml``（经后端 pydantic 模型校验），两段（2023-04-10、2026-07-06）逐段断言：

- 买入单位：主板 / 创业板 / ETF（含科创板 ETF，不适用科创板第 6.7 条）为 100 的整数倍；科创板股票/CDR 单笔 ≥ 200，
  超出部分按 1 股递增；
- 零股卖出（设可卖数量为 A）：主板/创业板/ETF 合规当且仅当 q ≤ A 且（q % 100 == 0 或 q == A）；科创板 A ≥ 200 时
  200 ≤ q ≤ A，A < 200 时只能 q == A；按可卖数量而非持仓余额判定；“整手连带零股”（持有 250 卖 150）V1 不允许；
- 单笔申报上限：竞价 ≤ 100 万；科创板限价 ≤ 10 万、市价 ≤ 5 万、盘后固定价格 ≤ 100 万；创业板限价 ≤ 30 万、
  市价 ≤ 15 万；超限返回 lot_rule 并带 max_qty。

被测为后端纯函数 ``app.market_rules.lots.check_qty``（不访问数据库与网络）。所测后端没有该模块（如 origin
0cb78ad）时 xfail，owner 后端 T-B47-R10。草案数量超上限“截断并提示”（plan 2.13）尚无可测入口，见 T-T25.md 缺口。
"""

from __future__ import annotations

import importlib
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.unit]

O_LOTS = "后端 T-B47-R10（app.market_rules.lots：在本地 main 07b8d74，未推 origin）"
#: T-R10 文档的值（plan §6.1 两段相同）
TR10 = {"buy_lot": 100, "star_min_buy": 200, "star_step": 1, "star_odd_lot_threshold": 200, "max_order_qty": 1_000_000,
        "star_max_limit_order": 100_000, "star_max_market_order": 50_000, "star_max_after_hours": 1_000_000,
        "chinext_max_limit_order": 300_000, "chinext_max_market_order": 150_000}


def _lots() -> Any:
    try:
        return importlib.import_module("app.market_rules.lots")
    except ModuleNotFoundError:
        pytest.xfail(O_LOTS)


@pytest.fixture(scope="module")
def segments(config_dir: Path) -> list[Any]:
    import yaml

    _lots()
    cf = importlib.import_module("app.config_files")
    raw = yaml.safe_load((config_dir / "market_rules.yaml").read_text(encoding="utf-8"))
    segs = list(cf.MarketRulesConfig.model_validate(raw).segments)
    assert len(segs) >= 2
    return segs


def _ok(seg: Any, *, board: str, side: str, qty: int, sellable: int | None = None, sec: str | None = "stock",
        order_type: str = "limit") -> dict[str, Any] | None:
    return _lots().check_qty(seg, board=board, security_type=sec, side=side, qty=Decimal(qty),
                             sellable_qty=None if sellable is None else Decimal(sellable), order_type=order_type)


def test_config_lot_values_are_t_r10(segments: list[Any]) -> None:
    for seg in segments:
        got = {k: getattr(seg.lot, k) for k in TR10}
        assert got == TR10, (str(seg.effective_from), got)


# ------------------------------ 买入单位 ------------------------------
BUY = [
    # (board, security_type, qty, 合规)
    ("main_board", "stock", 100, True), ("main_board", "stock", 200, True), ("main_board", "stock", 150, False),
    ("main_board", "stock", 99, False), ("main_board", "stock", 0, False),
    ("chinext", "stock", 100, True), ("chinext", "stock", 250, False),
    ("main_board", "etf", 100, True), ("main_board", "etf", 150, False),
    ("star", "etf", 100, True), ("star", "etf", 300, True), ("star", "etf", 250, False), ("star", "etf", 201, False),
    ("star", "stock", 200, True), ("star", "stock", 201, True), ("star", "stock", 377, True),
    ("star", "stock", 199, False), ("star", "stock", 100, False),
    ("star", "cdr", 200, True), ("star", "cdr", 150, False),
]


@pytest.mark.parametrize("board,sec,qty,ok", BUY, ids=[f"{b}-{s}-{q}" for b, s, q, _ in BUY])
def test_buy_unit(segments: list[Any], board: str, sec: str, qty: int, ok: bool) -> None:
    for seg in segments:
        r = _ok(seg, board=board, side="buy", qty=qty, sec=sec)
        assert (r is None) is ok, (str(seg.effective_from), r)
        if r is not None:
            assert r["issue"] == "lot_rule" and r["field"] == "chosen_qty"


def test_buy_fractional_is_lot_rule(segments: list[Any]) -> None:
    lots = _lots()
    for seg in segments:
        r = lots.check_qty(seg, board="main_board", security_type="stock", side="buy", qty=Decimal("100.5"))
        assert r is not None and r["issue"] == "lot_rule"


def test_qty_range_star_200_1_others_100_100(segments: list[Any]) -> None:
    lots = _lots()
    for seg in segments:
        assert lots.qty_range_lot(seg, board="star", security_type="stock") == (200, 1)
        assert lots.qty_range_lot(seg, board="star", security_type="etf") == (100, 100)
        assert lots.qty_range_lot(seg, board="chinext", security_type="stock") == (100, 100)


# ------------------------------ 零股卖出：按可卖数量 A 判定 ------------------------------
SELL = [
    # (board, security_type, A, q, 合规)
    ("main_board", "stock", 250, 100, True), ("main_board", "stock", 250, 200, True),
    ("main_board", "stock", 250, 250, True), ("main_board", "stock", 250, 150, False),  # 整手连带零股 V1 不允许
    ("main_board", "stock", 250, 50, False), ("main_board", "stock", 250, 300, False),  # q > A
    ("main_board", "stock", 50, 50, True), ("main_board", "stock", 50, 30, False),
    ("chinext", "stock", 130, 130, True), ("chinext", "stock", 130, 100, True), ("chinext", "stock", 130, 30, False),
    ("main_board", "etf", 150, 150, True), ("main_board", "etf", 150, 50, False),
    ("star", "stock", 350, 250, True), ("star", "stock", 350, 350, True), ("star", "stock", 350, 200, True),
    ("star", "stock", 350, 150, False), ("star", "stock", 350, 351, False),  # 契约 §7.7 例
    ("star", "stock", 200, 200, True), ("star", "stock", 200, 199, False),
    ("star", "stock", 150, 150, True), ("star", "stock", 150, 100, False), ("star", "stock", 150, 149, False),
    ("star", "etf", 150, 100, True), ("star", "etf", 150, 150, True), ("star", "etf", 150, 120, False),
]


@pytest.mark.parametrize("board,sec,a,q,ok", SELL, ids=[f"{b}-{s}-A{a}-q{q}" for b, s, a, q, _ in SELL])
def test_odd_lot_sell_against_sellable(segments: list[Any], board: str, sec: str, a: int, q: int, ok: bool) -> None:
    for seg in segments:
        r = _ok(seg, board=board, side="sell", qty=q, sellable=a, sec=sec)
        assert (r is None) is ok, (str(seg.effective_from), r)


def test_odd_lot_uses_sellable_not_holding(segments: list[Any]) -> None:
    """持有 300（其中 100 当日买入不可卖，A=200）：卖 200 合规；卖 300 超过可卖 → 拒绝。"""
    for seg in segments:
        assert _ok(seg, board="main_board", side="sell", qty=200, sellable=200) is None
        assert _ok(seg, board="main_board", side="sell", qty=300, sellable=200) is not None


# ------------------------------ 单笔申报上限 ------------------------------
CAPS = [
    # (board, security_type, order_type, 上限键)
    ("main_board", "stock", "limit", "max_order_qty"), ("main_board", "stock", "market", "max_order_qty"),
    ("star", "stock", "limit", "star_max_limit_order"), ("star", "stock", "market", "star_max_market_order"),
    ("star", "stock", "after_hours", "star_max_after_hours"), ("star", "cdr", "market", "star_max_market_order"),
    ("chinext", "stock", "limit", "chinext_max_limit_order"),
    ("chinext", "stock", "market", "chinext_max_market_order"),
    ("chinext", "etf", "limit", "max_order_qty"), ("star", "etf", "limit", "max_order_qty"),
]


@pytest.mark.parametrize("board,sec,order_type,key", CAPS, ids=[f"{b}-{s}-{o}" for b, s, o, _ in CAPS])
@pytest.mark.parametrize("side", ["buy", "sell"])
def test_per_order_cap(segments: list[Any], board: str, sec: str, order_type: str, key: str, side: str) -> None:
    """恰好等于上限合规；上限 + 一个申报单位 → lot_rule 且 details.max_qty = 上限（买卖都适用）。"""
    cap = TR10[key]
    step = 1 if board == "star" and sec in ("stock", "cdr") else 100
    for seg in segments:
        kw = {"board": board, "sec": sec, "order_type": order_type, "side": side}
        big = 10 * TR10["max_order_qty"]
        assert _ok(seg, qty=cap, sellable=big if side == "sell" else None, **kw) is None, (str(seg.effective_from), kw)
        r = _ok(seg, qty=cap + step, sellable=big if side == "sell" else None, **kw)
        assert r is not None and r["issue"] == "lot_rule" and r.get("max_qty") == str(cap), (kw, r)


def test_cap_does_not_block_selling_odd_remainder(segments: list[Any]) -> None:
    """一次性卖出不足一个申报单位的全部零股不受上限约束的下限分支影响（A=150 科创板市价卖 150 合规）。"""
    for seg in segments:
        assert _ok(seg, board="star", side="sell", qty=150, sellable=150, order_type="market") is None
