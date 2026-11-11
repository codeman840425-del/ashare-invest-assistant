"""Conservative T-R58d verdict: unknown evidence never becomes a passed check."""

from __future__ import annotations

from datetime import date
from math import isfinite
from statistics import mean, median
from typing import Any

import numpy as np

from . import experiments as exp
from . import runner_data, splice, stats


def _trial(phase: exp.Phase | None, name: str = "selected_A") -> exp.Trial | None:
    return next((t for t in phase.trials if t.candidate.name == name), None) if phase else None


def _rows(trial: exp.Trial | None) -> list[exp.Observed]:
    return trial.rows if trial else []


def _score(
    rows: list[exp.Observed],
    days: list[date],
    config: dict[str, Any],
    *,
    values: list[float] | None = None,
) -> dict[str, Any]:
    index = {day: i for i, day in enumerate(days)}
    slots = np.array([index[row.entry_date] for row in rows], dtype=np.int64)
    bp = [r.leg.pnl_bp for r in rows] if values is None else values
    options = config["stats"]
    low, high = stats.block_bootstrap_mean(
        slots,
        np.asarray(bp),
        len(days),
        options["bootstrap_block"],
        options["bootstrap_reps"],
        options["seed"],
    )
    return {
        "n": len(rows),
        "days": len(set(slots)),
        "mean": mean(bp) if bp else None,
        "low": low if isfinite(low) else None,
        "high": high if isfinite(high) else None,
    }


def _windows(phase: exp.Phase | None, dates: list[date]) -> list[date]:
    return (
        [day for day in dates if phase.segments[0].start <= day <= phase.segments[-1].end]
        if phase
        else []
    )


def _check(value: bool | None, **detail: object) -> dict[str, object]:
    return {"status": "unknown" if value is None else "pass" if value else "fail", **detail}


def _environment(
    phases: list[exp.Phase], prepared: runner_data.Prepared, config: dict[str, Any]
) -> dict[str, Any]:
    days_by_year: dict[int, list[date]] = {}
    rows_by_year: dict[int, list[exp.Observed]] = {}
    for phase in phases:
        for day in _windows(phase, prepared.dates):
            days_by_year.setdefault(day.year, []).append(day)
        for row in _rows(_trial(phase)):
            rows_by_year.setdefault(row.entry_date.year, []).append(row)
    by_label: dict[str, tuple[list[date], list[exp.Observed]]] = {}
    labels = {}
    for year, days in days_by_year.items():
        start, end = prepared.index_close[days[0]], prepared.index_close[days[-1]]
        label = "up" if end > start else "down" if end < start else "flat"
        labels[year] = label
        dates, rows = by_label.setdefault(label, ([], []))
        dates.extend(days)
        rows.extend(rows_by_year.get(year, []))
    scores = {label: _score(rows, dates, config) for label, (dates, rows) in by_label.items()}
    if not {"up", "down"} <= set(scores) or any(scores[x]["high"] is None for x in ("up", "down")):
        return _check(None, labels=labels, scores=scores)
    return _check(all(scores[x]["high"] >= 0 for x in ("up", "down")), labels=labels, scores=scores)


def _multiplicity(
    phase: exp.Phase,
    days: list[date],
    chosen: exp.Candidate | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    options = config["stats"]
    positions = {day: i for i, day in enumerate(days)}
    rng = np.random.default_rng(options["seed"])
    block, reps = options["bootstrap_block"], options["bootstrap_reps"]
    starts = rng.integers(0, len(days), size=(reps, (len(days) + block - 1) // block))
    samples = ((starts[:, :, None] + np.arange(block)) % len(days)).reshape(reps, -1)[
        :, : len(days)
    ]
    raw, sharpe = [], []
    by_trial = {}
    for trial in phase.trials:
        leg_day = np.array([positions[r.entry_date] for r in trial.rows], dtype=np.int64)
        bp = np.array([r.leg.pnl_bp for r in trial.rows])
        totals = np.bincount(leg_day, weights=bp, minlength=len(days))
        counts = np.bincount(leg_day, minlength=len(days))
        if bp.size:
            sample_counts = counts[samples].sum(axis=1)
            sample_totals = totals[samples].sum(axis=1)
            observed = float(bp.mean())
            sampled = sample_totals[sample_counts > 0] / sample_counts[sample_counts > 0]
            # Center the trading-day block distribution under the no-edge null.
            p = (1 + int((sampled - observed >= observed).sum())) / (1 + len(sampled))
        else:
            p = 1.0
        raw.append(p)
        daily = totals[counts > 0] / counts[counts > 0]
        sd = float(daily.std(ddof=1)) if len(daily) > 1 else 0.0
        sr = float(daily.mean() / sd) if sd > 0 else None
        sharpe.append(sr)
        by_trial[trial.candidate.name] = (daily, sr)
    adjusted = stats.holm(raw)
    dsr = None
    if chosen and all(sr is not None for sr in sharpe):
        daily, sr = by_trial[chosen.name]
        z = (daily - daily.mean()) / daily.std()
        dsr = stats.deflated_sharpe(
            sr, sharpe, len(daily), float(np.mean(z**3)), float(np.mean(z**4))
        )
    return {
        "family": len(adjusted),
        "dsr": dsr,
        "p_method": "one_sided_centered_day_block",
        "trials": {
            t.candidate.name: {"raw_p": p, "holm_p": corrected, "conservative_p1": not bool(t.rows)}
            for t, p, corrected in zip(phase.trials, raw, adjusted, strict=True)
        },
    }


NO_PERIOD_SUSPENDED_GAP_DAYS = 5  # 仅用于区分「停牌到摘牌」形态，不作为通过阈值（T-A155）


def _suspended_missing_days(
    prepared: runner_data.Prepared,
    key: tuple[str, str],
    start: date,
    end: date,
) -> bool:
    """start < d <= end 的交易日是否全部为已确认停牌（用于「不等但停牌」判定）。"""
    days = [day for day in prepared.dates if start < day <= end]
    if not days:
        return False
    confirmed = prepared.meta.get("confirmed_suspension") or set()
    return all((key[1], key[0], day) in confirmed for day in days)


def _delisting(
    prepared: runner_data.Prepared,
    last_bars: dict[tuple[str, str], date],
) -> dict[str, Any]:
    official = prepared.meta.get("termination_list")
    pool = {stock[:2]: stock[2] for stock in prepared.pool}
    hf_count = prepared.evidence["stock_pool"]["delisted_hf"]
    if not official:
        return {
            "state": "unknown",
            "reason": "exchange termination list missing or empty",
            "hf_pool_delisted": hf_count,
        }
    missing = sorted(official.keys() - pool.keys())
    unknown = []
    truncated = []
    with_period = []
    by_rule = []
    evidence_only = []
    suspended_until_delisting = []
    coverage = prepared.meta.get("coverage") or {}
    evidence_map = prepared.meta.get("termination_evidence") or {}
    for key in sorted(official.keys() & pool.keys()):
        start = min(
            (
                lo
                for lo, _, state in prepared.listing_history.get(key, [])
                if state == "delisting_period" and lo <= official[key]
            ),
            default=None,
        )
        if start is not None:
            if key not in last_bars or last_bars[key] < start:
                truncated.append(key)
            else:
                with_period.append(key)
            continue
        # T-A155：交易类强制退市/主动退市没有整理期。判据是 HF 元数据认定的应有末日
        # （expected_end_date == 最后一根 bar），不另拍自然日阈值；不等时只有在缺口
        # 全是已确认停牌时才按「停牌到摘牌」放行，否则走尾段缺失路径。
        expected_end = coverage.get(key[1], {}).get("expected_end_date")
        last = last_bars.get(key)
        if last is None or expected_end is None:
            unknown.append(key)
            continue
        if last == expected_end:
            if (official[key] - last).days > NO_PERIOD_SUSPENDED_GAP_DAYS:
                suspended_until_delisting.append(key)
            elif evidence_map.get(key) == "no_title_evidence":
                evidence_only.append(key)
            else:
                by_rule.append(key)
        elif _suspended_missing_days(prepared, key, last, expected_end):
            suspended_until_delisting.append(key)
        else:
            truncated.append(key)
    no_period_total = len(by_rule) + len(evidence_only) + len(suspended_until_delisting)
    return {
        "state": "fail" if missing or truncated else "unknown" if unknown else "pass",
        "hf_pool_delisted": hf_count,
        "official_count": len(official),
        "missing": missing,
        "missing_share": len(missing) / len(official),
        "tail_missing": truncated,
        "period_unknown": unknown,
        "pass_with_period": with_period,
        "no_delisting_period_total": no_period_total,
        "no_delisting_period_by_rule": by_rule,
        "no_delisting_period_evidence_only": evidence_only,
        "suspended_until_delisting": suspended_until_delisting,
        "no_period_policy": "last_bar_equals_hf_expected_end",
        "residual_risk": (
            f"{len(evidence_only)} 只无整理期标题证据的股票按 expected_end_date 判等通过，"
            "需逐股读终止上市公告正文交叉核后收口"
            if evidence_only
            else None
        ),
    }


def evaluate(
    result: exp.WalkForward,
    prepared: runner_data.Prepared,
    config: dict[str, Any],
    *,
    last_bars: dict[tuple[str, str], date] | None = None,
) -> dict[str, Any]:
    held = _rows(_trial(result.holdout))
    hold_days = _windows(result.holdout, prepared.dates)
    held_score = _score(held, hold_days, config)
    folds = [
        _score(_rows(_trial(p)), _windows(p, prepared.dates), config) for p in result.evaluations
    ]
    coverage = [*folds, held_score]
    enough = all(
        s["n"] >= config["grid"]["min_legs_select"]
        and s["days"] >= config["stats"]["min_cover_days"]
        for s in coverage
    )
    held_mean = held_score["mean"]
    fold_means = [s["mean"] for s in folds]
    robustness = None
    if len(fold_means) == 4 and all(value is not None for value in fold_means):
        robustness = 0.6 * median(fold_means) + 0.4 * min(fold_means)
    p2 = (
        held_mean > 0
        and held_score["low"] > 0
        and robustness > 0
        and sum(value > 0 for value in fold_means) >= 3
        if held_score["low"] is not None and robustness is not None
        else None
    )
    costs = [
        sum((leg.commission, leg.stamp, leg.transfer, leg.slippage, leg.impact))
        / leg.notional
        * 1e4
        for row in held
        if (leg := row.leg)
    ]
    average_cost = mean(costs) if costs else None
    bad = sum(
        row.leg.reason == "time"
        or row.leg.reason == "deferred"
        or row.leg.reason.startswith("unvaluable_")
        for row in held
    )
    bad_share = bad / len(held) if held else None
    paired = [
        row
        for row in held
        if row.control is not None and row.control.n_ok == config["stats"]["r_draws"]
    ]
    r = _score(
        paired, hold_days, config, values=[row.leg.pnl_bp - row.control.mean_bp for row in paired]
    )
    p5 = (
        r["mean"] > 0 and r["low"] > 0
        if len(paired) == len(held) and r["low"] is not None
        else None
    )
    final = result.training[-1]
    chosen = result.final_choice.a
    grid = {t.candidate.point: t for t in final.trials if t.candidate.base == "A"}
    values = [t.mean_bp for t in exp._neighbors(chosen.point, grid)] if chosen else []
    p6 = (
        all(x > 0 and x >= values[0] / 2 for x in values)
        if values and all(map(isfinite, values))
        else None
    )
    environment = [*result.evaluations, *([result.holdout] if result.holdout else [])]
    p8 = {}
    for name in ("p8_notional_10000", "p8_commission_0.0003"):
        a, b = _trial(result.sensitivities, name), _trial(result.holdout, name)
        p8[name] = {
            "train": a.mean_bp if a and a.rows else None,
            "holdout": b.mean_bp if b and b.rows else None,
        }
    unrestricted = all(
        value is not None and value > 0 for evidence in p8.values() for value in evidence.values()
    )
    scope = result.training_scope or {}
    x, y = (scope.get(label, {}).get("bound") for label in ("X", "Y"))
    boundary = (
        None
        if unrestricted or x is None or y is None
        else {
            "min_notional_yuan": x,
            "max_commission_rate": y,
            "small_notional_applicable": False,
            "basis": "observed positive side of a training-only sign bracket",
        }
    )
    delisting = _delisting(prepared, last_bars or {})
    p9 = None if delisting["state"] == "unknown" else delisting["state"] == "pass"
    criteria = {
        "P1": _check(enough, windows=coverage),
        "P2": _check(p2, robustness=robustness),
        "P3": _check(
            held_mean > config["stats"]["edge_cost_mult_p3"] * average_cost
            if average_cost is not None
            else None,
            average_cost_bp=average_cost,
        ),
        "P4": _check(
            bad_share <= config["stats"]["max_bad_exit_share"] if bad_share is not None else None,
            share=bad_share,
        ),
        "P5": _check(p5, paired=r),
        "P6": _check(p6, neighbors=values),
        "P7": _environment(environment, prepared, config),
        "P8": _check(
            True if unrestricted or boundary is not None else None,
            sensitivities=p8,
            training_brackets=result.training_scope,
            boundary=boundary,
        ),
        "P9": _check(p9, **delisting),
        "P10": _check(
            bool(result.final_choice.directions), directions=result.final_choice.directions
        ),
    }
    if not enough or p9 is not True:
        status, reason = (
            "data_insufficient",
            "P9 evidence incomplete" if enough else "P1 samples insufficient",
        )
    elif any(check["status"] != "pass" for key, check in criteria.items() if key != "P8"):
        status, reason = "not_passed", "one or more required criteria failed or are unknown"
    elif not unrestricted and boundary is None:
        status, reason = "scope_unresolved", "training break-even bounds required before review"
    else:
        status, reason = "eligible_for_review", "all required criteria passed"
    pre = [r for r in held if r.entry_date <= splice.HF_END]
    post = [r for r in held if r.entry_date > splice.HF_END]
    return {
        "criteria": criteria,
        "delisting": delisting,
        "multiplicity": _multiplicity(final, _windows(final, prepared.dates), chosen, config),
        "conclusion": {"status": status, "promote": False, "reason": reason},
        "holdout_by_source": {
            "through_2026-08-06": _score(pre, [d for d in hold_days if d <= splice.HF_END], config),
            "from_2026-08-07": _score(post, [d for d in hold_days if d > splice.HF_END], config),
        },
    }
