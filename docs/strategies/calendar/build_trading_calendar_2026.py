# T-R16：按沪深交易所 2026 年休市通知生成 open_days（格式同 financial_basis.TradingCalendar）。
import datetime as dt, json, pathlib

def fail(msg: object = "") -> None:
    """Explicit failure that survives python -O (unlike assert)."""
    raise AssertionError(msg)


def require(cond: object, msg: object = "") -> None:
    if not cond:
        fail(msg)

CLOSED = {  # 官方通知原文休市区间（含首尾），沪深两份逐字一致
 "元旦": ("2026-01-01", "2026-01-03"), "春节": ("2026-02-15", "2026-02-23"), "清明节": ("2026-04-04", "2026-04-06"),
 "劳动节": ("2026-05-01", "2026-05-05"), "端午节": ("2026-06-19", "2026-06-21"), "中秋节": ("2026-09-25", "2026-09-27"),
 "国庆节": ("2026-10-01", "2026-10-07")}
REOPEN = {"元旦": "2026-01-05", "春节": "2026-02-24", "清明节": "2026-04-07", "劳动节": "2026-05-06", "端午节": "2026-06-22", "中秋节": "2026-09-28", "国庆节": "2026-10-08"}
WEEKEND_NOTED = ["2026-01-04", "2026-02-14", "2026-02-28", "2026-05-09", "2026-09-20", "2026-10-10"]  # 通知点名的周末休市（调休上班日），不开市
SSE = ("https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml", "关于上海证券交易所2026年部分节假日休市安排的通知（上证公告〔2025〕45号）", "2025-12-22")
SZSE = ("https://www.szse.cn/disclosure/notice/general/t20251222_618087.html", "关于2026年部分节假日休市安排的通知（深证会〔2025〕481号）", "2025-12-22")
d = lambda s: dt.date.fromisoformat(s)
closed = set()
for a, b in CLOSED.values():
    x = d(a)
    while x <= d(b): closed.add(x); x += dt.timedelta(1)
days, x = [], d("2026-01-01")
while x <= d("2026-12-31"):
    if x.weekday() < 5 and x not in closed: days.append(x.isoformat())
    x += dt.timedelta(1)
# 断言
require(all(d(s).weekday() < 5 for s in days))
require(not set(WEEKEND_NOTED) & set(days) and all(d(s).weekday() >= 5 for s in WEEKEND_NOTED))
for h, r in REOPEN.items():
    require(r in days, h)
    prev = max(s for s in days if s < r) if any(s < r for s in days) else None
    require(prev is None or prev < CLOSED[h][0], h)
    require(next(s for s in days if s > CLOSED[h][1]) == r, h)
require(days == sorted(set(days)))
out = {"coverage_start": "2026-01-01", "coverage_end": "2026-12-31", "open_days": days,
       "source": f"上交所 {SSE[1]}，{SSE[2]}，{SSE[0]}；深交所 {SZSE[1]}，{SZSE[2]}，{SZSE[0]}；两所休市区间逐项一致；周末（含调休上班的周六日）不开市"}
p = pathlib.Path(__file__).parent / "trading_calendar_2026.json"
p.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n"); print(len(days))
