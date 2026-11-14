"""T-R65 ②-a：沪市 ST 历史（巨潮公告事件 + 交易日校正）→ runner 输入。

口径（与 README 一致）：
- 事件分类只看公告标题：只撤销 → false；撤销但继续实施/新实施另一类 → 仍 true；只实施 → true；
  申请/可能/进展/继续/叠加/风险提示 → 不构成切换。
- 生效日 = 公告日后的第一个交易日（深市简称变更实测：公告日在生效日前 1/3/6 个自然日，对应周末与长假）。
- 保守外扩 pad 个交易日：置 true 时提前 pad 天开始，置 false 时延后 pad 天结束（宁多剔除，不漏剔除）。
- 窗口起点状态：用 2021 年同一套关键词公告推出；无任何公告 → false（并披露该假设）。
- 每只股票从窗口起点连续覆盖到开区间（open-ended），供 data.load_status_history 直接读取。

用法：
  uv run --no-project python docs/strategies/T-R65/build_st_history_sh.py \
      --events F:/t-r65-data/cninfo_v2/events.jsonl --events-2021 F:/t-r65-data/cninfo_2021/events.jsonl \
      --hf-manifest data/hf-1min/2022plus/manifest_files.csv \
      --calendar data/hf-1min/raw/metadata/market_calendar.csv \
      --sz-csv data/retest-inputs/st_history_sz.csv \
      --out-dir data/retest-inputs
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import html
import json
import re
from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))
SH_PREFIXES = ("600", "601", "603", "605", "688", "689")
SZ_PREFIXES = ("000", "001", "002", "003", "300", "301", "302")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean(title: str) -> str:
    t = re.sub(r"</?em>", "", title or "")
    return re.sub(r"\s+", "", html.unescape(t))


HYPOTHETICAL = re.compile(r"可能(被)?(叠加)?(实施|实行)(退市|其他)?风险警示")
CLAUSE_SPLIT = re.compile(r"[暨及并、，。；]")


def classify(title: str) -> tuple[str | None, bool]:
    """返回 (切换, 断言仍处于风险警示)。

    - 切换 "true"/"false"：公告生效后 ST/*ST 任一为真/假；
    - 断言 True：标题表明公告日仍处于风险警示状态（继续实施、叠加、进展、申请撤销中），但不构成切换；
    - (None, False)：与状态无关（可能被实施、终止上市等）。
    先剔除「可能被实施…」预测，再按 暨/及/并/、/，/。 分句判断，避免「撤销…实施退市风险警示」把被撤销对象当成新实施。
    """
    core = HYPOTHETICAL.sub("", clean(title))
    assertions = False
    impl = False
    revoke = False
    verb: str | None = None
    for clause in CLAUSE_SPLIT.split(core):
        if not clause:
            continue
        has_flags = "风险警示" in clause
        if not has_flags:
            # 没有「风险警示」字样的从句与状态无关（如「重大资产重组实施进展」）
            continue
        has_revoke = "撤销" in clause
        has_impl = "实施" in clause or "实行" in clause
        has_continue = "继续" in clause and has_impl
        has_progress = any(x in clause for x in ("进展", "措施", "情况"))
        has_apply = "申请" in clause
        if has_progress:
            assertions = True
        elif has_continue:
            # 继续实施某类风险警示 → 该 flag 仍生效
            impl = True
            assertions = True
            verb = "impl"
        elif has_apply and (has_revoke or has_impl):
            # 申请撤销/申请实施 期间仍处于风险警示
            assertions = True
        elif has_revoke:
            revoke = True
            verb = "revoke"
            # 同句「撤销…实施退市风险警示」中的实施是被撤销对象，不另算新实施
        elif has_impl:
            impl = True
            assertions = True
            verb = "impl"
        elif verb == "revoke":
            revoke = True
        elif verb == "impl":
            impl = True
            assertions = True
    if impl and revoke:
        return "true", True
    if impl:
        return "true", True
    if revoke:
        return "false", False
    if assertions:
        return None, True
    return None, False


def ms_date(ms: int) -> date:
    return datetime.fromtimestamp(ms / 1000, tz=CST).date()


def load_trading_days(path: Path) -> list[date]:
    days = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["is_trading_day"].lower() == "true":
                days.append(date.fromisoformat(r["date"]))
    days.sort()
    return days


def shift(days: list[date], day: date, n: int) -> date:
    i = bisect.bisect_left(days, day)
    j = min(max(i + n, 0), len(days) - 1)
    return days[j]


def read_events(
    paths: list[Path],
    prefixes: tuple[str, ...],
    keep: set[str] | None = None,
    per_stock_paths: list[Path] | None = None,
) -> dict[str, list[tuple[date, str | None, bool]]]:
    events: dict[str, list[tuple[date, str | None, bool]]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)

    def add(code: str, day: date, title: str, key: str) -> None:
        if not code.startswith(prefixes) or (keep is not None and code not in keep):
            return
        if key in seen[code]:
            return
        seen[code].add(key)
        transition, asserted = classify(title)
        if transition is None and not asserted:
            return
        events[code].append((day, transition, asserted))

    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            code = str(r["secCode"])
            key = f"{code}|{r.get('announcementId') or r.get('announcementTime')}"
            add(code, ms_date(r["announcementTime"]), r["title"], key)
    # 逐股公告补齐：同一条公告（代码+时间+标题）去重，用于已知缺口定向补漏
    for path in per_stock_paths or []:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if "error" in row:
                continue
            code = str(row["symbol"])
            for ann in row.get("announcements") or []:
                if ann.get("time") is None:
                    continue
                key = f"{code}|{ann['time']}|{(ann.get('title') or '')[:40]}"
                add(code, ms_date(ann["time"]), ann.get("title") or "", key)
    return events


def build_intervals(
    events: dict[str, list[tuple[date, str | None, bool]]],
    codes: list[str],
    days: list[date],
    window_start: date,
    pad: int,
) -> tuple[dict[str, list[tuple[date, date | None, bool]]], dict]:
    result = {}
    stats = {"baseline_true": 0, "assertion_recovered": [], "after_calendar": []}
    for code in codes:
        changes = sorted(events.get(code, []), key=lambda item: item[0])
        baseline = False
        for day, transition, asserted in changes:
            if day >= window_start:
                break
            if transition is not None:
                baseline = transition == "true"
            elif asserted:
                baseline = True
        if baseline:
            stats["baseline_true"] += 1
        segs: list[tuple[date, date | None, bool]] = []
        state, start = baseline, window_start
        for day, transition, asserted in changes:
            if day < window_start:
                continue
            if day > days[-1]:
                stats["after_calendar"].append([code, day.isoformat()])
                continue
            if transition is None:
                if asserted and not state:
                    # 只有「继续/进展」类断言而缺实施公告：保守补成 ST（公告日前一个交易日起）
                    edge = shift(days, shift(days, day, 1), -pad)
                    stats["assertion_recovered"].append([code, day.isoformat(), edge.isoformat()])
                    if edge > start:
                        segs.append((start, edge, state))
                        start = edge
                    state = True
                continue
            value = transition == "true"
            if value == state:
                continue
            eff = shift(days, day, 1)  # 公告日后的第一个交易日生效
            if value:
                edge = shift(days, eff, -pad)  # 保守：提前 pad 个交易日
                if edge <= start:
                    state = True
                    continue
                segs.append((start, edge, state))
                start, state = edge, True
            else:
                edge = shift(days, eff, pad)  # 保守：延后 pad 个交易日
                segs.append((start, edge, state))
                start, state = edge, False
        segs.append((start, None, state))
        # 合并相邻同类段（保守外扩可能产生零长/同类段）
        merged: list[tuple[date, date | None, bool]] = []
        for seg in segs:
            if merged and merged[-1][2] == seg[2]:
                merged[-1] = (merged[-1][0], seg[1], seg[2])
            else:
                merged.append(seg)
        result[code] = merged
    return result, stats


def state_at(segs: list[tuple[date, date | None, bool]], day: date) -> bool:
    for start, end, value in segs:
        if start <= day and (end is None or day < end):
            return value
    return False


def calibrate_sz(
    sz_csv: Path,
    events_paths: list[Path],
    days: list[date],
    window_start: date,
    window_end: date,
    pad: int,
    delist_dates: dict[str, date] | None = None,
) -> dict:
    truth: dict[str, list[tuple[date, date | None, bool]]] = defaultdict(list)
    with sz_csv.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            truth[r["symbol"]].append(
                (
                    date.fromisoformat(r["valid_from"]),
                    date.fromisoformat(r["valid_to"]) if r["valid_to"] else None,
                    r["is_st"] == "true",
                )
            )
    sz_codes = sorted(truth)
    sz_events = read_events(events_paths, SZ_PREFIXES, set(sz_codes))
    built, sz_stats = build_intervals(sz_events, sz_codes, days, window_start, pad)
    # 退市股进入整理期后由 listing-history 剔除，本校准只比「仍在正常交易」的日子（终止日前 30 自然日之前）
    skip_after = {
        code: day - timedelta(days=30) for code, day in (delist_dates or {}).items() if code in truth
    }
    days_in = [d for d in days if d <= window_end]
    over = under = 0
    missed_starts = []
    for sym, segs in truth.items():
        b = built[sym]
        cut = skip_after.get(sym)
        for d in days_in:
            if cut is not None and d >= cut:
                continue
            bv, tv = state_at(b, d), state_at(segs, d)
            if bv != tv:
                if bv:
                    over += 1
                else:
                    under += 1
        for s, _, v in segs:
            if v and date(2022, 5, 1) <= s <= date(2026, 8, 6) and not state_at(b, s):
                if cut is not None and s >= cut:
                    continue
                missed_starts.append([sym, s.isoformat()])
    return {
        "over_days": over,
        "under_days": under,
        "missed_st_start_days": len(missed_starts),
        "missed_starts": missed_starts[:50],
        "sz_stocks": len(sz_codes),
        "sz_stocks_with_events": sum(1 for s in sz_codes if sz_events.get(s)),
        "sz_baseline_true": sz_stats["baseline_true"],
        "sz_assertion_recovered": len(sz_stats["assertion_recovered"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events", action="append", required=True)
    ap.add_argument(
        "--per-stock-jsonl",
        action="append",
        default=None,
        help="巨潮逐股公告 jsonl（已知缺口定向补漏；与 --events 去重合并）",
    )
    ap.add_argument("--hf-manifest", required=True)
    ap.add_argument("--vipdoc-dir", default=None, help="沪市 vipdoc/minline 目录（补 VIPDOC-only 股票）")
    ap.add_argument("--calendar", required=True)
    ap.add_argument("--sz-csv", default=None, help="深市 ST 历史（用于合并 + 校准）")
    ap.add_argument("--securities-csv", default=None, help="库内 securities 导出（校准排除整理期用）")
    ap.add_argument("--window-start", default="2022-01-01")
    ap.add_argument("--window-end", default="2026-11-10")
    ap.add_argument("--pad", type=int, default=1)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    window_start, window_end = date.fromisoformat(args.window_start), date.fromisoformat(args.window_end)
    days = load_trading_days(Path(args.calendar))

    pool_codes: list[str] = []
    with Path(args.hf_manifest).open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r.get("is_bj") == "True" or r.get("exchange") != "SH":
                continue
            if r["symbol"].startswith(SH_PREFIXES):
                pool_codes.append(r["symbol"])
    if args.vipdoc_dir:
        for path in Path(args.vipdoc_dir).glob("sh*.lc1"):
            code = path.stem[2:]
            if len(code) == 6 and code.startswith(SH_PREFIXES):
                pool_codes.append(code)
    pool_codes = sorted(set(pool_codes))
    transitions = read_events(
        [Path(p) for p in args.events],
        SH_PREFIXES,
        set(pool_codes),
        [Path(p) for p in (args.per_stock_jsonl or [])],
    )
    built, build_stats = build_intervals(transitions, pool_codes, days, window_start, args.pad)

    sh_path = out / "st_history_sh.csv"
    rows = 0
    with sh_path.open("w", encoding="utf-8", newline="\n") as fh:
        w = csv.writer(fh)
        w.writerow(["exchange", "symbol", "valid_from", "valid_to", "is_st"])
        for code in pool_codes:
            for start, end, value in built[code]:
                w.writerow(["SH", code, start.isoformat(), end.isoformat() if end else "", "true" if value else "false"])
                rows += 1

    manifest: dict = {
        "product": "st_history_sh",
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "window": {"start": window_start.isoformat(), "end": None},
        "format": "csv exchange,symbol,valid_from,valid_to,is_st (runner data.load_status_history)",
        "rule": {
            "events": "巨潮公告标题：撤销/实施（含「实行」）风险警示判切换；继续实施、叠加、进展、申请撤销中判「仍处于风险警示」断言；「可能被实施」先剔除",
            "effective_date": "公告日后第一个交易日",
            "padding": f"置 true 提前 {args.pad} 个交易日；置 false 延后 {args.pad} 个交易日（保守多剔除）",
            "baseline": "窗口起点状态取窗口前最后一条事件：切换按其值、断言按 true；无事件 → false（披露）",
            "assertion_recovery": "窗口内状态为 false 却出现「仍处于风险警示」断言 → 保守补为 ST（公告日前一个交易日起），逐条入 manifest",
            "coverage": "每只股票从窗口起点连续覆盖到开区间",
            "not_mixed_with": ["security_risk_flag_history"],
        },
        "pool": {"stocks": len(pool_codes), "source": "HF manifest 沪市 A 股前缀 + vipdoc sh/minline 补 VIPDOC-only"},
        "events": {
            "files": [
                {"path": f"{Path(p).parent.name}/{Path(p).name}", "sha256": sha256(Path(p))}
                for p in args.events
            ],
            "per_stock_gapfix": [
                {"path": f"{Path(p).parent.name}/{Path(p).name}", "sha256": sha256(Path(p))}
                for p in (args.per_stock_jsonl or [])
            ],
        },
        "coverage": {
            "stocks_covered": len(built),
            "stocks_with_st": sum(1 for segs in built.values() if any(v for _, _, v in segs)),
            "st_true_intervals": sum(1 for segs in built.values() for _, _, v in segs if v),
            "baseline_true_stocks": build_stats["baseline_true"],
            "assertion_recovered": len(build_stats["assertion_recovered"]),
            "assertion_recovered_sample": build_stats["assertion_recovered"][:20],
            "events_after_calendar": len(build_stats["after_calendar"]),
            "events_after_calendar_sample": build_stats["after_calendar"][:10],
            "rows": rows,
        },
        "outputs": {"st_history_sh": {"file": sh_path.name, "sha256": sha256(sh_path), "rows": rows}},
    }
    if args.sz_csv:
        delist_dates: dict[str, date] = {}
        if args.securities_csv:
            for r in csv.DictReader(Path(args.securities_csv).open(newline="", encoding="utf-8-sig")):
                sym, exch = r["code"].split(".")
                if exch == "SZ" and r.get("delist_date"):
                    delist_dates[sym] = date.fromisoformat(r["delist_date"])
        calib = calibrate_sz(
            Path(args.sz_csv),
            [Path(p) for p in args.events],
            days,
            window_start,
            window_end,
            args.pad,
            delist_dates,
        )
        manifest["calibration_sz"] = calib
        # 合并成 runner 单文件
        merged_path = out / "st_history.csv"
        merged_rows = 0
        with merged_path.open("w", encoding="utf-8", newline="\n") as fh:
            w = csv.writer(fh)
            w.writerow(["exchange", "symbol", "valid_from", "valid_to", "is_st"])
            for path in (Path(args.sz_csv), sh_path):
                with path.open(newline="", encoding="utf-8-sig") as src:
                    for r in csv.DictReader(src):
                        w.writerow([r["exchange"], r["symbol"], r["valid_from"], r["valid_to"], r["is_st"]])
                        merged_rows += 1
        manifest["outputs"]["st_history_merged"] = {
            "file": merged_path.name,
            "sha256": sha256(merged_path),
            "rows": merged_rows,
            "sz_sha256": sha256(Path(args.sz_csv)),
        }
    (out / "st_history_sh_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in manifest.items() if k in ("coverage", "calibration_sz")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
