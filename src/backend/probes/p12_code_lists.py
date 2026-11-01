"""第 12 项：麦蕊代码集合完整落盘（security_master.md §7 第 1 条）。

对象：/hslt/list、/bj/list/all、/kc/list/all 的全部字段，以及 /hsrl/ssjy/all、/hsrl/real/all 的完整 dm 集合。
复用：同一次运行中 p11（GAP4）已取的 /hslt/list、p01 已取的两个全市场接口直接复用内存中的完整响应，
     不再重复调用（批量接口文档限 1 次/分钟，重复调用有触发 429 → 熔断的风险）。
     只有本次运行没跑过 p01/p11（如 `run_all.py p12`）时才自己调用，此时共 5 次。
说明：/bj/list/all、/kc/list/all 的路径来自 docs/plan.md，本地文档缓存（/tmp/mrdoc）未收录，未经验证；
     若返回 404/错误，照常记录（原始响应也保存），不重试。

输出（当次运行目录 results/run-<ts>/code_lists/，独占创建、不覆盖）：
  raw_<key>.json         接口原始响应文本（已脱敏；写盘前断言不含证书）
  codes.csv              规范化清单：endpoint,dm_raw,code6,mc,jys,suffix（全部端点、全部行）
  mairui_dm_<key>.txt    每行一个 6 位 dm（去重、排序），可直接喂给 /tmp/t7/compare_mairui_codes.py
  mairui_dm_lists.txt    三个列表接口（hslt/list ∪ bj ∪ kc）的并集
  mairui_dm_union_all.txt  五个接口的并集
结构化结论写入 results/run-<ts>/p12_code_lists.json（含 URL(脱敏)、fetched_at(UTC)、行数、sha256、字段、文件名）。
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime, timezone

import common as c

SUBDIR = "code_lists"
# (key, 名称, 路径模板, 是否批量接口, 可复用的上游探针)
ENDPOINTS = [
    ("hslt_list", "股票列表", "/hslt/list/{licence}", False, "p11_gaps(GAP4)"),
    ("bj_list_all", "京市股票列表", "/bj/list/all/{licence}", False, None),
    ("kc_list_all", "科创板列表", "/kc/list/all/{licence}", False, None),
    ("hsrl_ssjy_all", "全市场实时（券商源）", "/hsrl/ssjy/all/{licence}", True, "p01_realtime"),
    ("hsrl_real_all", "全市场实时（网络源）", "/hsrl/real/all/{licence}", True, "p01_realtime"),
]
LIST_KEYS = ("hslt_list", "bj_list_all", "kc_list_all")
CSV_FIELDS = ["endpoint", "dm_raw", "code6", "mc", "jys", "suffix"]
_CODE_RE = re.compile(r"^(?:(sh|sz|bj)\.?)?(\d{6})(?:\.(sh|sz|bj))?$", re.I)


def norm_code(dm) -> tuple:
    """dm → (6 位代码 or None, 交易所后缀 or '')。支持 000001 / 000001.SZ / sz000001 / 整数 1。"""
    if dm is None or isinstance(dm, bool):
        return None, ""
    if isinstance(dm, int):
        dm = str(dm).zfill(6) if 0 <= dm <= 999999 else str(dm)
    s = str(dm).strip()
    m = _CODE_RE.match(s)
    if not m:
        return None, ""
    return m.group(2), (m.group(1) or m.group(3) or "").upper()


def _row_dm(r: dict):
    for k in ("dm", "code", "zqdm", "symbol"):
        if k in r:
            return r.get(k)
    return None


def extract(data) -> list:
    """响应 → [{dm_raw, code6, mc, jys, suffix}]（保持接口原始顺序，含无法规范化的行）。"""
    out = []
    for r in c.rows(data):
        if not isinstance(r, dict):
            continue
        dm = _row_dm(r)
        code6, suf = norm_code(dm)
        out.append({"dm_raw": "" if dm is None else str(dm), "code6": code6 or "",
                    "mc": str(r.get("mc", r.get("name", "")) or ""), "jys": str(r.get("jys", "") or ""),
                    "suffix": suf})
    return out


def dm_text(codes) -> str:
    return "".join(f"{x}\n" for x in sorted(codes))


def _get(key, tpl, src):
    """优先复用本次运行已取得的完整响应；否则调用 1 次（不重试）。返回 (Resp, 来源, 取得时刻 UTC)。"""
    kept = c.reuse(key)
    if kept is not None:
        return kept[0], f"reused:{src}", kept[1]
    r = c.call(f"code_list_{key}", tpl)
    return r, "called", datetime.now(timezone.utc).isoformat(timespec="seconds")


def main(res):
    csv_buf = io.StringIO()
    w = csv.DictWriter(csv_buf, fieldnames=CSV_FIELDS, lineterminator="\n")
    w.writeheader()
    sets, items = {}, []
    for key, title, tpl, bulk, src in ENDPOINTS:
        r, how, fetched_utc = _get(key, tpl, src)
        rows = extract(r.data) if r.ok else []
        raw_path = c.write_raw(f"{SUBDIR}/raw_{key}.json", r.text or "")
        codes = {x["code6"] for x in rows if x["code6"]}
        bad = [x["dm_raw"] for x in rows if not x["code6"]]
        dup = len([x for x in rows if x["code6"]]) - len(codes)
        for x in rows:
            w.writerow({"endpoint": key, **x})
        txt = c.write_raw(f"{SUBDIR}/mairui_dm_{key}.txt", dm_text(codes)) if codes else None
        sets[key] = codes
        items.append({
            "name": f"CODES_{key}", "title": title, "source": how, "url": r.url_redacted, "status": r.status,
            "ok": r.ok, "fetched_at_utc": fetched_utc, "ms": r.ms, "bytes": r.nbytes,
            "sha256": hashlib.sha256((r.text or "").encode("utf-8")).hexdigest(),
            "rows": len(rows), "codes_6digit": len(codes), "duplicate_rows": dup,
            "non_6digit_dm": len(bad), "non_6digit_examples": bad[:10],
            "fields": c.fields_of(r.data) if r.ok else [],
            "jys_counts": _count(x["jys"] or "(空)" for x in rows),
            "prefix3_counts": _count(x["code6"][:3] for x in rows if x["code6"]),
            "error": None if r.ok else (r.text[:300] or r.error),
            "raw_file": _rel(raw_path), "dm_file": _rel(txt) if txt else None})
    csv_path = c.write_raw(f"{SUBDIR}/codes.csv", csv_buf.getvalue())
    lists = set().union(*(sets.get(k, set()) for k in LIST_KEYS))
    union = set().union(*sets.values())
    lp = c.write_raw(f"{SUBDIR}/mairui_dm_lists.txt", dm_text(lists)) if lists else None
    up = c.write_raw(f"{SUBDIR}/mairui_dm_union_all.txt", dm_text(union)) if union else None
    res.extend(items)
    res.append({"name": "CODES_SUMMARY", "csv_file": _rel(csv_path),
                "lists_union_file": _rel(lp) if lp else None, "lists_union_n": len(lists),
                "all_union_file": _rel(up) if up else None, "all_union_n": len(union),
                "calls_made": sum(1 for x in items if x["source"] == "called"),
                "reused": [x["name"] for x in items if x["source"].startswith("reused")],
                "compare_hint": "python3 /tmp/t7/compare_mairui_codes.py <run_dir>/" + SUBDIR + "/mairui_dm_lists.txt",
                "limits": ["/bj/list/all、/kc/list/all 路径来自 plan.md，本地文档缓存未收录",
                           "复用的响应取自本次运行较早时刻（p01/p11），与列表接口不是同一时刻的快照"]})


def _count(it) -> dict:
    d: dict = {}
    for k in it:
        d[k] = d.get(k, 0) + 1
    return dict(sorted(d.items(), key=lambda kv: -kv[1])[:30])


def _rel(p):
    try:
        return str(p.relative_to(c.ctx().run_dir)).replace("\\", "/")
    except ValueError:
        return str(p)


def selftest_pure() -> list:
    cases = [("000001", ("000001", "")), ("000001.SZ", ("000001", "SZ")), ("sh600519", ("600519", "SH")),
             (1, ("000001", "")), ("920000.BJ", ("920000", "BJ")), ("101076.BKZS", (None, "")), ("", (None, "")),
             (None, (None, ""))]
    bad = [(i, norm_code(i), e) for i, e in cases if norm_code(i) != e]
    return [("代码规范化 norm_code", not bad, f"{len(cases)} 例" + (f" 失败 {bad}" if bad else ""))]


if __name__ == "__main__":
    import sys
    import run_all
    sys.exit(run_all.cli(["p12_code_lists", *sys.argv[1:]]))
