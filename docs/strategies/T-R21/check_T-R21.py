# T-R21 派生键边界例的独立算术检查（全部数值为【虚构】；不读行情、不发请求）。用法：python check_T-R21.py
from decimal import Decimal as D, ROUND_HALF_UP
def lim(base, pct, up=True):  # 涨跌停价：基准价×(1±比例)，四舍五入到 0.01（不含 3.3.17/3.3.19 边界条款，那两条由 market_rules 模块处理）
    k = D(1) + D(pct) / 100 if up else D(1) - D(pct) / 100
    return (D(base) * k).quantize(D("0.01"), ROUND_HALF_UP)
def exref(prev_close, cash_per_share=D(0), bonus_ratio=D(0)):  # 除权（息）参考价 =（前收 − 每股现金红利）/（1 + 每股送转），舍入到 0.01
    return ((D(prev_close) - cash_per_share) / (1 + bonus_ratio)).quantize(D("0.01"), ROUND_HALF_UP)
def locked(o, h, l, c, v, limit, up=True):  # 一字：四价都等于涨（跌）停价且 v>0；limit 为 null 或缺价 → None
    if limit is None or None in (o, h, l, c, v): return None
    return o == h == l == c == limit and v > 0
def rsi(closes, n=14, warm=28):  # Wilder：种子 = 前 n 个收益的简单平均；有效 K 少于 warm → None；平盘规则待裁定，这里返回 "flat"
    if len(closes) < warm: return None
    d = [b - a for a, b in zip(closes, closes[1:])]
    g = sum(max(x, 0) for x in d[:n]) / n; s = sum(max(-x, 0) for x in d[:n]) / n
    for x in d[n:]: g = (g * (n - 1) + max(x, 0)) / n; s = (s * (n - 1) + max(-x, 0)) / n
    if g == 0 and s == 0: return "flat"
    return 100.0 if s == 0 else round(100 - 100 / (1 + g / s), 2)
ok = []
ok += [lim("10.00", 10) == D("11.00"), lim("10.00", 10, False) == D("9.00")]
ok += [lim("12.34", 20) == D("14.81"), lim("12.34", 20, False) == D("9.87")]    # 14.808→14.81；9.872→9.87
ok += [lim("3.35", 5) == D("3.52"), lim("3.35", 10) == D("3.69")]                 # 主板 ST 跨生效日（2026-07-06 前 5%，之后 10%）
ok += [lim("3.35", 20) == D("4.02")]                                              # 创业板/科创板风险警示股仍为 20%
# 除权日必须用参考价，不能用前收盘：虚构 前收 20.00、每 10 股派 5 元 → 参考价 19.50
ok += [exref("20.00", D("0.5")) == D("19.50"), lim(exref("20.00", D("0.5")), 10) == D("21.45"), lim("20.00", 10) != D("21.45")]
ok += [exref("15.00", D(0), D("0.5")) == D("10.00")]                              # 10 送 5
ok += [locked(*[D("11.00")]*4, 1000, D("11.00")) is True,
       locked(D("10.50"), D("11.00"), D("10.40"), D("11.00"), 1000, D("11.00")) is False,  # 收盘触及涨停 ≠ 全天一字
       locked(*[D("11.00")]*4, 0, D("11.00")) is False, locked(*[D("11.00")]*4, 1000, None) is None]
up = [10 + 0.1 * i for i in range(30)]; ok += [rsi(up) == 100.0, rsi([10.0] * 30) == "flat", rsi(up[:27]) is None]
zz = [10, 10.2] * 15; r = rsi(zz); ok += [r is not None and 45 < r < 55]
# qfq 的比例缩放会改变除权日之前的价差，所以 RSI 必须在每个 as_of 用完整 qfq 序列重新计算，不能沿用旧值递推（虚构：除权前段 ×0.5）
a = [10 + (0.3 if i % 3 else -0.2) * i / 10 for i in range(40)]; b = [x * 0.5 for x in a[:20]] + a[20:]
ok += [rsi(a) != rsi(b)]
print("PASS" if all(ok) else f"FAIL {[i for i, x in enumerate(ok) if not x]}", len(ok)); raise SystemExit(0 if all(ok) else 1)
