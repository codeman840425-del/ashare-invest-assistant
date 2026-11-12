"""深交所「简称变更」→ 按股票 ST/*ST 状态区间转换（T-DATA-ST，策略研究员）。

只读公开 xlsx，纯离线、确定性，不调麦蕊、不读私有样本、不写库、不发网络请求。
输入：深交所简称变更 xlsx（https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=SSGSGMXX&TABKEY=tab2）
输出：按股票的 ST 状态区间（每个区间 [valid_from, valid_to) 带 flag），JSONL + 汇总。

ST 判定沿用 security_master §5.5 的确定性派生规则（本脚本只落地深市历史口径）：
  - 简称以 `*ST` 开头           → flag = `*ST`
  - 否则简称以 `ST` 开头        → flag = `ST`
  - 简称含 "退"                 → flag = `退`（delisting_period 或已终止，须另同终止上市名单判 is_delisted）
  - 其余                        → flag = 无（不属于 ST 状态，区间闭合为该状态的结束）
简称中的前缀判定在 NFKC 归一 + 去空白之后做；"ST" 前缀须紧贴开头（"*ST" 优先于 "ST"）。
区间：按变更日期升序遍历同股变更记录，每次「变更后简称」决定的 flag 从该日起生效，
      直到下一条变更日（左闭右开 [d_start, d_end)）；最后一条持续到无界（end=None）。

用法：
  python st_ranges_sz.py --xlsx <path.xlsx> --out <outdir> [--since 2022-01-01]

依赖：openpyxl（读 xlsx）。研究侧用 `uv run --no-project --with openpyxl==3.1.5 python`。
不把原始 xlsx 入库；只入库本脚本与给定样例输出（脱敏、公开代码）。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from pathlib import Path

# security_master §3.2 前缀校验（A 股普通股，仅告警不影响结果）
_SZ_PREFIX = ("000", "001", "002", "003", "300", "301", "200", "201")


def normalize_name(s: object) -> str:
    """深交所简称规范：NFKC、去首尾/中间空白、全角转半角（星号等）。"""
    t = unicodedata.normalize("NFKC", str(s or ""))
    return re.sub(r"\s+", "", t).strip()


def flag_of(name: str) -> str | None:
    """证券简称 → ST flag；返回 None 表示非 ST 状态。"""
    if name.startswith("*ST"):
        return "*ST"
    if name.startswith("ST"):
        return "ST"
    if "退" in name:
        return "退"
    return None


def build_ranges(rows: list[dict], since: str, delist: dict[str, str] | None = None) -> list[dict]:
    """rows: [{code, name_after, change_date}]，按代码分组、日期升序构建区间。
    delist: {code: 终止上市日期}，用于闭合无后续变更记录的末端区间（退市股）。"""
    by_code: dict[str, list[dict]] = {}
    for r in rows:
        by_code.setdefault(r["code"], []).append(r)
    out: list[dict] = []
    for code, items in sorted(by_code.items()):
        items.sort(key=lambda r: r["change_date"])
        current: dict | None = None
        for it in items:
            flag = flag_of(it["name_after"])
            if current is not None:
                # 闭合上一区间 [current.start, it.change_date)
                current["end"] = it["change_date"]
                out.append(current)
            current = {
                "code": code,
                "flag": flag,
                "start": it["change_date"],
                "end": None,
            }
        if current is not None:
            # 终止上市名单闭合末端（退市股的最后一段往往没有"摘帽/终止"变更记录）
            if delist and code in delist and (current["end"] is None or delist[code] < current["end"]):
                current["end"] = delist[code]
                current["closed_by_delist"] = True
            out.append(current)
    # since 过滤：只保留与 [since, ∞) 相交的区间
    filtered = []
    for r in out:
        if r["end"] is not None and r["end"] < since:
            continue
        filtered.append(r)
    filtered.sort(key=lambda r: (r["code"], r["start"]))
    return filtered


def load_xlsx(path: Path) -> tuple[list[str], list[dict]]:
    from openpyxl import load_workbook  # 延迟 import，脚本可读性优先

    # 该 xlsx 仅数百 KB，用普通模式全量加载（read_only 模式对该文件的共享工作表读不完整）。
    wb = load_workbook(path, data_only=True)
    ws = wb.active
    header = [c.value for c in ws[1]]
    # 列：0 变更日期 1 证券代码 2 证券简称 3 变更前简称 4 变更后简称
    idx = {
        "date": 0,
        "code": 1,
        "after": 4,
    }
    rows = []
    for i in range(2, ws.max_row + 1):
        date_cell = ws.cell(i, 1).value
        code_cell = ws.cell(i, 2).value
        after_cell = ws.cell(i, 5).value
        if date_cell is None or code_cell is None:
            continue
        rows.append(
            {
                "code": str(code_cell).strip(),
                "name_after": normalize_name(after_cell),
                "change_date": str(date_cell)[:10],
            }
        )
    wb.close()
    return header, rows


def load_delist_xlsx(path: Path) -> dict[str, str]:
    """深交所终止上市列表（CATALOGID=1793_ssgs TABKEY=tab2）→ {code: 终止上市日期}。"""
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True)
    ws = wb.active
    out: dict[str, str] = {}
    for i in range(2, ws.max_row + 1):
        code = ws.cell(i, 1).value
        date = ws.cell(i, 4).value
        if code is not None and date is not None:
            out[str(code).strip()] = str(date)[:10]
    wb.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--since", default="2022-01-01")
    ap.add_argument("--delist-xlsx", default=None, help="深交所终止上市列表 xlsx（用于闭合退市股末端区间）")
    ap.add_argument("--csv", action="store_true", help="额外输出 CSV 便于人工核对")
    args = ap.parse_args()

    header, rows = load_xlsx(Path(args.xlsx))
    delist = load_delist_xlsx(Path(args.delist_xlsx)) if args.delist_xlsx else None
    ranges = build_ranges(rows, args.since, delist)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    st_ranges = [r for r in ranges if r["flag"] is not None]
    nonst_ends = [r for r in ranges if r["flag"] is None]

    # JSONL 全量区间（含非 ST 段，用于闭合与覆盖审计）
    with open(outdir / "sz_st_ranges.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for r in ranges:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 汇总
    codes_st = sorted({r["code"] for r in st_ranges})
    summary = {
        "source": "szse_name_change_xlsx",
        "since": args.since,
        "total_change_rows": len(rows),
        "records_with_st": len(st_ranges),       # ST 相关区间段数
        "distinct_stocks_with_st": len(codes_st),
        "stocks": codes_st,
        "non_st_closing_segments": len(nonst_ends),
        "header": header,
    }
    with open(outdir / "sz_st_summary.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    if args.csv:
        with open(outdir / "sz_st_ranges.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["code", "flag", "start", "end"])
            for r in st_ranges:
                w.writerow([r["code"], r["flag"], r["start"], r["end"] or ""])

    print(json.dumps(
        {
            "total_change_rows": len(rows),
            "st_records": len(st_ranges),
            "distinct_stocks_with_st": len(codes_st),
            "since": args.since,
        },
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
