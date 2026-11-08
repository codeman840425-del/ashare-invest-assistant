# T-R15 golden 期望值生成/自检脚本（仅研究侧辅助，不是业务代码/测试）。
# 全部价格、成交额、持仓、证券场景均为虚构；证券代码只作板块场景标签，不代表任何真实行情。
# 用法：python gen_T-R15.py  → 校验并写 T-R15_golden.json；退出码非 0 表示期望值与本地求值不一致。
import json, math, sys, pathlib
from decimal import Decimal, ROUND_HALF_UP
import yaml
ROOT = pathlib.Path(__file__).resolve().parents[3]
MR = yaml.safe_load((ROOT / "config/market_rules.yaml").read_text())

def seg(as_of):
    s = [x for x in MR["segments"] if x["effective_from"] <= as_of]
    return max(s, key=lambda x: x["effective_from"])

def limit_prices(board, prev_close, list_days, as_of, st=False):
    """按 market_rules.yaml 生效段取比例；注册制新股前 N 日无涨跌幅 → None（不写 20%）。"""
    g = seg(as_of)
    if list_days is not None and list_days <= g["no_limit"]["registered_ipo_first_days"]:
        return None, None
    pct = g["price_limit_pct"][board if not (st and board == "main_board") else "main_board_st"]
    q = lambda v: float(Decimal(str(v)).quantize(Decimal("0.01"), ROUND_HALF_UP))
    return q(prev_close * (1 + pct / 100)), q(prev_close * (1 - pct / 100))

def ma(x, n): return None if len(x) < n else sum(x[-n:]) / n
def atr(h, l, c, n=14, wilder=False):
    if len(c) < n + 1: return None
    tr = [max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1])) for i in range(1, len(c))]
    if not wilder: return sum(tr[-n:]) / n
    a = sum(tr[:n]) / n
    for t in tr[n:]: a = (a * (n - 1) + t) / n
    return a
def for_days(fn, k, *ser):
    """<expr> for k days：最近 k 根有效日 K 每根都为真；任一根无法求值 → None。"""
    out = []
    for j in range(k):
        cut = [s[:len(s) - j] for s in ser]
        v = fn(*cut)
        if v is None: return None
        out.append(v)
    return all(out)

def mk(closes, band=0.015, amount=2e8):
    c = [round(v, 2) for v in closes]
    return {"f.close_qfq": c, "f.high_qfq": [round(v * (1 + band), 2) for v in c],
            "f.low_qfq": [round(v * (1 - band), 2) for v in c], "f.amount": [amount] * len(c)}

def path(n_up, r_up, tail, start=20.0):
    c = [start]
    for _ in range(n_up - 1): c.append(c[-1] * (1 + r_up))
    for r in tail: c.append(c[-1] * (1 + r))
    return c

W_P = dict(ma_fast=20, ma_slow=60, trend_days=5, pullback_pct=0.02, max_dd_from_high=0.15, exit_confirm_days=2,
           atr_mult=2.0, time_stop=40, trail_trigger_r=2.0, trail_atr_mult=2.0, rsi_overheat=75.0, np_yoy_floor=-30.0,
           min_amount=50000000.0, min_list_days=120, slippage_bp=10.0, fixed_cost_bp=8.0, min_edge_cost_mult=3.0)
H_P = dict(ma_long=60, ma_break_days=3, cost_atr_k=2.0, single_cap=0.20, sector_cap=0.40, reclaim_days=2)

def watr(s): return atr(s["f.high_qfq"], s["f.low_qfq"], s["f.close_qfq"], wilder=True)
def satr(s): return atr(s["f.high_qfq"], s["f.low_qfq"], s["f.close_qfq"])

def eval_w01(fx, p=W_P):
    s, f = fx["series"], fx["features"]; c, lo, am = s["f.close_qfq"], s["f.low_qfq"], s["f.amount"]
    held = "holding" in fx; ctx = fx.get("ctx", {}); plan = fx.get("plan", {})
    def nn(*v): return any(x is None for x in v)
    def ATRb(cmp):  # Wilder（plan 2.5.14 T-R15 ③）
        a = watr(s); return None if a is None else cmp(a)
    R = {}
    R["E1"] = for_days(lambda x: None if ma(x, p["ma_slow"]) is None else ma(x, p["ma_fast"]) > ma(x, p["ma_slow"]), p["trend_days"], c)
    m20 = ma(c, p["ma_fast"])
    R["E2"] = None if m20 is None or len(lo) < 3 else (min(lo[-3:]) <= m20 * (1 + p["pullback_pct"]) and c[-1] > m20)
    R["E3"] = None if len(c) < 60 else c[-1] >= max(c[-60:]) * (1 - p["max_dd_from_high"])
    mn = f.get("f.main_net_20d"); R["A1"] = None if mn is None else mn > 0
    R["F1"] = None if ma(am, 20) is None else ma(am, 20) >= p["min_amount"]
    ld = f.get("f.list_days"); R["F2"] = None if ld is None else ld >= p["min_list_days"]
    R["F3"] = ATRb(lambda a: a / c[-1] * 10000 >= p["min_edge_cost_mult"] * (2 * p["slippage_bp"] + p["fixed_cost_bp"]))
    rg = f.get("f.market_regime_idx"); R["V1"] = None if rg is None else rg == "downtrend"
    ny = f.get("f.np_yoy_latest"); R["V2"] = None if ny is None else ny < p["np_yoy_floor"]
    rs = f.get("f.rsi14"); R["V4"] = None if rs is None else rs > p["rsi_overheat"]
    R["C2"] = None if mn is None else mn < 0
    R["C3"] = None if ma(am, 20) is None else am[-1] < ma(am, 20) * 0.5
    R["I1"] = None if ma(c, p["ma_slow"]) is None else m20 < ma(c, p["ma_slow"])
    R["I2"] = R["V1"]
    R["X1"] = for_days(lambda x: None if ma(x, p["ma_fast"]) is None else x[-1] < ma(x, p["ma_fast"]), p["exit_confirm_days"], c)
    if held:
        R["X2"] = None if plan.get("plan.stop_loss") is None else ctx["ctx.last_price"] <= plan["plan.stop_loss"]
        R["X3"] = ctx["ctx.holding_days"] >= p["time_stop"] and ctx["ctx.max_r_reached"] < 1
    if held:
        R["X6"] = ATRb(lambda a: c[-1] <= max(plan["plan.entry_price_qfq"] - p["atr_mult"] * a, min(lo[-21:-1])))
    R["X4"] = None if len(lo) < 21 else c[-1] < min(lo[-21:-1])
    if held:
        R["X5"] = ATRb(lambda a: ctx["ctx.max_r_reached"] >= p["trail_trigger_r"] and c[-1] < ctx["ctx.highest_close_since_entry_qfq"] - p["trail_atr_mult"] * a)
    order = ["E1","E2","E3","A1","F1","F2","F3","V1","V2","V4","C2","C3","I1","I2","X1","X2","X3","X4","X5","X6"]
    passed = [k for k in order if R.get(k) is True]
    rc = []
    if held:
        ex = [k for k in ("X1","X2","X3","X4","X5","X6") if R.get(k) is True]
        st, ac = ("exit_signal", "sell") if ex else ("hold_ok", "hold")
        if ex and fx["holding"]["sellable"] == 0: rc.append("T1_NOT_SELLABLE")
    else:
        if any(R[k] is True for k in ("V1","V2","V4")): st, ac = "vetoed", "wait"
        elif any(R[k] is None for k in ("E1","E2","E3","F1","F2","F3")): st, ac = "insufficient_data", "wait"
        elif all(R[k] for k in ("E1","E2","E3","F1","F2","F3")): st, ac = "entry_ok", "buy"
        else: st, ac = "not_triggered", "wait"
        if st != "vetoed" and any(R[k] is None for k in ("V1","V2","V4")) and st == "entry_ok": rc.append("KEY_DATA_MISSING")
        if st == "entry_ok" and f.get("f.limit_locked_up") is True: rc.append("LIMIT_LOCKED")
        if ld is not None and ld < 30: rc.append("NEW_LISTING")
    return {"state": st, "action": ac, "rule_ids_passed": passed, **({"reason_codes": rc} if rc else {})}

def eval_h01(fx, p=H_P):
    s, ctx, plan = fx["series"], fx["ctx"], fx.get("plan", {}); c = s["f.close_qfq"]
    a = watr(s); R = {}
    R["X1"] = None if plan.get("plan.stop_loss") is None else ctx["ctx.last_price"] <= plan["plan.stop_loss"]
    R["X2"] = None if a is None else c[-1] < ctx["ctx.cost_price_qfq"] - p["cost_atr_k"] * a
    R["W1"] = for_days(lambda x: None if ma(x, p["ma_long"]) is None else x[-1] < ma(x, p["ma_long"]), p["ma_break_days"], c)
    R["W2"] = ctx["ctx.position_weight"] > p["single_cap"]
    sw = ctx.get("ctx.sector_weight"); R["W3"] = None if sw is None else sw > p["sector_cap"]
    rg = fx["features"].get("f.market_regime_idx"); R["C1"] = None if rg is None else rg == "uptrend"
    R["C2"] = None if ma(c, 20) is None else c[-1] > ma(c, 20)
    R["I1"] = for_days(lambda x: None if ma(x, p["ma_long"]) is None else x[-1] > ma(x, p["ma_long"]), p["reclaim_days"], c)
    passed = [k for k in ("X1","X2","W1","W2","W3","C1","C2","I1") if R[k] is True]
    if any(R[k] is True for k in ("X1","X2")): st, ac = "exit_signal", "sell"
    elif any(R[k] is True for k in ("W1","W2","W3")): st, ac = "weakening", "reduce"
    elif R["X2"] is None or R["W1"] is None: st, ac = "insufficient_data", "hold"
    else: st, ac = "hold_ok", "hold"
    rc = ["T1_NOT_SELLABLE"] if st in ("exit_signal","weakening") and fx["holding"]["sellable"] == 0 else []
    return {"state": st, "action": ac, "rule_ids_passed": passed, **({"reason_codes": rc} if rc else {})}

def post(fx, e):
    """执行层可断言部分：停牌、卖出方向一字跌停（detail.direction=sell）、lot_rule（读 market_rules.yaml）。"""
    f, sec = fx["features"], fx["security"]; rc = e.setdefault("reason_codes", []); lot = seg(fx["as_of"])["lot"]
    d = "buy" if e["action"] == "buy" else "sell"; det = {}
    if f.get("f.is_suspended") and e["action"] in ("buy", "sell", "reduce"): rc.append("SUSPENDED"); det["SUSPENDED"] = {"direction": d}
    if e["action"] in ("sell", "reduce") and f.get("f.limit_locked_down"): rc.append("LIMIT_LOCKED"); det["LIMIT_LOCKED"] = {"direction": "sell"}
    if e["action"] == "buy" and "LIMIT_LOCKED" in rc: det["LIMIT_LOCKED"] = {"direction": "buy"}
    star = sec["board"] == "star"
    if e["action"] in ("buy", "sell", "reduce"):   # plan 2.5.14 T-R15 ⑨：{min_buy, step, odd_lot_sell_all, sell_qty?}
        lr = {"min_buy": lot["star_min_buy"] if star else lot["buy_lot"], "step": lot["star_step"] if star else lot["buy_lot"], "odd_lot_sell_all": False}
        if e["action"] != "buy":
            thr = lot["star_odd_lot_threshold"] if star else lot["buy_lot"]; q = fx["holding"]["qty"]
            if q < thr: lr.update(odd_lot_sell_all=True, sell_qty=q)
        e["lot_rule"] = lr
    if not rc: del e["reason_codes"]
    if det: e["reason_details"] = det
    return e

AS = "2026-10-30"
SEC = {"688018": ("688018.SH", "star"), "688073": ("688073.SH", "star"), "300364": ("300364.SZ", "chinext"), "301218": ("301218.SZ", "chinext")}
LD = {600: "2024-03-01", 900: "2023-01-03", 3: "2026-10-28"}   # 虚构上市日（与虚构 list_days 对应）
def mk(raw, band=0.015, amount=2e8, A=None):
    """raw=不复权收盘；A(d)=累计后复权因子；qfq@as_of：x(d)×A(d)/A(T)。high/low 按不复权带宽生成后同样折算。"""
    A = A or [1.0] * len(raw); k = [a / A[-1] for a in A]
    r = [round(v, 2) for v in raw]
    s = {"f.close_qfq": [round(v * q, 4) for v, q in zip(r, k)], "f.high_qfq": [round(round(v * (1 + band), 2) * q, 4) for v, q in zip(r, k)],
         "f.low_qfq": [round(round(v * (1 - band), 2) * q, 4) for v, q in zip(r, k)], "f.amount": [amount] * len(r)}
    return s, r
def feat(board, s, raw, list_days, extra, as_of=AS):
    c = s["f.close_qfq"]; prev = c[-2] if len(c) > 1 else None     # 基准价 = 前收按 qfq@T 折算 = 除权参考价
    up, dn = (None, None) if prev is None else limit_prices(board, prev, list_days, as_of)
    f = {"f.list_days": list_days, "f.is_suspended": False, "f.limit_up_price": up, "f.limit_down_price": dn,
         "f.limit_locked_up": False, "f.limit_locked_down": False}
    f.update(extra); return f
def fx_(cid, code, desc, s, raw, ld, extra, A=None, **kw):
    c, board = SEC[code]; x = {"id": cid, "desc": "【虚构】" + desc, "as_of": AS, "security": {"code": c, "board": board, "list_date": LD[ld]}}
    x.update({"series": s, "features": feat(board, s, raw, ld, extra)}); x.update(kw); return x

UP = path(74, 0.004, [-0.006, -0.006, -0.006, 0.004, 0.004, 0.004])
WB = {"f.main_net_20d": 30000000.0, "f.np_yoy_latest": 12.0, "f.rsi14": 56.0, "f.market_regime_idx": "range"}
W = []
s, r = mk(UP); W.append(fx_("W01-FX1", "300364", "满足：创业板场景；趋势成立、回踩不破、无否决；买入 lot_rule=100/100", s, r, 600, WB))
s, r = mk(UP[:-1] + [UP[-2] * 0.95]); W.append(fx_("W01-FX2", "301218", "不满足：当日收盘跌破 MA20（E2 不成立）", s, r, 600, WB))
s, r = mk(UP); W.append(fx_("W01-FX3", "688018", "缺数据：f.np_yoy_latest 缺失 → V2 无法判定，买入草案 KEY_DATA_MISSING；科创板买入 lot_rule=200/1", s, r, 900, {**WB, "f.np_yoy_latest": None}))
s, r = mk(UP); W.append(fx_("W01-FX4", "688073", "维度分歧：技术满足，主力净流出（并列，不合并；v2 删除 C1 行业反证）", s, r, 900, {**WB, "f.main_net_20d": -20000000.0}))
lu = UP[:-1] + [float(limit_prices("star", round(UP[-2], 2), 900, AS)[0])]
s, r = mk(lu); s["f.high_qfq"][-1] = s["f.low_qfq"][-1] = s["f.close_qfq"][-1]
W.append(fx_("W01-FX5", "688073", "一字涨停：科创板 20% 涨停价由 market_rules 计算；规则满足但不可成交", s, r, 900, {**WB, "f.rsi14": 70.0, "f.limit_locked_up": True}))
dn = UP[:-1] + [UP[-2] * 0.965, UP[-2] * 0.94]
s, r = mk(dn); W.append(fx_("W01-FX6", "301218", "T+1：当日买入（可卖 0）后触及止损，执行层 T1_NOT_SELLABLE（替代做T无底仓，H⑩）", s, r, 600, WB,
    holding={"qty": 1000, "sellable": 0}, ctx={"ctx.last_price": round(UP[-2] * 0.94, 2), "ctx.holding_days": 0, "ctx.sellable_qty": 0, "ctx.max_r_reached": 0.0, "ctx.highest_close_since_entry_qfq": round(UP[-2] * 0.965, 2)},
    plan={"plan.entry_price": round(UP[-2] * 0.965, 2), "plan.entry_price_qfq": round(UP[-2] * 0.965, 2), "plan.stop_loss": round(UP[-2] * 0.945, 2)}))
s, r = mk([30.0, 31.5, 33.2]); W.append(fx_("W01-FX7", "688018", "上市初期：第 3 个交易日，注册制新股前 5 日无涨跌幅（limit 价 null，不按 20%）；K 线不足 → insufficient_data，不产候选", s, r, 3, WB))
lv = path(74, 0.002, [-0.002, -0.002, -0.002, -0.002, 0.0005, 0.0005])
s, r = mk(lv, band=0.0012); W.append(fx_("W01-FX8", "300364", "成本拒绝：ATR14(Wilder)/收盘 < 3×(2×滑点+固定费率) → F3 不满足", s, r, 600, WB))
s, r = mk(UP); W.append(fx_("W01-FX9", "688018", "失效：大盘 downtrend → V1 否决、I2 命中", s, r, 900, {**WB, "f.market_regime_idx": "downtrend"}))
br = UP[:-2] + [UP[-3] * 0.95, UP[-3] * 0.93]
s, r = mk(br); W.append(fx_("W01-FX10", "688073", "科创板零股：持有 150 股（<200）；收盘连续 2 日破 MA20 → sell，lot_rule 要求一次性卖出全部 150 股", s, r, 900, WB,
    holding={"qty": 150, "sellable": 150}, ctx={"ctx.last_price": round(UP[-3] * 0.93, 2), "ctx.holding_days": 12, "ctx.sellable_qty": 150, "ctx.max_r_reached": 0.4, "ctx.highest_close_since_entry_qfq": round(UP[-3], 2)},
    plan={"plan.entry_price": round(UP[-3] * 0.98, 2), "plan.entry_price_qfq": round(UP[-3] * 0.98, 2), "plan.stop_loss": round(UP[-3] * 0.85, 2)}))
# ---- 新增 ----
s, r = mk(UP); W.append(fx_("W01-FX11", "301218", "停牌：as_of 当日 f.is_suspended=true（规则按此前有效日 K 求值），买入不可执行 SUSPENDED", s, r, 600, WB))
W[-1]["features"]["f.is_suspended"] = True
# 除权：送转 10 送 5（A 由 1.0 → 1.5），建仓在除权前，as_of 在除权后 6 根
def exdiv(n_pre, n_post, p0, r_pre, r_post, ratio):
    raw = [p0]; A = [1.0]
    for _ in range(n_pre - 1): raw.append(raw[-1] * (1 + r_pre)); A.append(1.0)
    raw.append(raw[-1] / ratio); A.append(ratio)
    for _ in range(n_post - 1): raw.append(raw[-1] * (1 + r_post)); A.append(ratio)
    return raw, A
raw, A = exdiv(74, 6, 15.0, 0.004, 0.0, 1.5)
s, r = mk(raw, A=A); ent = round(r[-9], 2)   # 建仓于除权前第 3 根（不复权成交价）
W.append(fx_("W01-FX12", "688018", f"除权·送转：10 送 5，A(d)=前 74 根 1.0、后 6 根 1.5；建仓不复权价 {ent}，plan.entry_price_qfq={ent}×1.0/1.5；X6 用 qfq 口径不触发（若误用不复权建仓价会误触发）", s, r, 900, WB, A=A,
    holding={"qty": 600, "sellable": 600}, ctx={"ctx.last_price": r[-1], "ctx.holding_days": 8, "ctx.sellable_qty": 600, "ctx.max_r_reached": 0.2, "ctx.highest_close_since_entry_qfq": r[-1]},
    plan={"plan.entry_price": ent, "plan.entry_price_qfq": round(ent * 1.0 / 1.5, 4), "plan.stop_loss": round(ent / 1.5 * 0.9, 2)}))
raw, A = exdiv(74, 6, 20.0, 0.004, 0.0, 1.03)    # 现金分红：A 1.0 → 1.03（每股派息约 3%，虚构）
s, r = mk(raw, band=0.004, A=A); ent = round(r[-9], 2)
W.append(fx_("W01-FX13", "300364", f"除权·现金分红：A(d)=前 74 根 1.0、后 6 根 1.03；建仓不复权价 {ent}，plan.entry_price_qfq={ent}/1.03；X6 不触发（误用不复权价会误触发）", s, r, 600, WB, A=A,
    holding={"qty": 1000, "sellable": 1000}, ctx={"ctx.last_price": r[-1], "ctx.holding_days": 8, "ctx.sellable_qty": 1000, "ctx.max_r_reached": 0.1, "ctx.highest_close_since_entry_qfq": r[-1]},
    plan={"plan.entry_price": ent, "plan.entry_price_qfq": round(ent / 1.03, 4), "plan.stop_loss": round(ent / 1.03 * 0.9, 2)}))
raw, A = exdiv(74, 6, 15.0, 0.004, 0.0, 1.5)
s, r = mk(raw, A=A); hi = round(r[73], 2); ent = round(r[40], 2)
W.append(fx_("W01-FX15", "688073", f"跟踪止盈跨除权：10 送 5，A(d)=前 74 根 1.0、后 6 根 1.5；入场以来最高不复权收盘 {hi}（除权前）→ ctx.highest_close_since_entry_qfq={hi}×1.0/1.5；已达 2.5R，X5 按 qfq 不触发（误用不复权最高价会误触发）", s, r, 900, WB, A=A,
    holding={"qty": 800, "sellable": 800}, ctx={"ctx.last_price": r[-1], "ctx.holding_days": 39, "ctx.sellable_qty": 800, "ctx.max_r_reached": 2.5, "ctx.highest_close_since_entry_qfq": round(hi / 1.5, 4)},
    plan={"plan.entry_price": ent, "plan.entry_price_qfq": round(ent / 1.5, 4), "plan.stop_loss": round(ent / 1.5 * 0.9, 2)}))
# ATR 口径敏感：前段高波动、最后 14 根低波动 → SMA ATR < 84bp ≤ Wilder ATR
bands = [0.03] * 66 + [0.001] * 14
c0 = [round(v, 2) for v in UP]; hs = [round(v * (1 + b), 2) for v, b in zip(c0, bands)]; ls = [round(v * (1 - b), 2) for v, b in zip(c0, bands)]
s = {"f.close_qfq": c0, "f.high_qfq": hs, "f.low_qfq": ls, "f.amount": [2e8] * 80}
W.append(fx_("W01-FX14", "688073", "ATR 口径锁定：Wilder ATR14 ≥ 84bp 而 SMA ATR14 < 84bp → F3 按 Wilder 满足 → entry_ok（若误用 SMA 则 not_triggered）", s, c0, 900, WB))

HU = path(80, 0.003, []); last = HU[-1]
def cx(cost, w=0.10, sw=0.20, lp=None, sell=1000, hd=30, cq=None):
    return {"ctx.last_price": round(lp or last, 2), "ctx.cost_price": round(cost, 3), "ctx.cost_price_qfq": round(cq if cq is not None else cost, 4),
            "ctx.position_weight": w, "ctx.sector_weight": sw, "ctx.holding_days": hd, "ctx.sellable_qty": sell}
def hfx(i, code, desc, closes, ld, extra_f, holding, ctx, plan=None, band=0.015, A=None):
    s, r = mk(closes, band=band, A=A); kw = {"holding": holding, "ctx": ctx}
    if plan: kw["plan"] = plan
    return fx_(f"H01-FX{i}", code, desc, s, r, ld, extra_f, A=A, **kw)
H = []
H.append(hfx(1, "300364", "健康持仓：无离场/转弱命中 → hold_ok", HU, 600, {"f.market_regime_idx": "uptrend"}, {"qty": 1000, "sellable": 1000}, cx(last * 0.9)))
mb = path(74, 0.003, [-0.03, -0.03, -0.03, -0.02, -0.01, -0.005])
H.append(hfx(2, "301218", "转弱：收盘连续 3 日低于 MA60 → weakening/reduce", mb, 600, {"f.market_regime_idx": "range"}, {"qty": 1000, "sellable": 1000}, cx(mb[-1] * 0.85, lp=mb[-1])))
H.append(hfx(3, "688018", "跌破成本(qfq)−2×ATR → exit_signal/sell", mb, 900, {"f.market_regime_idx": "range"}, {"qty": 400, "sellable": 400}, cx(mb[-1] * 1.20, lp=mb[-1], sell=400)))
H.append(hfx(4, "688073", "盘中触及计划止损且当日买入可卖 0（科创板 400 股）→ exit_signal/sell + T1_NOT_SELLABLE", HU, 900, {"f.market_regime_idx": "range"}, {"qty": 400, "sellable": 0},
             cx(last, lp=last * 0.93, sell=0, hd=0), {"plan.entry_price": round(last, 2), "plan.entry_price_qfq": round(last, 2), "plan.stop_loss": round(last * 0.94, 2)}))
H.append(hfx(5, "300364", "单只仓位 0.35 > 上限 0.20 → weakening/reduce", HU, 600, {"f.market_regime_idx": "uptrend"}, {"qty": 1000, "sellable": 1000}, cx(last * 0.9, w=0.35)))
H.append(hfx(6, "688018", "科创板零股：持有 150 股；收盘连续 3 日低于 MA60 → reduce，lot_rule 一次性卖出 150 股", mb, 900, {"f.market_regime_idx": "range"}, {"qty": 150, "sellable": 150}, cx(mb[-1] * 0.85, lp=mb[-1], sell=150)))
lim = path(78, 0.003, [-0.10]); ldn = float(limit_prices("chinext", round(lim[-2], 2), 600, AS)[1]); lim[-1] = ldn
x = hfx(7, "301218", "一字跌停（创业板 20% 跌停价由 market_rules 计算）：跌破成本−2×ATR → sell；卖出方向 LIMIT_LOCKED，detail.direction=sell", lim, 600, {"f.market_regime_idx": "range", "f.limit_locked_down": True}, {"qty": 1000, "sellable": 1000}, cx(lim[-2] * 1.05, lp=ldn))
x["series"]["f.high_qfq"][-1] = x["series"]["f.low_qfq"][-1] = x["series"]["f.close_qfq"][-1]; H.append(x)
H.append(hfx(8, "688073", "上市初期第 3 个交易日（无涨跌幅，limit 价 null）；MA60/ATR 无法求值、无命中 → insufficient_data，不产候选、建议显示 hold", [30.0, 31.5, 33.2], 3, {"f.market_regime_idx": "range"}, {"qty": 200, "sellable": 200}, cx(30.0, lp=33.2, sell=200, hd=2)))
H.append(hfx(9, "300364", "反证与失效并存：C1/C2/I1 命中、行业占比 0.45 > 0.40 → weakening/reduce（反证并列，不抵消）", HU, 600, {"f.market_regime_idx": "uptrend"}, {"qty": 1000, "sellable": 1000}, cx(last * 0.9, sw=0.45)))
# ---- 新增 ----
x = hfx(10, "301218", "停牌：as_of f.is_suspended=true，收盘连续 3 日低于 MA60 → reduce，执行层 SUSPENDED", mb, 600, {"f.market_regime_idx": "range"}, {"qty": 1000, "sellable": 1000}, cx(mb[-1] * 0.85, lp=mb[-1]))
x["features"]["f.is_suspended"] = True; H.append(x)
raw, A = exdiv(74, 6, 15.0, 0.003, 0.002, 1.5)
cost_raw = round(raw[60] , 2)   # 建仓于第 61 根（除权前，A(e)=1.0）
x = hfx(11, "688018", f"成本跨除权：10 送 5，A(d)=前 74 根 1.0、后 6 根 1.5；不复权成本 {cost_raw}，ctx.cost_price_qfq={cost_raw}×1.0/1.5；X2 不触发（误用不复权成本会误触发）", raw, 900, {"f.market_regime_idx": "range"},
        {"qty": 600, "sellable": 600}, cx(cost_raw, lp=round(raw[-1], 2), sell=600, cq=cost_raw / 1.5), A=A)
H.append(x)

EXPECT = {"W01-FX1": "entry_ok", "W01-FX2": "not_triggered", "W01-FX3": "entry_ok", "W01-FX4": "entry_ok", "W01-FX5": "entry_ok",
 "W01-FX6": "exit_signal", "W01-FX7": "insufficient_data", "W01-FX8": "not_triggered", "W01-FX9": "vetoed", "W01-FX10": "exit_signal",
 "W01-FX11": "entry_ok", "W01-FX12": "hold_ok", "W01-FX13": "hold_ok", "W01-FX14": "entry_ok", "W01-FX15": "hold_ok",
 "H01-FX1": "hold_ok", "H01-FX2": "weakening", "H01-FX3": "exit_signal", "H01-FX4": "exit_signal", "H01-FX5": "weakening",
 "H01-FX6": "weakening", "H01-FX7": "exit_signal", "H01-FX8": "insufficient_data", "H01-FX9": "weakening", "H01-FX10": "weakening", "H01-FX11": "hold_ok"}
bad = 0
for fx in W: fx["expect"] = post(fx, eval_w01(fx))
for fx in H: fx["expect"] = post(fx, eval_h01(fx))
a = [x for x in W if x["id"] == "W01-FX14"][0]["series"]; sm, wl = satr(a) / a["f.close_qfq"][-1] * 1e4, watr(a) / a["f.close_qfq"][-1] * 1e4
print(f"FX14 SMA {sm:.1f}bp Wilder {wl:.1f}bp"); bad += not (sm < 84 <= wl)
for fx in W + H:
    ok = fx["expect"]["state"] == EXPECT[fx["id"]]; bad += not ok
    print(("OK " if ok else "BAD"), fx["id"], json.dumps(fx["expect"], ensure_ascii=False))
out = {"task": "T-R15", "card_version": 2, "revised_by": "T-R20（plan T-R19 裁定③④，78de694）；v1 冻结于 golden/history/T-R15_golden.v1.json", "fictitious": True, "note": "全部数值虚构；证券代码仅为板块场景标签，不代表真实行情；价格 series 为 qfq@as_of", "generated_by": "docs/strategies/golden/gen_T-R15.py",
       "params": {"sw_ma_trend_pullback": W_P, "hold_risk_monitor": H_P}, "cards": {"sw_ma_trend_pullback": W, "hold_risk_monitor": H}}
(pathlib.Path(__file__).parent / "T-R15_golden.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
sys.exit(1 if bad else 0)
