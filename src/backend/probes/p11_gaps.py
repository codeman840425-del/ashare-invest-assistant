"""第 11 项：catalog.md §5 缺口补测（快照延迟、cje/v 单位、plrq 覆盖与修订、退市股、公告时间精度、
因子空值与时点性、因子数量核对）。

设计原则：调用量少（约 40～45 次 HTTP）、串行、复用同一 Session；每项输出结构化结论：
  {"name": "GAP<n>_...", "item": 说明, "status": "measured|skipped|inconclusive|error",
   "conclusion": {...}, "evidence": {...}, "limits": [...], "next_steps": [...]}
本文件不含任何证书；URL 模板中的 {licence} 由 common.call 填充并在日志中脱敏。
"""
from __future__ import annotations

import json
import math
import re
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path

import common as c
from _helpers import probe

BJ = timezone(timedelta(hours=8))      # 北京时间固定 UTC+8（不依赖 zoneinfo/tzdata，Windows 也可用）

# dry-run 用：None=按真实北京时间判断；True/False=强制视为盘中/盘后（仅 dry-run 时生效）
FORCE_SESSION = None

LAT_CODE = "000001"
LAT_SAMPLES = 6            # 每个快照源采样次数（5～10 之间）
LAT_INTERVAL_S = 5.0       # 采样间隔秒数（dry-run 时缩短）

# ---- 探针开关（T-B05 复测；由 run_all.py 的命令行参数设置，缺省 = 原行为）
LAT_CODES: list = [LAT_CODE]   # --gap1-codes：GAP1 采样股票列表（复测 1 用 5 只）
LAT_MAX_CODES = 10             # 上限：每只每轮 2 次调用，10 只 × 2 × 6 = 120 次
# --local-ahead-s / --ntp-file：本机时钟比 NTP 快多少秒（本机 − NTP）。可给多次（时段前、后），取均值修正。
# w32tm /stripchart /dataonly 的数值按“正值 = 本机比目标快”读入（w32tm.com 说明）；符号另用 HTTP Date 头交叉检查。
LOCAL_AHEAD_S: list = []
NTP_SOURCES: list = []         # 记录 NTP 数值来源（文件名/命令行），写进结论
NTP_RAW: dict = {}             # --ntp-file 的原文（文件名 → 文本），原样存进 GAP1 evidence 备查
ONLY = None                    # --p11-only：None=全部 GAP1–7；见 ONLY_CHOICES
ONLY_CHOICES = ("gap1", "gap6-history", "gap6-nulls")
HISTORY_BASELINE = None        # --history-baseline：基线样例目录（只读本地文件，比对是否回填；不发请求）
PIT_BATCH_DAY = None           # batch 请求日期 YYYY-MM-DD；None = history 序列中点（离线重放时填原请求日）
NULLS_BASE_CODES = ["600519", "300750", "000001", "688981", "920000"]   # 复测 2：原 3 只 + 科创 + 北交所
NULLS_ZT_PICK = 2              # 复测 2：取当时已在涨停池里的前 N 只（按首次封板时间升序）
ZT_CODES: list = []            # --zt-codes：收盘后复跑时沿用盘中那次选出的涨停股（仍会取一次涨停池核对）
SEAL_FACTORS = ["limit_up_streak", "seal_ratio", "seal_to_float"]
_CODE6 = re.compile(r"^\d{6}$")

# ---- 文档依据（/tmp/mrdoc 缓存的公开文档页，2026-11-01 读取）
DOC_UNITS = {
    "hsstock/real/time（券商源）": "cje: 成交总额（未注明单位）; v: 成交总量（未注明单位）; pv: 原始成交总量; tv: 成交量",
    "hsrl/ssjy（网络源）": "cje: 成交额（元）; v: 成交量（手）",
    "hsstock/latest|history 日线": "a: 成交额（未注明单位）; v: 成交量（未注明单位）",
}
DOC_INCOME_FIELDS = set((
    "jzrq plrq yysr yzbf fdczssr yyzcb fdczscb yffy tbj pczjje tqbxhtzbjje bdhlzc fbfy gyjzbdsy qhsy tgsy btsr "
    "qtywlr bhbfzhbqsljlr lxsr sxfjyjsr sxfjyjzc qtywcb hdsy fldzcczsy sdsfy wqrtzss gsmgsyzzdjlr lxzc qtywsr "
    "yyzsr yycb yysjjfj xsfy glfy cwfy zcjzss tzsy lyqyhhhqydtzsy yylr ywsr ywzc lrze jlr jlrhfcjcx ssgdsy jbmgsy "
    "xsmgsy zhsyz gsssgdzhsyz qtsy").split())
# 文档因子页：85 个；其中 north_5d_net / north_20d_net / north_holding_ratio 按设计返回空，其余 82 个“已上线”
DOC_FACTORS = {
    "valuation": "pe_ttm pb ps_ttm pcf_ttm ev_ebitda peg graham_value price_vs_graham",
    "quality": "roe_ttm roa_ttm gross_margin net_margin debt_ratio current_ratio asset_turnover accrual_ratio",
    "growth": "rev_yoy rev_cagr_3y profit_yoy profit_cagr_3y eps_yoy eps_cagr_3y rev_profit_scissors",
    "momentum": "momentum_5d momentum_20d momentum_60d momentum_120d rs_20d high52_distance ma_deviation",
    "capital": "north_5d_net north_20d_net north_holding_ratio main_5d_net main_20d_net flow_5d_ratio "
               "flow_20d_ratio big_order_net_5d",
    "signal": "macd_signal ma5_ma20_cross ma20_ma60_cross kdj_signal boll_position volume_ratio rsi_14 ma_trend "
              "boll_squeeze volume_price_divergence",
    "risk": "beta_252d volatility_20d volatility_60d sharpe_252d max_drawdown_252d var_95",
    "dividend": "dividend_yield payout_ratio dividend_continuous_years dividend_growth_3y dividend_avg_3y",
    "scale": "total_market_cap float_market_cap float_ratio turnover_20d_avg amihud_20d cap_scale",
    "sentiment": "limit_up_count_20d limit_down_count_20d attention_score recent_event event_date event_impact "
                 "limit_up_streak seal_ratio seal_to_float limit_up_break pre_auction_volume_ratio dragontiger_count",
    "intraday": "intraday_vol_20d intraday_parkinson_20d overnight_gap_20d intraday_momentum_20d "
                "intraday_amplitude_20d vwap_deviation_20d intraday_turnover_ratio_20d intraday_skew_20d",
}
DOC_FACTOR_IDS = [f for v in DOC_FACTORS.values() for f in v.split()]
DOC_NORTH_EMPTY = ["north_5d_net", "north_20d_net", "north_holding_ratio"]
DOC_82 = [f for f in DOC_FACTOR_IDS if f not in DOC_NORTH_EMPTY]
FACTOR_META = {"code", "name", "trade_date", "update_time", "report_period", "calc_version", "dm", "mc", "theme"}
# 精度差判定（T-B48，T-B05 前按架构裁定收紧）：只有“较短一方 = 较长一方四舍五入或截断到较短一方的小数位数”
# 才算精度噪声；较短一方的小数位数须在 [MIN, MAX] 之间。MIN=4：像 15.0（0 位）↔ 14.97 这种位数很少的值，
# 舍入后相等也可能是真实变化，不算。实测截断是 6 位（1.4714182949831487 ↔ 1.471418）。
PRECISION_MIN_DECIMALS = 4
PRECISION_MAX_DECIMALS = 8

# 上市较早的股票（上市日期为公开常识：000001 平安银行(原深发展) 1991-04-03；600000 浦发银行 1999-11-10；
# 600519 贵州茅台 2001-08-27，与 T003 实测日线首行 2001-08-27 一致）
EARLY_STOCKS = ["600519.SH", "000001.SZ", "600000.SH"]

# 已退市股票：文档无“退市股列表”接口（股票列表 /hslt/list 字段仅 dm/mc/jys，未说明是否含退市股），
# 因此以下代码来自公开报道/交易所终止上市公告（凭常识列出，未经接口核实；若接口返回“代码不存在”，
# 需人工确认是否为代码记忆错误，而非数据缺失）：
DELISTED = [
    ("600087.SH", "长航油运", "2014-06 终止上市（首家退市央企控股公司，上交所公告）"),
    ("600432.SH", "吉恩镍业", "2018-07 终止上市（上交所公告）"),
    ("000979.SZ", "中弘股份", "2018-12 终止上市（连续 20 日收盘价低于面值，深交所公告）"),
    ("002450.SZ", "康得新", "2021-05/06 终止上市（深交所公告）"),
]

FACTOR_STOCKS = ["600519", "000001", "300750"]
PIT_FACTORS = ["profit_yoy", "roe_ttm"]          # 纯财务驱动：值只应在财报披露后跳变
PIT_ST, PIT_ET = "20250501", "20261031"          # 约 365 个交易日，覆盖 6 次定期报告披露


# =========================================================================== 纯函数（dry-run 可离线单测）
def bj_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(BJ)


def is_bj_session(dt: datetime, need_s: float = 0.0) -> bool:
    """dt（北京时间）是否处于连续竞价时段（工作日 9:30–11:30、13:00–15:00），且距本段结束至少 need_s 秒。
    不含节假日判断（另用交易日历接口确认）。"""
    if dt.weekday() >= 5:
        return False
    sec = dt.hour * 3600 + dt.minute * 60 + dt.second
    for a, b in ((9 * 3600 + 30 * 60, 11 * 3600 + 30 * 60), (13 * 3600, 15 * 3600)):
        if a <= sec < b and sec + need_s <= b:
            return True
    return False


def same_auction_session(snap, recv) -> bool:
    """快照 t 与本机收到时刻是否同属一个北京时间连续竞价时段（同一自然日的 9:30–11:30 或 13:00–15:00）。
    用于计算 stale_threshold 时丢掉停牌/隔夜/午休冻结等不能代表本段行情延迟的样本。
    时区按 Asia/Shanghai；naive 视为北京时间。"""
    if snap is None or recv is None:
        return False
    if snap.tzinfo is None:
        snap = snap.replace(tzinfo=BJ)
    else:
        snap = snap.astimezone(BJ)
    if recv.tzinfo is None:
        recv = recv.replace(tzinfo=BJ)
    else:
        recv = recv.astimezone(BJ)
    if snap.date() != recv.date():
        return False
    if not (is_bj_session(snap) and is_bj_session(recv)):
        return False
    return (snap.hour < 12) == (recv.hour < 12)


def _as_bj(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=BJ)
    return dt.astimezone(BJ)


def _canonical_session_anchor(recv):
    """把收到时刻映射到一个规范连续竞价时刻（最近工作日 13:30，北京时间），供 dry-run 强制盘中使用。"""
    recv = _as_bj(recv)
    d = recv.replace(hour=13, minute=30, second=0, microsecond=0)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def in_session_for_threshold(snap, recv, force_session: bool = False) -> bool:
    """stale_threshold 的同段判定。实盘 = same_auction_session。
    dry-run 且 FORCE_SESSION、但收到时刻已在盘外时：将 (snap, recv) 平移同一差值，使 recv 落到
    规范连续竞价时刻后再判定。延迟与日期间隔不变，因此午休冻结/隔夜旧票仍排除，
    mock 的「当前时刻−数秒」活样本在盘后 dry-run 仍计入。"""
    if not force_session:
        return same_auction_session(snap, recv)
    recv = _as_bj(recv)
    if recv is not None and is_bj_session(recv):
        return same_auction_session(snap, recv)
    if snap is None or recv is None:
        return False
    snap = _as_bj(snap)
    anchor = _canonical_session_anchor(recv)
    return same_auction_session(snap + (anchor - recv), anchor)


def session_lags(samples: list) -> list:
    """samples 中 in_session 且有 lag_s 的延迟秒数。"""
    return [s["lag_s"] for s in samples if s.get("lag_s") is not None and s.get("in_session")]


def norm_date(v) -> str | None:
    """'2026-09-30' / '20260930' / '2026-09-30 00:00:00' / 20260930 → '2026-09-30'。"""
    if v in (None, ""):
        return None
    m = re.match(r"\s*(\d{4})-?(\d{2})-?(\d{2})", str(v))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def parse_bj(ts) -> datetime | None:
    m = re.match(r"\s*(\d{4})-?(\d{2})-?(\d{2})[ T]?(\d{2}):?(\d{2}):?(\d{2})?", str(ts or ""))
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return datetime(y, mo, d, h, mi, s, tzinfo=BJ)


def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


V_UNITS = {1: "股", 100: "手(100股)", 10_000: "万股", 1_000_000: "万手"}
CJE_UNITS = {1: "元", 10_000: "万元"}


def infer_units(rec: dict, v_key="v", amt_key="cje", price_keys=("p", "c")) -> dict:
    """用同一条记录的 成交额/(成交量×价格) 推断单位。对每个 (v 单位, 额单位) 组合计算 VWAP，
    落在 [最低价×0.98, 最高价×1.02] 内即为“可行”。返回可行组合与首选结论（优先额=元）。"""
    v, a = _num(rec.get(v_key)), _num(rec.get(amt_key))
    hi, lo = _num(rec.get("h")), _num(rec.get("l"))
    p = next((_num(rec.get(k)) for k in price_keys if _num(rec.get(k))), None)
    if not v or not a or not (p or (hi and lo)):
        return {"ok": False, "reason": f"缺少字段或为 0：{v_key}={rec.get(v_key)} {amt_key}={rec.get(amt_key)}"}
    hi = hi or p
    lo = lo or p
    mid = (hi + lo) / 2
    raw = a / (v * mid)
    feas = []
    for vm, vn in V_UNITS.items():
        for am, an in CJE_UNITS.items():
            vwap = a * am / (v * vm)
            if lo * 0.98 <= vwap <= hi * 1.02:
                feas.append({"v": vn, amt_key: an, "vwap": round(vwap, 4)})
    pick = next((f for f in feas if f[amt_key] == "元"), feas[0] if feas else None)
    return {"ok": bool(feas), "ratio_amt_over_v_x_mid": round(raw, 4), "low": lo, "high": hi,
            "feasible": feas, "pick": pick}


def classify_time_precision(values: list) -> dict:
    """公告时间字段精度：day（仅日期，或时间部分恒为 00:00:00）/ hour / minute / second。"""
    n = len(values)
    only_date = with_time = zero_time = sec_nonzero = min_nonzero = 0
    hours = {}
    for v in values:
        s = str(v or "").strip()
        m = re.match(r"^\d{4}-?\d{2}-?\d{2}(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?", s)
        if not m:
            continue
        if m.group(1) is None:
            only_date += 1
            continue
        with_time += 1
        h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        if (h, mi, se) == (0, 0, 0):
            zero_time += 1
            continue
        hours[h] = hours.get(h, 0) + 1
        sec_nonzero += se != 0
        min_nonzero += mi != 0
    if sec_nonzero:
        prec = "second"
    elif min_nonzero:
        prec = "minute"
    elif hours:
        prec = "hour"
    elif only_date or zero_time:
        prec = "day"
    else:
        prec = "unknown"
    return {"n": n, "only_date": only_date, "with_time": with_time, "time_all_zero": zero_time,
            "nonzero_second": sec_nonzero, "nonzero_minute": min_nonzero, "precision": prec,
            "hour_hist": dict(sorted(hours.items())), "examples": [str(x) for x in values[:5]]}


def analyze_fin_rows(rows: list) -> dict:
    """plrq 覆盖率与修订迹象。"""
    rows = [r for r in rows if isinstance(r, dict)]
    if not rows:
        return {"rows": 0}
    keys = sorted({k for r in rows for k in r})
    has_plrq = "plrq" in keys
    rs = sorted(rows, key=lambda r: norm_date(r.get("jzrq")) or "")
    plrq_null = [r for r in rs if not norm_date(r.get("plrq"))]
    early = [r for r in rs if (norm_date(r.get("jzrq")) or "9999") < "2007-01-01"]
    lags, neg, huge = [], [], []
    for r in rs:
        j, p = norm_date(r.get("jzrq")), norm_date(r.get("plrq"))
        if j and p:
            d = (date.fromisoformat(p) - date.fromisoformat(j)).days
            lags.append(d)
            if d < 0:
                neg.append({"jzrq": j, "plrq": p})
            if d > 400:
                huge.append({"jzrq": j, "plrq": p, "lag_days": d})
    groups = {}
    for r in rs:
        groups.setdefault(norm_date(r.get("jzrq")), []).append(r)
    dups = {k: v for k, v in groups.items() if k and len(v) > 1}
    dup_examples = []
    for k, v in list(dups.items())[:3]:
        diff = sorted({f for f in keys if len({str(x.get(f)) for x in v}) > 1})
        dup_examples.append({"jzrq": k, "n": len(v), "plrq": [x.get("plrq") for x in v], "diff_fields": diff[:15]})
    flag_like = [k for k in keys if k not in DOC_INCOME_FIELDS and re.search(
        r"(gz|xz|bg|type|flag|ver|source|ly|status|zt|sfgz|sfxz|update|gxsj|modify|correct)", k, re.I)]
    return {
        "rows": len(rs), "fields_n": len(keys), "has_plrq_field": has_plrq,
        "jzrq_min": norm_date(rs[0].get("jzrq")), "jzrq_max": norm_date(rs[-1].get("jzrq")),
        "earliest_row_plrq": rs[0].get("plrq"), "earliest_with_plrq": next(
            (norm_date(r.get("jzrq")) for r in rs if norm_date(r.get("plrq"))), None),
        "plrq_null_ratio": round(len(plrq_null) / len(rs), 4),
        "plrq_null_ratio_before_2007": round(sum(1 for r in early if not norm_date(r.get("plrq"))) / len(early), 4)
        if early else None,
        "lag_days_p50": statistics.median(lags) if lags else None, "lag_days_max": max(lags) if lags else None,
        "plrq_before_jzrq": neg[:5], "lag_over_400d": huge[:5], "lag_over_400d_n": len(huge),
        "duplicate_periods_n": len(dups), "duplicate_examples": dup_examples,
        "undocumented_fields": [k for k in keys if k not in DOC_INCOME_FIELDS][:30],
        "correction_flag_like_fields": flag_like,
    }


def _decimals(x: float) -> int:
    s = repr(float(x))
    if "e" in s or "E" in s:
        return 99
    return len(s.split(".")[1].rstrip("0")) if "." in s else 0


def precision_only(a, b) -> bool:
    """a、b 只是小数位数不同 → True。规则（架构裁定，T-B05 前收紧）：
    1. 两者小数位数（repr 去掉末尾 0 后）不同；位数相同的不同值一定是真变化；
    2. 较短一方的位数 k 满足 PRECISION_MIN_DECIMALS ≤ k ≤ PRECISION_MAX_DECIMALS；
    3. 较长一方按 k 位四舍五入（half-up 或 half-even）或截断（向零）后，与较短一方逐位相等（十进制精确比较）。
    例：1.4714182949831487 ↔ 1.471418（截断到 6 位）、82.98214819072565 ↔ 82.982148 → True；
    15.0 ↔ 14.97（较短一方 0 位，<4）、1.471419 ↔ 1.4714182949831487（舍入/截断都得不到）→ False。"""
    x, y = _num(a), _num(b)
    if x is None or y is None or x == y:
        return False
    dx, dy = _decimals(x), _decimals(y)
    if dx == dy:
        return False
    (short, k), long_ = ((x, dx), y) if dx < dy else ((y, dy), x)
    if not (PRECISION_MIN_DECIMALS <= k <= PRECISION_MAX_DECIMALS):
        return False
    try:
        ds, dl, q = Decimal(repr(float(short))), Decimal(repr(float(long_))), Decimal(1).scaleb(-k)
        return any(dl.quantize(q, rounding=m) == ds for m in (ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_DOWN))
    except InvalidOperation:
        return False


def change_points(series: list) -> list:
    """series: [(YYYY-MM-DD, value)] 升序 → 值发生变化的日期列表（含前后值）。
    只是小数位数不同的变化标 precision_only=True（T-B48），由 classify_pit 单独计数、不算前视。"""
    out, prev = [], None
    for d, v in series:
        x = _num(v)
        if x is None:
            continue
        if prev is not None and abs(x - prev[1]) > 1e-9 * max(1.0, abs(prev[1])):
            ch = {"date": d, "from": prev[1], "to": x}
            if precision_only(prev[1], x):
                ch["precision_only"] = True
            out.append(ch)
        prev = (d, x)
    return out


def classify_pit(changes: list, reports: list, window_days: int = 10) -> dict:
    """reports: [{"jzrq","plrq"}]（YYYY-MM-DD）。对每个变化点判定：
    after_plrq —— 变化日落在某份报告披露日之后 window 天内（与“按时点”一致）；
    before_disclosure —— 变化日落在某报告期末之后、但该报告披露日之前（前视：用到了尚未披露的数据）；
    unexplained —— 其他（可能是口径、股本或行情驱动，需人工看）；
    precision_only —— 只是小数位数变化（截断/四舍五入，T-B48），不是值的变化，不参与判定。"""
    res = {"after_plrq": [], "before_disclosure": [], "unexplained": [], "precision_only": []}
    for ch in changes:
        if ch.get("precision_only"):
            res["precision_only"].append({**ch, "tag": "precision_only"})
            continue
        d = date.fromisoformat(ch["date"])
        tag = "unexplained"
        for r in reports:
            j, p = r.get("jzrq"), r.get("plrq")
            if not j or not p:
                continue
            jd, pd = date.fromisoformat(j), date.fromisoformat(p)
            if pd <= d <= pd + timedelta(days=window_days):
                tag = "after_plrq"
                break
            if jd < d < pd:
                tag = "before_disclosure"
        res[tag].append({**ch, "tag": tag})
    n = {k: len(v) for k, v in res.items()}
    if not changes or len(changes) == n["precision_only"]:
        verdict = "no_change_in_window"
    elif n["before_disclosure"]:
        verdict = "lookahead_suspected"
    elif n["after_plrq"] and not n["unexplained"]:
        verdict = "consistent_with_pit"
    else:
        verdict = "inconclusive"
    return {"verdict": verdict, "counts": n, "details": {k: v[:8] for k, v in res.items()}}


def factor_keys(d) -> tuple:
    """factor/all 返回 → (扁平 dict, 因子 id 列表)。
    实测结构（T-B48）：{"code":200,"data":{"code","name","theme","trade_date","factors":{85 个因子}},"msg"}；
    也兼容旧设想的扁平结构 {"data":{因子...}} 与直接给 dict。元数据键与因子键合并进同一个 dict。"""
    if isinstance(d, dict) and isinstance(d.get("data"), dict):
        d = d["data"]
    if not isinstance(d, dict):
        return None, None
    if isinstance(d.get("factors"), dict):
        flat = {k: v for k, v in d.items() if k != "factors"}
        flat.update(d["factors"])
        ks = [k for k in d["factors"] if k not in FACTOR_META and not k.endswith("_rank")]
        return flat, ks
    ks = [k for k in d if k not in FACTOR_META and not k.endswith("_rank") and k != "factors"]
    return d, ks


def batch_values(d, code: str) -> tuple:
    """factor/batch 返回 → ({因子 id: 值}, trade_date)。
    实测结构（T-B48）：{"code":200,"data":{"items":{"600519":{"profit_yoy":..,"roe_ttm":..}},"trade_date":"20260130"}}；
    也兼容 items 为列表（[{"code":..,"factors":{..}}] 或 [{"code":.., 因子...}]）和 data 为列表。"""
    if isinstance(d, dict) and isinstance(d.get("data"), (dict, list)):
        d = d["data"]
    td = d.get("trade_date") if isinstance(d, dict) else None
    items = d.get("items") if isinstance(d, dict) else d
    row = None
    if isinstance(items, dict):
        row = items.get(code)
        if row is None and len(items) == 1 and isinstance(next(iter(items.values())), dict):
            row = next(iter(items.values()))
    elif isinstance(items, list):
        cand = [x for x in items if isinstance(x, dict)]
        row = next((x for x in cand if str(x.get("code", x.get("dm", ""))).split(".")[0] == code),
                   cand[0] if len(cand) == 1 else None)
    if not isinstance(row, dict):
        return {}, td
    td = row.get("trade_date", td)
    vals = row.get("factors") if isinstance(row.get("factors"), dict) else row
    return {k: v for k, v in vals.items() if k not in FACTOR_META}, td


def batch_dates(d, code: str) -> tuple:
    """factor/batch 返回 → (该股记录自带的数据日期, 响应层 data.trade_date)，都规范成 YYYY-MM-DD 或 None。"""
    resp_td = None
    if isinstance(d, dict) and isinstance(d.get("data"), (dict, list)):
        d = d["data"]
    if isinstance(d, dict):
        resp_td = norm_date(d.get("trade_date"))
    items = d.get("items") if isinstance(d, dict) else d
    row = None
    if isinstance(items, dict):
        row = items.get(code)
        if row is None and len(items) == 1 and isinstance(next(iter(items.values())), dict):
            row = next(iter(items.values()))
    elif isinstance(items, list):
        cand = [x for x in items if isinstance(x, dict)]
        row = next((x for x in cand if str(x.get("code", x.get("dm", ""))).split(".")[0] == code),
                   cand[0] if len(cand) == 1 else None)
    rec_td = None
    if isinstance(row, dict):
        f = row.get("factors") if isinstance(row.get("factors"), dict) else {}
        rec_td = norm_date(row.get("trade_date") or f.get("trade_date"))
    return rec_td, resp_td


def batch_asof(requested: str | None, record_date: str | None, response_date: str | None) -> dict:
    """/factor/batch 的数据日期裁定（plan 34d475d）：一律以响应里每条记录自带的数据日期为准；
    没有这个字段或与请求日期不一致 → as_of_mismatch，该批不用于回填（use_for_backfill=False）。
    记录层没有日期、但响应层 data.trade_date 有时，用响应层日期（它是这批记录共同携带的数据日期），source 记为
    "response"——实测响应只有响应层 trade_date（T-B48），是否接受响应层日期见 T-B05-switches.md 待裁定项。
    记录层与响应层都有但不同 → as_of_mismatch。"""
    req = norm_date(requested) if requested else None
    if record_date and response_date and record_date != response_date:
        data_date, source, reason = record_date, "record", "record_vs_response_differ"
    elif record_date:
        data_date, source, reason = record_date, "record", None
    elif response_date:
        data_date, source, reason = response_date, "response", None
    else:
        data_date, source, reason = None, None, "missing_data_date"
    if reason is None and req and data_date != req:
        reason = "data_date_differs_from_request"
    if reason is None and not req:
        reason = "missing_requested_date"
    ok = reason is None
    return {"requested_date": req, "record_date": record_date, "response_date": response_date,
            "data_date": data_date, "date_source": source, "status": "ok" if ok else "as_of_mismatch",
            "reason": reason, "use_for_backfill": ok}


def parse_codes(text, max_n: int = LAT_MAX_CODES) -> list:
    """'000001,600519 300750' → ['000001','600519','300750']（6 位数字、去重保序）；非法或超过上限抛 ValueError。"""
    raw = [x.strip() for x in re.split(r"[,\s]+", str(text or "")) if x.strip()]
    bad = [x for x in raw if not _CODE6.match(x)]
    if bad:
        raise ValueError(f"股票代码须为 6 位数字：{bad[:5]}")
    out = list(dict.fromkeys(raw))
    if not out:
        raise ValueError("股票列表为空")
    if len(out) > max_n:
        raise ValueError(f"股票最多 {max_n} 只（每只每轮 2 次调用），收到 {len(out)} 只")
    return out


_W32TM = re.compile(r"^\s*\d{1,2}:\d{2}:\d{2}\s*,\s*(?:d:\S+\s+)?(?:o:)?([+-]?\d+(?:\.\d+)?)s\b", re.M)
_W32TM_O = re.compile(r"\bo:([+-]?\d+(?:\.\d+)?)s\b")


def parse_w32tm(text: str) -> list:
    """w32tm /stripchart /dataonly 输出 → 偏差秒数列表（"18:45:01, -00.0008123s" 或 "... o:+00.1024506s"）。
    出错行（如 "error: 0x800705B4"）跳过。数值按 w32tm 原样返回（正值 = 本机比目标快）。"""
    vals = []
    for ln in str(text or "").splitlines():
        m = _W32TM_O.search(ln) or _W32TM.match(ln)
        if m:
            try:
                vals.append(float(m.group(1)))
            except ValueError:
                pass
    return vals


def pctl(vals, q: float):
    """线性插值分位数（与 numpy percentile 默认法一致）；空 → None。"""
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    pos = (len(v) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return round(v[lo] + (v[hi] - v[lo]) * (pos - lo), 3)


def lag_quantiles(lags, local_ahead_s=None) -> dict:
    """延迟样本 → 未修正与按 NTP 修正两套 min/p50/p95/max（研究员要求）。
    修正：真实延迟 = 本机收到时刻 − 本机快的秒数 − 快照 t = lag − local_ahead_s。没有 NTP 值时修正套为 None。"""
    lags = [x for x in lags if x is not None]

    def q(v):
        return {"n": len(v), "min": min(v) if v else None, "p50": pctl(v, 0.5), "p95": pctl(v, 0.95),
                "max": max(v) if v else None}
    out = {"uncorrected": q(lags), "ntp_corrected": None}
    if local_ahead_s is not None:
        out["ntp_corrected"] = q([round(x - local_ahead_s, 3) for x in lags])
    return out


def stale_threshold(per_source_q: dict) -> dict:
    """stale_threshold_s 参考值 = 各源修正后 p95 的最大值（研究员要求）；没有 NTP 时退回未修正 p95 并注明。
    建议值 = ceil(max(2 × 参考值, 10))，由用户确认（倍数 2 与下限 10s 是后端拟定，非研究口径）。"""
    corr = [v["ntp_corrected"]["p95"] for v in per_source_q.values() if v.get("ntp_corrected")
            and v["ntp_corrected"]["p95"] is not None]
    unc = [v["uncorrected"]["p95"] for v in per_source_q.values() if v["uncorrected"]["p95"] is not None]
    if corr:
        ref, basis = max(corr), "ntp_corrected_p95"
    elif unc:
        ref, basis = max(unc), "uncorrected_p95（无 NTP 偏差，仅供参考）"
    else:
        return {"ref_p95_s": None, "basis": None, "suggested_s": None}
    return {"ref_p95_s": ref, "basis": basis, "suggested_s": int(math.ceil(max(ref * 2, 10)))}


def compare_history(base: list, new: list) -> dict:
    """复测 3：两次 factor/history 序列 [(YYYY-MM-DD, 值)] 逐日比对。
    已有日期的值变了（精度差除外，用 precision_only）→ 改写；基线有、新序列没有 → 删除；
    新序列在基线末日之前多出的日期 → 插入；只在末尾新增日期 → 正常。"""
    b, n = dict(base), dict(new)
    last = max(b) if b else None
    changed, prec = [], []
    for d in sorted(set(b) & set(n)):
        x, y = _num(b[d]), _num(n[d])
        if x == y or (x is None and y is None):
            continue
        (prec if precision_only(x, y) else changed).append({"date": d, "base": b[d], "new": n[d]})
    removed = sorted(set(b) - set(n))
    inserted = sorted(d for d in set(n) - set(b) if last and d <= last)
    appended = sorted(d for d in set(n) - set(b) if not last or d > last)
    if not b or not n:
        verdict = "inconclusive"
    elif changed or removed or inserted:
        verdict = "rewritten"
    else:
        verdict = "no_rewrite"
    return {"verdict": verdict, "common_days": len(set(b) & set(n)), "changed": len(changed),
            "precision_only": len(prec), "removed": len(removed), "inserted": len(inserted),
            "appended_tail": len(appended), "examples": {"changed": changed[:8], "precision_only": prec[:4],
                                                         "removed": removed[:8], "inserted": inserted[:8]}}


def history_series(data) -> list:
    """factor/history 响应（或 save_sample 文件里的 data）→ [(YYYY-MM-DD, 值)] 升序。"""
    return sorted((norm_date(x.get("trade_date")), x.get("value")) for x in c.rows(data)
                  if isinstance(x, dict) and norm_date(x.get("trade_date")))


def load_history_sample(path) -> list:
    """读 save_sample 写的 p11_pit_history_*.json（本地文件，不发请求）→ 序列。"""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return history_series(d.get("data") if isinstance(d, dict) and "url" in d else d)


def pick_limit_up(pool: list, sampled_at: datetime, k: int, exclude=()) -> dict:
    """复测 2：从涨停池里选 k 只（研究员要求：限于取样时刻已在池中的股票，避免事后选样）。
    条件：dm 为 6 位代码、不在 exclude、首次封板时间 fbt（HH:mm:ss）存在且 ≤ 取样时刻（北京时间）。
    顺序按接口给的顺序（文档：按封板时间升序）。返回 {picks, rejected 计数, sampled_at_bj}。"""
    t_s = sampled_at.astimezone(BJ).strftime("%H:%M:%S")
    picks, rej = [], {"bad_code": 0, "excluded": 0, "no_fbt": 0, "fbt_after_sample": 0}
    for r in pool:
        if not isinstance(r, dict):
            continue
        dm = str(r.get("dm", "")).split(".")[0]
        fbt = str(r.get("fbt") or "")
        if not _CODE6.match(dm):
            rej["bad_code"] += 1
        elif dm in exclude:
            rej["excluded"] += 1
        elif not re.match(r"^\d{2}:\d{2}:\d{2}$", fbt):
            rej["no_fbt"] += 1
        elif fbt > t_s:
            rej["fbt_after_sample"] += 1
        elif len(picks) < k:
            picks.append({"dm": dm, "mc": r.get("mc"), "fbt": fbt, "lbt": r.get("lbt"), "zbc": r.get("zbc"),
                          "lbc": r.get("lbc")})
    return {"sampled_at_bj": sampled_at.astimezone(BJ).isoformat(timespec="seconds"), "pool_rows": len(pool),
            "picks": picks, "rejected": rej}


def selftest_pure() -> list:
    """dry-run 离线单测纯函数（不发请求）。返回 [(名称, 是否通过, 细节)]。"""
    out = []
    mon = datetime(2026, 11, 2, 9, 55, tzinfo=BJ)
    out.append(("盘中判定：周一 09:55 北京=盘中；12:00=午休；周日=休市；14:59:50 且需 40s=否",
                is_bj_session(mon, 40) and not is_bj_session(mon.replace(hour=12)) and
                not is_bj_session(mon - timedelta(days=1)) and
                not is_bj_session(mon.replace(hour=14, minute=59, second=50), 40), ""))
    u = infer_units({"p": 11.64, "h": 11.67, "l": 11.4, "cje": 2152393900, "v": 1864245})
    u2 = infer_units({"p": 11.64, "h": 11.67, "l": 11.4, "cje": 2152393886.36, "v": 186.42})
    out.append(("单位推断：T003 实测样例 real/time v=手、ssjy v=万手（与文档“手”不符）",
                u["pick"]["v"].startswith("手") and u2["pick"]["v"] == "万手", f"{u['pick']} / {u2['pick']}"))
    tp = classify_time_precision(["2026-10-30 00:00:00", "2026-10-29", "2026-10-28 18:31:00"])
    out.append(("公告时间精度分类", tp["precision"] == "minute", str(tp["precision"])))
    cp = change_points([("2025-08-01", 1), ("2025-08-13", 2), ("2025-09-30", 2), ("2025-10-05", 3)])
    pit = classify_pit(cp, [{"jzrq": "2025-06-30", "plrq": "2025-08-12"}, {"jzrq": "2025-09-30", "plrq": "2025-10-25"}])
    out.append(("时点性判定：披露后跳变=一致，披露前跳变=前视", pit["counts"] == {
        "after_plrq": 1, "before_disclosure": 1, "unexplained": 0, "precision_only": 0}
        and pit["verdict"] == "lookahead_suspected", str(pit["counts"])))
    cp2 = change_points([("2026-04-27", 1.4714182949831487), ("2026-08-03", 1.471418),
                         ("2026-08-14", 1.4714182949831487), ("2026-08-15", -1.9515948550279467)])
    pit2 = classify_pit(cp2, [{"jzrq": "2026-06-30", "plrq": "2026-08-15"}])
    out.append(("时点性判定：小数截断（1.4714182949831487↔1.471418）不算前视（T-B48）",
                pit2["counts"] == {"after_plrq": 1, "before_disclosure": 0, "unexplained": 0, "precision_only": 2}
                and pit2["verdict"] == "consistent_with_pit", str(pit2["counts"])))
    fd, fk = factor_keys({"code": 200, "data": {"code": "600519", "name": "贵州茅台", "theme": "x",
                                                "trade_date": "20261030", "factors": {"pe_ttm": 20.1, "seal_ratio": None}}})
    bv, btd = batch_values({"code": 200, "data": {"items": {"600519": {"profit_yoy": 6.2, "roe_ttm": 90.1}},
                                                  "trade_date": "20260130"}}, "600519")
    out.append(("嵌套解析：factor/all 的 data.factors、factor/batch 的 data.items.{code}（T-B48）",
                sorted(fk) == ["pe_ttm", "seal_ratio"] and fd.get("trade_date") == "20261030"
                and bv == {"profit_yoy": 6.2, "roe_ttm": 90.1} and btd == "20260130", f"{fk} / {bv} / {btd}"))
    # ---- 精度差规则收紧（架构裁定）：反例必须判为真变化
    pos = [(1.4714182949831487, 1.471418), (82.98214819072565, 82.982148), (1.471418, 1.4714182949831487),
           (-1.9515948550279467, -1.951594), (2.12345678, 2.1235)]
    neg = [(15.0, 14.97), (14.97, 15.0), (1.4714182949831487, 1.471419), (1.4714182949831487, 1.47),
           (1.471418, 1.471419), (100.0, 99.99999), (6.2458449524124315, 6.245846)]
    bad = [x for x in pos if not precision_only(*x)] + [x for x in neg if precision_only(*x)]
    out.append(("精度差规则：截断/舍入到较短一方位数（≥4 位）才算；反例 15.0↔14.97 不算",
                not bad, f"正例 {len(pos)}、反例 {len(neg)}" + (f"；错判 {bad}" if bad else "")))
    cp3 = change_points([("2026-04-01", 15.0), ("2026-04-02", 14.97)])
    pit3 = classify_pit(cp3, [{"jzrq": "2026-03-31", "plrq": "2026-04-28"}])
    out.append(("精度差规则：15.0→14.97 计入真实跳变（披露前 → 前视嫌疑），不进 precision_only",
                pit3["counts"]["precision_only"] == 0 and pit3["verdict"] == "lookahead_suspected", str(pit3["counts"])))
    # ---- factor/batch 数据日期裁定（plan 34d475d）
    real = {"code": 200, "data": {"items": {"600519": {"profit_yoy": 6.2, "roe_ttm": 90.1}}, "trade_date": "20260130"}}
    a_ok = batch_asof("2026-01-30", *batch_dates(real, "600519"))
    a_mis = batch_asof("2026-04-17", *batch_dates(real, "600519"))
    a_miss = batch_asof("2026-01-30", *batch_dates({"code": 200, "data": {"items": {"600519": {"roe_ttm": 1}}}},
                                                    "600519"))
    a_rec = batch_asof("2026-01-30", *batch_dates({"data": {"trade_date": "20260130", "items": [
        {"code": "600519", "trade_date": "20260129", "factors": {"roe_ttm": 1}}]}}, "600519"))
    a_rec_ok = batch_asof("2026-01-30", *batch_dates({"data": {"items": [
        {"code": "600519", "trade_date": "2026-01-30", "roe_ttm": 1}]}}, "600519"))
    out.append(("batch 数据日期：一致=ok；与请求不同/缺失/记录与响应层不同 → as_of_mismatch 且不用于回填",
                a_ok["status"] == "ok" and a_ok["use_for_backfill"] and a_ok["date_source"] == "response"
                and a_mis["status"] == "as_of_mismatch" and a_mis["reason"] == "data_date_differs_from_request"
                and not a_mis["use_for_backfill"] and a_mis["data_date"] == "2026-01-30"
                and a_miss["reason"] == "missing_data_date" and not a_miss["use_for_backfill"]
                and a_rec["reason"] == "record_vs_response_differ" and not a_rec["use_for_backfill"]
                and a_rec_ok["status"] == "ok" and a_rec_ok["date_source"] == "record",
                f"{a_ok['status']}/{a_mis['reason']}/{a_miss['reason']}/{a_rec['reason']}/{a_rec_ok['date_source']}"))
    # ---- 开关用到的纯函数
    try:
        parse_codes("000001,60051")
        pc_bad = False
    except ValueError:
        pc_bad = True
    pc = parse_codes("000001, 600519 300750,000001")
    out.append(("GAP1 股票列表解析：6 位、去重保序、非法拒绝", pc == ["000001", "600519", "300750"] and pc_bad, str(pc)))
    w = parse_w32tm("Tracking ntp.aliyun.com [1.2.3.4:123].\nCollecting 3 samples.\n"
                    "18:45:01, -00.0008123s\n18:45:03, +01.2500000s\n08:38:57 d:+00.0417301s o:+00.1024506s [ * ]\n"
                    "18:45:05, error: 0x800705B4\n")
    out.append(("w32tm 输出解析（/dataonly 与 o: 两种格式，跳过 error 行）", w == [-0.0008123, 1.25, 0.1024506], str(w)))
    lq = lag_quantiles([7.0, 8.0, 9.0, 10.0, 11.0, 12.0], 1.5)
    st_ = stale_threshold({"a": lq, "b": lag_quantiles([1.0, 2.0], 1.5)})
    st_u = stale_threshold({"a": lag_quantiles([7.0, 8.0, 9.0, 10.0, 11.0, 12.0])})
    out.append(("延迟分位数：未修正与 NTP 修正两套；stale 参考 = 修正后 p95（无 NTP 时退回未修正 p95）",
                lq["uncorrected"]["p95"] == 11.75 and lq["ntp_corrected"]["p95"] == 10.25
                and lq["ntp_corrected"]["min"] == 5.5 and st_["ref_p95_s"] == 10.25
                and st_["basis"] == "ntp_corrected_p95" and st_["suggested_s"] == 21
                and st_u["basis"].startswith("uncorrected") and st_u["ref_p95_s"] == 11.75, f"{lq} / {st_}"))
    # T-B117：同段连续竞价过滤；勿把午休冻结/隔夜旧票计入 stale_threshold
    recv = datetime(2026, 11, 10, 13, 5, 49, tzinfo=BJ)
    t_live = datetime(2026, 11, 10, 13, 5, 36, tzinfo=BJ)
    t_lunch = datetime(2026, 11, 10, 11, 30, 57, tzinfo=BJ)
    t_old = datetime(2026, 7, 16, 9, 23, 33, tzinfo=BJ)
    out.append(("同段连续竞价：下午收到只与下午盘中 t 同段；11:30:57 午休冻结与 7 月旧票排除",
                same_auction_session(t_live, recv) and not same_auction_session(t_lunch, recv)
                and not same_auction_session(t_old, recv)
                and not same_auction_session(t_live, recv.replace(hour=10)), ""))
    after = datetime(2026, 11, 10, 15, 40, tzinfo=BJ)
    t_live_ah = after - timedelta(seconds=3)
    out.append(("dry-run 强制盘中且收到时刻在盘后：延迟数秒的活样本仍计入；午休冻结与隔夜旧票仍排除",
                not same_auction_session(t_live_ah, after)
                and in_session_for_threshold(t_live_ah, after, True)
                and not in_session_for_threshold(t_lunch, after, True)
                and not in_session_for_threshold(t_old, after, True)
                and in_session_for_threshold(t_live, recv, True)
                and not in_session_for_threshold(t_lunch, recv, True), ""))
    # T-B117：w32tm 负值 = 本机慢；探针 local_ahead_s 与 RFC 5905 offset 符号相反，修正公式 lag − local_ahead
    w32 = parse_w32tm("22:05:36, -00.4414716s\n22:05:38, -00.4405399s\n22:05:40, -00.4387174s\n")
    ahead_s = round(sum(w32) / len(w32), 4)
    rfc = round(-ahead_s, 4)
    lag_raw, lag_corr = 10.182, round(10.182 - ahead_s, 3)
    out.append(("NTP 符号：w32tm 负值=本机慢；local_ahead_s=本机−NTP；RFC 5905 offset=server−local=−local_ahead_s；"
                "本机慢时真实延迟 = lag − local_ahead_s（比未修正更大）",
                ahead_s < 0 and rfc > 0 and abs(ahead_s + 0.4402) < 1e-3 and lag_corr == round(10.182 + 0.4402, 3)
                and lag_corr > lag_raw, f"ahead={ahead_s} rfc={rfc} corr={lag_corr}"))
    base = [("2026-01-29", 1.4714182949831487), ("2026-01-30", 2.0), ("2026-02-02", 3.0)]
    h_ok = compare_history(base, [("2026-01-29", 1.471418), ("2026-01-30", 2.0), ("2026-02-02", 3.0),
                                  ("2026-11-09", 4.0)])
    h_bad = compare_history(base, [("2026-01-29", 1.4714182949831487), ("2026-01-30", 2.5), ("2026-02-02", 3.0)])
    h_ins = compare_history(base, [*base, ("2026-01-31", 2.0)])
    h_rm = compare_history(base, base[1:])
    out.append(("回填比对：精度差/末尾新增=未改写；值变、插入、删除=改写",
                h_ok["verdict"] == "no_rewrite" and h_ok["precision_only"] == 1 and h_ok["appended_tail"] == 1
                and h_bad["verdict"] == "rewritten" and h_bad["changed"] == 1 and h_ins["verdict"] == "rewritten"
                and h_rm["verdict"] == "rewritten",
                f"{h_ok['verdict']}/{h_bad['verdict']}/{h_ins['verdict']}/{h_rm['verdict']}"))
    pool = [{"dm": "600519", "fbt": "09:30:00"}, {"dm": "002001", "fbt": "09:31:05"}, {"dm": "300001"},
            {"dm": "603001", "fbt": "09:40:00"}, {"dm": "000002", "fbt": "10:30:00"}, {"dm": "603002", "fbt": "09:59:59"}]
    pk = pick_limit_up(pool, datetime(2026, 11, 2, 10, 0, 0, tzinfo=BJ), 2, exclude=NULLS_BASE_CODES)
    pk3 = pick_limit_up(pool, datetime(2026, 11, 2, 10, 0, 0, tzinfo=BJ), 5, exclude=NULLS_BASE_CODES)
    out.append(("涨停股选样：只取取样时刻前已封板（fbt ≤ 取样时刻）、排除原样本、记录取样时刻",
                [x["dm"] for x in pk["picks"]] == ["002001", "603001"]
                and [x["dm"] for x in pk3["picks"]] == ["002001", "603001", "603002"]
                and pk3["rejected"]["fbt_after_sample"] == 1 and pk3["rejected"]["no_fbt"] == 1
                and pk3["rejected"]["excluded"] == 1 and pk["sampled_at_bj"] == "2026-11-02T10:00:00+08:00",
                f"{[x['dm'] for x in pk3['picks']]} {pk3['rejected']}"))
    return out


# =========================================================================== 各项
def _item(res, name, item, status, conclusion, evidence=None, limits=None, next_steps=None):
    d = {"name": name, "item": item, "status": status, "conclusion": conclusion, "evidence": evidence or {},
         "limits": limits or [], "next_steps": next_steps or []}
    res.append(d)
    print(f"--> {name} [{status}] {conclusion.get('summary', '')}")
    return d


def _guard(res, name, item, fn):
    try:
        return fn()
    except c.LimitHit:
        raise
    except Exception as e:    # 单项分析出错不影响其它项（调用本身已记录在 calls.jsonl）
        _item(res, name, item, "error", {"summary": f"分析异常 {type(e).__name__}: {str(e)[:200]}"})
        return None


def _snap_record(r) -> dict | None:
    d = r.data
    if isinstance(d, dict) and isinstance(d.get("data"), dict):
        d = d["data"]
    if isinstance(d, list) and d and isinstance(d[0], dict):
        d = d[0]
    return d if isinstance(d, dict) else None


def _local_ahead():
    """本机比 NTP 快的秒数（多次取均值）；没有提供 → None。"""
    return round(statistics.fmean(LOCAL_AHEAD_S), 4) if LOCAL_AHEAD_S else None


def item1_latency(res, shared):
    name, item = "GAP1_snapshot_latency", "快照延迟：快照时间戳 t vs 本机时钟（北京时间）"
    ctx = c.ctx()
    now = bj_now()
    codes = list(LAT_CODES) or [LAT_CODE]
    interval = 0.05 if ctx.dry_run else LAT_INTERVAL_S
    # 每轮 2×N 次调用（按调用间隔约 0.25s + RTT 约 0.25s 估）+ 轮间停顿；留 20s 余量
    need = LAT_SAMPLES * (interval + 2 * len(codes) * (0.05 if ctx.dry_run else 0.5)) + 20
    in_sess = is_bj_session(now, need)
    if ctx.dry_run and FORCE_SESSION is not None:
        in_sess = bool(FORCE_SESSION)
    ahead = _local_ahead()
    ntp = {"local_ahead_s": ahead, "values_s": list(LOCAL_AHEAD_S), "sources": list(NTP_SOURCES),
           "convention": "本机 − NTP（秒），正值=本机快；与 RFC 5905 offset（server − local）符号相反。"
                         "w32tm /dataonly 数值按正值=本机比目标快读入；字段含义未翻转",
           "rfc5905_offset_s": None if ahead is None else round(-ahead, 4)} \
        if LOCAL_AHEAD_S else "unknown"
    limits = ["延迟 = 本机收到响应时刻 − 快照 t，含本机时钟误差；提供 NTP 偏差（--local-ahead-s/--ntp-file）时另给"
              "修正后的一套分位数。另用服务端 HTTP Date 头（秒级）估计本机与服务端的钟差供参考，服务端时钟本身的准确性同样未知",
              "t 字段只到秒，单次延迟分辨率约 ±1s",
              "每个 源×股票 只有 6 个样本，p95 实际接近最大值",
              "stale_threshold 只用快照 t 与收到时刻同属本段连续竞价的样本；"
              "隔夜/午休冻结/长期未更新的 t 仍记在 evidence 与 per_source_stock 全量分位数里"]
    if not in_sess:
        return _item(res, name, item, "skipped",
                     {"summary": "盘后无法测", "bj_now": now.isoformat(timespec="seconds"), "codes": codes,
                      "reason": "当前北京时间不在连续竞价时段（工作日 9:30–11:30、13:00–15:00），或距本时段结束不足"
                                f" {need:.0f}s；盘后快照 t 停在收盘时刻，延迟无意义", "ntp_offset": ntp},
                     limits=limits, next_steps=["在北京时间交易时段内重跑：python run_all.py p11 --p11-only gap1"])
    # 交易日历确认是否节假日（1 次调用）
    cal = probe(res, "tcalendar_this_year", "/tcalendar/list/" + str(now.year) + "/{licence}")
    days = [str(x) for x in (cal.data if isinstance(cal.data, list) else c.rows(cal.data))]
    today = now.strftime("%Y%m%d")
    cal_state = "unknown" if not days else ("trading_day" if any(today in d.replace("-", "") for d in days)
                                            else "holiday")
    if cal_state == "holiday" and not (ctx.dry_run and FORCE_SESSION):
        return _item(res, name, item, "skipped", {"summary": "盘后无法测（交易日历显示今日非交易日）",
                                                   "bj_now": now.isoformat(timespec="seconds"), "codes": codes,
                                                   "ntp_offset": ntp}, limits=limits)
    srcs = {"real_time_broker": "/hsstock/real/time/{code}/{{licence}}",
            "ssjy_web": "/hsrl/ssjy/{code}/{{licence}}"}
    samples = {k: {cd: [] for cd in codes} for k in srcs}
    for i in range(LAT_SAMPLES):
        for code in codes:
            for k, tpl in srcs.items():
                t_send = time.time()
                # 单只时沿用原调用名 lat_<源>_<i>，多只时加代码，便于与原 run 对照
                nm = f"lat_{k}_{i + 1}" if len(codes) == 1 else f"lat_{k}_{code}_{i + 1}"
                r = probe(res, nm, tpl.format(code=code))
                t_recv = time.time()
                rec = _snap_record(r)
                if rec is not None:
                    shared.setdefault("snap", {})[(k, code)] = rec
                ts = parse_bj(rec.get("t")) if rec else None
                srv = None
                try:
                    srv = parsedate_to_datetime(r.headers.get("Date") or r.headers.get("date")).timestamp()
                except Exception:
                    srv = None
                recv_dt = datetime.fromtimestamp(t_recv, BJ)
                samples[k][code].append({
                    "i": i + 1, "t": rec.get("t") if rec else None,
                    "recv_bj": recv_dt.isoformat(timespec="milliseconds"),
                    "lag_s": round(t_recv - ts.timestamp(), 3) if ts else None,
                    "in_session": in_session_for_threshold(
                        ts, recv_dt, force_session=bool(ctx.dry_run and FORCE_SESSION)),
                    "rtt_ms": r.ms,
                    "local_minus_server_date_s": round((t_send + t_recv) / 2 - srv, 3) if srv else None})
        if i + 1 < LAT_SAMPLES:
            time.sleep(interval)
    per_stock, per_source, offs_all = {}, {}, []
    n_excl = 0
    for k, by_code in samples.items():
        pooled = []
        for code, ss in by_code.items():
            lags = [s["lag_s"] for s in ss if s["lag_s"] is not None]
            sess = session_lags(ss)
            n_excl += len(lags) - len(sess)
            offs = [s["local_minus_server_date_s"] for s in ss if s["local_minus_server_date_s"] is not None]
            offs_all += offs
            pooled += sess
            per_stock[f"{k}/{code}"] = {"n": len(ss), "n_with_t": len(lags),
                                         "n_in_session": len(sess),
                                         "t_distinct": len({s["t"] for s in ss if s["t"]}),
                                         "clock_offset_vs_server_date_s_p50": statistics.median(offs) if offs else None,
                                         **lag_quantiles(lags, ahead),
                                         "in_session": lag_quantiles(sess, ahead)}
        per_source[k] = lag_quantiles(pooled, ahead)
    thr = stale_threshold(per_source)
    if n_excl:
        thr["basis"] = (thr["basis"] or "") + (
            f"；已排除 {n_excl} 个快照 t 不在本段连续竞价时段的样本（停牌/隔夜/午休冻结等，不代表本段延迟）")
        thr["excluded_n"] = n_excl
        thr["session_filter"] = "same_auction_session"
    http_off = statistics.median(offs_all) if offs_all else None
    sign_check = None
    if ahead is not None and http_off is not None and abs(ahead) >= 0.5 and abs(http_off) >= 0.5:
        sign_check = "consistent" if (ahead > 0) == (http_off > 0) else \
            "opposite（NTP 偏差与 HTTP Date 钟差符号相反：先核对 w32tm 符号约定再用修正值）"
    measured = any(v["uncorrected"]["p50"] is not None for v in per_source.values())
    unc = {k: v["uncorrected"] for k, v in per_source.items()}
    return _item(res, name, item, "measured" if measured else "inconclusive", {
        "summary": "；".join(f"{k}: 延迟 p50={v['p50']}s p95={v['p95']}s max={v['max']}s（未修正，{v['n']} 个样本）"
                            for k, v in unc.items())
                   + (f"；NTP 修正（本机快 {ahead}s）后 p95=" + "/".join(
                       str(v["ntp_corrected"]["p95"]) for v in per_source.values()) if ahead is not None else "")
                   + f"；stale_threshold 参考 {thr['ref_p95_s']}s（{thr['basis']}）",
        "bj_start": now.isoformat(timespec="seconds"), "calendar": cal_state, "codes": codes,
        "per_source": per_source, "per_source_stock": per_stock,
        "stale_threshold": thr, "suggested_stale_threshold_s": thr["suggested_s"],
        "clock_offset_vs_server_date_s_p50": http_off, "ntp_offset": ntp, "ntp_sign_check": sign_check},
        evidence={"samples": samples, "ntp_raw": dict(NTP_RAW)}, limits=limits,
        next_steps=["时段开始前、结束后各在 Windows 执行 w32tm /stripchart /computer:ntp.aliyun.com /samples:3 "
                    "/dataonly > ntp_<时段>_<前|后>.txt（只读，不改系统时间），用 --ntp-file 传入"])


def item2_units(res, shared):
    name, item = "GAP2_cje_v_units", "cje/v 单位：成交额 /(成交量×价格) 交叉推断"
    snap = shared.setdefault("snap", {})
    out = {}
    for code, mcode in (("000001", "000001.SZ"), ("600519", "600519.SH")):
        for k, tpl in (("real_time_broker", f"/hsstock/real/time/{code}/{{licence}}"),
                       ("ssjy_web", f"/hsrl/ssjy/{code}/{{licence}}")):
            rec = snap.get((k, code))
            if rec is None:            # 第 1 项未采样（盘后）或无该股，则补 1 次
                rec = _snap_record(probe(res, f"units_{k}_{code}", tpl))
            if rec:
                inf = infer_units(rec, "v", "cje", ("p",))
                if "pv" in rec and _num(rec.get("pv")) and _num(rec.get("v")):
                    inf["pv_over_v"] = round(_num(rec["pv"]) / _num(rec["v"]), 3)
                inf["t"] = rec.get("t")
                out[f"{k}/{code}"] = inf
        r = probe(res, f"units_daily_latest_{code}", f"/hsstock/latest/{mcode}/d/n/{{licence}}", lt=1)
        rr = c.rows(r.data)
        if rr:
            inf = infer_units(rr[-1], "v", "a", ("c",))
            inf["t"] = rr[-1].get("t")
            out[f"daily_latest/{code}"] = inf
    picks = {}
    for k, v in out.items():
        src = k.split("/")[0]
        if v.get("pick"):
            picks.setdefault(src, set()).add(f"v={v['pick']['v']}, 额={list(v['pick'].values())[1]}")
    concl = {src: sorted(s) for src, s in picks.items()}
    mism = []
    if any("万手" in x for x in concl.get("ssjy_web", [])):
        mism.append("ssjy（网络源）文档写 v=成交量（手），实测推断为“万手”量级")
    status = "measured" if concl and all(len(s) == 1 for s in concl.values()) else "inconclusive"
    return _item(res, name, item, status, {
        "summary": "；".join(f"{k}: {'/'.join(v)}" for k, v in concl.items()) or "无可用数据",
        "per_source": concl, "doc": DOC_UNITS, "doc_mismatch": mism}, evidence=out,
        limits=["按 VWAP 必须落在当日[最低价, 最高价]内判定；‘股+元’与‘万股+万元’比例相同无法区分，"
                "按成交额量级（亿元级）取‘元’",
                "盘中快照与日线不是同一交易日（日线 15:30 后才更新），故各源独立推断，不做跨源相等比较"])


def item3_plrq(res, shared):
    name, item = "GAP3_plrq_coverage_revision", "plrq 披露日：历史覆盖、空值率、修订/更正迹象"
    per = {}
    for code in EARLY_STOCKS:
        r = probe(res, f"plrq_income_full_{code}", f"/hsstock/financial/income/{code}/{{licence}}")
        rows = c.rows(r.data)
        per[f"income/{code}"] = analyze_fin_rows(rows)
        if code == "600519.SH":
            shared["income_600519"] = rows
    for st in ("balance", "cashflow"):
        r = probe(res, f"plrq_{st}_600519", f"/hsstock/financial/{st}/600519.SH/{{licence}}")
        a = analyze_fin_rows(c.rows(r.data))
        per[f"{st}/600519.SH"] = {k: a.get(k) for k in ("rows", "has_plrq_field", "jzrq_min", "earliest_row_plrq",
                                                          "plrq_null_ratio", "duplicate_periods_n",
                                                          "correction_flag_like_fields")}
    inc = [v for k, v in per.items() if k.startswith("income/") and v.get("rows")]
    if not inc:
        return _item(res, name, item, "inconclusive", {"summary": "利润表无数据，无法判断"}, evidence=per)
    dup = sum(v["duplicate_periods_n"] for v in inc)
    flags = sorted({f for v in inc for f in v["correction_flag_like_fields"]})
    if dup:
        rev = "存在同一报告期多行 → 可能保留了修订/更正版本（见 duplicate_examples 的 plrq 与差异字段）"
    elif flags:
        rev = f"未见同期多行，但有疑似更正/版本字段 {flags}，需人工看取值"
    else:
        rev = "每个报告期仅 1 行、无更正标志字段 → 推测只保留一个版本（最新或首发未知）；无法用本接口还原更正前数值"
    cover = {k: {"earliest_jzrq": v["jzrq_min"], "earliest_row_plrq": v["earliest_row_plrq"],
                 "plrq_null_ratio": v["plrq_null_ratio"], "before_2007_null_ratio": v["plrq_null_ratio_before_2007"]}
             for k, v in per.items() if k.startswith("income/")}
    late = sum(v["lag_over_400d_n"] for v in inc)
    return _item(res, name, item, "measured", {
        "summary": f"覆盖：{ {k: (v['earliest_jzrq'], v['plrq_null_ratio']) for k, v in cover.items()} }；修订：{rev}",
        "coverage": cover, "revision": rev, "duplicate_periods_total": dup, "flag_like_fields": flags,
        "plrq_lag_over_400d_rows": late,
        "balance_cashflow_have_plrq": {k: v.get("has_plrq_field") for k, v in per.items() if not k.startswith("income/")}},
        evidence=per,
        limits=["“披露日 − 报告期 > 400 天”的行可能是 plrq 被更正公告日期覆盖的迹象（不是确证）",
                "若每期仅 1 行，无法区分‘保留首发’与‘被更正覆盖’；需用已知发生过财报更正的股票对比原公告"],
        next_steps=["挑 1～2 只公开发生过会计差错更正的股票，对比本接口数值与原始定期报告（巨潮）首发数值"])


def item4_delisted(res, shared):
    name, item = "GAP4_delisted_survivorship", "退市股：股票列表是否含退市股、日线/财务是否可得、幸存者偏差"
    lst = probe(res, "delisted_stock_list", "/hslt/list/{licence}")
    c.keep("hslt_list", lst)               # p12 复用完整股票列表（不重复调用 /hslt/list）
    rows = c.rows(lst.data)
    dms = {str(r.get("dm", "")).split(".")[0] for r in rows if isinstance(r, dict)}
    tui = [r for r in rows if isinstance(r, dict) and "退" in str(r.get("mc", ""))][:10]
    per = {}
    for code, nm, src in DELISTED:
        pure = code.split(".")[0]
        ins = probe(res, f"delisted_instrument_{pure}", f"/hsstock/instrument/{code}/{{licence}}")
        h = probe(res, f"delisted_daily_{pure}", f"/hsstock/history/{code}/d/n/{{licence}}")
        f = probe(res, f"delisted_income_{pure}", f"/hsstock/financial/income/{code}/{{licence}}")
        hr, fr = c.rows(h.data), c.rows(f.data)
        per[code] = {"name": nm, "source": src, "in_stock_list": pure in dms,
                     "instrument_ok": ins.ok, "instrument": _snap_record(ins) if ins.ok else (ins.text[:150] or ins.error),
                     "daily_rows": len(hr), "daily_last": (hr[-1].get("t") if hr and isinstance(hr[-1], dict) else None),
                     "daily_err": None if h.ok else (h.text[:150] or h.error),
                     "income_rows": len(fr), "income_err": None if f.ok else (f.text[:150] or f.error)}
    n = len(per)
    in_list = sum(v["in_stock_list"] for v in per.values())
    has_d = sum(v["daily_rows"] > 0 for v in per.values())
    has_f = sum(v["income_rows"] > 0 for v in per.values())
    if not rows:
        verdict = "股票列表未取到，无法判断列表是否含退市股"
    elif in_list == 0 and has_d == 0:
        verdict = "严重幸存者偏差：列表不含退市股，且退市股历史日线不可得 → 回测须另找退市股数据源"
    elif in_list == 0:
        verdict = (f"列表不含退市股，但 {has_d}/{n} 只退市股日线可取（财务 {has_f}/{n}）→ 数据在，"
                   "需外部退市名单补全股票池，否则用 /hslt/list 选股会有幸存者偏差")
    else:
        verdict = f"列表含 {in_list}/{n} 只退市样本 → 列表可能含退市股（需看名称/状态字段区分）"
    return _item(res, name, item, "measured" if rows or has_d else "inconclusive", {
        "summary": verdict, "stock_list_rows": len(rows), "delisted_in_list": in_list, "daily_available": has_d,
        "financial_available": has_f, "sample_n": n, "list_names_with_退": tui},
        evidence=per,
        limits=["文档无退市股列表接口，退市代码为常识列举（见代码注释），未经接口核实；若返回“代码不存在”"
                "既可能是数据缺失也可能是代码记忆错误",
                "样本仅 4 只，不足以给出覆盖率，只能定性"],
        next_steps=["用交易所/巨潮公开的终止上市名单批量核对（数百只，可分多天、每次少量）"])


def item5_announce(res, shared):
    name, item = "GAP5_announcement_time_precision", "公告时间字段精度（天/分/秒）"
    per, allv = {}, []
    for code in ("600519", "000001"):
        r = probe(res, f"ann_{code}", f"/hsstock/announcement/{code}/{{licence}}")
        rr = [x for x in c.rows(r.data) if isinstance(x, dict)]
        tkey = next((k for k in ("t", "rq", "sj", "time", "date") if rr and k in rr[0]), None)
        vals = [x.get(tkey) for x in rr] if tkey else []
        allv += vals
        per[code] = {"rows": len(rr), "time_key": tkey, "fields": list(rr[0].keys()) if rr else [],
                     **classify_time_precision(vals)}
    agg = classify_time_precision(allv)
    st = "measured" if allv else "inconclusive"
    return _item(res, name, item, st, {
        "summary": f"时间字段精度={agg['precision']}（样本 {agg['n']} 条；时间恒为 00:00:00 的 {agg['time_all_zero']} 条，"
                   f"仅日期 {agg['only_date']} 条）", "precision": agg["precision"], "hour_hist": agg["hour_hist"]},
        evidence=per,
        limits=["字段格式的精度不等于真实发布时刻的准确度；若为 day，事件研究只能按“T 日盘后可用、T+1 开盘可交易”处理"])


def _fetch_pit_history(res) -> dict:
    """600519 的 PIT_FACTORS 各取一次 factor/history（共 2 次），保存完整序列（≤400 行）供复测 3 比对回填。"""
    out = {}
    for fid in PIT_FACTORS:
        r = probe(res, f"pit_history_{fid}_600519", f"/factor/history/{fid}/600519/{{licence}}",
                  sample=f"p11_pit_history_{fid}_600519", n=400,
                  st=PIT_ST, et=PIT_ET, limit=400)
        out[fid] = history_series(r.data)
    return out


def _baseline_dir():
    """--history-baseline：给目录（含 p11_pit_history_*.json）或真实运行的 run_id（到 samples/<run_id>/ 找）。"""
    if not HISTORY_BASELINE:
        return None
    d = Path(HISTORY_BASELINE)
    if d.is_dir() and any(d.glob("p11_pit_history_*.json")):
        return d
    alt = c.SAMPLES_ROOT / Path(HISTORY_BASELINE).name
    return alt if alt.is_dir() else d


def item6_history_only(res, shared):
    """--p11-only gap6-history（复测 3）：只取 2 次 factor/history；给了基线目录时离线逐日比对是否回填/改写。"""
    name, item = "GAP6_history_only", "因子历史复取（只跑 GAP6 history，比对回填）"
    hist = _fetch_pit_history(res)
    per = {fid: {"points": len(ser), "first": ser[0][0] if ser else None, "last": ser[-1][0] if ser else None,
                 "change_points": len(change_points(ser))} for fid, ser in hist.items()}
    bdir, cmp_, missing = _baseline_dir(), {}, []
    if bdir is not None:
        for fid, ser in hist.items():
            f = bdir / f"p11_pit_history_{fid}_600519.json"
            if f.is_file():
                cmp_[fid] = compare_history(load_history_sample(f), ser)
            else:
                missing.append(str(f.name))
    verdicts = {fid: v["verdict"] for fid, v in cmp_.items()}
    if not all(v["points"] for v in per.values()):
        st, summ = "inconclusive", "factor/history 有因子没取到数据"
    elif bdir is None:
        st, summ = "measured", "已保存完整序列（未给 --history-baseline，本次作为基线）"
    elif missing or not cmp_:
        st, summ = "inconclusive", f"基线目录缺文件 {missing}"
    elif any(v == "rewritten" for v in verdicts.values()):
        st, summ = "measured", f"存在回填/改写：{verdicts}"
    else:
        st, summ = "measured", f"已有日期的值未改写（精度差除外）：{verdicts}"
    return _item(res, name, item, st, {
        "summary": summ, "baseline": str(bdir) if bdir else None, "per_factor": per, "compare": cmp_,
        "verdict": verdicts}, evidence={"baseline_missing": missing},
        limits=["只比对 600519 的 profit_yoy、roe_ttm；精度差（precision_only）不算改写",
                "基线与复取须用同一区间 PIT_ST–PIT_ET 和 limit"])


def item6_nulls(res, shared):
    """--p11-only gap6-nulls（复测 2）：先取当日涨停池并记录取样时刻，只从当时已在池中的股票里选
    NULLS_ZT_PICK 只（研究员要求），再加 NULLS_BASE_CODES，逐只 factor/all 统计空值。共 1 + 7 = 8 次。"""
    name, item = "GAP6_nulls_retest", "空值因子复测（涨停股 + 原样本）"
    t0 = bj_now()
    pool_r = probe(res, "ztgc_today", f"/hslt/ztgc/{t0.date().isoformat()}/{{licence}}")
    t1 = bj_now()
    pool = [x for x in c.rows(pool_r.data) if isinstance(x, dict)]
    sel = pick_limit_up(pool, t0, NULLS_ZT_PICK, exclude=NULLS_BASE_CODES)
    sel["received_at_bj"] = t1.isoformat(timespec="seconds")
    in_pool = {str(x.get("dm", "")).split(".")[0] for x in pool}
    if ZT_CODES:          # 收盘后复跑：沿用盘中选出的代码；记录它们此刻是否仍在池中
        zt = list(ZT_CODES)
        sel["zt_codes_given"] = {cd: cd in in_pool for cd in zt}
    else:
        zt = [x["dm"] for x in sel["picks"]]
    per, null_sets = {}, {}
    for code in [*zt, *NULLS_BASE_CODES]:
        r = probe(res, f"factor_all_{code}", f"/factor/all/{code}/{{licence}}")
        d, ks = factor_keys(r.data)
        if not ks:
            per[code] = {"ok": False, "err": (r.text or "")[:200] or r.error}
            continue
        nl = sorted(k for k in ks if d.get(k) in (None, "", "null"))
        null_sets[code] = nl
        per[code] = {"ok": True, "n_factors": len(ks), "nulls": nl, "limit_up": code in zt,
                     "trade_date": d.get("trade_date"), "update_time": d.get("update_time")}
    seal = {f: {"limit_up_null": [cd for cd in zt if f in null_sets.get(cd, [f])],
                "others_null": [cd for cd in NULLS_BASE_CODES if f in null_sets.get(cd, [f])]} for f in SEAL_FACTORS}
    ok_zt = [cd for cd in zt if cd in null_sets]
    if not ok_zt:
        st, summ = "inconclusive", f"没有可用的涨停股（池 {len(pool)} 行，选中 {len(zt)} 只）"
    else:
        has_val = [f for f in SEAL_FACTORS if not seal[f]["limit_up_null"]]
        st, summ = "measured", (f"涨停股 {ok_zt} 上有值的封板类因子 {has_val}；"
                                f"仍为空 {[f for f in SEAL_FACTORS if f not in has_val]}")
    return _item(res, name, item, st, {
        "summary": summ, "limit_up_sampling": sel, "zt_codes": zt, "base_codes": NULLS_BASE_CODES,
        "seal_factors": seal, "null_sets": null_sets}, evidence={"per_stock": per},
        limits=["涨停池盘中每 10 分钟更新，取样时刻的池子本身有滞后；只选 fbt ≤ 取样时刻的股票",
                "factor/* 需要因子包或 Quant Pro 权益，否则 403"])


def item67_factors(res, shared):
    name6, item6 = "GAP6_factor_nulls_pit", "因子空值统计与时点性（point-in-time）"
    name7, item7 = "GAP7_factor_count", "因子数量核对（文档 85 / 82）"
    fl = probe(res, "factor_list", "/factor/list/{licence}")
    list_ids = [x.get("factor_id") for x in c.rows(fl.data) if isinstance(x, dict) and x.get("factor_id")]
    per, nulls, returned, meta_seen = {}, {}, set(), {}
    for code in FACTOR_STOCKS:
        r = probe(res, f"factor_all_{code}", f"/factor/all/{code}/{{licence}}")
        d, ks = factor_keys(r.data)
        if not ks:
            per[code] = {"ok": False, "err": r.text[:200] or r.error}
            continue
        returned |= set(ks)
        nl = [k for k in ks if d.get(k) in (None, "", "null")]
        for k in ks:
            nulls.setdefault(k, 0)
            nulls[k] += k in nl
        meta_seen[code] = {k: d.get(k) for k in FACTOR_META if k in d}
        per[code] = {"ok": True, "n_factors": len(ks), "nulls": nl}
    n_ok = sum(1 for v in per.values() if v.get("ok"))
    null_any = {k: f"{v}/{n_ok}" for k, v in sorted(nulls.items()) if v}
    # ---- 时点性：factor/history（纯财务因子）的跳变日 vs 利润表披露日 plrq
    inc = shared.get("income_600519") or []
    reports = [{"jzrq": norm_date(r.get("jzrq")), "plrq": norm_date(r.get("plrq"))} for r in inc if isinstance(r, dict)]
    reports = [r for r in reports if r["jzrq"] and r["jzrq"] >= "2024-01-01"]
    pit = {}
    hist_dates = _fetch_pit_history(res)
    for fid in PIT_FACTORS:
        ser = hist_dates[fid]
        cp = change_points(ser)
        pit[fid] = {"points": len(ser), "first": ser[0][0] if ser else None, "last": ser[-1][0] if ser else None,
                    "null_points": sum(1 for _, v in ser if _num(v) is None),
                    **classify_pit(cp, reports)}
    # batch 指定历史 trade_date 与 history 同日值比对（同一张表应一致；不一致说明有重算）
    ser = hist_dates.get(PIT_FACTORS[0]) or []
    probe_day = PIT_BATCH_DAY or (ser[len(ser) // 2][0] if ser else "2025-10-15")
    b = probe(res, "pit_batch_hist_date", "/factor/batch/{licence}", method="POST",
              json_body={"codes": ["600519"], "factor_ids": PIT_FACTORS, "trade_date": probe_day.replace("-", "")})
    bf, _ = batch_values(b.data, "600519")
    # 数据日期一律取响应自带的日期（plan 34d475d）；缺失或与请求不一致 → as_of_mismatch，不参与比对/回填
    asof = batch_asof(probe_day, *batch_dates(b.data, "600519"))
    day = asof["data_date"]
    cmp_ = {}
    for fid in PIT_FACTORS:
        hv = dict(hist_dates.get(fid) or []).get(day) if day else None
        bv = bf.get(fid)
        cmp_[fid] = {"date": day, "requested_date": probe_day, "as_of_status": asof["status"], "history": hv,
                     "batch": bv, "equal": (hv is not None and bv is not None and _num(hv) == _num(bv))
                     if asof["use_for_backfill"] else None}
    has_asof = {k: sorted(v) for k, v in meta_seen.items()}
    verdicts = {fid: v["verdict"] for fid, v in pit.items()}
    prec_n = {fid: v["counts"].get("precision_only", 0) for fid, v in pit.items()}
    if any(v == "lookahead_suspected" for v in verdicts.values()):
        pit_c = "存在前视嫌疑：财务因子在报告披露日之前就已跳变（历史可能用后来披露的数据回填）"
        st6 = "measured"
    elif verdicts and all(v == "consistent_with_pit" for v in verdicts.values()):
        pit_c = "与按时点计算一致：财务因子仅在 plrq 之后 10 天内跳变（单只股票、两个因子，属必要不充分证据）"
        st6 = "measured"
    else:
        pit_c = "单次运行无法定论（无跳变/无 plrq/跳变无法归因）"
        st6 = "inconclusive"
    _item(res, name6, item6, st6, {
        "summary": f"空值因子 {list(null_any)}；时点性：{pit_c}",
        "null_factors": null_any, "doc_declared_empty": DOC_NORTH_EMPTY + ["attention_score(FAQ)", "ev_ebitda(可 null)"],
        "pit_verdict": verdicts, "pit_conclusion": pit_c, "precision_only_changes": prec_n,
        "asof_fields_in_factor_all": has_asof,
        "history_vs_batch_same_day": cmp_, "batch_as_of": asof},
        evidence={"per_stock": per, "pit": pit, "reports_used": reports},
        limits=["factor/history 文档注明“历史表随日终追加”：上线之后的点天然按时点；上线前若有回填，口径未知",
                "只用 600519 一只、两个财务因子；行情类因子（动量/估值分母价格）无法用此法判定",
                "history 与 batch 读同一张表，二者一致只能说明接口自洽，不能证明按时点",
                "batch 的数据日期以响应自带日期为准；as_of_mismatch 时 equal=null，该批不参与比对、不用于回填"],
        next_steps=["保存本次 factor/history 结果，间隔 ≥1 周后重取同一区间逐日比对：若历史值被改写 → 非时点（会重算）",
                    "用 plrq ≤ T 的利润表自行计算 T 日 profit_yoy，与 history 的 T 日值逐点比对"])
    # ---- 第 7 项：数量核对
    ret = sorted(returned)
    _item(res, name7, item7, "measured" if ret else "inconclusive", {
        "summary": f"factor/all 实返因子字段 {len(ret)} 个（并集，不含 *_rank 与元数据）；factor/list {len(list_ids)} 个；"
                   f"文档 85 / 82",
        "returned_n": len(ret), "factor_list_n": len(list_ids), "doc_n": len(DOC_FACTOR_IDS), "doc_live_n": len(DOC_82),
        "missing_vs_doc85": sorted(set(DOC_FACTOR_IDS) - returned),
        "extra_vs_doc85": sorted(returned - set(DOC_FACTOR_IDS)),
        "list_missing_vs_doc85": sorted(set(DOC_FACTOR_IDS) - set(list_ids)) if list_ids else None,
        "list_extra_vs_doc85": sorted(set(list_ids) - set(DOC_FACTOR_IDS)) if list_ids else None,
        "returned_but_all_null": sorted(k for k, v in nulls.items() if n_ok and v == n_ok)},
        evidence={"returned": ret, "factor_list_ids": list_ids})


ONLY_PLAN = {    # --p11-only 各模式跑哪些项（调用次数见 README §6A）
    "gap1": (("GAP1_snapshot_latency", "快照延迟", item1_latency),),
    "gap6-history": (("GAP6_history_only", "因子历史复取", item6_history_only),),
    "gap6-nulls": (("GAP6_nulls_retest", "空值因子复测", item6_nulls),),
}


def main(res):
    shared: dict = {}
    if ONLY is not None:
        if ONLY not in ONLY_PLAN:
            raise ValueError(f"未知 --p11-only：{ONLY}")
        for name, item, fn in ONLY_PLAN[ONLY]:
            _guard(res, name, item, lambda fn=fn: fn(res, shared))
        res.append({"name": "GAP_SUMMARY", "only": ONLY, "items": [
            {"name": x["name"], "status": x["status"], "summary": x["conclusion"].get("summary")}
            for x in res if isinstance(x, dict) and str(x.get("name", "")).startswith("GAP") and "status" in x]})
        return
    for name, item, fn in (
            ("GAP1_snapshot_latency", "快照延迟", item1_latency),
            ("GAP2_cje_v_units", "cje/v 单位", item2_units),
            ("GAP3_plrq_coverage_revision", "plrq", item3_plrq),
            ("GAP4_delisted_survivorship", "退市股", item4_delisted),
            ("GAP5_announcement_time_precision", "公告时间精度", item5_announce),
            ("GAP6_factor_nulls_pit", "因子空值/时点 + 因子数量", item67_factors)):
        _guard(res, name, item, lambda fn=fn: fn(res, shared))
    res.append({"name": "GAP_SUMMARY", "items": [
        {"name": x["name"], "status": x["status"], "summary": x["conclusion"].get("summary")}
        for x in res if isinstance(x, dict) and str(x.get("name", "")).startswith("GAP") and "status" in x]})


if __name__ == "__main__":
    import sys
    import run_all
    sys.exit(run_all.cli(["p11_gaps", *sys.argv[1:]]))
