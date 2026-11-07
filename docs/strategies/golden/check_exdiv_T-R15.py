# 除权/ATR 例的独立算术检查：只读 T-R15_golden.json，不导入生成器；常数手写自 plan 2.5.14 T-R15 ⓪/③。
import json, pathlib
G = json.loads((pathlib.Path(__file__).parent / "T-R15_golden.json").read_text())
fx = {x["id"]: x for c in G["cards"].values() for x in c}
def wilder(h, l, c, n=14):
    tr = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, len(c))]
    v = sum(tr[:n]) / n
    for t in tr[n:]: v = v * (n-1) / n + t / n
    return v
def sma(h, l, c, n=14):
    return sum(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(len(c)-n, len(c))) / n
err = []
for fid, AT, key in (("W01-FX12", 1.5, "plan"), ("W01-FX13", 1.03, "plan"), ("H01-FX11", 1.5, "ctx")):
    x = fx[fid]; s = x["series"]; c, h, l = s["f.close_qfq"], s["f.high_qfq"], s["f.low_qfq"]
    if "f.close_raw" in x["features"]: err.append(fid + " 含未登记键 f.close_raw")
    if abs(c[74] - c[73]) > 0.02: err.append(fid + " 除权处 qfq 不连续")          # 除权日第 75 根，后 6 根
    raw_p = x[key]["plan.entry_price" if key == "plan" else "ctx.cost_price"]
    q_p = x[key]["plan.entry_price_qfq" if key == "plan" else "ctx.cost_price_qfq"]
    if abs(q_p - raw_p * 1.0 / AT) > 1e-3: err.append(fid + " P×A(e)/A(T) 不符")
    a = wilder(h, l, c)
    if key == "plan":
        st = lambda P: c[-1] <= max(P - 2.0 * a, min(l[-21:-1]))
        good, wrong = st(q_p), st(raw_p)
        exp = "X6" in x["expect"]["rule_ids_passed"]
    else:
        good, wrong = c[-1] < q_p - 2.0 * a, c[-1] < raw_p - 2.0 * a
        exp = "X2" in x["expect"]["rule_ids_passed"]
    print(fid, f"A(T)={AT} P_raw={raw_p} P_qfq={q_p:.4f} close={c[-1]} wilder={a:.4f} 正确口径命中={good} 混用命中={wrong} expect命中={exp}")
    if good != exp or good == wrong: err.append(fid + " 口径不可区分或期望错")
# W01-FX15：跟踪止盈跨除权（X5），最高收盘不复权价写在 desc，qfq = hi×1.0/1.5
x = fx["W01-FX15"]; s = x["series"]; c = s["f.close_qfq"]; a = wilder(s["f.high_qfq"], s["f.low_qfq"], c)
import re as _re; hi = float(_re.search(r"最高不复权收盘 ([0-9.]+)", x["desc"]).group(1)); hq = x["ctx"]["ctx.highest_close_since_entry_qfq"]
good, wrong = c[-1] < hq - 2.0 * a, c[-1] < hi - 2.0 * a
print(f"W01-FX15 hi_raw={hi} hi_qfq={hq} close={c[-1]} wilder={a:.4f} 正确口径命中={good} 混用命中={wrong}")
if abs(hq - hi / 1.5) > 1e-3 or good == wrong or ("X5" in x["expect"]["rule_ids_passed"]) != good or x["ctx"]["ctx.max_r_reached"] < 2.0: err.append("W01-FX15")
x = fx["W01-FX14"]; s = x["series"]; c = s["f.close_qfq"]
w, m = wilder(s["f.high_qfq"], s["f.low_qfq"], c) / c[-1] * 1e4, sma(s["f.high_qfq"], s["f.low_qfq"], c) / c[-1] * 1e4
thr = 3.0 * (2 * 10 + 8); print(f"W01-FX14 wilder={w:.1f}bp sma={m:.1f}bp thr={thr}")
if not (m < thr <= w) or "F3" not in x["expect"]["rule_ids_passed"]: err.append("FX14")
print("PASS" if not err else err); raise SystemExit(bool(err))
