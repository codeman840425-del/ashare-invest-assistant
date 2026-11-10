"""Prespecified train/evaluation phases; only the frozen recipe enters holdout."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from itertools import pairwise, product
from math import isfinite
from statistics import mean, median
from typing import Any

import numpy as np

from . import sim, stats
from .errors import DataFormatError


@dataclass(frozen=True)
class Candidate:
    name: str
    params: sim.Params
    point: tuple[int, ...]
    base: str


@dataclass(frozen=True)
class Observed:
    exchange: str
    entry_date: date
    leg: sim.Leg
    control: sim.RLeg | None = None

    def key(self) -> tuple[str, str, date, str]:
        return self.exchange, self.leg.symbol, self.entry_date, self.leg.direction


@dataclass
class Trial:
    candidate: Candidate
    rows: list[Observed]
    selected: bool = False
    status: str = "completed"
    elapsed_seconds: float | None = None

    @property
    def mean_bp(self) -> float:
        return mean(x.leg.pnl_bp for x in self.rows) if self.rows else float("nan")


@dataclass(frozen=True)
class Choice:
    a: Candidate | None
    b: Candidate | None
    volume_a: Candidate | None
    volume_b: Candidate | None
    directions: tuple[str, ...]
    use_volume: bool

    def main(self) -> Candidate | None:
        picked = self.volume_a if self.use_volume else self.a
        return (
            replace(picked, params=replace(picked.params, directions=self.directions))
            if picked is not None and self.directions
            else None
        )


Batch = Callable[[Sequence[Candidate], list[sim.Segment], bool], dict[str, Trial]]


def base_grid(config: dict[str, Any]) -> list[Candidate]:
    a, b = config["grid"]["A"], config["grid"]["B"]
    shared = {
        key: config["rules"][key]
        for key in (
            "entry_start",
            "entry_end",
            "confirm",
            "revert_band",
            "stop_mult",
            "trend_abs_pct",
            "min_edge_cost_mult",
            "time_stop",
            "last_fill",
            "sigma_warmup",
        )
    }
    shared.update(
        commission_rate=config["costs"]["commission_rate"],
        notional=float(config["costs"]["notional"]),
    )
    candidates = [
        Candidate(
            f"A{i + 1:02}.{j + 1}",
            sim.Params(group="A", k=k, floor=floor, **shared),
            (i, j),
            "A",
        )
        for (i, k), (j, floor) in product(enumerate(a["k"]), enumerate(a["floor"]))
    ]
    candidates.extend(
        Candidate(
            f"B{i + 1:02}",
            sim.Params(group="B", d=d, **shared),
            (i,),
            "B",
        )
        for i, d in enumerate(b["d"])
    )
    if len(candidates) != 26 or sum(c.base == "A" for c in candidates) != 21:
        raise DataFormatError("T-R58d base grid must contain A21+B5")
    return candidates


def volume_grid(
    config: dict[str, Any], a: Candidate | None, b: Candidate | None
) -> list[Candidate]:
    return [
        Candidate(
            f"C{base}{i + 1:02}",
            replace(candidate.params, group="C" if base == "A" else "B", v=v),
            (i,),
            f"C{base}",
        )
        for base, candidate in (("A", a), ("B", b))
        if candidate is not None
        for i, v in enumerate(config["grid"]["C"]["v"])
    ]


def _neighbors(point: tuple[int, ...], grid: dict[tuple[int, ...], Trial]) -> list[Trial]:
    result = [grid[point]]
    for dimension in range(len(point)):
        for step in (-1, 1):
            adjacent = (*point[:dimension], point[dimension] + step, *point[dimension + 1 :])
            if adjacent in grid:
                result.append(grid[adjacent])
    return result


def select(trials: Sequence[Trial], group: str, minimum: int) -> Trial | None:
    grid = {t.candidate.point: t for t in trials if t.candidate.base == group}
    eligible = []
    for point, trial in grid.items():
        if len(trial.rows) < minimum:
            continue
        values = [x.mean_bp for x in _neighbors(point, grid)]
        if all(isfinite(value) for value in values):
            eligible.append((median(values), trial))
    # The predeclared grid order breaks exact ties, never the evaluation fold.
    return max(eligible, key=lambda item: item[0])[1] if eligible else None


def paired_interval(
    left: Sequence[Observed], right: Sequence[Observed], dates: list[date], config: dict[str, Any]
) -> tuple[float | None, float | None, float | None, int]:
    right_bp = {row.key(): row.leg.pnl_bp for row in right}
    index = {day: i for i, day in enumerate(dates)}
    common = [
        (index[row.entry_date], row.leg.pnl_bp - right_bp[row.key()])
        for row in left
        if row.key() in right_bp
    ]
    if not common:
        return None, None, None, 0
    ix, diff = zip(*common, strict=True)
    options = config["stats"]
    lo, hi = stats.block_bootstrap_mean(
        np.array(ix),
        np.array(diff),
        len(dates),
        options["bootstrap_block"],
        options["bootstrap_reps"],
        options["seed"],
    )
    return mean(diff), lo, hi, len(diff)


def choose(
    run: Batch, config: dict[str, Any], training: list[sim.Segment], dates: list[date]
) -> tuple[Choice, list[Trial]]:
    if not training or any(
        segment.name == "holdout" or not segment.embargo for segment in training
    ):
        raise DataFormatError("selection cannot consume holdout")
    base = base_grid(config)
    all_base = list(run(base, training, False).values())
    minimum = config["grid"]["min_legs_select"]
    a, b = select(all_base, "A", minimum), select(all_base, "B", minimum)
    volume = volume_grid(config, a.candidate if a else None, b.candidate if b else None)
    all_volume = list(run(volume, training, False).values()) if volume else []
    va, vb = select(all_volume, "CA", minimum), select(all_volume, "CB", minimum)
    for group, selected in (("A", a), ("B", b)):
        if selected is None:
            # Keep the prespecified family at 34 even when no C base can be trained.
            template = next(item.params for item in base if item.base == group)
            for i, v in enumerate(config["grid"]["C"]["v"]):
                candidate = Candidate(
                    f"C{group}{i + 1:02}",
                    replace(template, k=None, floor=0.0, d=None, v=v),
                    (i,),
                    f"C{group}",
                )
                all_volume.append(Trial(candidate, [], status="base_unselected"))
    if len(all_base) + len(all_volume) != 34:
        raise DataFormatError("T-R58d training must account for all 34 trials")
    for trial in (a, b, va, vb):
        if trial:
            trial.selected = True
    day_index = [day for day in dates if training[0].start <= day <= training[-1].end]
    use_volume = False
    if a and va:
        _, lo, _, _ = paired_interval(va.rows, a.rows, day_index, config)
        use_volume = lo is not None and lo > 0
    effective = va if use_volume else a
    directions = (
        ()
        if effective is None
        else tuple(
            direction
            for direction in effective.candidate.params.directions
            if (values := [r.leg.pnl_bp for r in effective.rows if r.leg.direction == direction])
            and mean(values) > 0
        )
    )
    return Choice(
        a.candidate if a else None,
        b.candidate if b else None,
        va.candidate if va else None,
        vb.candidate if vb else None,
        directions,
        use_volume,
    ), all_base + all_volume


def sensitivity(config: dict[str, Any], chosen: Candidate, *, holdout: bool) -> list[Candidate]:
    params = chosen.params
    costs = config["costs"]
    output = [
        replace(chosen, name="p8_notional_10000", params=replace(params, notional=10000.0)),
        replace(
            chosen, name="p8_commission_0.0003", params=replace(params, commission_rate=0.0003)
        ),
    ]
    if holdout:
        return output
    for amount in costs["notional_sens"]:
        if amount != 10000:
            output.append(
                replace(
                    chosen,
                    name=f"notional_{amount}",
                    params=replace(params, notional=float(amount)),
                )
            )
    for rate in costs["commission_rate_sens"]:
        if rate != 0.0003:
            output.append(
                replace(
                    chosen, name=f"commission_{rate}", params=replace(params, commission_rate=rate)
                )
            )
    for name, step in config["sens_steps"].items():
        for direction in (-1, 1):
            output.append(
                replace(
                    chosen,
                    name=f"{name}_{direction:+d}",
                    params=replace(
                        params,
                        **{name: getattr(params, name) + step * direction},
                    ),
                )
            )
    output.append(
        replace(
            chosen,
            name="entry_exit_delay",
            params=replace(
                params,
                fill_delay=config["latency_fill_delay"],
            ),
        )
    )
    return output


@dataclass
class Phase:
    name: str
    segments: list[sim.Segment]
    trials: list[Trial]


@dataclass
class WalkForward:
    training: list[Phase]
    evaluations: list[Phase]
    final_choice: Choice
    holdout: Phase | None
    sensitivities: Phase | None
    training_scope: dict[str, Any] | None = None


def _training_scope(trials: list[Trial], main: Candidate) -> dict[str, Any]:
    """Freeze observed sign brackets; do not extrapolate a break-even root."""
    scope = {}
    for parameter, positive_high, label in (
        ("notional", True, "X"),
        ("commission_rate", False, "Y"),
    ):
        other = "commission_rate" if parameter == "notional" else "notional"
        values = sorted(
            (getattr(t.candidate.params, parameter), t.mean_bp)
            for t in trials
            if t.candidate.name == "p8_primary"
            or (
                t.candidate.name.startswith(("p8_", "notional_", "commission_"))
                and getattr(t.candidate.params, other) == getattr(main.params, other)
                and getattr(t.candidate.params, parameter) != getattr(main.params, parameter)
            )
        )
        signs = [mean_bp > 0 for _, mean_bp in values]
        bracket = None
        if values and all(isfinite(mean_bp) for _, mean_bp in values):
            wanted = sorted(signs, reverse=not positive_high)
            if signs == wanted and any(signs) and not all(signs):
                positive = [point for point, mean_bp in values if mean_bp > 0]
                negative = [point for point, mean_bp in values if mean_bp <= 0]
                bracket = (
                    (max(negative), min(positive))
                    if positive_high
                    else (max(positive), min(negative))
                )
        scope[label] = {"observed": values, "bracket": bracket}
    return scope


def _refine_scope(
    run: Batch,
    training: list[sim.Segment],
    phase: Phase,
    main: Candidate,
) -> dict[str, Any]:
    """Use train-only bisection and keep both observed sides of each boundary."""
    scope = _training_scope(phase.trials, main)
    for label, field, tolerance, positive_high in (
        ("X", "notional", 100.0, True),
        ("Y", "commission_rate", 1e-6, False),
    ):
        evidence = scope[label]
        bracket = evidence["bracket"]
        if bracket is None:
            evidence.update(state="unbracketed", bound=None)
            continue
        low, high = bracket
        for step in range(16):
            if high - low <= tolerance:
                break
            mid = (low + high) / 2
            candidate = replace(
                main,
                name=f"p8_bound_{label}_{step:02}",
                params=replace(main.params, **{field: mid}),
            )
            trial = run([candidate], training, False)[candidate.name]
            phase.trials.append(trial)
            score = trial.mean_bp
            evidence["observed"].append((mid, score))
            if not isfinite(score):
                evidence.update(state="insufficient", bound=None)
                break
            if (score > 0) == positive_high:
                high = mid
            else:
                low = mid
        else:
            evidence.update(state="resolution_not_met", bound=None)
        if "state" not in evidence:
            evidence.update(
                state="bracketed",
                bracket=(low, high),
                bound=high if positive_high else low,
                tolerance=tolerance,
            )
    return scope


def _evaluation_candidates(choice: Choice) -> list[Candidate]:
    main = choice.main()
    if main is None:
        return []
    candidates = [replace(main, name="selected_A")]
    if choice.b:
        candidates.append(
            replace(
                choice.b,
                name="selected_B",
                params=replace(choice.b.params, directions=choice.directions),
            )
        )
    return candidates


def walk_forward(
    run: Batch,
    config: dict[str, Any],
    segments: list[sim.Segment],
    dates: list[date],
    freeze: Callable[[Choice, Sequence[Candidate], dict[str, Any]], None],
) -> WalkForward:
    names = [segment.name for segment in segments]
    if names != ["fold1", "fold2", "fold3", "fold4", "fold5", "holdout"]:
        raise DataFormatError("invalid walk-forward segment order")
    if any(a.end >= b.start for a, b in pairwise(segments)):
        raise DataFormatError("walk-forward segments overlap")
    if segments[-1].embargo:
        raise DataFormatError("holdout must use the research-cutoff policy")
    training = []
    evaluations = []
    for count in range(1, 5):
        train = segments[:count]
        evaluation = segments[count : count + 1]
        picked, trials = choose(run, config, train, dates)
        training.append(Phase(f"training_{count}", train, trials))
        candidates = _evaluation_candidates(picked)
        results = list(run(candidates, evaluation, True).values()) if candidates else []
        evaluations.append(Phase(f"evaluation_{count}", evaluation, results))
    final_segments = segments[:5]
    picked, trials = choose(run, config, final_segments, dates)
    training.append(Phase("training_final", final_segments, trials))
    main = picked.main()
    if main is None:
        return WalkForward(training, evaluations, picked, None, None)
    variants = [replace(main, name="p8_primary"), *sensitivity(config, main, holdout=False)]
    sens = Phase(
        "sensitivity_train", final_segments, list(run(variants, final_segments, False).values())
    )
    scope = _refine_scope(run, final_segments, sens, main)
    # Persist all prespecified holdout settings before the only call that can use it.
    candidates = _evaluation_candidates(picked) + sensitivity(config, main, holdout=True)
    freeze(picked, candidates, scope)
    holdout_segment = segments[-1:]
    held = Phase("holdout", holdout_segment, list(run(candidates, holdout_segment, True).values()))
    return WalkForward(training, evaluations, picked, held, sens, scope)
