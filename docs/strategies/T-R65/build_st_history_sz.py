"""T-R65 ①：深市 ST/*ST 历史 → T-B136 runner 输入（`load_status_history` 接口）。

来源：深交所「上市公司简称变更」公开 xlsx（SSGSGMXX，全历史，覆盖 1994-01-03 至 2026-11-10）
      + HF manifest（深市 A 股池）+ 本地 vipdoc `sz/minline/*.lc1` 文件名（补 vipdoc-only 代码）。
      **不与 `security_risk_flag_history` 混写**：本产物只来自深交所公开简称变更，独立 sha256 + manifest。

口径（与 `src/backend/retest/t_r58/data.py::load_status_history` 对齐）：
  - CSV 列：`exchange,symbol,valid_from,valid_to,is_st`；`is_st ∈ {true,false}`；`valid_to` 空 = 开区间。
  - 每只股票的区间从 `WINDOW_START` 起**连续**覆盖（无缝、无重叠），末段到开区间。
  - 首条变更记录：`变更前简称` 的 ST 状态决定 `[WINDOW_START, 首变日)`；`变更后简称` 决定 `[变更日, 下一变更日)`。
  - 无变更记录 → 全程 `is_st=false`（简称从未变化 ⇒ 窗口内不可能有 ST/*ST 段）。
  - `is_st=true` 仅当简称以 `*ST` / `ST` 开头（NFKC 归一、去空白）；「退」**不算** is_st（退市整理期由
    listing-status 输入处理，本文件不混写）。

用法：
  uv run --no-project --with openpyxl==3.1.5 python docs/strategies/T-R65/build_st_history_sz.py \
      --xlsx F:/tdata-st-research/szse_name_change_20261110.xlsx \
      --hf-manifest F:/ashare-invest-assistant/data/hf-1min/2022plus/manifest_files.csv \
      --vipdoc-dir "D:/西部证券/vipdoc/sz/minline" \
      --out-dir F:/ashare-invest-assistant/data/retest-inputs
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path

WINDOW_START = "2022-01-01"
SZ_A_PREFIX = ("000", "001", "002", "003", "300", "301", "302")
SOURCE = {
    "name": "szse_ssgsgmxx_name_change_xlsx",
    "url": "https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=SSGSGMXX&TABKEY=tab2",
    "note": "深交所「上市公司简称变更」公开导出；全历史 1994-01-03 起",
}
CST = timezone(timedelta(hours=8))


def norm(s: object) -> str:
    t = unicodedata.normalize("NFKC", str(s or ""))
    return re.sub(r"\s+", "", t).strip()


def is_st_name(name: str) -> bool:
    return name.startswith("*ST") or name.startswith("ST")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_changes(xlsx: Path) -> dict[str, list[dict]]:
    from openpyxl import load_workbook

    wb = load_workbook(xlsx, data_only=True)
    ws = wb.active
    if [c.value for c in ws[1]][:5] != ["变更日期", "证券代码", "证券简称", "变更前简称", "变更后简称"]:
        raise SystemExit("unexpected xlsx header")
    by_code: dict[str, list[dict]] = {}
    for i in range(2, ws.max_row + 1):
        d = ws.cell(i, 1).value
        code = ws.cell(i, 2).value
        if d is None or code is None:
            continue
        code = str(code).strip()
        by_code.setdefault(code, []).append(
            {
                "date": str(d)[:10],
                "current": norm(ws.cell(i, 3).value),
                "before": norm(ws.cell(i, 4).value),
                "after": norm(ws.cell(i, 5).value),
            }
        )
    wb.close()
    for items in by_code.values():
        items.sort(key=lambda r: r["date"])
    return by_code


def pool_codes(hf_manifest: Path, vipdoc_dir: Path | None) -> set[str]:
    codes: set[str] = set()
    with hf_manifest.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row.get("is_bj") == "True":
                continue
            sym = row["symbol"].strip()
            if row["exchange"] == "SZ" and sym[:3] in SZ_A_PREFIX:
                codes.add(sym)
    if vipdoc_dir is not None and vipdoc_dir.exists():
        for p in vipdoc_dir.glob("sz*.lc1"):
            sym = p.stem[2:]
            if len(sym) == 6 and sym[:3] in SZ_A_PREFIX:
                codes.add(sym)
    return codes


def build_intervals(code: str, changes: list[dict] | None) -> list[dict]:
    """返回连续区间 [{valid_from, valid_to|None, is_st}]，从 WINDOW_START 到开区间。

    xlsx 是全历史（1994 起），窗口起点之前的状态由「最后一条 ≤ 起点的变更」决定；
    起点之后每条变更开新段。"""
    if not changes:
        return [{"valid_from": WINDOW_START, "valid_to": None, "is_st": False}]
    pre = [c for c in changes if c["date"] < WINDOW_START]
    post = [c for c in changes if c["date"] >= WINDOW_START]
    if pre:
        base_name = pre[-1]["after"] or pre[-1]["current"]
    else:
        base_name = post[0]["before"]
    out: list[dict] = [{
        "valid_from": WINDOW_START,
        "valid_to": post[0]["date"] if post else None,
        "is_st": is_st_name(base_name),
    }]
    for idx, ch in enumerate(post):
        nxt = post[idx + 1]["date"] if idx + 1 < len(post) else None
        name = ch["after"] or ch["current"]
        out.append({"valid_from": ch["date"], "valid_to": nxt, "is_st": is_st_name(name)})
    # 去掉零长度段（变更日恰在窗口起点）：以新状态为准
    merged: list[dict] = []
    for seg in out:
        if seg["valid_to"] is not None and seg["valid_to"] <= seg["valid_from"]:
            if merged:
                merged[-1] = dict(seg, valid_from=merged[-1]["valid_from"])
            continue
        if merged and merged[-1]["valid_to"] == seg["valid_from"] and merged[-1]["is_st"] == seg["is_st"]:
            merged[-1]["valid_to"] = seg["valid_to"]
            continue
        merged.append(dict(seg))
    # 连续性校验：首段从窗口起点、段间无缝、末段开区间
    if merged[0]["valid_from"] != WINDOW_START:
        raise SystemExit(f"{code}: first interval does not start at {WINDOW_START}")
    for a, b in zip(merged, merged[1:]):
        if a["valid_to"] != b["valid_from"]:
            raise SystemExit(f"{code}: interval gap/overlap {a} -> {b}")
    if merged[-1]["valid_to"] is not None:
        raise SystemExit(f"{code}: last interval is not open-ended")
    return merged


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--hf-manifest", required=True)
    ap.add_argument("--vipdoc-dir", default=None)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    xlsx = Path(args.xlsx)
    changes = load_changes(xlsx)
    codes = pool_codes(Path(args.hf_manifest), Path(args.vipdoc_dir) if args.vipdoc_dir else None)
    if not codes:
        raise SystemExit("empty stock pool")

    intervals: dict[str, list[dict]] = {}
    for code in sorted(codes):
        intervals[code] = build_intervals(code, changes.get(code))

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "st_history_sz.csv"
    rows = 0
    st_true = 0
    stocks_with_st = 0
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["exchange", "symbol", "valid_from", "valid_to", "is_st"])
        for code, segs in intervals.items():
            has = any(s["is_st"] for s in segs)
            stocks_with_st += int(has)
            for s in segs:
                w.writerow(["SZ", code, s["valid_from"], s["valid_to"] or "", "true" if s["is_st"] else "false"])
                rows += 1
                st_true += int(s["is_st"])

    manifest = {
        "product": "st_history_sz",
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "source": {
            **SOURCE,
            "xlsx_path_name": xlsx.name,
            "xlsx_bytes": xlsx.stat().st_size,
            "xlsx_sha256": sha256(xlsx),
        },
        "window": {"start": WINDOW_START, "end": None},
        "format": "csv exchange,symbol,valid_from,valid_to,is_st (runner data.load_status_history)",
        "not_mixed_with": ["security_risk_flag_history"],
        "rule": {
            "is_st_true": "简称以 *ST / ST 开头（NFKC 归一、去空白）",
            "tui": "简称含「退」不计入 is_st；退市整理期由 listing-status 输入处理",
            "no_change_records": "全程 is_st=false（简称从未变化）",
            "continuity": "每只股票从 WINDOW_START 连续覆盖到开区间",
        },
        "pool": {
            "stocks": len(intervals),
            "source_pool": "HF manifest 深市 A 股 + vipdoc sz/minline 文件名",
            "prefixes": list(SZ_A_PREFIX),
        },
        "coverage": {
            "stocks_expected": len(codes),
            "stocks_covered": len(intervals),
            "stocks_with_st": stocks_with_st,
            "st_true_intervals": st_true,
            "continuous_from_window_start": True,
        },
        "rows": rows,
        "output": {"file": csv_path.name, "bytes": csv_path.stat().st_size, "sha256": sha256(csv_path)},
    }
    manifest_path = out / "st_history_sz_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps({"rows": rows, "stocks": len(intervals), "stocks_with_st": stocks_with_st,
                      "st_true_intervals": st_true, "csv_sha256": manifest["output"]["sha256"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
