"""T-R65 ②/③ 自检：三项状态输入（st_history / listing_history / termination_list）结构 + P9 就绪度。

只读 data/ 下的产物；复用 runner 的 load_status_history 契约；不写库、不联网。

用法：
  python docs/strategies/T-R65/check_status_inputs.py \
      --st data/retest-inputs/st_history.csv \
      --listing data/retest-inputs/listing_history.csv \
      --delisting data/retest-inputs/termination_list.csv \
      --hf-manifest data/hf-1min/2022plus/manifest_files.csv \
      --coverage-csv data/hf-1min/raw/metadata/coverage_by_instrument.csv \
      --securities-csv F:/t-r65-data/db/securities_shsz.csv \
      --calendar data/hf-1min/raw/metadata/market_calendar.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src" / "backend"))
from retest.t_r58 import data  # noqa: E402

WINDOW_START = date(2022, 1, 1)


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--st", required=True)
    ap.add_argument("--listing", required=True)
    ap.add_argument("--delisting", required=True)
    ap.add_argument("--hf-manifest", required=True)
    ap.add_argument("--coverage-csv", required=True)
    ap.add_argument("--securities-csv", required=True)
    ap.add_argument("--calendar", required=True)
    args = ap.parse_args()
    failures: list[str] = []
    report: dict = {}

    pool = [
        (r["exchange"], r["symbol"])
        for r in read_csv(Path(args.hf_manifest))
        if r.get("is_bj") == "False"
    ]
    pool_set = set(pool)
    securities = {}
    for r in read_csv(Path(args.securities_csv)):
        sym, exch = r["code"].split(".")
        securities[(exch, sym)] = r
    coverage = {(r["exchange"], r["symbol"]): r for r in read_csv(Path(args.coverage_csv))}
    trading = [
        date.fromisoformat(r["date"])
        for r in read_csv(Path(args.calendar))
        if r["is_trading_day"].lower() == "true"
    ]
    days = [d for d in trading if d >= WINDOW_START]

    # 1) ST 历史
    st, st_summary = data.load_status_history(Path(args.st), "st")
    report["st"] = dict(st_summary or {})
    st_codes = {symbol for (_, symbol) in st}
    if set(pool_set) - set(st.keys()):
        missing = sorted(f"{e}:{s}" for e, s in set(pool_set) - set(st.keys()))
        failures.append(f"ST 历史缺 {len(missing)} 只池内股票: {missing[:5]}")
    gaps = []
    for key, intervals in st.items():
        last = intervals[-1]
        if last[1] is not None:
            failures.append(f"ST 历史未开区间收尾: {key}")
        if intervals[0][0] > WINDOW_START:
            gaps.append([*key, intervals[0][0].isoformat(), "late_start"])
        for a, b in zip(intervals, intervals[1:]):
            if a[1] != b[0]:
                gaps.append([*key, a[1].isoformat() if a[1] else None, b[0].isoformat()])
    report["st_gaps"] = len(gaps)
    if gaps:
        failures.append(f"ST 历史区间不连续 {len(gaps)} 处，例: {gaps[:3]}")
    st_true_days = Counter()
    for key, intervals in st.items():
        for start, end, value in intervals:
            if value:
                st_true_days[key[0]] += sum(1 for d in days if start <= d and (end is None or d < end))
    report["st_true_stock_days_by_exchange"] = dict(st_true_days)
    report["st_with_st_stocks"] = sum(1 for key, iv in st.items() if any(v for _, _, v in iv))

    # 2) 上市状态历史
    listing, listing_summary = data.load_status_history(Path(args.listing), "listing")
    report["listing"] = dict(listing_summary or {})
    fallback = set()
    listing_manifest = Path(args.listing).with_name("listing_history_manifest.json")
    if listing_manifest.exists():
        meta = json.loads(listing_manifest.read_text(encoding="utf-8"))
        fallback = {(x[0], x[1]) for x in meta.get("stats", {}).get("fallback_stocks", [])}
    missing_listing = set(pool_set) - set(listing.keys())
    unexplained = missing_listing - fallback
    report["listing_missing"] = {
        "total": len(missing_listing),
        "fallback_unknown": sorted(f"{e}:{s}" for e, s in missing_listing & fallback),
        "unexplained": sorted(f"{e}:{s}" for e, s in unexplained),
    }
    if unexplained:
        failures.append(f"上市状态缺 {len(unexplained)} 只池内股票（非 fallback 披露）: {sorted(unexplained)[:5]}")
    bad_status = [
        [*key, value]
        for key, intervals in listing.items()
        for _, _, value in intervals
        if value not in ("listed", "delisting_period", "delisted")
    ]
    if bad_status:
        failures.append(f"非法上市状态 {bad_status[:3]}")
    period_starts = defaultdict(list)
    status_counts = Counter()
    for key, intervals in listing.items():
        for start, end, value in intervals:
            status_counts[value] += 1
            if value == "delisting_period":
                period_starts[key].append(start)
    report["listing_status_rows"] = status_counts

    # 3) 终止名单
    termination = {}
    duplicates = set()
    for r in read_csv(Path(args.delisting)):
        key = (r["exchange"], r["symbol"])
        if key in termination:
            duplicates.add(key)
        termination[key] = date.fromisoformat(r["delisting_date"])
    if duplicates:
        failures.append(f"终止名单重复 {sorted(duplicates)[:5]}")
    official = {k: v for k, v in termination.items() if WINDOW_START <= v <= date(2026, 8, 7)}
    not_in_pool = sorted(f"{e}:{s}" for e, s in official.keys() - pool_set)
    if not_in_pool:
        failures.append(f"终止名单有 {len(not_in_pool)} 只不在池内（P9 missing 会 fail）: {not_in_pool[:5]}")
    period_unknown = sorted(f"{e}:{s}" for e, s in official if not any(x <= official[(e, s)] for x in period_starts.get((e, s), [])))
    period_ready = len(official) - len(period_unknown)
    report["termination"] = {
        "rows": len(termination),
        "by_exchange": dict(Counter(e for e, _ in termination)),
        "official_in_window": len(official),
        "period_ready": period_ready,
        "period_unknown": period_unknown[:20],
    }
    # 4) 整理期起点之后是否还有 K 线（P9 truncated 检查）
    truncated = []
    for key in official:
        starts = period_starts.get(key)
        if not starts:
            continue
        last = coverage.get(key, {}).get("last_timestamp", "")
        if not last:
            continue
        last_day = date.fromisoformat(last[:10])
        if last_day < min(starts):
            truncated.append(f"{key[0]}:{key[1]}")
    if truncated:
        failures.append(f"整理期起点晚于最后一根 K 线（P9 truncated fail）{len(truncated)}: {truncated[:5]}")
    report["p9"] = {
        "state": "pass" if not (set(official) - pool_set or period_unknown or truncated) else "unknown/fail",
        "missing": len(official.keys() - pool_set),
        "period_unknown": len(period_unknown),
        "truncated": len(truncated),
    }

    report["failures"] = failures
    report["ok"] = not failures
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
