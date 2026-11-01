"""第 11 项：catalog.md §5 缺口补测（快照延迟、cje/v 单位、plrq 覆盖与修订、退市股、公告时间精度、
因子空值与时点性、因子数量核对）。

设计原则：调用量少（约 40～45 次 HTTP）、串行、复用同一 Session；每项输出结构化结论：
  {"name": "GAP<n>_...", "item": 说明, "status": "measured|skipped|inconclusive|error",
   "conclusion": {...}, "evidence": {...}, "limits": [...], "next_steps": [...]}
本文件不含任何证书；URL 模板中的 {licence} 由 common.call 填充并在日志中脱敏。
"""
from __future__ import annotations

import math
import re
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import common as c
from _helpers import probe

BJ = timezone(timedelta(hours=8))      # 北京时间固定 UTC+8（不依赖 zoneinfo/tzdata，Windows 也可用）

# dry-run 用：None=按真实北京时间判断；True/False=强制视为盘中/盘后（仅 dry-run 时生效）
FORCE_SESSION = None

LAT_CODE = "000001"
LAT_SAMPLES = 6            # 每个快照源采样次数（5～10 之间）
LAT_INTERVAL_S = 5.0       # 采样间隔秒数（dry-run 时缩短）

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
FACTOR_META = {"code", "name", "trade_date", "update_time", "report_period", "calc_version", "dm", "mc"}

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


def change_points(series: list) -> list:
    """series: [(YYYY-MM-DD, value)] 升序 → 值发生变化的日期列表（含前后值）。"""
    out, prev = [], None
    for d, v in series:
        x = _num(v)
        if x is None:
            continue
        if prev is not None and abs(x - prev[1]) > 1e-9 * max(1.0, abs(prev[1])):
            out.append({"date": d, "from": prev[1], "to": x})
        prev = (d, x)
    return out


def classify_pit(changes: list, reports: list, window_days: int = 10) -> dict:
    """reports: [{"jzrq","plrq"}]（YYYY-MM-DD）。对每个变化点判定：
    after_plrq —— 变化日落在某份报告披露日之后 window 天内（与“按时点”一致）；
    before_disclosure —— 变化日落在某报告期末之后、但该报告披露日之前（前视：用到了尚未披露的数据）；
    unexplained —— 其他（可能是口径、股本或行情驱动，需人工看）。"""
    res = {"after_plrq": [], "before_disclosure": [], "unexplained": []}
    for ch in changes:
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
    if not changes:
        verdict = "no_change_in_window"
    elif n["before_disclosure"]:
        verdict = "lookahead_suspected"
    elif n["after_plrq"] and not n["unexplained"]:
        verdict = "consistent_with_pit"
    else:
        verdict = "inconclusive"
    return {"verdict": verdict, "counts": n, "details": {k: v[:8] for k, v in res.items()}}


def factor_keys(d) -> tuple:
    if isinstance(d, dict) and isinstance(d.get("data"), dict):
        d = d["data"]
    if not isinstance(d, dict):
        return None, None
    ks = [k for k in d if k not in FACTOR_META and not k.endswith("_rank")]
    return d, ks


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
        "after_plrq": 1, "before_disclosure": 1, "unexplained": 0} and pit["verdict"] == "lookahead_suspected",
        str(pit["counts"])))
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


def item1_latency(res, shared):
    name, item = "GAP1_snapshot_latency", "快照延迟：快照时间戳 t vs 本机时钟（北京时间）"
    ctx = c.ctx()
    now = bj_now()
    need = LAT_SAMPLES * (LAT_INTERVAL_S if not ctx.dry_run else 0.05) * 2 + 20
    in_sess = is_bj_session(now, need)
    if ctx.dry_run and FORCE_SESSION is not None:
        in_sess = bool(FORCE_SESSION)
    limits = ["本机时钟与标准时间（NTP）的偏差未知：延迟 = 本机收到响应时刻 − 快照 t，含本机时钟误差；"
              "另用服务端 HTTP Date 头（秒级）估计本机与服务端的钟差供参考，服务端时钟本身的准确性同样未知",
              "t 字段只到秒，单次延迟分辨率约 ±1s"]
    if not in_sess:
        return _item(res, name, item, "skipped",
                     {"summary": "盘后无法测", "bj_now": now.isoformat(timespec="seconds"),
                      "reason": "当前北京时间不在连续竞价时段（工作日 9:30–11:30、13:00–15:00），或距本时段结束不足"
                                f" {need:.0f}s；盘后快照 t 停在收盘时刻，延迟无意义"},
                     limits=limits, next_steps=["在北京时间交易时段内重跑：python run_all.py p11"])
    # 交易日历确认是否节假日（1 次调用）
    cal = probe(res, "tcalendar_this_year", "/tcalendar/list/" + str(now.year) + "/{licence}")
    days = [str(x) for x in (cal.data if isinstance(cal.data, list) else c.rows(cal.data))]
    today = now.strftime("%Y%m%d")
    cal_state = "unknown" if not days else ("trading_day" if any(today in d.replace("-", "") for d in days)
                                            else "holiday")
    if cal_state == "holiday" and not (ctx.dry_run and FORCE_SESSION):
        return _item(res, name, item, "skipped", {"summary": "盘后无法测（交易日历显示今日非交易日）",
                                                   "bj_now": now.isoformat(timespec="seconds")}, limits=limits)
    interval = 0.05 if ctx.dry_run else LAT_INTERVAL_S
    srcs = {"real_time_broker": f"/hsstock/real/time/{LAT_CODE}/{{licence}}",
            "ssjy_web": f"/hsrl/ssjy/{LAT_CODE}/{{licence}}"}
    samples = {k: [] for k in srcs}
    for i in range(LAT_SAMPLES):
        for k, tpl in srcs.items():
            t_send = time.time()
            r = probe(res, f"lat_{k}_{i + 1}", tpl)
            t_recv = time.time()
            rec = _snap_record(r)
            if rec is not None:
                shared.setdefault("snap", {})[(k, LAT_CODE)] = rec
            ts = parse_bj(rec.get("t")) if rec else None
            srv = None
            try:
                srv = parsedate_to_datetime(r.headers.get("Date") or r.headers.get("date")).timestamp()
            except Exception:
                srv = None
            samples[k].append({
                "i": i + 1, "t": rec.get("t") if rec else None,
                "recv_bj": datetime.fromtimestamp(t_recv, BJ).isoformat(timespec="milliseconds"),
                "lag_s": round(t_recv - ts.timestamp(), 3) if ts else None,
                "rtt_ms": r.ms,
                "local_minus_server_date_s": round((t_send + t_recv) / 2 - srv, 3) if srv else None})
        if i + 1 < LAT_SAMPLES:
            time.sleep(interval)
    stats = {}
    for k, ss in samples.items():
        lags = [s["lag_s"] for s in ss if s["lag_s"] is not None]
        offs = [s["local_minus_server_date_s"] for s in ss if s["local_minus_server_date_s"] is not None]
        ts_distinct = len({s["t"] for s in ss if s["t"]})
        stats[k] = {"n": len(ss), "n_with_t": len(lags),
                    "lag_s_min": min(lags) if lags else None, "lag_s_p50": statistics.median(lags) if lags else None,
                    "lag_s_max": max(lags) if lags else None, "t_distinct": ts_distinct,
                    "clock_offset_vs_server_date_s_p50": statistics.median(offs) if offs else None}
    p50s = [v["lag_s_p50"] for v in stats.values() if v["lag_s_p50"] is not None]
    suggest = None
    if p50s:
        worst = max(v["lag_s_max"] for v in stats.values() if v["lag_s_max"] is not None)
        suggest = int(math.ceil(max(worst * 2, 10)))
    return _item(res, name, item, "measured" if p50s else "inconclusive", {
        "summary": "；".join(f"{k}: 延迟 p50={v['lag_s_p50']}s max={v['lag_s_max']}s，t 变化 {v['t_distinct']} 次/"
                            f"{v['n']} 次采样" for k, v in stats.items()),
        "bj_start": now.isoformat(timespec="seconds"), "calendar": cal_state, "per_source": stats,
        "suggested_stale_threshold_s": suggest,
        "ntp_offset": "unknown"}, evidence={"samples": samples}, limits=limits,
        next_steps=["如需排除本机钟差：运行前在 Windows 执行 w32tm /stripchart /computer:ntp.aliyun.com /samples:3 "
                    "/dataonly 记录偏差（只读命令，不改系统时间）"])


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
    pit, hist_dates = {}, {}
    for fid in PIT_FACTORS:
        r = probe(res, f"pit_history_{fid}_600519", f"/factor/history/{fid}/600519/{{licence}}",
                  st=PIT_ST, et=PIT_ET, limit=400)
        ser = sorted((norm_date(x.get("trade_date")), x.get("value")) for x in c.rows(r.data)
                     if isinstance(x, dict) and norm_date(x.get("trade_date")))
        hist_dates[fid] = ser
        cp = change_points(ser)
        pit[fid] = {"points": len(ser), "first": ser[0][0] if ser else None, "last": ser[-1][0] if ser else None,
                    "null_points": sum(1 for _, v in ser if _num(v) is None),
                    **classify_pit(cp, reports)}
    # batch 指定历史 trade_date 与 history 同日值比对（同一张表应一致；不一致说明有重算）
    ser = hist_dates.get(PIT_FACTORS[0]) or []
    probe_day = ser[len(ser) // 2][0] if ser else "2025-10-15"
    b = probe(res, "pit_batch_hist_date", "/factor/batch/{licence}", method="POST",
              json_body={"codes": ["600519"], "factor_ids": PIT_FACTORS, "trade_date": probe_day.replace("-", "")})
    brow = next((x for x in c.rows(b.data) if isinstance(x, dict)), {})
    bf = brow.get("factors") if isinstance(brow.get("factors"), dict) else brow
    cmp_ = {}
    for fid in PIT_FACTORS:
        hv = dict(hist_dates.get(fid) or []).get(probe_day)
        cmp_[fid] = {"date": probe_day, "history": hv, "batch": bf.get(fid) if isinstance(bf, dict) else None}
    has_asof = {k: sorted(v) for k, v in meta_seen.items()}
    verdicts = {fid: v["verdict"] for fid, v in pit.items()}
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
        "pit_verdict": verdicts, "pit_conclusion": pit_c, "asof_fields_in_factor_all": has_asof,
        "history_vs_batch_same_day": cmp_},
        evidence={"per_stock": per, "pit": pit, "reports_used": reports},
        limits=["factor/history 文档注明“历史表随日终追加”：上线之后的点天然按时点；上线前若有回填，口径未知",
                "只用 600519 一只、两个财务因子；行情类因子（动量/估值分母价格）无法用此法判定",
                "history 与 batch 读同一张表，二者一致只能说明接口自洽，不能证明按时点"],
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


def main(res):
    shared: dict = {}
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
