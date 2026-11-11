"""T-R68：复测产物 P1–P10 / 红旗 / R 组预筛（出数即判，纯标准库）。

输入正式跑三件套（summary.json / trials.csv / legs.csv），输出 JSON 预筛结果 + 一屏摘要：
- 判定快照：P1–P10 的 status 与关键数值（直接读 summary.criteria）；
- 红旗：R0–R14 中可由产物自动判的部分（hit/clear/unknown/manual，附证据数值）；
- R 组：P5 配对差 + 1:1 对应 + 反推 R 均值（逐腿对照值未落盘，见字段映射表 §3）；
- 数据质量：按年剔除计数、ST/上市状态覆盖、腿的 reason 分布。

口径：本脚本只做「预筛/读数」，不替代方案 §8.3 判定、不新增阈值、不改 runner 产物。
用法：
  python docs/strategies/T-R59/prescreen.py --summary <run>/summary.json \
      --trials <run>/trials.csv --legs <run>/legs.csv [--out prescreen.json]
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from datetime import date
from pathlib import Path

STAMP_CHANGE = date(2023, 8, 28)
LEG_NUMERIC = (
    "entry_price",
    "exit_price",
    "q",
    "notional",
    "planned_amount",
    "participation_pct",
    "impact_bp_frozen",
    "theta",
    "sigma",
    "dev",
    "commission",
    "stamp",
    "transfer",
    "slippage",
    "impact",
    "pnl_yuan",
    "pnl_bp",
    "cons_pnl_yuan",
    "cons_pnl_bp",
    "hold_bars",
    "mae_bp",
)
TRIAL_NUMERIC = ("n", "mean_bp", "ci_low_bp", "ci_high_bp", "elapsed_seconds")
COST_COLUMNS = ("commission", "stamp", "transfer", "slippage", "impact")


def _num(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _rows(path: Path, numeric: tuple[str, ...]) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        for name in numeric:
            if name in row:
                row[name] = _num(row[name])
    return rows


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _share(part: int, total: int) -> float | None:
    return round(part / total, 6) if total else None


def _flag(fid: str, name: str, state: str, **detail: object) -> dict:
    return {"id": fid, "name": name, "state": state, **detail}


def _sell_date(leg: dict) -> date | None:
    raw = leg.get("entry_date") if leg.get("direction") == "sell_first" else leg.get("exit_date")
    return date.fromisoformat(raw) if raw else None


def _cost_rate(leg: dict) -> float | None:
    notional = leg.get("notional") or 0.0
    if not notional:
        return None
    total = sum(leg.get(column) or 0.0 for column in COST_COLUMNS)
    return total / notional * 1e4


def _holdout_legs(legs: list[dict]) -> list[dict]:
    return [leg for leg in legs if leg.get("trial_id") == "holdout/selected_A"]


def _trial(trials: list[dict], trial_id: str) -> dict | None:
    return next((row for row in trials if row.get("trial_id") == trial_id), None)


def _fold_means(trials: list[dict]) -> dict[str, float]:
    result = {}
    for row in trials:
        phase = row.get("phase") or ""
        if phase.startswith("evaluation_") and str(row.get("selected")).lower() == "true":
            if row.get("mean_bp") is not None:
                result[phase] = row["mean_bp"]
    return result


def _criteria_snapshot(criteria: dict) -> dict:
    keep = {
        "P1": ("windows",),
        "P2": ("robustness",),
        "P3": ("average_cost_bp",),
        "P4": ("share",),
        "P5": ("paired",),
        "P6": ("neighbors",),
        "P7": ("labels", "scores"),
        "P8": ("sensitivities", "boundary"),
        "P9": ("state", "official_count", "period_unknown", "tail_missing", "missing"),
        "P10": ("directions",),
    }
    snapshot = {}
    for name in (f"P{index}" for index in range(1, 11)):
        block = criteria.get(name) or {}
        entry = {"status": block.get("status")}
        for key in keep.get(name, ()):
            if key in block:
                entry[key] = block[key]
        snapshot[name] = entry
    return snapshot


def analyze(summary: dict, trials: list[dict], legs: list[dict]) -> dict:
    criteria = summary.get("criteria") or {}
    checks = summary.get("checks") or {}
    exclusions = summary.get("exclusions") or {}
    holdout_legs = _holdout_legs(legs)
    paired = (criteria.get("P5") or {}).get("paired") or {}
    paired_n = paired.get("n")
    a_mean = _mean([leg["pnl_bp"] for leg in holdout_legs if leg.get("pnl_bp") is not None])
    if a_mean is None:
        trial = _trial(trials, "holdout/selected_A")
        a_mean = trial.get("mean_bp") if trial else None
    implied_r_mean = None
    if a_mean is not None and paired.get("mean") is not None:
        implied_r_mean = round(a_mean - paired["mean"], 4)
    one_to_one = None
    if paired_n is not None and holdout_legs:
        one_to_one = paired_n == len(holdout_legs)

    r_group = {
        "holdout_legs": len(holdout_legs),
        "paired_n": paired_n,
        "one_to_one": one_to_one,
        "paired_mean_bp": paired.get("mean"),
        "paired_low_bp": paired.get("low"),
        "paired_high_bp": paired.get("high"),
        "pair_significant": (paired.get("low") is not None and paired["low"] > 0),
        "a_star_holdout_mean_bp": None if a_mean is None else round(a_mean, 4),
        "implied_control_mean_bp": implied_r_mean,
        "per_leg_control_values_persisted": False,
        "cannot_compute": ["R 组分布对称性", "逐腿配对 t 检验"],
    }

    # ---- 数据质量 ----
    year_stats = {}
    for year, counts in sorted(exclusions.items()):
        total = sum(counts.values()) if isinstance(counts, dict) else 0
        year_stats[year] = {
            "exclusions": counts if isinstance(counts, dict) else {},
            "shares": {k: _share(v, total) for k, v in (counts or {}).items()} if total else {},
        }
    l9 = checks.get("L9") or {}
    stock_days = l9.get("stock_days") or {}
    total_days = sum(stock_days.values()) if stock_days else 0
    data_quality = {
        "stock_days_by_year": stock_days,
        "exclusions_by_year": year_stats,
        "legs_total": len(legs),
        "legs_by_trial": dict(Counter(leg.get("trial_id") for leg in legs)),
        "reason_counts": dict(Counter(leg.get("reason") for leg in legs)),
        "coverage": summary.get("coverage"),
        "st_coverage": (summary.get("data") or {}).get("st_coverage"),
        "listing_coverage": (summary.get("data") or {}).get("listing_coverage"),
        "termination_list_sha256": (summary.get("data") or {}).get("termination_list_sha256"),
    }

    # ---- 红旗 ----
    flags = []
    failed_checks = [
        name
        for name, value in checks.items()
        if name != "bar_quality"
        and isinstance(value, dict)
        and str(value.get("status") or value.get("state") or "").lower() in {"fail", "failed", "blocked"}
    ]
    flags.append(_flag("R0", "L1-L14 检查 fail", "hit" if failed_checks else "clear", failed_checks=failed_checks))

    folds = _fold_means(trials)
    holdout_mean = None
    trial = _trial(trials, "holdout/selected_A")
    if trial and trial.get("mean_bp") is not None:
        holdout_mean = trial["mean_bp"]
    if holdout_mean is None and (criteria.get("P1") or {}).get("windows"):
        holdout_mean = criteria["P1"]["windows"][-1].get("mean")
    r1_state, r1_detail = "unknown", {}
    if len(folds) >= 2 and holdout_mean is not None:
        ordered = [folds[key] for key in sorted(folds)]
        increasing = all(b > a for a, b in zip(ordered, ordered[1:]))
        if increasing and holdout_mean < min(ordered):
            r1_state = "hit"
        elif holdout_mean > max(ordered) * 1.5:
            r1_state = "hit"
        else:
            r1_state = "clear"
        r1_detail = {"fold_means": folds, "holdout_mean": holdout_mean, "monotonic_increasing": increasing}
    flags.append(_flag("R1", "折均值递增+保留集回落 / 保留集远好于折", r1_state, **r1_detail))

    cost_sums = {column: sum((leg.get(column) or 0.0) for leg in legs) for column in COST_COLUMNS}
    r2_state, r2_detail = "unknown", {"cost_sums": cost_sums, "implied_control_mean_bp": implied_r_mean}
    if legs and all(value == 0 for value in cost_sums.values()):
        r2_state = "hit"
    elif implied_r_mean is not None and implied_r_mean >= 0:
        r2_state = "hit"
    elif legs:
        r2_state = "clear"
    sensitivities = (criteria.get("P8") or {}).get("sensitivities") or {}
    notional = sensitivities.get("p8_notional_10000") or {}
    commission = sensitivities.get("p8_commission_0.0003") or {}
    sensitivity_detail = {"p8_notional_10000": notional, "p8_commission_0.0003": commission}
    if r2_state != "hit" and holdout_mean is not None:
        if notional.get("holdout") is not None and notional["holdout"] >= holdout_mean:
            r2_state = "hit"
        if commission.get("holdout") is not None and commission["holdout"] >= holdout_mean:
            r2_state = "hit"
    r2_detail["sensitivities"] = sensitivity_detail
    flags.append(_flag("R2", "R 组均值/成本项/敏感性方向", r2_state, **r2_detail))

    sources = summary.get("holdout_by_source") or {}
    first, second = sources.get("through_2026-08-06") or {}, sources.get("from_2026-08-07") or {}
    r3_state, r3_detail = "unknown", {"first": first, "second": second}
    if first.get("n") and second.get("n") and first.get("mean") is not None and second.get("mean") is not None:
        one, two = first["mean"], second["mean"]
        if one * two < 0 or (min(abs(one), abs(two)) > 0 and max(abs(one), abs(two)) / min(abs(one), abs(two)) > 3):
            r3_state = "hit"
        else:
            r3_state = "clear"
    flags.append(_flag("R3", "保留集两段符号/量级", r3_state, **r3_detail))

    flags.append(
        _flag(
            "R4",
            "2026-04-13 前后剔除行为跳变",
            "manual",
            by_year={year: stats["shares"] for year, stats in year_stats.items()},
        )
    )

    pre_stamp, post_stamp = [], []
    for leg in legs:
        rate = leg.get("stamp") or 0.0
        notional_value = leg.get("notional") or 0.0
        if not notional_value:
            continue
        day = _sell_date(leg)
        if day is None:
            continue
        (pre_stamp if day <= date(2023, 8, 27) else post_stamp).append(rate / notional_value)
    r5_state, r5_detail = "unknown", {
        "pre_2023-08-28_mean_rate": _mean(pre_stamp),
        "from_2023-08-28_mean_rate": _mean(post_stamp),
    }
    if pre_stamp and post_stamp and r5_detail["pre_2023-08-28_mean_rate"]:
        ratio = r5_detail["from_2023-08-28_mean_rate"] / r5_detail["pre_2023-08-28_mean_rate"]
        r5_detail["rate_ratio"] = round(ratio, 4)
        r5_state = "hit" if 0.9 <= ratio <= 1.1 else "clear"
    flags.append(_flag("R5", "印花税分段", r5_state, **r5_detail))

    trigger_rate = _share(len(legs), total_days) if total_days else None
    group_means = {}
    for group in ("A", "B"):
        values = [
            row["mean_bp"]
            for row in trials
            if row.get("group") == group and row.get("phase") == "training_final" and row.get("mean_bp") is not None
        ]
        group_means[group] = _mean(values)
    r6_state, r6_detail = "unknown", {"trigger_rate": trigger_rate, "group_means": group_means}
    if not legs:
        r6_detail["note"] = "0 腿：触发率不可判（先看 R0/R14 数据门禁）"
    elif trigger_rate is not None:
        if trigger_rate < 0.0001 or trigger_rate > 0.2:
            r6_state = "hit"
        elif group_means.get("A") is not None and group_means.get("B") is not None:
            r6_state = "hit" if (group_means["A"] < 0 < group_means["B"]) else "clear"
        else:
            r6_state = "clear"
    flags.append(_flag("R6", "触发率/A-B 方向", r6_state, **r6_detail))

    flags.append(
        _flag(
            "R7",
            "T+1/底仓逻辑",
            "manual",
            directions=dict(Counter(leg.get("direction") for leg in legs)),
            prior_anomaly=dict(Counter(leg.get("prior_anomaly") for leg in legs)),
        )
    )

    exec_anomaly = Counter(leg.get("exec_anomaly") for leg in legs)
    participations = [leg["participation_pct"] for leg in legs if leg.get("participation_pct") is not None]
    flags.append(
        _flag(
            "R8",
            "成交容量/不可成交",
            "manual",
            exec_anomaly=dict(exec_anomaly),
            max_participation_pct=max(participations) if participations else None,
            L13=checks.get("L13"),
        )
    )

    bad = sum(1 for leg in holdout_legs if leg.get("reason") in {"time", "deferred"} or str(leg.get("reason", "")).startswith("unvaluable_"))
    bad_share = _share(bad, len(holdout_legs))
    time_share = _share(sum(1 for leg in holdout_legs if leg.get("reason") == "time"), len(holdout_legs))
    r9_state, r9_detail = "unknown", {"time_stop_share": time_share, "bad_share": bad_share, "holdout_mean": holdout_mean}
    if time_share is not None and holdout_mean is not None:
        r9_state = "hit" if (time_share > 0.5 and abs(holdout_mean) < 5) else "clear"
    flags.append(_flag("R9", "时间止损率", r9_state, **r9_detail))

    segments = summary.get("segments") or {}
    overrun = []
    embargo_entries = []
    for leg in legs:
        segment = segments.get(leg.get("segment") or "")
        if not segment:
            continue
        end = segment.get("end")
        if end and leg.get("exit_date") and leg["exit_date"] > end:
            overrun.append([leg.get("trial_id"), leg.get("symbol"), leg["exit_date"], end])
        if segment.get("embargo") and end and leg.get("entry_date") == end:
            embargo_entries.append([leg.get("symbol"), leg["entry_date"]])
    holm_misplaced = [
        row.get("trial_id")
        for row in trials
        if str(row.get("holm_family")).lower() == "true" and row.get("phase") != "training_final"
    ]
    flags.append(
        _flag(
            "R10",
            "选参纪律/embargo/越段",
            "hit" if overrun or embargo_entries or holm_misplaced else "clear",
            exit_overrun=overrun[:10],
            embargo_entries=embargo_entries[:10],
            holm_family_outside_final=holm_misplaced,
        )
    )

    p9 = criteria.get("P9") or {}
    p9_state = str(p9.get("status") or "")
    r11_state = "clear" if p9_state == "pass" else ("hit" if p9_state == "fail" else "unknown")
    flags.append(_flag("R11", "P9 退市股核验", r11_state, p9=p9, delisting=summary.get("delisting")))

    unvaluable = sum(1 for leg in holdout_legs if str(leg.get("reason", "")).startswith("unvaluable_"))
    unvaluable_share = _share(unvaluable, len(holdout_legs))
    l12 = checks.get("L12") or {}
    r12_state = "unknown" if unvaluable_share is None else ("hit" if unvaluable_share > 0.15 else "clear")
    flags.append(_flag("R12", "无法估值率", r12_state, unvaluable_share=unvaluable_share, L12=l12))

    r13_state = "unknown" if one_to_one is None else ("clear" if one_to_one else "hit")
    flags.append(
        _flag(
            "R13",
            "R 组 1:1 / 分布",
            r13_state,
            paired_n=paired_n,
            holdout_legs=len(holdout_legs),
            note="逐腿对照值未落盘，分布对称性无法判",
        )
    )

    st_unknown = sum((counts or {}).get("st_unknown", 0) for counts in exclusions.values() if isinstance(counts, dict))
    st_unknown_share = _share(st_unknown, total_days) if total_days else None
    st_coverage = (summary.get("data") or {}).get("st_coverage")
    r14_state = "clear" if st_coverage else ("hit" if st_unknown_share == 0 else "unknown")
    flags.append(_flag("R14", "ST 不明剔除/数据源", r14_state, st_unknown_share=st_unknown_share, st_coverage=st_coverage))

    return {
        "task": "T-R68 prescreen",
        "run_meta": {
            "plan": summary.get("plan"),
            "seed": summary.get("seed"),
            "conclusion": summary.get("conclusion"),
            "trials_rows": len(trials),
            "legs_rows": len(legs),
            "phases": dict(Counter(row.get("phase") for row in trials)),
        },
        "criteria": _criteria_snapshot(criteria),
        "red_flags": flags,
        "r_group": r_group,
        "data_quality": data_quality,
        "cannot_compute": [
            "R 组逐腿分布/对称性（RLeg 未落盘）",
            "R2 的 20 万档敏感性（本轮只跑 1 万/0.03 两档）",
            "R8 不可成交率精确值（无 unfilled 计数，只有腿部 exec_anomaly）",
        ],
    }


def _load(summary_path: Path, trials_path: Path, legs_path: Path) -> tuple[dict, list[dict], list[dict]]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return summary, _rows(trials_path, TRIAL_NUMERIC), _rows(legs_path, LEG_NUMERIC)


def _print_summary(result: dict) -> None:
    meta = result["run_meta"]
    conclusion = meta.get("conclusion") or {}
    print(f"trials={meta['trials_rows']} legs={meta['legs_rows']} conclusion={conclusion.get('status')} ({conclusion.get('reason')})")
    for name, block in result["criteria"].items():
        print(f"  {name}: {block.get('status')}")
    for flag in result["red_flags"]:
        print(f"  {flag['id']} {flag['state']:<8} {flag['name']}")
    r = result["r_group"]
    print(f"  R 组: paired_n={r['paired_n']} legs={r['holdout_legs']} 1:1={r['one_to_one']} diff_mean={r['paired_mean_bp']} implied_R={r['implied_control_mean_bp']}")


def _self_test() -> int:
    summary = {
        "plan": "test",
        "seed": 1,
        "criteria": {f"P{index}": {"status": "pass"} for index in range(1, 11)},
        "checks": {"L1": {"status": "pass"}},
        "exclusions": {"2024": {"st_unknown": 0, "suspended": 10}},
        "data": {"st_coverage": {"rows": 1}, "listing_coverage": {"rows": 1}, "termination_list_sha256": "x"},
        "segments": {"fold1": {"start": "2023-04-10", "end": "2023-10-17", "embargo": True}},
        "holdout_by_source": {
            "through_2026-08-06": {"n": 2, "mean": 40.0},
            "from_2026-08-07": {"n": 2, "mean": 30.0},
        },
        "criteria_p9": {},
    }
    summary["criteria"]["P1"] = {"status": "pass", "windows": [{"n": 4, "days": 4, "mean": 50.0, "low": 10.0, "high": 90.0}]}
    summary["criteria"]["P5"] = {"status": "pass", "paired": {"n": 2, "days": 2, "mean": 20.0, "low": 5.0, "high": 35.0}}
    summary["criteria"]["P8"] = {
        "status": "pass",
        "sensitivities": {"p8_notional_10000": {"train": 40.0, "holdout": 30.0}, "p8_commission_0.0003": {"train": 45.0, "holdout": 38.0}},
    }
    trials = [
        {"trial_id": "evaluation_1/selected_A", "phase": "evaluation_1", "group": "A", "selected": "True", "mean_bp": 20.0, "n": 2},
        {"trial_id": "holdout/selected_A", "phase": "holdout", "group": "A", "selected": "True", "mean_bp": 50.0, "n": 2},
        {"trial_id": "training_final/A01.1", "phase": "training_final", "group": "A", "selected": "False", "mean_bp": 10.0, "n": 2},
    ]
    legs = [
        {
            "trial_id": "holdout/selected_A",
            "group": "A",
            "segment": "fold1",
            "symbol": "600000",
            "direction": "buy_first",
            "entry_date": "2023-05-04",
            "exit_date": "2023-05-05",
            "reason": "revert",
            "notional": 50000.0,
            "pnl_bp": 40.0,
            "commission": 25.0,
            "stamp": 25.0,
            "transfer": 1.0,
            "slippage": 100.0,
            "impact": 0.0,
            "participation_pct": 0.01,
            "exec_anomaly": None,
        },
        {
            "trial_id": "holdout/selected_A",
            "group": "A",
            "segment": "fold1",
            "symbol": "600001",
            "direction": "sell_first",
            "entry_date": "2023-05-04",
            "exit_date": "2023-05-05",
            "reason": "time",
            "notional": 50000.0,
            "pnl_bp": 60.0,
            "commission": 25.0,
            "stamp": 25.0,
            "transfer": 1.0,
            "slippage": 100.0,
            "impact": 0.0,
            "participation_pct": 0.01,
            "exec_anomaly": None,
        },
    ]
    result = analyze(summary, trials, legs)
    assert result["r_group"]["one_to_one"] is True and result["r_group"]["holdout_legs"] == 2
    assert result["r_group"]["paired_mean_bp"] == 20.0
    assert result["r_group"]["implied_control_mean_bp"] == 30.0
    assert any(flag["id"] == "R0" and flag["state"] == "clear" for flag in result["red_flags"])
    assert any(flag["id"] == "R13" and flag["state"] == "clear" for flag in result["red_flags"])
    print("self-test ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--trials", type=Path)
    parser.add_argument("--legs", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return _self_test()
    if not (args.summary and args.trials and args.legs):
        parser.error("需要 --summary/--trials/--legs（或 --self-test）")
    result = analyze(*_load(args.summary, args.trials, args.legs))
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
