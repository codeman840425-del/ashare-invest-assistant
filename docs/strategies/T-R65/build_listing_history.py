"""T-R65 ②-b：沪深上市状态历史 → runner 输入（loaded by data.load_status_history kind="listing"）。

口径：
- 覆盖起点 = max(2022-01-01, 上市日)；上市日缺失时用 HF metadata 的 listing_date。
- 退市整理期起点：深市优先用简称变更里首次出现「退」的日期；沪市（及深市缺失者）用巨潮「进入退市整理期」首次公告日期。
  两者都有时交叉核对并统计日差。
- 整理期起点缺失的退市股：listed 段在终止日前 30 个自然日截止，剩余区间不覆盖（runner 记 listing_status_unknown 剔除并计数）。
- 终止日后 open-ended 记 `delisted`（不伪造「unknown」；runner 侧该区间之后无 K 线，会走停牌分支，manifest 披露）。
- 非退市股：`listed` 从覆盖起点 open-ended。
- 区间严格半开 [valid_from, valid_to)，与库内表同口径。

用法：
  uv run --no-project python docs/strategies/T-R65/build_listing_history.py \
      --hf-manifest data/hf-1min/2022plus/manifest_files.csv \
      --securities-csv F:/t-r65-data/db/securities_shsz.csv \
      --name-history-csv F:/t-r65-data/db/name_history.csv \
      --coverage-csv data/hf-1min/raw/metadata/coverage_by_instrument.csv \
      --delisting-period-csv data/retest-inputs/delisting_period.csv \
      --out-dir data/retest-inputs
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))
WINDOW_START = date(2022, 1, 1)
FALLBACK_GAP_DAYS = 30


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hf-manifest", required=True)
    ap.add_argument("--securities-csv", required=True)
    ap.add_argument("--name-history-csv", required=True)
    ap.add_argument("--coverage-csv", required=True)
    ap.add_argument("--vipdoc-sh", default=None)
    ap.add_argument("--vipdoc-sz", default=None)
    ap.add_argument("--delisting-period-csv", default=None)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    pool = [
        (r["exchange"], r["symbol"])
        for r in read_csv(Path(args.hf_manifest))
        if r.get("is_bj") == "False"
    ]
    prefixes = {
        "SH": ("600", "601", "603", "605", "688", "689"),
        "SZ": ("000", "001", "002", "003", "300", "301", "302"),
    }
    for directory, exchange in ((args.vipdoc_sh, "SH"), (args.vipdoc_sz, "SZ")):
        if not directory:
            continue
        for path in Path(directory).glob(f"{exchange.lower()}*.lc1"):
            code = path.stem[2:]
            if len(code) == 6 and code.isdigit() and code.startswith(prefixes[exchange]):
                pool.append((exchange, code))
    pool = sorted(set(pool))
    securities = {}
    for r in read_csv(Path(args.securities_csv)):
        sym, exch = r["code"].split(".")
        securities[(exch, sym)] = r
    coverage = {(r["exchange"], r["symbol"]): r for r in read_csv(Path(args.coverage_csv))}
    delist_start: dict[tuple[str, str], date] = {}
    if args.delisting_period_csv:
        for r in read_csv(Path(args.delisting_period_csv)):
            delist_start[(r["exchange"], r["symbol"])] = date.fromisoformat(r["start_date"])
    tui_start: dict[tuple[str, str], date] = {}
    for r in read_csv(Path(args.name_history_csv)):
        sym, exch = r["code"].split(".")
        if exch != "SZ" or "退" not in r["name"]:
            continue
        key = ("SZ", sym)
        day = date.fromisoformat(r["valid_from"])
        if key not in tui_start or day < tui_start[key]:
            tui_start[key] = day

    rows: list[dict] = []
    stats = {
        "stocks": len(pool),
        "listed_open": 0,
        "delisted_with_period": 0,
        "delisted_fallback_unknown": 0,
        "list_date_missing": [],
        "period_source": defaultdict(int),
        "period_checks": [],
        "fallback_stocks": [],
        "post_delist_rows": 0,
        "pre_list_uncovered": 0,
    }
    for exch, sym in sorted(pool):
        key = (exch, sym)
        sec = securities.get(key) or {}
        cov = coverage.get(key) or {}
        list_day = sec.get("list_date") or cov.get("listing_date") or ""
        if not list_day:
            stats["list_date_missing"].append([exch, sym])
            continue
        list_day = date.fromisoformat(list_day)
        delist_day = date.fromisoformat(sec["delist_date"]) if sec.get("delist_date") else None
        start = max(WINDOW_START, list_day)
        if start > WINDOW_START:
            stats["pre_list_uncovered"] += 1
        if delist_day is None or delist_day <= WINDOW_START:
            rows.append({"exchange": exch, "symbol": sym, "valid_from": start.isoformat(), "valid_to": "", "status": "listed"})
            stats["listed_open"] += 1
            continue
        tui = tui_start.get(key)
        ann = delist_start.get(key)
        if tui and ann:
            stats["period_source"]["sz_name_history(checked vs cninfo)"] += 1
            stats["period_checks"].append([exch, sym, tui.isoformat(), ann.isoformat(), (tui - ann).days])
        elif tui:
            stats["period_source"]["sz_name_history"] += 1
        elif ann:
            stats["period_source"]["cninfo_announcement"] += 1
        period = tui or ann
        if period and period > list_day:
            if period < start:
                period = start
            if period < delist_day:
                rows.append({"exchange": exch, "symbol": sym, "valid_from": start.isoformat(), "valid_to": period.isoformat(), "status": "listed"})
                rows.append({"exchange": exch, "symbol": sym, "valid_from": period.isoformat(), "valid_to": delist_day.isoformat(), "status": "delisting_period"})
                rows.append({"exchange": exch, "symbol": sym, "valid_from": delist_day.isoformat(), "valid_to": "", "status": "delisted"})
                stats["delisted_with_period"] += 1
                stats["post_delist_rows"] += 1
                continue
        # 整理期起点缺失：保守截断 listed 段，尾部不覆盖（unknown 剔除并计数）
        cut = delist_day - timedelta(days=FALLBACK_GAP_DAYS)
        if cut > start:
            rows.append({"exchange": exch, "symbol": sym, "valid_from": start.isoformat(), "valid_to": cut.isoformat(), "status": "listed"})
        stats["delisted_fallback_unknown"] += 1
        stats["fallback_stocks"].append([exch, sym, delist_day.isoformat()])
        stats["period_source"]["fallback_unknown"] += 1

    path = out / "listing_history.csv"
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.DictWriter(fh, fieldnames=["exchange", "symbol", "valid_from", "valid_to", "status"])
        w.writeheader()
        w.writerows(rows)

    # 诊断：P9 所需整理期覆盖（官方终止名单窗口内）
    official = [
        (exch, sym, date.fromisoformat(sec["delist_date"]))
        for (exch, sym), sec in securities.items()
        if sec.get("listing_status") == "delisted" and sec.get("delist_date")
        and WINDOW_START <= date.fromisoformat(sec["delist_date"]) <= date(2026, 8, 7)
    ]
    by_key = defaultdict(list)
    for r in rows:
        if r["status"] == "delisting_period":
            by_key[(r["exchange"], r["symbol"])].append(date.fromisoformat(r["valid_from"]))
    p9_missing = [f"{e}:{s}" for e, s, d in official if not any(x <= d for x in by_key.get((e, s), []))]

    manifest = {
        "product": "listing_history",
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "window": {"start": WINDOW_START.isoformat(), "end": None},
        "format": "csv exchange,symbol,valid_from,valid_to,status (runner data.load_status_history kind=listing)",
        "statuses": ["listed", "delisting_period", "delisted"],
        "inputs": {
            "securities_csv": {"sha256": sha256(Path(args.securities_csv)), "name": Path(args.securities_csv).name},
            "name_history_csv": {"sha256": sha256(Path(args.name_history_csv)), "name": Path(args.name_history_csv).name},
            "coverage_csv": {"sha256": sha256(Path(args.coverage_csv)), "name": Path(args.coverage_csv).name},
            "delisting_period_csv": (
                {"sha256": sha256(Path(args.delisting_period_csv)), "name": Path(args.delisting_period_csv).name}
                if args.delisting_period_csv
                else None
            ),
        },
        "stats": {
            "stocks": stats["stocks"],
            "listed_open_ended": stats["listed_open"],
            "delisted_with_period": stats["delisted_with_period"],
            "delisted_fallback_unknown": stats["delisted_fallback_unknown"],
            "period_source": dict(stats["period_source"]),
            "list_date_missing": stats["list_date_missing"],
            "pre_list_uncovered_stocks": stats["pre_list_uncovered"],
            "fallback_stocks": stats["fallback_stocks"],
            "period_checks_count": len(stats["period_checks"]),
            "period_check_days": sorted({x[4] for x in stats["period_checks"]}),
            "period_check_mismatch": [x for x in stats["period_checks"] if x[4] != 0][:20],
            "p9_official_in_window": len(official),
            "p9_period_missing": p9_missing,
        },
        "output": {"file": path.name, "sha256": sha256(path), "rows": len(rows)},
    }
    (out / "listing_history_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps({k: manifest["stats"][k] for k in ("stocks", "listed_open_ended", "delisted_with_period", "delisted_fallback_unknown", "period_source", "p9_official_in_window")}, ensure_ascii=False, default=str))
    print("p9 period missing:", len(p9_missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
