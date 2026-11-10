# ruff: noqa: E501, S101, PLR2004  自检脚本：断言即检查；数字为合成数据
"""T-B136 做T复测引擎自检（只用合成数据，不读样本、不连库、不调用任何外部接口）。

运行：``/workspace/venv-datasrc/bin/python3 src/backend/selfchecks/tb136_retest.py``（需要 numpy）。
覆盖方案 docs/strategies/T-R58/retest_plan.md（docs/T-R58@5955bf3）§9 的 L1、L2、L4–L7、L11–L13，
以及 §1 量比舍入、§2.2 第 3 条逐根检查、§6 费用、S3 保守估值、R 组与自助法的可复现性。
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from retest.t_r58 import features, rules, sim, stats

FAILS: list[str] = []
PASSES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSES if cond else FAILS).append(name + ("" if cond else f"：{detail}"))


# ---------------------------------------------------------------- 制度与费用


def t_rules() -> None:
    check("L5 印花税 2023-08-25 卖出 0.1%", rules.stamp_duty_rate(date(2023, 8, 25)) == 0.001)
    check("L5 印花税 2023-08-28 起 0.05%", rules.stamp_duty_rate(date(2023, 8, 28)) == 0.0005)
    check("佣金最低 5 元", rules.commission(10000.0, 0.00025) == 5.0)
    check("佣金按费率", abs(rules.commission(50000.0, 0.00025) - 12.5) < 1e-9)
    tiers = [(0.1, 0), (0.11, 5), (0.5, 5), (1.0, 15), (2.0, 30), (2.01, 60), (None, 60)]
    check("冲击分档", all(rules.impact_bp(p) == bp for p, bp in tiers), str([rules.impact_bp(p) for p, _ in tiers]))
    check("整手 主板", rules.lot_floor("main", 50000.0, 10.37) == 4800)
    check("整手 科创不足 200 股为 0", rules.lot_floor("star", 50000.0, 300.0) == 0)
    check("整手 科创按 1 股", rules.lot_floor("star", 50000.0, 240.0) == 208)
    check("板块", (rules.board("SH", "688001"), rules.board("SZ", "300750"), rules.board("SZ", "000001"), rules.board("SH", "600000")) == ("star", "chinext", "main", "main"))
    check("涨跌幅 主板 ST 2026-07-06 前 5%", rules.limit_pct("main", True, date(2026, 7, 3)) == 0.05)
    check("涨跌幅 主板 ST 2026-07-06 起 10%", rules.limit_pct("main", True, date(2026, 7, 6)) == 0.10)
    check("涨跌幅 创业板 20%", rules.limit_pct("chinext", False, date(2024, 1, 2)) == 0.20)
    check("涨跌停价", rules.limit_prices(10.0, 0.1) == (11.0, 9.0))
    check("涨跌停价四舍五入", rules.limit_prices(2.45, 0.1)[1] == 2.21, str(rules.limit_prices(2.45, 0.1)))
    check("除权参考价 派息", abs(rules.ref_price(10.0, 0.2, 0.0, 0.0, 0.0) - 9.8) < 1e-12)
    check("除权参考价 送转", abs(rules.ref_price(10.0, 0.2, 0.0, 0.5, 0.0) - 9.8 / 1.5) < 1e-12)


# ---------------------------------------------------------------- 特征


def t_minutes() -> None:
    got = [features.minutes_elapsed(x) for x in ("09:31", "11:30", "12:15", "13:01", "15:00")]
    check("L1 minutes_elapsed 11:30/12:15/13:01/15:00", got == [1, 120, 120, 121, 240], str(got))
    check("SLOT_END 240 根", len(features.SLOT_END) == 240 and features.SLOT_END[0] == "09:31" and features.SLOT_END[119] == "11:30" and features.SLOT_END[120] == "13:01" and features.SLOT_END[239] == "15:00")


def t_bar_ok() -> None:
    o = np.array([10.0, 10.0, 10.0, 10.0, np.nan])
    h = np.array([10.1, 10.1, 10.1, 10.1, np.nan])
    lo = np.array([9.9, 9.9, 9.9, 9.9, np.nan])
    c = o.copy()
    v = np.array([100.0, 0.0, 0.0, 100.0, np.nan])
    a = np.array([1000.0, 0.0, 5.0, 2000.0, np.nan])
    got = features.bar_ok(o, h, lo, c, v, a).tolist()
    check("§2.2 第 3 条逐根检查", got == [True, True, False, False, False], str(got))


def t_vr() -> None:
    check("量比 1.00", features.vr_rounded(100, 1, 120000) == Decimal("1.00"))
    check("量比 ROUND_HALF_UP", features.vr_rounded(1005, 1, 1200000) == Decimal("1.01"), str(features.vr_rounded(1005, 1, 1200000)))
    check("量比 V5=0 为 None", features.vr_rounded(100, 1, 0) is None)


def _rand_day(rng: np.random.Generator) -> tuple[np.ndarray, ...]:
    c = 10.0 * np.exp(np.cumsum(rng.normal(0, 0.002, 240)))
    o = np.r_[10.0, c[:-1]]
    h = np.maximum(o, c) * 1.001
    lo = np.minimum(o, c) * 0.999
    v = rng.integers(1000, 20000, 240).astype(float)
    a = v * (o + c) / 2
    return o, h, lo, c, v, a


def t_truncation() -> None:
    rng = np.random.default_rng(7)
    o, h, lo, c, v, a = _rand_day(rng)
    full = features.day_features(o, h, lo, c, v, a)
    ok = True
    for t in (29, 30, 100, 200):
        cut = [x.copy() for x in (o, h, lo, c, v, a)]
        for x in cut:
            x[t + 1 :] = np.nan
        part = features.day_features(*cut)
        for key in ("vwap", "dev", "sigma", "cumvol"):
            if not np.allclose(full[key][: t + 1], part[key][: t + 1], equal_nan=True):
                ok = False
    check("L1 截断 t 之后数据，t 时刻特征不变", ok)


def t_lookback() -> None:
    n = 30
    vol = np.full(n, 1e6)
    amt = np.full(n, 1e7)
    traded = np.ones(n, dtype=bool)
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]
    v5a, adva, cnta = features.lookbacks(dates, vol, amt, traded, [])
    vol2, amt2 = vol.copy(), amt.copy()
    vol2[20] = 9e9
    amt2[20] = 9e9
    v5b, advb, cntb = features.lookbacks(dates, vol2, amt2, traded, [])
    check("L4 V5、ADV 不含当日", v5a[20] == v5b[20] and adva[20] == advb[20] and cnta[20] == cntb[20])
    check("L4 V5 为此前 5 个有成交日", v5a[20] == 5e6 and v5b[21] == 4e6 + 9e9)
    ev = [sim.Event(ex_date=dates[22], cash=0.0, pp=0.0, s=1.0, r=0.0)]
    v5c, _, _ = features.lookbacks(dates, vol, amt, traded, ev)
    check("V5 股本换算含当日事件", v5c[22] == 1e7 and v5c[21] == 5e6 and v5c[23] == 4e6 * 2 + 1e6, str(v5c[21:24]))


# ---------------------------------------------------------------- 模拟（合成行情）

D0 = date(2024, 3, 4)


def _flat_day(price: float = 10.0, vol: float = 10000.0) -> list[np.ndarray]:
    o = np.full(240, price)
    c = np.full(240, price)
    h = o * 1.001
    lo = o * 0.999
    v = np.full(240, vol)
    a = v * price
    return [o, h, lo, c, v, a]


def _set(day: list[np.ndarray], s0: int, s1: int, price: float) -> None:
    o, h, lo, c, v, a = day
    o[s0:s1] = price
    c[s0:s1] = price
    h[s0:s1] = price * 1.001
    lo[s0:s1] = price * 0.999
    a[s0:s1] = v[s0:s1] * price
    if s0 > 0:
        o[s0] = c[s0 - 1]
        h[s0] = max(o[s0], c[s0]) * 1.001
        lo[s0] = min(o[s0], c[s0]) * 0.999
        a[s0] = v[s0] * (o[s0] + c[s0]) / 2


def _sell_day() -> list[np.ndarray]:
    d = _flat_day()
    _set(d, 60, 70, 10.30)
    _set(d, 70, 240, 10.10)
    return d


def _buy_lock_day() -> list[np.ndarray]:
    """buy_first 入场后跌到跌停价 9.00 封死到收盘：止损触发但卖不出，收盘未了结。"""
    d = _flat_day()
    _set(d, 60, 63, 9.70)
    _set(d, 63, 240, 9.00)
    d[0][63:] = 9.00
    return d


def _stock(days: list[list[np.ndarray]], kinds: list[int] | None = None, events: list[sim.Event] | None = None) -> sim.StockInput:
    n = len(days)
    arr = [np.stack([d[i] for d in days]) for i in range(6)]
    return sim.StockInput(
        exchange="SZ",
        symbol="000001",
        dates=[D0 + timedelta(days=i) for i in range(n)],
        o=arr[0], h=arr[1], l=arr[2], c=arr[3], v=arr[4], a=arr[5],
        day_kind=np.array(kinds if kinds is not None else [sim.OK] * n, dtype=np.int8),
        st=np.zeros(n, dtype=bool),
        events=events or [],
    )


PB = sim.Params(group="B", d=0.01)


def _seg(stock: sim.StockInput, end_idx: int | None = None) -> list[sim.Segment]:
    end = stock.dates[-1] if end_idx is None else stock.dates[end_idx]
    return [sim.Segment("f1", stock.dates[0], end)]


def _base(n_flat: int = 6) -> list[list[np.ndarray]]:
    return [_flat_day() for _ in range(n_flat)]


def t_sim_basic() -> None:
    st = _stock([*_base(), _sell_day(), _flat_day(), _sell_day(), _flat_day()])
    legs = sim.simulate(st, PB, _seg(st))
    check("合成行情产生 sell_first 腿", len(legs) >= 2 and all(lg.direction == "sell_first" for lg in legs), str(legs))
    check("L2 全部腿成交 bar 晚于触发 bar", all((lg.entry_day, lg.entry_slot) > (lg.entry_day, lg.trigger_slot) and (lg.exit_day, lg.exit_slot) > (lg.exit_trigger_day, lg.exit_trigger_slot) for lg in legs if lg.exit_slot is not None))
    check("同股每日最多 1 笔", len({lg.entry_day for lg in legs}) == len(legs))
    lg = legs[0] if legs else None
    if lg is not None:
        exp_q = rules.lot_floor("main", 50000.0, 10.30)
        check("q 用信号 bar 收盘价冻结", lg.q == exp_q, f"{lg.q}≠{exp_q}")
        check("入场为下一根开盘价", lg.entry_slot == lg.trigger_slot + 1 and lg.entry_price == st.o[lg.entry_day, lg.entry_slot])
        check("扣费结果 bp = 元 ÷ N", abs(lg.pnl_bp - lg.pnl_yuan / 50000.0 * 1e4) < 1e-9)
        costs = lg.commission + lg.stamp + lg.transfer + lg.slippage + lg.impact
        gross = (lg.exit_price - lg.entry_price) * lg.q * (-1 if lg.direction == "sell_first" else 1)
        check("单腿结果 = 价差 × q − 成本", abs(lg.pnl_yuan - (gross - costs)) < 1e-6, f"{lg.pnl_yuan} vs {gross - costs}")
        check("预热窗口前不开腿（触发 bar ≥ 第 30 根）", all(x.trigger_slot >= 29 for x in legs))
    # L13：改动成交 bar 自身的量（保持 > 0），入场成交不变
    st2 = _stock([*_base(), _sell_day(), _flat_day(), _sell_day(), _flat_day()])
    for x in legs:
        st2.v[x.entry_day, x.entry_slot] = 1.0
        st2.a[x.entry_day, x.entry_slot] = st2.o[x.entry_day, x.entry_slot]
    legs2 = sim.simulate(st2, PB, _seg(st2))
    ent = [(x.entry_day, x.trigger_slot, x.entry_slot, x.entry_price, x.q) for x in legs]
    ent2 = [(x.entry_day, x.trigger_slot, x.entry_slot, x.entry_price, x.q) for x in legs2]
    check("L13 成交容量不看成交 bar 自身量", ent == ent2, f"{ent} vs {ent2}")
    key = [(x.entry_day, x.entry_slot, x.entry_price, x.exit_day, x.exit_slot, x.exit_price, x.q) for x in legs]
    # 上一根已完成 bar 量 < q → 不成交：信号出现后各根量都压到 100 股，当日无腿
    st3 = _stock([*_base(), _sell_day(), _flat_day()])
    st3.v[6, 59:] = 100.0
    st3.a[6, 59:] = 100.0 * (st3.o[6, 59:] + st3.c[6, 59:]) / 2
    l4 = sim.simulate(st3, PB, _seg(st3))
    check("上一根量 < q 入场放弃", all(x.entry_day != 6 for x in l4), str(l4))
    # L11：除权日晚于末日的事件不影响结果
    st4 = _stock([*_base(), _sell_day(), _flat_day(), _sell_day(), _flat_day()], events=[sim.Event(ex_date=D0 + timedelta(days=400), cash=0.5, pp=0.0, s=0.0, r=0.0)])
    key4 = [(x.entry_day, x.entry_slot, x.entry_price, x.exit_day, x.exit_slot, x.exit_price, x.q) for x in sim.simulate(st4, PB, _seg(st4))]
    check("L11 未来除权事件不影响结果", key4 == key)
    # embargo：段末日不开腿，了结日不超过段末
    legs_e = sim.simulate(st, PB, _seg(st, end_idx=8))
    check("L7 embargo 日不开新腿", all(x.entry_day < 8 for x in legs_e) and all(x.entry_day != 8 for x in legs_e))
    check("L7 了结日不超过段末", all(x.exit_day is None or x.exit_day <= 8 for x in legs_e))
    # 剔除日不开腿
    kinds = [sim.OK] * 10
    kinds[6] = sim.EXCLUDED
    st5 = _stock([*_base(), _sell_day(), _flat_day(), _sell_day(), _flat_day()], kinds=kinds)
    check("剔除日不开腿", all(x.entry_day != 6 for x in sim.simulate(st5, PB, _seg(st5))))


def _lock_stock(next_kind: int, events: list[sim.Event] | None = None, tail: int = 2) -> sim.StockInput:
    days = [*_base(), _buy_lock_day()] + [_flat_day(9.0) for _ in range(tail)]
    kinds = [sim.OK] * len(days)
    kinds[7] = next_kind
    return _stock(days, kinds=kinds, events=events)


def t_deferral() -> None:
    st = _lock_stock(sim.OK)
    legs = sim.simulate(st, PB, _seg(st))
    first = legs[0] if legs else None
    check("buy_first 封跌停 → 顺延到下一交易日首根可成交 bar", first is not None and first.direction == "buy_first" and first.reason == "deferred" and first.exit_day == 7 and first.exit_slot == 0, str(first))
    check("L6 顺延期间与了结日不开新 T", all(b.entry_day > a.exit_day for a, b in zip(legs, legs[1:], strict=False) if a.exit_day is not None))
    st_s = _lock_stock(sim.SUSPENDED)
    ls = sim.simulate(st_s, PB, _seg(st_s))
    check("顺延日停牌继续顺延", bool(ls) and ls[0].reason == "deferred" and ls[0].exit_day == 8, str(ls[:1]))
    st_x = _lock_stock(sim.EXCLUDED)
    lx = sim.simulate(st_x, PB, _seg(st_x))
    check("顺延日被剔除 → 无法估值", bool(lx) and lx[0].reason == "unvaluable_excluded", str(lx[:1]))
    ev = [sim.Event(ex_date=D0 + timedelta(days=7), cash=0.1, pp=0.0, s=0.0, r=0.0)]
    st_e = _lock_stock(sim.OK, events=ev)
    le = sim.simulate(st_e, PB, _seg(st_e))
    check("L12 跨除权日 → 无法估值", bool(le) and le[0].reason == "unvaluable_exdate", str(le[:1]))
    lb = sim.simulate(st, PB, _seg(st, end_idx=6))
    check("L7 段末仍未了结 → 无法估值（embargo）", bool(lb) and lb[0].reason == "unvaluable_embargo" and lb[0].exit_day is None, str(lb[:1]))
    if lb:
        u = lb[0]
        check("无法估值按 0 计", u.pnl_yuan == 0.0 and u.pnl_bp == 0.0)
        check("S3 保守估值 < 0（封跌停按最后收盘 9.00 计并扣费）", u.cons_pnl_yuan < 0 and abs(u.cons_mark_price - 9.0) < 1e-9, f"{u.cons_pnl_yuan} {u.cons_mark_price}")


def t_random_and_stats() -> None:
    st = _stock([*_base(), _sell_day(), _flat_day(), _sell_day(), _flat_day()])
    legs = sim.simulate(st, PB, _seg(st))
    r1 = sim.simulate_random(st, PB, _seg(st), legs, draws=20, seed=136)
    r2 = sim.simulate_random(st, PB, _seg(st), legs, draws=20, seed=136)
    check("R 组每笔 20 次、种子可复现", len(r1) == len(legs) and [x.mean_bp for x in r1] == [x.mean_bp for x in r2])
    check("R 组同股票-日、同方向", all(r.entry_day == lg.entry_day and r.direction == lg.direction for r, lg in zip(r1, legs, strict=True)))
    days = np.arange(50)
    leg_day = np.repeat(days, 2)
    vals = np.linspace(-5, 15, leg_day.size)
    a = stats.block_bootstrap_mean(leg_day, vals, n_days=50, block=5, reps=200, seed=1)
    b = stats.block_bootstrap_mean(leg_day, vals, n_days=50, block=5, reps=200, seed=1)
    check("块自助法种子可复现", a == b and a[0] <= vals.mean() <= a[1], str(a))
    check("Holm", stats.holm([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06], str(stats.holm([0.01, 0.04, 0.03])))
    grid = {(0, 0): 1.0, (0, 1): 5.0, (1, 0): 2.0, (1, 1): 9.0}
    check("邻域中位数（±1 步）", stats.neighborhood_median(grid, (0, 0)) == 2.0 and stats.neighborhood_median(grid, (1, 1)) == 5.0)


def main() -> int:
    for fn in (t_rules, t_minutes, t_bar_ok, t_vr, t_truncation, t_lookback, t_sim_basic, t_deferral, t_random_and_stats):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001  自检汇总：任何异常记为失败
            FAILS.append(f"{fn.__name__} 异常：{type(exc).__name__}: {exc}")
    for p in PASSES:
        print("PASS", p)
    for f in FAILS:
        print("FAIL", f)
    print(f"tb136 自检：{len(PASSES)} 过 / {len(FAILS)} 败")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
