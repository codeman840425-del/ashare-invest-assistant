"""T-R12 / T-R12a 离线分析（T-B05 财务时点自算实测项 ①–⑨）：只读 p13_fin_pit 保存的完整原始响应，不联网、不读证书。

用法：
  python p13_analyze.py <run_dir>            # 例：results/run-20261102-093000；写 <run_dir>/p13_analysis.json（不覆盖）
  python p13_analyze.py <run_dir> --stdout   # 只打印，不写文件

口径（plan 2.12.1，docs 提交 6efedef + de86b99）：
- '-'、''、None、'--'、非数字 → 空（null）；从不用 0 补。
- 经营现金流每个 YTD 分量 = coalesce(jyhdcsdxjlxj, jyhdcsdxjlje)，实际所用字段记 basis.ocf_field；两者皆空 → 分量缺失。
- PB = d 日不复权收盘 c × zgb(d) ÷ 归母权益 gsmgdqsyhj(P)；zgb(d) 取 bdrq ≤ d 且 next_trading_day(plrq) ≤ d 的
  bdrq 最大一行（离线近似：plrq < d，即 plrq 的下一自然日 ≤ d；无交易日历时保守取严格小于）；
  权益取 plrq < d 的最新报告期（同 jzrq 取 plrq 最新且 < d 的版本；plrq ≤ jzrq 的占位行丢弃；jzrq ≥ d − 15 个月）；
  权益 ≤ 0 或缺失 → null 且不进分母；行业分位按申万一级、组内 N < 5 → null。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.financial_basis import (  # noqa: E402
    CDR_UNIT_SIGNOFF, TradingCalendar, load_calendar, load_share_classes, share_class_at, v5g_conditions,
)

SUBDIR = "p13_fin_pit"
SHARE_CLASS_PATH = Path(__file__).resolve().parents[3] / "config/share_class_list.yaml"
NULL_TOKENS = {"", "-", "--", "—", "null", "None", "nan", "NaN"}
OCF_FIELDS = ("jyhdcsdxjlxj", "jyhdcsdxjlje")
# 公开来源核对值（引用见 /workspace/team/reports/T-R12-material.md §0）
EXPECT = {
    "600519_bonus_2011": {"ex_date": "2011-07-01", "zgb_before": 943_800_000, "zgb_after": 1_038_180_000},
    # V5g（review-af589c0 m2）：核对值取巨潮披露。601318：2025 年年度报告摘要（巨潮
    # http://static.cninfo.com.cn/finalpage/2026-03-27/1225038326.PDF）期末总股本 18,107,641,995 股
    # = A 10,660,065,083 + H 7,447,576,912；2025-09-03 前后完成注销回购 A 股 102,592,612 股，故窗口 [2025-09-03, 2025-12-31]。
    "601318_capital": {"not_before": "2025-09-03", "at": "2025-12-31", "a": 10_660_065_083, "h": 7_447_576_912,
                       "total": 18_107_641_995, "source": "cninfo 2026-03-27 中国平安 2025 年年度报告摘要（1225038326）"},
    # 000550：江铃汽车 2025 年年度报告（巨潮，2026-03-28 披露）期末 A 519,214,000 + B 344,000,000
    "000550_capital": {"not_before": None, "at": "2025-12-31", "a": 519_214_000, "b": 344_000_000,
                       "total": 863_214_000, "source": "cninfo 2026-03-28 江铃汽车 2025 年年度报告"},
    # V5j（review-af589c0 M1）：九号公司 10 份 CDR = 1 股基础股票。来源：九号 2025 年年度报告（巨潮
    # https://static.cninfo.com.cn/finalpage/2026-03-31/1225063705.PDF，第七节“股份变动”）：存托凭证总数
    # 2024-12-31 为 717,120,523 份、2025-12-31 为 720,335,578 份（2025-12-17 行权登记后）；基础股数 = 份数 / 10
    # （年报“存托凭证所代表的基础股票数量”同样按 1/10 列示，含小数）。
    "689009_cdr": {"ratio": 10, "source": "cninfo 2026-03-31 九号公司 2025 年年度报告", "checkpoints": [
        {"name": "fy2024_end", "not_before": "2024-10-01", "at": "2024-12-31", "cdr_units": 717_120_523,
         "base_shares": 71_712_052.3},
        {"name": "fy2025_end", "not_before": "2025-12-17", "at": "2025-12-31", "cdr_units": 720_335_578,
         "base_shares": 72_033_557.8}]},
}
INSURERS_SW = {"601318": "中国平安", "601628": "中国人寿", "601601": "中国太保", "601336": "新华保险",
               "601319": "中国人保"}
# Exact metadata names AND recognized values: business abbreviations (hbzj/yfbzj)
# and strings in arbitrary business fields are never metadata evidence.
CURRENCY_KEYS = {"currency", "currency_code", "bizhong", "bz", "币种"}
UNIT_KEYS = {"unit", "amount_unit", "monetary_unit", "danwei", "dw", "单位", "金额单位"}
CURRENCY_VALUES = {
    "cny": "CNY", "rmb": "CNY", "人民币": "CNY", "人民币元": "CNY",
    "usd": "USD", "美元": "USD", "hkd": "HKD", "港元": "HKD", "港币": "HKD",
    "eur": "EUR", "欧元": "EUR", "jpy": "JPY", "日元": "JPY", "gbp": "GBP", "英镑": "GBP",
}
UNIT_VALUES = {"元": "元", "人民币元": "元", "千元": "千元", "万元": "万元",
               "百万元": "百万元", "亿元": "亿元", "yuan": "元"}


# --------------------------------------------------------------------------- 基础
def num(v):
    """'-'、空、非数字 → None；数值原样（float）。0 仍是 0（是否可信由调用方判断）。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v else None
    s = str(v).strip().replace(",", "")
    if s in NULL_TOKENS:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def d10(v) -> str | None:
    """'20260930' / '2026-09-30' / '2026-09-30 00:00:00' → '2026-09-30'；无法解析 → None。"""
    if v is None:
        return None
    s = str(v).strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return m.group(0) if m else None


def to_date(s: str | None):
    s = d10(s)
    return date.fromisoformat(s) if s else None


def rows_of(data) -> list:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for k in ("data", "list", "items", "rows"):
            v = data.get(k)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
            if isinstance(v, dict):
                inner = rows_of(v)
                if inner:
                    return inner
    return []


def months_before(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    m += 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


def quarter(jzrq: str) -> str | None:
    return {"03-31": "Q1", "06-30": "H1", "09-30": "Q3", "12-31": "FY"}.get((d10(jzrq) or "")[5:])


def close_enough(a: float, b: float, abs_tol: float = 1.0, rel_tol: float = 1e-9) -> bool:
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def nonnull_rate(rows: list, field: str) -> dict:
    n = len(rows)
    k = sum(1 for r in rows if num(r.get(field)) is not None)
    return {"n": n, "nonnull": k, "rate": round(k / n, 4) if n else None,
            "absent_key": sum(1 for r in rows if field not in r)}


# --------------------------------------------------------------------------- ① cashflow
def ocf_component(row: dict):
    """返回 (值, 所用字段)；两者皆空 → (None, None)。不用 0 补。"""
    for f in OCF_FIELDS:
        v = num(row.get(f))
        if v is not None:
            return v, f
    return None, None


def latest_versions(rows: list) -> dict:
    """{jzrq: 该期 plrq 最新的一行}（离线“现在可见”口径，用于覆盖率统计，不用于时点计算）。"""
    out = {}
    for r in rows:
        j = d10(r.get("jzrq"))
        if not j:
            continue
        if j not in out or (d10(r.get("plrq")) or "") > (d10(out[j].get("plrq")) or ""):
            out[j] = r
    return out


def cashflow_checks(rows: list) -> dict:
    ident = {"equal": 0, "unequal": 0, "not_checkable": 0, "subtotals_zero_placeholder": 0, "mismatch_examples": []}
    both = {"both_present": 0, "equal": 0, "unequal_examples": []}
    for r in rows:
        xj, lr, lc = num(r.get("jyhdcsdxjlxj")), num(r.get("jyhdxjlrxj")), num(r.get("jyhdxjlcxj"))
        if xj is None or lr is None or lc is None:
            ident["not_checkable"] += 1
        elif lr == 0 and lc == 0 and xj != 0:
            ident["subtotals_zero_placeholder"] += 1
        elif close_enough(xj, lr - lc):
            ident["equal"] += 1
        else:
            ident["unequal"] += 1
            if len(ident["mismatch_examples"]) < 8:
                ident["mismatch_examples"].append({"jzrq": r.get("jzrq"), "plrq": r.get("plrq"), "xj": xj,
                                                   "lr_minus_lc": round(lr - lc, 2), "diff": round(xj - (lr - lc), 2)})
        je = num(r.get("jyhdcsdxjlje"))
        if xj is not None and je is not None:
            both["both_present"] += 1
            if close_enough(xj, je):
                both["equal"] += 1
            elif len(both["unequal_examples"]) < 8:
                both["unequal_examples"].append({"jzrq": r.get("jzrq"), "plrq": r.get("plrq"), "xj": xj, "je": je})
    lv = list(latest_versions(rows).values())
    ocf_used = {"jyhdcsdxjlxj": 0, "jyhdcsdxjlje": 0, "missing": 0}
    for r in lv:
        _, f = ocf_component(r)
        ocf_used[f or "missing"] += 1
    return {
        "rows": len(rows), "periods_latest_version": len(lv),
        "jzrq_min": min((d10(r.get("jzrq")) or "9" for r in rows), default=None),
        "jzrq_max": max((d10(r.get("jzrq")) or "" for r in rows), default=None),
        "nonnull": {f: nonnull_rate(rows, f) for f in (*OCF_FIELDS, "jyhdxjlrxj", "jyhdxjlcxj")},
        "nonnull_by_quarter": {q: {f: nonnull_rate([r for r in rows if quarter(r.get("jzrq") or "") == q], f)["rate"]
                                   for f in OCF_FIELDS} for q in ("Q1", "H1", "Q3", "FY")},
        "nonnull_since_2015": {f: nonnull_rate([r for r in rows if (d10(r.get("jzrq")) or "") >= "2015"], f)
                               for f in OCF_FIELDS},
        "identity_xj_eq_lr_minus_lc": ident, "xj_vs_je": both, "ocf_field_used_latest": ocf_used,
        "ytd": ytd_check(lv),
    }


def ytd_check(latest_rows: list) -> dict:
    """累计口径判定：用经营活动现金流入小计（恒正）看 Q1 < H1 < Q3 < FY 及 FY/Q1 比值；
    YTD 预期 FY/Q1≈4（≥2.5），单季预期 ≈1（≤1.8）。缺流入小计时用 销售商品收到的现金 xssptglwsddxj。"""
    by_year: dict = {}
    for r in latest_rows:
        j = d10(r.get("jzrq")) or ""
        q = quarter(j)
        if q:
            by_year.setdefault(j[:4], {})[q] = r
    years, ytd_like, single_like, other, examples = 0, 0, 0, 0, []
    for y, qs in sorted(by_year.items()):
        if not all(k in qs for k in ("Q1", "H1", "Q3", "FY")):
            continue
        field = None
        for f in ("jyhdxjlrxj", "xssptglwsddxj"):
            vals = [num(qs[k].get(f)) for k in ("Q1", "H1", "Q3", "FY")]
            if all(v is not None and v > 0 for v in vals):
                field = f
                break
        if field is None:
            continue
        years += 1
        q1, h1, q3, fy = vals
        ratio = fy / q1
        if q1 < h1 < q3 < fy and ratio >= 2.5:
            ytd_like += 1
        elif ratio <= 1.8:
            single_like += 1
        else:
            other += 1
        if len(examples) < 4 or y >= "2024":
            examples.append({"year": y, "field": field, "Q1": q1, "H1": h1, "Q3": q3, "FY": fy,
                             "FY_over_Q1": round(ratio, 2)})
    verdict = ("insufficient" if years == 0 else "ytd_cumulative" if ytd_like >= 0.8 * years
               else "single_quarter" if single_like >= 0.8 * years else "mixed")
    return {"complete_years": years, "ytd_like": ytd_like, "single_quarter_like": single_like, "other": other,
            "verdict": verdict, "examples": examples[-8:]}


def ocf_ttm(rows: list, y: int, q: str) -> dict:
    """TTM(y,q) = YTD(y,q) + FY(y−1) − YTD(y−1,q)（q=FY 时即 FY(y)）；按分量记 ocf_field；任一分量缺失 → null。"""
    lv = latest_versions(rows)
    md = {"Q1": "03-31", "H1": "06-30", "Q3": "09-30", "FY": "12-31"}
    need = [f"{y}-{md[q]}"] if q == "FY" else [f"{y}-{md[q]}", f"{y - 1}-12-31", f"{y - 1}-{md[q]}"]
    comps, fields, val = [], [], 0.0
    for i, j in enumerate(need):
        r = lv.get(j)
        v, f = ocf_component(r) if r else (None, None)
        comps.append({"jzrq": j, "plrq": d10(r.get("plrq")) if r else None, "value": v})
        fields.append(f)
        if v is None:
            return {"value": None, "basis": {"ocf_field": fields, "components": comps, "null_reason": "ocf_missing"}}
        val += -v if i == 2 else v
    return {"value": round(val, 2), "basis": {"ocf_field": fields, "components": comps}}


# --------------------------------------------------------------------------- ② balance
def balance_checks(rows: list, kind: str) -> dict:
    lv = latest_versions(rows)
    recent = [lv[k] for k in sorted(lv) if k >= "2015"]
    le0 = [{"jzrq": r.get("jzrq"), "plrq": r.get("plrq"), "gsmgdqsyhj": num(r.get("gsmgdqsyhj"))}
           for r in rows if (num(r.get("gsmgdqsyhj")) is not None and num(r.get("gsmgdqsyhj")) <= 0)]
    last = lv[max(lv)] if lv else {}
    za, fz, eq = num(last.get("zczj")), num(last.get("fzhj")), num(last.get("gsmgdqsyhj"))
    ident = {"zczj_eq_fzhgdqyzj": 0, "unequal": 0, "not_checkable": 0}
    for r in recent:
        a, b = num(r.get("zczj")), num(r.get("fzhgdqyzj"))
        if a is None or b is None:
            ident["not_checkable"] += 1
        elif close_enough(a, b, abs_tol=1000.0, rel_tol=1e-6):
            ident["zczj_eq_fzhgdqyzj"] += 1
        else:
            ident["unequal"] += 1
    unit = "unknown"
    if za is not None and kind in ("bank", "insurer"):
        unit = "yuan(likely)" if za >= 1e11 else "not_yuan?(check)" if za <= 1e10 else "ambiguous"
    jumps = magnitude_jumps(recent, "zczj")
    return {
        "rows": len(rows), "nonnull": {f: nonnull_rate(rows, f) for f in ("gsmgdqsyhj", "fzhj", "zczj", "syzqyhj")},
        "nonnull_since_2015": {f: nonnull_rate(recent, f)["rate"] for f in ("gsmgdqsyhj", "fzhj", "zczj")},
        "latest": {"jzrq": last.get("jzrq"), "plrq": last.get("plrq"), "zczj": za, "fzhj": fz, "gsmgdqsyhj": eq,
                   "equity_le_assets_minus_liab": (eq <= za - fz + 1.0) if None not in (eq, za, fz) else None},
        "magnitude_hint_not_for_conversion": unit, "assets_identity_since_2015": ident,
        "parent_equity_le0_rows": le0[:20], "parent_equity_le0_n": len(le0), "magnitude_jumps": jumps,
    }


def magnitude_jumps(rows: list, field: str, factor: float = 50.0) -> list:
    """相邻报告期数值相差 ≥ factor 倍 → 疑似单位不连续（plan 2.12.1 边界 5：只告警，不换算）。"""
    out, prev = [], None
    for r in rows:
        v = num(r.get(field))
        if v is None or v <= 0:
            continue
        if prev and (v / prev[1] >= factor or prev[1] / v >= factor):
            out.append({"from": prev[0], "to": r.get("jzrq"), "ratio": round(v / prev[1], 4)})
        prev = (r.get("jzrq"), v)
    return out


# --------------------------------------------------------------------------- ③ 多版本
def multi_versions(rows: list, keep_fields: int = 400) -> dict:
    groups: dict = {}
    for r in rows:
        groups.setdefault(d10(r.get("jzrq")) or "?", []).append(r)
    multi = {}
    for j, g in sorted(groups.items()):
        if len(g) < 2:
            continue
        g = sorted(g, key=lambda r: d10(r.get("plrq")) or "")
        diffs = []
        for a, b in zip(g, g[1:]):
            ch = {}
            for k in sorted(set(a) | set(b)):
                if k in ("plrq",):
                    continue
                va, vb = a.get(k), b.get(k)
                if num(va) is not None and num(vb) is not None:
                    if not close_enough(num(va), num(vb), abs_tol=0.005):
                        ch[k] = [va, vb]
                elif va != vb:
                    ch[k] = [va, vb]
            diffs.append({"plrq_from": a.get("plrq"), "plrq_to": b.get("plrq"), "changed_n": len(ch),
                          "changed": dict(list(ch.items())[:keep_fields])})
        multi[j] = {"versions": [d10(r.get("plrq")) for r in g], "diffs": diffs, "rows_full": g}
    return {"periods": len(groups), "multi_version_periods": len(multi), "groups": multi}


def restatement_match(mv: dict, periods: list, announce: str, window_days: int = 3) -> dict:
    """更正公告日附近（±window_days）是否出现新的 plrq 版本；按受影响期逐一列出。"""
    ad = to_date(announce)
    out = {}
    for j in periods:
        g = mv["groups"].get(j)
        vers = g["versions"] if g else []
        near = [v for v in vers if v and ad and abs((to_date(v) - ad).days) <= window_days]
        out[j] = {"versions": vers, "version_near_announcement": near, "multi": bool(g)}
    return out


# --------------------------------------------------------------------------- ④⑦⑧ capital / 分红送转
def capital_rows(rows: list) -> list:
    out = []
    for r in rows:
        b = d10(r.get("bdrq"))
        if b:
            out.append({**r, "_bdrq": b, "_plrq": d10(r.get("plrq"))})
    return sorted(out, key=lambda r: (r["_bdrq"], r["_plrq"] or ""))


def capital_semantics(rows: list) -> dict:
    cr = capital_rows(rows)
    lags = [(to_date(r["_plrq"]) - to_date(r["_bdrq"])).days for r in cr if r["_plrq"]]
    eq = sum(1 for x in lags if x == 0)
    fields = sorted({k for r in rows for k in r})
    split = {k: [k for k in fields if re.search(p, k, re.I)] for k, p in
             (("a_share", r"ag|a股"), ("b_share", r"bg|b股"), ("h_share", r"hg|h股|jw|境外"),
              ("restricted", r"xs"), ("float", r"lt"))}
    return {"rows": len(cr), "fields": fields, "share_class_field_guess": split,
            "plrq_eq_bdrq": eq, "plrq_after_bdrq": sum(1 for x in lags if x > 0),
            "plrq_before_bdrq": sum(1 for x in lags if x < 0), "plrq_missing": len(cr) - len(lags),
            "lag_days_min": min(lags) if lags else None, "lag_days_max": max(lags) if lags else None,
            "lag_days_median": sorted(lags)[len(lags) // 2] if lags else None,
            "bdrq_is_quarter_end_rate": round(sum(1 for r in cr if r["_bdrq"][5:] in
                                                  ("03-31", "06-30", "09-30", "12-31")) / len(cr), 4) if cr else None}


def zgb_change_around(rows: list, ex_date: str, days: int = 400) -> dict:
    cr = capital_rows(rows)
    ex = to_date(ex_date)
    win = [r for r in cr if abs((to_date(r["_bdrq"]) - ex).days) <= days]
    before = [r for r in cr if r["_bdrq"] < ex_date]
    after = [r for r in cr if r["_bdrq"] >= ex_date]
    first_after = after[0] if after else None
    return {"ex_date": ex_date,
            "last_row_before": _cap_view(before[-1]) if before else None,
            "first_row_on_or_after": _cap_view(first_after) if first_after else None,
            "rows_in_window": [_cap_view(r) for r in win][:30],
            "first_after_bdrq_eq_ex_date": bool(first_after and first_after["_bdrq"] == ex_date),
            "first_after_plrq_vs_ex_days": ((to_date(first_after["_plrq"]) - ex).days
                                            if first_after and first_after["_plrq"] else None)}


def _cap_view(r: dict) -> dict:
    return {k: v for k, v in r.items() if not k.startswith("_")}


def share_split_check(rows: list, exp: dict) -> dict:
    """V5g：zgb 是否含 B/H——对照巨潮：取巨潮总股本已知日期窗口 bdrq ∈ [exp.not_before, exp.at] 的最后一行，
    与总股本 / 仅 A 股比较。"""
    if not capital_rows(rows):
        return {"verdict": "no_rows", "cninfo_date": exp.get("at"), "source": exp.get("source")}
    r = row_in_window(rows, exp.get("at"), exp.get("not_before"))
    if r is None:
        return {"verdict": "no_row_in_window", "cninfo_date": exp.get("at"), "not_before": exp.get("not_before"),
                "source": exp.get("source")}
    zgb = num(r.get("zgb"))
    a_only = exp.get("a")
    total = exp.get("total")
    verdict = ("includes_non_a" if zgb is not None and close_enough(zgb, total, abs_tol=1e4, rel_tol=0.002)
               else "a_share_only" if zgb is not None and close_enough(zgb, a_only, abs_tol=1e4, rel_tol=0.002)
               else "neither(check)")
    a_sum = sum(num(r.get(k)) or 0 for k in ("ysltag", "xsltgf"))
    return {"row": _cap_view(r), "zgb": zgb, "expected_total": total, "expected_a": a_only, "verdict": verdict,
            "cninfo_date": exp.get("at"), "not_before": exp.get("not_before"), "source": exp.get("source"),
            "ysltag_plus_xsltgf": a_sum, "zgb_minus_a_fields": (zgb - a_sum) if zgb is not None else None}


def dividend_events(rows: list) -> list:
    out = []
    for r in rows:
        give, chg = num(r.get("give")) or 0.0, num(r.get("change")) or 0.0
        cd = d10(r.get("cdate"))
        if (give > 0 or chg > 0) and cd:
            out.append({"sdate": d10(r.get("sdate")), "cdate": cd, "give": give, "change": chg,
                        "line": r.get("line"), "rdate": r.get("rdate")})
    return sorted(out, key=lambda e: e["cdate"])


def bonus_visibility(cap_rows: list, events: list) -> dict:
    """V5d：每个送转事件，capital 中 zgb 变化行的 plrq 相对除权日早/晚多少天。"""
    cr = capital_rows(cap_rows)
    res = []
    for e in events:
        ex = e["cdate"]
        before = [r for r in cr if r["_bdrq"] < ex]
        z0 = num(before[-1].get("zgb")) if before else None
        ratio = 1 + (e["give"] + e["change"]) / 10
        hit = None
        for r in cr:
            z = num(r.get("zgb"))
            if r["_bdrq"] >= ex and z is not None and z0 and close_enough(z, z0 * ratio, abs_tol=1e4, rel_tol=0.01):
                hit = r
                break
        lag = (to_date(hit["_plrq"]) - to_date(ex)).days if hit and hit["_plrq"] else None
        res.append({**e, "zgb_before": z0, "expected_ratio": ratio,
                    "capital_row": _cap_view(hit) if hit else None,
                    "row_bdrq_minus_ex_days": (to_date(hit["_bdrq"]) - to_date(ex)).days if hit else None,
                    "row_plrq_minus_ex_days": lag})
    lags = [x["row_plrq_minus_ex_days"] for x in res if x["row_plrq_minus_ex_days"] is not None]
    late = sum(1 for x in lags if x > 0)
    rule = ("insufficient" if not lags else
            "must_integrate_dividend_feed" if late > len(lags) / 2 else "capital_timely_enough")
    return {"events": res, "matched": len(lags), "plrq_after_ex": late, "decision": rule,
            "rule": "多数（>50%）送转事件的 capital 行在除权日之后才可见 → 必须接入分红送转数据（plan 2.12.1 边界 2 / V5d）"}


def row_in_window(rows: list, at: str | None, not_before: str | None = None):
    """bdrq ∈ [not_before, at] 中 bdrq 最大的行（at=None → 最后一行）。"""
    cr = [r for r in capital_rows(rows) if (not at or r["_bdrq"] <= at) and (not not_before or r["_bdrq"] >= not_before)]
    return cr[-1] if cr else None


V5J_VALUES = ("zgb≈基础股数", "zgb≈CDR份数", "neither")


def cdr_unit_check(rows: list, exp: dict) -> dict:
    """V5j：689009 的 zgb 按基础股份还是 CDR 份数计。各核对点取 bdrq ∈ [not_before, at] 的最后一行；
    所有核对点同一口径才给定论，否则 neither。"""
    res = []
    for cp in exp.get("checkpoints", []):
        r = row_in_window(rows, cp["at"], cp.get("not_before"))
        z = num(r.get("zgb")) if r else None
        v = ("neither" if z is None
             else "zgb≈CDR份数" if abs(z - cp["cdr_units"]) / cp["cdr_units"] <= 0.001
             else "zgb≈基础股数" if abs(z - cp["base_shares"]) / cp["base_shares"] <= 0.001 else "neither")
        res.append({**cp, "row": _cap_view(r) if r else None, "zgb": z, "verdict": v,
                    "zgb_over_cdr_units": round(z / cp["cdr_units"], 6) if z else None})
    vs = {x["verdict"] for x in res}
    verdict = vs.pop() if len(vs) == 1 else "neither"
    return {"checkpoints": res, "v5j_cdr_unit": verdict, "ratio": exp.get("ratio"), "source": exp.get("source"),
            "rows": len(capital_rows(rows)), "relative_tolerance": 0.001,
            "data_quality": verdict == "neither",
            "rule": "T-R13容差0.1%：zgb≈CDR份数 → 总市值 = c × zgb，不乘转换比；zgb≈基础股数 → 总市值 = c × zgb × 10（比例入配置，"
                    "注明来源）；neither → 保留 verify_pending cdr_unit（T-R12e 第 3 条、T-R12f 第 7 条）"}


# --------------------------------------------------------------------------- V5g 名单（探针样本）
# T-R12e 第 2 条 / T-R12f 第 4 条：B/H 只按配置名单识别（不按代码段/名称）。旧plan元数据保留两个样本；正式分析读取版本化配置，
# 供 pb_at 读 non_a_share_capital（review-af589c0 m3，不再在 VERIFY_PENDING 写死）；全量名单草案见
# /workspace/team/reports/T-R12ef-lists.md。配置已由BusinessConfig接入；空生效日期草稿不参与历史打标。
SHARE_CLASS_LISTS_SAMPLE = {
    "source_note": "旧样本元数据；正式分析读取 config/share_class_list.yaml，缺上市日期时仍 unavailable",
    "A+H": {"601318": {"h_code": "02318", "source": "cninfo 1225038326 中国平安 2025 年年度报告摘要", "as_of": "2025-12-31"}},
    "A+B": {"000550": {"b_code": "200550", "source": "cninfo 江铃汽车 2025 年年度报告（2026-03-28）", "as_of": "2025-12-31"}},
}
# T-R12f 第 7 条：zgb 按基础股份计时 mcap = c × zgb × 每股基础股票对应 CDR 份数（逐证券配置，注明来源）
CDR_RATIO_SAMPLE = {"689009": {"cdr_per_base_share": 10,
                               "source": "SSE 上证公告（存托凭证）〔2020〕189号；cninfo 1225063705 九号公司 2025 年年度报告"}}


def share_class_member(lists: dict, code: str) -> str | None:
    return next((k for k in ("A+H", "A+B") if code in (lists.get(k) or {})), None)


# --------------------------------------------------------------------------- V5i 股本行可见时间
QUARTER_ENDS = ("03-31", "06-30", "09-30", "12-31")


def capital_deadline(bdrq: str) -> str | None:
    """bdrq 所属报告期的法定披露截止日（T-R12f 第 1 条）：Q1 → 4-30，H1 → 8-31，Q3 → 10-31，年报 → 次年 4-30。"""
    y, md = int(bdrq[:4]), bdrq[5:10]
    return {"03-31": f"{y}-04-30", "06-30": f"{y}-08-31", "09-30": f"{y}-10-31", "12-31": f"{y + 1}-04-30"}.get(md)


def v5i_applies(bdrq: str, plrq: str | None) -> bool:
    """T-R12f 第 1 条：bdrq 为季末，且 plrq = bdrq 或 plrq 也是季末。plrq = bdrq 但都不是季末 → 不适用。"""
    return bool(plrq) and bdrq[5:] in QUARTER_ENDS and (plrq == bdrq or plrq[5:] in QUARTER_ENDS)


def capital_visible(r: dict, incremental_first_seen_at: str | None = None, calendar: TradingCalendar | None = None) -> dict:
    """T-R12e 第 1 条 + T-R12f 第 1–3 条 + T-R12g：适用 V5i 的行——
      首次全量回填写入（无可信 first_seen_at，探针的全历史拉取即属此类）→ max(next_trading_day(plrq),
        next_trading_day(bdrq 所属报告期截止日) 09:30)，pit_basis 含 capital_deadline；
      增量采集（传 incremental_first_seen_at）→ max(next_trading_day(plrq), first_seen_at)，不套截止日。
    其余行 = next_trading_day(plrq) 09:30（与财务行一致）。pit_basis 为数组。
    T-B59：只用显式交易日历；缺少日历或覆盖不足则未确认，不再以自然日近似。"""
    b, p = r["_bdrq"], r["_plrq"]
    nxt = lambda x: calendar.next_day(x) if calendar else None
    if not p:
        return {"visible_from": None, "visible_at": None, "pit_basis": [], "deadline": None}
    next_plrq = nxt(p)
    deadline = capital_deadline(b) if v5i_applies(b, p) and not incremental_first_seen_at else None
    next_deadline = nxt(deadline) if deadline else None
    if not next_plrq or (deadline and not next_deadline):
        return {"visible_from": None, "visible_at": None,
                "pit_basis": ["capital_deadline"] if deadline else [], "deadline": deadline,
                "calendar_status": "unconfirmed", "reason": "calendar_missing_or_out_of_coverage"}
    if v5i_applies(b, p) and incremental_first_seen_at:
        cn = timezone(timedelta(hours=8))
        fs = datetime.fromisoformat(incremental_first_seen_at.replace("Z", "+00:00")).astimezone(cn)
        base = datetime.fromisoformat(f"{nxt(p)}T09:30:00+08:00")
        va = max(base, fs)
        # first_seen_at on a holiday is not itself a tradable visible session.
        if calendar and va.date().isoformat() not in calendar.open_days:
            nd = calendar.next_day(va.date().isoformat())
            if nd is None:
                return {"visible_from": None, "visible_at": None, "pit_basis": [], "deadline": None,
                        "calendar_status": "unconfirmed", "reason": "calendar_out_of_coverage"}
            va = datetime.fromisoformat(f"{nd}T09:30:00+08:00")
        return {"visible_from": va.date().isoformat(), "visible_at": va.isoformat(timespec="minutes"),
                "pit_basis": [], "deadline": None, "rule": "incremental_first_seen_at"}
    if v5i_applies(b, p):
        dl = capital_deadline(b)
        vf = max(nxt(p), nxt(dl))
        return {"visible_from": vf, "visible_at": f"{vf}T09:30+08:00", "pit_basis": ["capital_deadline"], "deadline": dl}
    vf = nxt(p)
    return {"visible_from": vf, "visible_at": f"{vf}T09:30+08:00", "pit_basis": [], "deadline": None}


def _quantiles(xs: list) -> dict:
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    q = lambda f: s[min(len(s) - 1, int(f * (len(s) - 1) + 0.5))]
    return {"n": len(s), "min": s[0], "p25": q(0.25), "median": q(0.5), "p75": q(0.75), "max": s[-1],
            "lt0": sum(1 for x in s if x < 0), "eq0": sum(1 for x in s if x == 0), "gt0": sum(1 for x in s if x > 0)}


V5I_VERDICTS = ("backfilled", "true_disclosure", "inconclusive")


def v5i_backfill(cap_rows: list, report_rows: list, first_seen_at: str | None = None, calendar: TradingCalendar | None = None) -> dict:
    """V5i 回填判定（review-af589c0 M2，T-R12f 第 1 条范围）。
    1) plrq 为季末的行数/占比；2) 每个季末 bdrq 行与同公司同 jzrq 的 balance/cashflow 最早 plrq 比较，
    diff = capital.plrq − 报告最早 plrq（天）；3) 判定：
      - 无可比行 → inconclusive；
      - diff < 0（股本行早于该期定期报告首次披露）占可比行 ≥ 20% → backfilled；
      - 无 diff < 0 且 0 ≤ diff ≤ 3 占 ≥ 80% → true_disclosure；其余 → inconclusive。
    4) 每行带 first_seen_at = 该次调用 manifest 的 fetched_at（离线回放时可能缺）。"""
    first: dict = {}
    for x in report_rows:
        j, p = d10(x.get("jzrq")), d10(x.get("plrq"))
        if j and p and (j not in first or p < first[j]):
            first[j] = p
    cr = capital_rows(cap_rows)
    with_p = [r for r in cr if r["_plrq"]]
    pq = [r for r in with_p if r["_plrq"][5:] in QUARTER_ENDS]
    rows, diffs = [], []
    for r in cr:
        if r["_bdrq"][5:] not in QUARTER_ENDS:
            continue
        rep = first.get(r["_bdrq"])
        diff = (to_date(r["_plrq"]) - to_date(rep)).days if (rep and r["_plrq"]) else None
        if diff is not None:
            diffs.append(diff)
        rows.append({"bdrq": r["_bdrq"], "plrq": r["_plrq"], "zgb": num(r.get("zgb")), "report_first_plrq": rep,
                     "diff_days": diff, "v5i_applies": v5i_applies(r["_bdrq"], r["_plrq"]),
                     "first_seen_at": first_seen_at, **{k: v for k, v in capital_visible(r, calendar=calendar).items()}})
    early = sum(1 for x in diffs if x < 0)
    aligned = sum(1 for x in diffs if 0 <= x <= 3)
    if not first:
        verdict, why = "inconclusive", "no_report_rows（只给内部统计）"
    elif not diffs:
        verdict, why = "inconclusive", "no_comparable_quarter_end_rows"
    elif early and early / len(diffs) >= 0.2:
        verdict, why = "backfilled", f"{early}/{len(diffs)} 个季末行早于该期定期报告首次披露"
    elif not early and aligned / len(diffs) >= 0.8:
        verdict, why = "true_disclosure", f"{aligned}/{len(diffs)} 个季末行与定期报告首次披露日相差 0–3 天"
    else:
        verdict, why = "inconclusive", f"早于报告 {early}、对齐 {aligned}、可比 {len(diffs)}"
    ex = sorted((x for x in rows if x["diff_days"] is not None), key=lambda x: x["diff_days"])
    return {"rows": len(cr), "rows_with_plrq": len(with_p),
            "plrq_is_quarter_end": {"n": len(pq), "rate": round(len(pq) / len(with_p), 4) if with_p else None},
            "plrq_eq_bdrq": sum(1 for r in with_p if r["_plrq"] == r["_bdrq"]),
            "quarter_end_bdrq_rows": len(rows), "v5i_applies_rows": sum(1 for x in rows if x["v5i_applies"]),
            "report_periods": len(first), "diff_days": _quantiles(diffs),
            "examples": {"earliest": ex[:3], "latest": ex[-3:] if len(ex) > 3 else []},
            "rows_detail_tail": rows[-20:], "first_seen_at": first_seen_at,
            "verdict": verdict, "why": why}


# --------------------------------------------------------------------------- ⑤ 申万
def sw_codes(list_rows: list, zg: dict, gg: dict) -> dict:
    sw = [r for r in list_rows if "申万" in str(r.get("name", "")) or str(r.get("code", "")).startswith("sw")]
    pref = {}
    for r in sw:
        p = str(r.get("code", "")).split("_")[0]
        pref[p] = pref.get(p, 0) + 1
    def by(kw: str) -> list:
        return [{k: r.get(k) for k in ("code", "name", "level", "pcode", "pname", "isleaf")}
                for r in sw if kw in str(r.get("name", ""))]
    l2 = [r for r in sw if str(r.get("code", "")).startswith("sw2_") or "申万二级" in str(r.get("name", ""))]
    gg_out = {}
    for code, rs in gg.items():
        dms = sorted({str(x.get("dm") or x.get("code") or "")[:6] for x in rs})
        gg_out[code] = {"n": len(rs), "codes": dms[:80], "insurer_list_match": sorted(set(dms) & set(INSURERS_SW)),
                        "insurer_list_missing": sorted(set(INSURERS_SW) - set(dms)) if "insurance" in code else None}
    return {"list_rows": len(list_rows), "sw_rows": len(sw), "code_prefix_counts": pref,
            "sw_l1_examples": [{k: r.get(k) for k in ("code", "name", "level", "pcode")}
                               for r in sw if str(r.get("pcode")) == "swhy"][:40],
            "bank_nodes": by("银行"), "insurance_nodes": by("保险"), "has_sw_l2": bool(l2), "sw_l2_n": len(l2),
            "zg": {k: [{kk: x.get(kk) for kk in ("code", "name", "level", "pcode")} for x in v
                       if "申万" in str(x.get("name", "")) or str(x.get("code", "")).startswith("sw")]
                   for k, v in zg.items()},
            "gg": gg_out, "configured_insurer_list": INSURERS_SW}


# --------------------------------------------------------------------------- ⑥ PB
def zgb_at(cap_rows: list, d: str, calendar: TradingCalendar | None = None):
    """review-af589c0 M3：bdrq ≤ d 且 visible_from ≤ d（T-R12e 第 1 条 + T-R12f 第 1–3 条，见 capital_visible；
    收盘价口径下“d 日 09:30 前可见”即可用）中 bdrq 最大的行；行上带 _pit。"""
    best = None
    for r in capital_rows(cap_rows):
        v = capital_visible(r, calendar=calendar)
        if r["_bdrq"] <= d and v["visible_from"] and v["visible_from"] <= d:
            if best is None or (r["_bdrq"], r["_plrq"]) > (best["_bdrq"], best["_plrq"]):
                best = {**r, "_pit": v}
    return best


def equity_at(bal_rows: list, d: str, floor_months: int = 15):
    dd = to_date(d)
    floor = months_before(dd, floor_months).isoformat()
    cands = []
    for r in bal_rows:
        j, p = d10(r.get("jzrq")), d10(r.get("plrq"))
        if not j or not p or p <= j or p >= d or j < floor:
            continue
        cands.append((j, p, r))
    if not cands:
        return None
    cands.sort(key=lambda x: (x[0], x[1]))
    return cands[-1][2]


# plan 2.12.1「T-R12b 补充裁定」第 1 条：封闭原因码表，同时命中多个时只写表中靠前的一个
NULL_REASONS = ("no_valid_bar", "share_change_pending", "a_share_only_capital", "no_visible_report",
                "pre_listing_equity", "pre_listing_capital", "unit_mismatch", "non_positive_earnings",
                "non_positive_equity", "no_capital_row", "ocf_missing", "component_missing", "data_conflict",
                "financial_sector_na")


def first_reason(hits: set) -> str | None:
    for r in NULL_REASONS:
        if r in hits:
            return r
    return None


def pb_at(bar: dict, cap_rows: list, bal_rows: list, verify_pending: list | None = None,
          ex_dates: list | None = None, share_class: str | None = None, share_class_list: str | None = None,
          lists_configured: bool = False, is_cdr: bool = False, cdr_unit: str | None = None,
          cdr_per_base_share: float | None = None, security_code: str | None = None,
          calendar: TradingCalendar | None = None, share_class_list_version: int | None = None) -> dict:
    """PB = 不复权 c × zgb(d) / 归母权益（plan 2.12.1 + T-R12a 边界 1–5 + T-R12b 原因码）。

    ex_dates：已知送转除权日（None = 没有送转数据源 → share_change_check=unavailable）；
    share_class：⑦ 判定（includes_non_a / a_share_only / None）。
    T-R12f 第 4 条：lists_configured=False（名单未接入）→ share_class_check=unavailable；接入后所有行 = list，
      名单内（share_class_list="A+H"/"A+B"）另打 non_a_share_capital；将来 capital 有区分字段 → field。
    T-R12e 第 3 条 + T-R12f 第 5–7 条 + T-R12g：is_cdr（securities.type=cdr）→ 照常算、verify_pending 加 cdr_unit
      （只是值上的标记；S2 池、F43/F48 分位池按 §1.4 本就不含 CDR，不写剔除条款）。
      cdr_unit="zgb≈CDR份数" → mcap = c × zgb，无需配置，T-B05 确认后即清除 cdr_unit；
      "zgb≈基础股数" → mcap = c × zgb × cdr_per_base_share（逐证券配置），确认且配置接入后清除。
      T-R13：只对已有逐证券签收且份数判定一致的 689009 清除，其他CDR不推广。
    银行/保险的 verify_pending 只继承标记，照常参与排序（T-R12f）。
    """
    d = d10(bar.get("t") or bar.get("d") or bar.get("trade_date"))
    vp = list(verify_pending or [])
    if lists_configured and share_class_list and "non_a_share_capital" not in vp:
        vp.append("non_a_share_capital")
    cdr_signed = (security_code or "").split(".")[0] in CDR_UNIT_SIGNOFF and cdr_unit == "zgb≈CDR份数"
    if is_cdr and cdr_signed:
        vp = [flag for flag in vp if flag != "cdr_unit"]
    elif is_cdr and "cdr_unit" not in vp:
        vp.append("cdr_unit")
    basis = {"trade_date": d, "mcap_basis": "a_price_total_shares", "verify_pending": vp,
             "calendar_status": "confirmed" if calendar else "unconfirmed"}
    if share_class_list_version is not None:
        basis["share_class_list_version"] = share_class_list_version
    if is_cdr and cdr_signed:
        basis["cdr_unit_signoff"] = CDR_UNIT_SIGNOFF[(security_code or "").split(".")[0]]
    basis["share_change_check"] = "unavailable" if ex_dates is None else "checked"
    basis["share_class_check"] = "list" if lists_configured else "unavailable"
    if lists_configured:
        basis["share_class_list"] = share_class_list
    if share_class:
        basis["share_class_probe_verdict"] = share_class
    if is_cdr:
        basis["cdr_unit_verdict"] = cdr_unit or "unverified"
    mult = cdr_per_base_share if (is_cdr and cdr_unit == "zgb≈基础股数" and cdr_per_base_share) else 1
    hits: set = set()
    c_ = num(bar.get("c"))
    if c_ is None or str(bar.get("sf", "0")) in ("1", "1.0"):
        hits.add("no_valid_bar")
    z = zgb_at(cap_rows, d, calendar=calendar) if d else None
    zv = num(z.get("zgb")) if z else None
    if zv is None or zv <= 0:
        hits.add("no_capital_row")
    if z and ex_dates:
        for ex in ex_dates:
            if ex and ex <= d and z["_bdrq"] < ex:
                hits.add("share_change_pending")
    if share_class == "a_share_only" and (share_class_list or not lists_configured):
        hits.add("a_share_only_capital")
    e = equity_at(bal_rows, d) if d else None
    eq = num(e.get("gsmgdqsyhj")) if e else None
    if e is None:
        hits.add("no_visible_report")
    elif eq is None:
        hits.add("component_missing")
    elif eq <= 0:
        hits.add("non_positive_equity")
    if z:
        basis.update({"zgb": zv, "zgb_bdrq": z["_bdrq"], "zgb_plrq": z["_plrq"], "zgb_visible_at": z["_pit"]["visible_at"]})
        if z["_pit"]["pit_basis"]:
            basis["pit_basis"] = list(z["_pit"]["pit_basis"])
    basis.update({"close_raw": c_, "period": d10(e.get("jzrq")) if e else None,
                  "equity_plrq": d10(e.get("plrq")) if e else None, "equity": eq})
    if c_ is not None and zv:
        basis["mcap"] = round(c_ * zv * mult, 2)
        if mult != 1:
            basis["cdr_per_base_share"] = mult
    reason = first_reason(hits)
    if reason:
        return {"value": None, "basis": {**basis, "null_reason": reason}}
    return {"value": round(c_ * zv * mult / eq, 4), "basis": basis}


def industry_pct(values: dict, industry: dict, min_n: int = 5) -> dict:
    """{code: pb or None} + {code: sw_l1} → {code: 分位(0–1) or None}；pb 为 None 不进分母；组内 N<5 → None。"""
    groups: dict = {}
    for code, v in values.items():
        ind = industry.get(code)
        if v is not None and ind:
            groups.setdefault(ind, []).append((v, code))
    out = {code: None for code in values}
    for ind, g in groups.items():
        if len(g) < min_n:
            continue
        g.sort()
        n = len(g)
        i = 0
        while i < n:
            k = i
            while k + 1 < n and g[k + 1][0] == g[i][0]:
                k += 1
            pct = ((i + k) / 2) / (n - 1) if n > 1 else 0.0
            for t in range(i, k + 1):
                out[g[t][1]] = round(pct, 6)
            i = k + 1
    return out


# --------------------------------------------------------------------------- ⑨ 币种/单位
def currency_unit_conclusion(by_response: dict) -> dict:
    """V5h: only explicit metadata with recognized values is confirmation.

    Confirmation is local to each response, not proof that other responses have
    the same basis. Unknown/partial metadata remains unconfirmed; never convert.
    """
    keys = sorted({k for v in by_response.values() for k in v["key_hits"]})
    strs = sorted({x for v in by_response.values() for x in v["string_value_hits"]})
    mismatch = any(v["unit_mismatch"] for v in by_response.values())
    complete = bool(by_response) and all(v["status"] == "confirmed" for v in by_response.values())
    if not keys:
        concl = "币种/单位未确认（未发现可信明确元数据）：只靠数量级不连续检查"
    elif not complete:
        concl = "仅部分币种/单位元数据已确认；其余未确认：只靠数量级不连续检查"
    else:
        concl = "各响应均有明确币种/单位元数据（仅限本批样本）"
    if mismatch:
        concl += "；已确认非人民币/非元 → unit_mismatch（不换算）"
    return {"by_response": by_response, "fields_found": keys, "string_hits": strs[:10],
            "status": "confirmed" if complete else "unconfirmed", "unit_mismatch": mismatch,
            "conclusion": concl}


def currency_unit_fields(responses: dict) -> dict:
    """Inspect only exact metadata names in records/envelopes or meta/metadata.

    Unknown values, units embedded in numbers, notes, and substring matches are
    not trusted. Distinct values in one response are a conflict, not confirmation.
    """
    hits = {}
    for name, response in responses.items():
        evidence, unknown, keys = [], [], set()

        def visit(value, path="", depth=0):
            if depth > 8:
                return
            if isinstance(value, list):
                for item in value:
                    visit(item, path, depth + 1)
            elif isinstance(value, dict):
                for k, v in value.items():
                    key = str(k).strip().lower()
                    keys.add(key)
                    if key in CURRENCY_KEYS or key in UNIT_KEYS:
                        kind = "currency" if key in CURRENCY_KEYS else "unit"
                        lookup = CURRENCY_VALUES if kind == "currency" else UNIT_VALUES
                        normalized = lookup.get(v.strip().lower()) if isinstance(v, str) else None
                        # Do not log arbitrary unrecognized metadata contents.
                        item = {"field": path + key, "kind": kind}
                        if normalized:
                            evidence.append({**item, "value": normalized})
                        else:
                            unknown.append(item)
                    elif key in {"meta", "metadata", "data", "rows", "result"}:
                        visit(v, path + key + ".", depth + 1)

        visit(response)
        evidence = [dict(zip(("field", "kind", "value"), v)) for v in
                    sorted({(x["field"], x["kind"], x["value"]) for x in evidence})]
        unknown = [dict(zip(("field", "kind"), v)) for v in
                   sorted({(x["field"], x["kind"]) for x in unknown})]
        currencies = {e["value"] for e in evidence if e["kind"] == "currency"}
        units = {e["value"] for e in evidence if e["kind"] == "unit"}
        conflict = len(currencies) > 1 or len(units) > 1
        status = "confirmed" if len(currencies) == len(units) == 1 and not unknown and not conflict else "unconfirmed"
        hits[name] = {"key_hits": sorted({e["field"] for e in evidence}),
                      "string_value_hits": sorted({e["value"] for e in evidence}),
                      "n_keys": len(keys), "metadata": evidence, "unrecognized_metadata": unknown,
                      "status": status, "conflict": conflict,
                      "unit_mismatch": bool(currencies - {"CNY"} or units - {"元"})}
    return hits


# --------------------------------------------------------------------------- 汇总
def load_raw(run_dir: Path) -> dict:
    sub = run_dir / SUBDIR
    out = {}
    for f in sorted(sub.glob("raw_*.json")):
        try:
            out[f.stem[4:]] = json.loads(f.read_text(encoding="utf-8") or "null")
        except ValueError:
            out[f.stem[4:]] = None
    return out


def load_first_seen(run_dir: Path) -> dict:
    """manifest.json → {调用名: fetched_at}（V5i first_seen_at；没有 manifest → {}）。"""
    f = run_dir / SUBDIR / "manifest.json"
    try:
        return {m["key"]: m.get("fetched_at") for m in json.loads(f.read_text(encoding="utf-8"))}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def analyze(raw: dict, plan: dict, first_seen: dict | None = None, calendar: TradingCalendar | None = None,
            share_class_config: dict | None = None) -> dict:
    """raw: {调用名: 解析后的 JSON}；plan: p13_fin_pit.PLAN_META（公司、类别、核对值）；
    first_seen: {调用名: manifest.fetched_at}（V5i 每行的 first_seen_at；缺 → None）。"""
    first_seen = first_seen or {}
    R = {k: rows_of(v) for k, v in raw.items()}
    kinds = plan.get("kinds", {})
    out: dict = {"inputs": sorted(raw), "plan": plan}
    out["1_cashflow"] = {c: {"kind": kinds.get(c), **cashflow_checks(R.get(f"cashflow_{c}", []))}
                         for c in plan.get("cashflow", [])}
    for c in plan.get("cashflow", []):
        rows = R.get(f"cashflow_{c}", [])
        lv = latest_versions(rows)
        if lv:
            j = max(lv)
            out["1_cashflow"][c]["ttm_example"] = {"period": j, **ocf_ttm(rows, int(j[:4]), quarter(j) or "FY")}
    out["2_balance"] = {c: {"kind": kinds.get(c), **balance_checks(R.get(f"balance_{c}", []), kinds.get(c, ""))}
                        for c in plan.get("balance", [])}
    mv = {}
    for name in sorted(R):
        if name.split("_")[0] in ("income", "balance", "cashflow"):
            m = multi_versions(R[name])
            mv[name] = {"periods": m["periods"], "multi_version_periods": m["multi_version_periods"],
                        "groups": {j: {"versions": g["versions"], "diffs": g["diffs"]} for j, g in m["groups"].items()}}
    rs = plan.get("restated", {})
    out["3_multi_version"] = {"by_response": mv, "restated": {
        "code": rs.get("code"), "announce": rs.get("announce"), "periods": rs.get("periods"),
        "match": {t: restatement_match(multi_versions(R.get(f"{t}_{rs.get('code')}", [])), rs.get("periods", []),
                                       rs.get("announce", "")) for t in ("income", "balance", "cashflow")}}}
    out["4_capital"] = {c: capital_semantics(R.get(f"capital_{c}", [])) for c in plan.get("capital", [])}
    out["4_capital"]["600519_bonus_2011"] = zgb_change_around(R.get("capital_600519", []), "2011-07-01")
    out["4_capital"]["600519_bonus_2011"]["expected"] = EXPECT["600519_bonus_2011"]
    reports = lambda c: [x for t in ("balance", "cashflow") for x in R.get(f"{t}_{c}", [])]
    bf = {c: v5i_backfill(R.get(f"capital_{c}", []), reports(c), first_seen.get(f"capital_{c}"), calendar=calendar)
          for c in plan.get("capital", [])}
    # Local citation permits only this annual public-disclosure cross-check;
    # it is NOT a fabricated vendor balance/cashflow row or earliest-plrq proof.
    annual550 = row_in_window(R.get("capital_000550", []), "2025-12-31")
    if "000550" in bf:
        bf["000550"]["public_annual_report_comparison"] = {
            "period": "2025-12-31", "public_disclosure_date": "2026-03-28",
            "source": EXPECT["000550_capital"]["source"],
            "capital_row": _cap_view(annual550) if annual550 else None,
            "diff_days": (to_date(d10(annual550["plrq"])) - date(2026, 3, 28)).days if annual550 and d10(annual550.get("plrq")) else None,
            "limitation": "仅本机已存巨潮年报披露日期引用；非供应商同期报告最早plrq，不能替代待补balance/cashflow响应"}
    out["4_capital"]["v5i_backfill"] = {
        "by_code": bf, "verdicts": {c: v["verdict"] for c, v in bf.items()},
        "rule": "T-R12f 第 1–3 条 + T-R12g：bdrq 季末且（plrq=bdrq 或 plrq 季末）——首次全量回填 → max(next_trading_day(plrq), "
                "next_trading_day(bdrq 所属报告期截止日) 09:30)，pit_basis 含 capital_deadline；增量 → max(ntd(plrq), "
                "first_seen_at)；其余 → plrq。探针为全历史拉取 = 首次回填口径"}
    lists = share_class_config if share_class_config is not None else (
        load_share_classes(SHARE_CLASS_PATH) if SHARE_CLASS_PATH.is_file() else
        {"list_version": 0, "as_of": "1970-01-01", "sources": {}, "records": []})
    canonical = lambda c: next((r["code"] for r in lists["records"] if r["code"].split(".")[0] == c), c)
    membership = lambda c, day: share_class_at(lists, canonical(c), day)
    out["7_share_class"] = {
        "601318_A+H": share_split_check(R.get("capital_601318", []), EXPECT["601318_capital"]),
        "000550_A+B": share_split_check(R.get("capital_000550", []), EXPECT["000550_capital"])}
    conditions = v5g_conditions(lists, out["7_share_class"])
    lists_on = conditions["list_integrated"]
    out["7_share_class_lists"] = {"config_loaded": bool(lists["records"]), "configured_in_probe": lists_on,
                                 "list_version": lists["list_version"],
                                 "members": {c: membership(c, lists["as_of"])["member"] for c in plan.get("capital", [])},
                                 "pending_effective_dates": sum(r["effective_from"] is None for r in lists["records"]),
                                 "v5g_close": {"conditions": conditions, "closed": all(conditions.values())}}
    out["trading_calendar"] = {"confirmed": calendar is not None,
                                "source": calendar.source if calendar else None,
                                "rule": "明确日历严格下一开市日；缺失或超覆盖不猜测"}
    # V5j：CDR 以 securities.type=cdr 识别（T-R12f 第 5 条）；探针里用 plan.kinds == "CDR" 代替
    cdrs = sorted(c for c, k in kinds.items() if k == "CDR")
    out["10_cdr"] = {c: cdr_unit_check(R.get(f"capital_{c}", []), EXPECT[f"{c}_cdr"]) for c in cdrs
                     if f"{c}_cdr" in EXPECT}
    out["v5j_cdr_unit"] = {c: v["v5j_cdr_unit"] for c, v in out["10_cdr"].items()}
    for code, check in out["10_cdr"].items():
        check["cdr_unit_cleared"] = code in CDR_UNIT_SIGNOFF and check["v5j_cdr_unit"] == "zgb≈CDR份数"
        check["signoff"] = CDR_UNIT_SIGNOFF.get(code) if check["cdr_unit_cleared"] else None
    ev = {c: dividend_events(R.get(f"jnfh_{c}", [])) for c in plan.get("jnfh", [])}
    out["8_dividend"] = {"has_dividend_feed": any(R.get(f"jnfh_{c}") for c in plan.get("jnfh", [])),
                         "fields": {c: sorted({k for r in R.get(f"jnfh_{c}", []) for k in r}) for c in plan.get("jnfh", [])},
                         "visibility": {c: bonus_visibility(R.get(f"capital_{c}", []), ev[c]) for c in ev}}
    zg = {k[3:]: v for k, v in R.items() if k.startswith("zg_")}
    gg = {k[3:]: v for k, v in R.items() if k.startswith("gg_")}
    out["5_sw"] = sw_codes(R.get("hszg_list", []), zg, gg)
    pb = {}
    for c in plan.get("pb", []):
        bars = sorted(R.get(f"daily_{c}", []), key=lambda b: d10(b.get("t") or b.get("d")) or "")
        vp = list(plan.get("verify_pending", {}).get(c, []))
        exd = [e["cdate"] for e in ev[c]] if c in ev else None
        sc = next((v["verdict"] for k, v in out["7_share_class"].items() if k.startswith(c)
                   and v.get("verdict") in ("includes_non_a", "a_share_only")), None)
        is_cdr = kinds.get(c) == "CDR"
        pb[c] = [pb_at(b, R.get(f"capital_{c}", []), R.get(f"balance_{c}", []), vp, exd, sc,
                       share_class_list=membership(c, d10(b.get("t") or b.get("d")) or lists["as_of"])["member"],
                       lists_configured=lists_on, is_cdr=is_cdr, security_code=c, calendar=calendar,
                       share_class_list_version=lists["list_version"],
                       cdr_unit=out["v5j_cdr_unit"].get(c),
                       cdr_per_base_share=(CDR_RATIO_SAMPLE.get(c) or {}).get("cdr_per_base_share"))
                 for b in bars[-5:]]
    out["6_pb"] = pb
    out["9_currency_unit"] = currency_unit_conclusion(currency_unit_fields(
        {k: v for k, v in raw.items() if k.split("_")[0] in ("income", "balance", "cashflow", "capital")}))
    decs = [v.get("decision") for v in out["8_dividend"]["visibility"].values() if v.get("decision")]
    # T-R12b 第 4 条（S1 硬条件 V5d）：股本行普遍晚于除权日才可见 → 必须接入送转数据
    out["8_dividend"]["overall_decision"] = (
        "must_integrate_dividend_feed" if "must_integrate_dividend_feed" in decs
        else ("capital_timely_enough" if decs else "inconclusive"))
    return out


def summary_lines(a: dict) -> list:
    L = []
    for c, v in a.get("1_cashflow", {}).items():
        nn = v["nonnull"]
        L.append(f"① {c}({v['kind']}): rows={v['rows']} xj非空率={nn['jyhdcsdxjlxj']['rate']} je非空率="
                 f"{nn['jyhdcsdxjlje']['rate']} 恒等式 等/不等/不可核={v['identity_xj_eq_lr_minus_lc']['equal']}/"
                 f"{v['identity_xj_eq_lr_minus_lc']['unequal']}/{v['identity_xj_eq_lr_minus_lc']['not_checkable']} "
                 f"两者皆有={v['xj_vs_je']['both_present']}(相等 {v['xj_vs_je']['equal']}) 累计口径={v['ytd']['verdict']}")
    for c, v in a.get("2_balance", {}).items():
        L.append(f"② {c}({v['kind']}): 归母权益非空率={v['nonnull']['gsmgdqsyhj']['rate']} fzhj={v['nonnull']['fzhj']['rate']}"
                 f" zczj={v['nonnull']['zczj']['rate']} 数量级提示（不据此换算）={v['magnitude_hint_not_for_conversion']} ≤0 行={v['parent_equity_le0_n']}")
    r = a.get("3_multi_version", {}).get("restated", {})
    L.append(f"③ 更正公司 {r.get('code')} 公告 {r.get('announce')}: " + json.dumps(
        {t: {j: m['version_near_announcement'] for j, m in v.items()} for t, v in (r.get("match") or {}).items()},
        ensure_ascii=False))
    b = a.get("4_capital", {}).get("600519_bonus_2011", {})
    L.append(f"④ 600519 2011-07-01: 之后首行={b.get('first_row_on_or_after')} plrq−除权日={b.get('first_after_plrq_vs_ex_days')}天")
    for k, v in a.get("7_share_class", {}).items():
        L.append(f"⑦ {k}: zgb={v.get('zgb')} 判定={v.get('verdict')}")
    for c, v in a.get("8_dividend", {}).get("visibility", {}).items():
        L.append(f"⑧ {c}: 送转事件匹配 {v['matched']}，plrq 晚于除权日 {v['plrq_after_ex']} → {v['decision']}")
    s = a.get("5_sw", {})
    L.append(f"⑤ 申万行 {s.get('sw_rows')}，前缀 {s.get('code_prefix_counts')}，有二级={s.get('has_sw_l2')}，"
             f"银行节点={[x['code'] for x in s.get('bank_nodes', [])][:4]} 保险节点={[x['code'] for x in s.get('insurance_nodes', [])][:4]}")
    for c, v in a.get("6_pb", {}).items():
        last = v[-1] if v else {}
        L.append(f"⑥ {c}: 最新 pb={last.get('value')} basis={json.dumps(last.get('basis'), ensure_ascii=False)[:240]}")
    hits = {k: v["key_hits"] for k, v in a.get("9_currency_unit", {}).get("by_response", {}).items()
            if v["key_hits"] or v["string_value_hits"]}
    L.append(f"⑨ 币种/单位疑似字段：{hits or '无'}；结论：{a.get('9_currency_unit', {}).get('conclusion')}")
    L.append(f"⑧ 总判定：{a.get('8_dividend', {}).get('overall_decision')}")
    for c, v in a.get("4_capital", {}).get("v5i_backfill", {}).get("by_code", {}).items():
        L.append(f"V5i {c}: rows={v['rows']} plrq季末={v['plrq_is_quarter_end']} 季末bdrq行={v['quarter_end_bdrq_rows']}"
                 f" diff_days={v['diff_days']} → {v['verdict']}（{v['why']}）")
    for c, v in a.get("10_cdr", {}).items():
        L.append(f"V5j {c}: " + "; ".join(f"{x['name']} zgb={x['zgb']} → {x['verdict']}" for x in v["checkpoints"])
                 + f" → v5j_cdr_unit={v['v5j_cdr_unit']}")
    return L


def selftest_pure() -> list:
    """纯函数单测（dry-run 阶段 6 与 selfchecks/tr12_fin.py 共用）。返回 [(名称, 通过, 说明)]。"""
    out = []
    # This is a synthetic all-open scenario, NOT a live exchange calendar.
    days = [(date(2000, 1, 1) + timedelta(days=i)).isoformat() for i in range(10227)]
    test_calendar = TradingCalendar("2000-01-01", "2027-12-31", tuple(days), "synthetic_selftest_only")
    cv = lambda *a, **k: capital_visible(*a, calendar=test_calendar, **k)
    z_at = lambda *a, **k: zgb_at(*a, calendar=test_calendar, **k)
    pb = lambda *a, **k: pb_at(*a, calendar=test_calendar, **k)

    def t(name, cond, detail=""):
        out.append((name, bool(cond), detail))

    t("num：'-'/'--'/''/None → None，0 仍为 0", [num(x) for x in ("-", "--", "", None, 0, "1,234.5")] ==
      [None, None, None, None, 0.0, 1234.5])
    cf = [{"jzrq": "2025-03-31", "plrq": "2025-04-29", "jyhdcsdxjlxj": "-", "jyhdcsdxjlje": 5.0},
          {"jzrq": "2024-12-31", "plrq": "2025-04-03", "jyhdcsdxjlxj": 30.0, "jyhdcsdxjlje": "-"},
          {"jzrq": "2024-03-31", "plrq": "2024-04-29", "jyhdcsdxjlxj": 4.0}]
    r = ocf_ttm(cf, 2025, "Q1")
    t("OCF coalesce + TTM = YTD + FY(y−1) − YTD(y−1)，basis.ocf_field 逐分量", r["value"] == 31.0 and
      r["basis"]["ocf_field"] == ["jyhdcsdxjlje", "jyhdcsdxjlxj", "jyhdcsdxjlxj"], str(r))
    cf[2] = {"jzrq": "2024-03-31", "plrq": "2024-04-29", "jyhdcsdxjlxj": "-", "jyhdcsdxjlje": "-"}
    r = ocf_ttm(cf, 2025, "Q1")
    t("OCF 两字段皆空 → TTM null（ocf_missing），不补 0", r["value"] is None and
      r["basis"]["null_reason"] == "ocf_missing")
    ident = cashflow_checks([{"jzrq": "2001-06-30", "jyhdcsdxjlxj": -8.0, "jyhdxjlrxj": 0.0, "jyhdxjlcxj": 0.0},
                             {"jzrq": "2025-03-31", "jyhdcsdxjlxj": 4000.0, "jyhdxjlrxj": 10000.0, "jyhdxjlcxj": 6000.0},
                             {"jzrq": "2025-06-30", "jyhdcsdxjlxj": 5000.0, "jyhdxjlrxj": 10000.0, "jyhdxjlcxj": 6000.0}])
    i = ident["identity_xj_eq_lr_minus_lc"]
    t("xj 恒等式：等/不等/小计为 0 的占位行分开计", (i["equal"], i["unequal"], i["subtotals_zero_placeholder"]) == (1, 1, 1))
    mk = lambda y, vals: [{"jzrq": f"{y}-{md}", "plrq": f"{y + (md == '12-31')}-{'04-30' if md == '12-31' else '10-30'}",
                           "jyhdxjlrxj": v} for md, v in zip(("03-31", "06-30", "09-30", "12-31"), vals)]
    t("YTD 判定：累计 → ytd_cumulative", ytd_check(mk(2024, (1, 2, 3, 4)))["verdict"] == "ytd_cumulative")
    t("YTD 判定：单季 → single_quarter", ytd_check(mk(2024, (1, 1.1, 0.9, 1.2)))["verdict"] == "single_quarter")
    mv = multi_versions([{"jzrq": "2024-09-30", "plrq": "2024-10-30", "a": 1.0, "b": "-"},
                         {"jzrq": "2024-09-30", "plrq": "2025-04-29", "a": 1.5, "b": "-"},
                         {"jzrq": "2024-12-31", "plrq": "2025-04-29", "a": 2.0}])
    g = mv["groups"].get("2024-09-30", {})
    t("多版本：同 jzrq 两版、字段差异只列 a", mv["multi_version_periods"] == 1 and
      g.get("diffs", [{}])[0].get("changed") == {"a": [1.0, 1.5]} and len(g.get("rows_full", [])) == 2)
    m = restatement_match(mv, ["2024-09-30", "2024-12-31"], "2025-04-29")
    t("更正匹配：公告日附近出现新版本", m["2024-09-30"]["version_near_announcement"] == ["2025-04-29"]
      and m["2024-12-31"]["multi"] is False)
    cap = [{"bdrq": "20110630", "plrq": "2011-06-30", "zgb": 943800000},
           {"bdrq": "20110701", "plrq": "2011-07-01", "zgb": 1038180000},
           {"bdrq": "20260930", "plrq": "2026-10-28", "zgb": 1250081601}]
    sem = capital_semantics(cap)
    t("capital：plrq−bdrq 天数统计", (sem["plrq_eq_bdrq"], sem["plrq_after_bdrq"], sem["lag_days_max"]) == (2, 1, 28))
    z = z_at(cap, "2026-10-28")
    t("zgb(d)：plrq 当日不可见（下一交易日才可见），取上一行", z and z["_bdrq"] == "2011-07-01")
    vis = bonus_visibility(cap, [{"cdate": "2011-07-01", "give": 1.0, "change": 0.0, "sdate": "2011-06-26"}])
    t("送转可见性：2011 10送1 匹配到 20110701 行，plrq−除权日 = 0 天", vis["matched"] == 1 and
      vis["events"][0]["row_plrq_minus_ex_days"] == 0 and vis["decision"] == "capital_timely_enough")
    late = bonus_visibility([{"bdrq": "20160331", "plrq": "2016-03-31", "zgb": 100},
                             {"bdrq": "20160616", "plrq": "2016-08-12", "zgb": 120}],
                            [{"cdate": "2016-06-16", "give": 0.0, "change": 2.0}])
    t("送转可见性：plrq 晚于除权日 → must_integrate_dividend_feed", late["decision"] == "must_integrate_dividend_feed")
    s3 = share_split_check([{"bdrq": "20250903", "plrq": "2025-09-03", "zgb": 10_660_065_083}],
                           EXPECT["601318_capital"])
    t("B/H：zgb = 仅 A 股 → a_share_only", s3["verdict"] == "a_share_only")
    bal = [{"jzrq": "2025-06-30", "plrq": "2025-08-20", "gsmgdqsyhj": 100.0},
           {"jzrq": "2025-09-30", "plrq": "2025-10-30", "gsmgdqsyhj": -5.0},
           {"jzrq": "2001-06-30", "plrq": "2001-06-30", "gsmgdqsyhj": 7.0}]
    capx = [{"bdrq": "20250630", "plrq": "2025-06-30", "zgb": 10}]
    t("PB：权益 ≤0 → null(non_positive_equity)", pb({"t": "2025-11-03", "c": 5.0, "sf": 0}, capx, bal)["basis"]
      .get("null_reason") == "non_positive_equity")
    p = pb({"t": "2025-10-30", "c": 5.0, "sf": 0}, capx, bal)
    t("PB：plrq 当日不可见 → 用上一期权益；值 = c×zgb/权益", p["value"] == 0.5 and p["basis"]["period"] == "2025-06-30"
      and p["basis"]["mcap_basis"] == "a_price_total_shares", str(p))
    t("PB：停牌 → no_valid_bar", pb({"t": "2025-10-30", "c": 5.0, "sf": 1}, capx, bal)["basis"]["null_reason"]
      == "no_valid_bar")
    t("PB：15 个月外无报告 → no_visible_report", pb({"t": "2027-03-01", "c": 5.0}, capx, bal[:1])["basis"]
      ["null_reason"] == "no_visible_report")
    r = pb({"t": "2025-10-30", "c": 5.0}, capx, bal, ex_dates=["2025-07-10"])["basis"]
    t("PB：除权日 ≤ d 但无 bdrq ≥ 除权日的可见股本行 → share_change_pending", r.get("null_reason") == "share_change_pending"
      and r["share_change_check"] == "checked")
    r = pb({"t": "2025-10-30", "c": 5.0}, capx, bal)["basis"]
    t("PB：无送转数据源/无法识别股本类别 → share_change_check、share_class_check = unavailable",
      r["share_change_check"] == "unavailable" and r["share_class_check"] == "unavailable" and "null_reason" not in r)
    t("PB：zgb 只含 A 股 → a_share_only_capital",
      pb({"t": "2025-10-30", "c": 5.0}, capx, bal, share_class="a_share_only")["basis"].get("null_reason")
      == "a_share_only_capital")
    r = pb({"t": "2025-10-30", "c": 5.0, "sf": 1}, [], [])["basis"]
    t("PB：多个原因同时命中 → 只写封闭表中靠前的一个（no_valid_bar 先于 no_visible_report/no_capital_row）",
      r.get("null_reason") == "no_valid_bar")
    t("PB：无可见股本行 → no_capital_row", pb({"t": "2025-10-30", "c": 5.0}, [], bal)["basis"].get("null_reason")
      == "no_capital_row")
    t("PB：plrq ≤ jzrq 的占位行不作为可见报告", equity_at(bal[2:], "2001-07-05") is None)
    cdr_rows = [{"bdrq": "20241231", "plrq": "2025-04-01", "zgb": 717_120_523},
                {"bdrq": "20251217", "plrq": "2025-12-17", "zgb": 720_335_578}]
    t("V5j：两核对点 zgb = CDR 份数 → zgb≈CDR份数", cdr_unit_check(cdr_rows, EXPECT["689009_cdr"])["v5j_cdr_unit"]
      == "zgb≈CDR份数")
    t("V5j：zgb = 份数/10 → zgb≈基础股数；两点口径不一或缺行 → neither",
      cdr_unit_check([{**r, "zgb": r["zgb"] / 10} for r in cdr_rows], EXPECT["689009_cdr"])["v5j_cdr_unit"]
      == "zgb≈基础股数"
      and cdr_unit_check([cdr_rows[0], {**cdr_rows[1], "zgb": 1}], EXPECT["689009_cdr"])["v5j_cdr_unit"] == "neither"
      and cdr_unit_check(cdr_rows[:1], EXPECT["689009_cdr"])["v5j_cdr_unit"] == "neither")
    t("V5i：截止日按 bdrq 所属报告期 Q1→4-30、H1→8-31、Q3→10-31、年报→次年 4-30，非季末 → None",
      [capital_deadline(x) for x in ("2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2025-07-01")]
      == ["2025-04-30", "2025-08-31", "2025-10-31", "2026-04-30", None])
    cr5 = {r["_bdrq"]: cv(r) for r in capital_rows([
        {"bdrq": "20250630", "plrq": "2025-06-30"}, {"bdrq": "20250930", "plrq": "2025-12-31"},
        {"bdrq": "20251231", "plrq": "2026-03-28"}, {"bdrq": "20250716", "plrq": "2025-07-16"},
        {"bdrq": "20240331", "plrq": "2024-06-30"}])}
    t("V5i（T-R12f 1–3）：plrq=bdrq 季末 / plrq 季末 → max(ntd(plrq), ntd(截止日) 09:30)、pit_basis=[capital_deadline]；"
      "plrq=bdrq 非季末、普通 plrq → plrq、pit_basis=[]",
      {k: (v["visible_from"], v["pit_basis"]) for k, v in cr5.items()} == {
          "2025-06-30": ("2025-09-01", ["capital_deadline"]), "2025-09-30": ("2026-01-01", ["capital_deadline"]),
          "2025-12-31": ("2026-03-29", []), "2025-07-16": ("2025-07-17", []),
          "2024-03-31": ("2024-07-01", ["capital_deadline"])}
      and cr5["2025-06-30"]["visible_at"] == "2025-09-01T09:30+08:00", str(cr5))
    z5 = z_at([{"bdrq": "20250630", "plrq": "2025-06-30", "zgb": 2}, {"bdrq": "20250331", "plrq": "2025-04-20", "zgb": 1}],
                "2025-08-20")
    z6 = z_at([{"bdrq": "20250630", "plrq": "2025-06-30", "zgb": 2}], "2025-09-01")
    t("V5i（M3）：zgb_at 用可见日——H1 回填行 ntd(8-31) 前不可见取上一行，之后可见且带 pit_basis",
      z5 and z5["_bdrq"] == "2025-03-31" and z6 and z6["_pit"]["pit_basis"] == ["capital_deadline"])
    rep = [{"jzrq": "2025-06-30", "plrq": "2025-08-13"}, {"jzrq": "2025-09-30", "plrq": "2025-10-25"},
           {"jzrq": "2025-12-31", "plrq": "2026-03-28"}, {"jzrq": "2025-12-31", "plrq": "2026-04-20"}]
    pos = v5i_backfill([{"bdrq": "20250630", "plrq": "2025-06-30"}, {"bdrq": "20250930", "plrq": "2025-09-30"},
                        {"bdrq": "20251231", "plrq": "2026-03-28"}, {"bdrq": "20250716", "plrq": "2025-07-16"}],
                       rep, "2026-11-01T03:00:00+00:00")
    t("V5i 回填（正例）：季末行早于同期报告最早 plrq → backfilled；diff 分布、first_seen_at 逐行",
      pos["verdict"] == "backfilled" and pos["diff_days"]["lt0"] == 2 and pos["diff_days"]["eq0"] == 1
      and pos["plrq_is_quarter_end"]["n"] == 2 and pos["quarter_end_bdrq_rows"] == 3
      and all(x["first_seen_at"] == "2026-11-01T03:00:00+00:00" for x in pos["rows_detail_tail"]), str(pos["diff_days"]))
    neg = v5i_backfill([{"bdrq": "20250630", "plrq": "2025-08-13"}, {"bdrq": "20250930", "plrq": "2025-10-26"},
                        {"bdrq": "20251231", "plrq": "2026-03-28"}], rep)
    t("V5i 回填（反例）：季末行 plrq 与同期报告首次披露差 0–3 天 → true_disclosure；无报告 → inconclusive",
      neg["verdict"] == "true_disclosure" and neg["diff_days"]["lt0"] == 0
      and v5i_backfill([{"bdrq": "20250630", "plrq": "2025-06-30"}], [])["verdict"] == "inconclusive", neg["why"])
    s4 = share_split_check([{"bdrq": "20250630", "plrq": "2025-06-30", "zgb": 18_210_234_607},
                            {"bdrq": "20250903", "plrq": "2025-09-03", "zgb": 18_107_641_995},
                            {"bdrq": "20260930", "plrq": "2026-09-30", "zgb": 1}], EXPECT["601318_capital"])
    t("V5g：对照巨潮——取 [2025-09-03, 2025-12-31] 内最后一行、带来源；窗口内无行 → no_row_in_window",
      s4["verdict"] == "includes_non_a" and s4["row"]["bdrq"] == "20250903" and "cninfo" in s4["source"]
      and share_split_check([{"bdrq": "20260930", "plrq": "2026-09-30", "zgb": 1}],
                            EXPECT["000550_capital"])["verdict"] == "no_row_in_window")
    capc = [{"bdrq": "20250415", "plrq": "2025-04-20", "zgb": 10}]
    r0 = pb({"t": "2025-10-30", "c": 5.0}, capc, bal)["basis"]
    r1 = pb({"t": "2025-10-30", "c": 5.0}, capc, bal, share_class_list="A+H", lists_configured=True)["basis"]
    r2 = pb({"t": "2025-10-30", "c": 5.0}, capc, bal, lists_configured=True)["basis"]
    t("V5g（T-R12f 4）：名单未接入 → unavailable；接入后所有行 list，名单内另打 non_a_share_capital",
      r0["share_class_check"] == "unavailable" and r1["share_class_check"] == "list"
      and r1["verify_pending"] == ["non_a_share_capital"] and r2["share_class_check"] == "list"
      and r2["verify_pending"] == [] and "pit_basis" not in r0)
    rc = pb({"t": "2025-10-30", "c": 5.0}, capc, bal, is_cdr=True)
    rb = pb({"t": "2025-10-30", "c": 5.0}, capc, bal, is_cdr=True, cdr_unit="zgb≈基础股数", cdr_per_base_share=10)
    rk = pb({"t": "2025-10-30", "c": 5.0}, capc, bal, ["bank_balance"])["basis"]
    t("V5j（T-R12f 5–7 + T-R12g）：CDR → 照常算、verify_pending cdr_unit、无剔除字段；zgb≈基础股数 → mcap × 10；"
      "银行只继承标记",
      rc["value"] == 0.5 and rc["basis"]["verify_pending"] == ["cdr_unit"]
      and not any(k.startswith("exclude") for k in rc["basis"])
      and rb["value"] == 5.0 and rb["basis"]["cdr_per_base_share"] == 10
      and rk["verify_pending"] == ["bank_balance"], str(rc))
    h1 = capital_rows([{"bdrq": "20250630", "plrq": "2025-06-30"}])[0]
    t("V5i（T-R12g）：增量采集的季末行 → max(ntd(plrq), first_seen_at)，不套截止日；首次回填 → 截止日",
      cv(h1, "2025-07-03T01:00:00+00:00")["visible_from"] == "2025-07-03"
      and cv(h1, "2025-07-03T01:00:00+00:00")["pit_basis"] == []
      and cv(h1)["pit_basis"] == ["capital_deadline"])
    pc = industry_pct({"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0, "e": 5.0, "f": None, "g": 1.0},
                      {"a": "X", "b": "X", "c": "X", "d": "X", "e": "X", "f": "X", "g": "Y"})
    t("行业分位：null 不进分母、组内 N<5 → null", pc["a"] == 0.0 and pc["e"] == 1.0 and pc["f"] is None
      and pc["g"] is None, str(pc))
    cu = currency_unit_fields({"balance_x": [{"jzrq": "2025", "bz": "CNY", "zczj": 1.0}],
                               "balance_y": [{"jzrq": "2025", "unit": "万元"}]})
    t("⑨ 币种/单位字段名与字符串值扫描", cu["balance_x"]["key_hits"] == ["bz"] and cu["balance_y"]["string_value_hits"])
    t("⑨ 无币种/单位字段 → 结论写明“只靠数量级不连续检查”",
      "只靠数量级不连续检查" in currency_unit_conclusion(currency_unit_fields({"b": [{"zczj": 1.0}]}))["conclusion"]
      and "unit_mismatch" in currency_unit_conclusion(cu)["conclusion"])
    t("单位不连续告警（≥50 倍）", magnitude_jumps([{"jzrq": "a", "zczj": 1e12}, {"jzrq": "b", "zczj": 1e8}], "zczj")
      [0]["to"] == "b")
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    run_dir = Path(argv[0])
    meta_f = run_dir / SUBDIR / "plan_meta.json"
    if not meta_f.is_file():
        print(f"找不到 {meta_f}（需要 p13_fin_pit 的运行目录）")
        return 2
    calendar_path = Path(argv[argv.index("--calendar") + 1]) if "--calendar" in argv else run_dir / "trading_calendar.json"
    a = analyze(load_raw(run_dir), json.loads(meta_f.read_text(encoding="utf-8")), load_first_seen(run_dir),
                calendar=load_calendar(calendar_path))
    for line in summary_lines(a):
        print(line)
    if "--stdout" not in argv:
        out = run_dir / "p13_analysis.json"
        if out.exists():
            print(f"{out} 已存在，不覆盖")
            return 1
        with open(out, "x", encoding="utf-8") as fh:
            json.dump(a, fh, ensure_ascii=False, indent=1, default=str)
        print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
