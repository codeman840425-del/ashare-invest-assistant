"""Offline T-R58d entry point. Validate the whole stock pool before any simulation."""

from __future__ import annotations

import argparse
import json
import tempfile
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from . import data, outputs, rules, runner_data, sim, splice, stats
from . import experiments as exp
from .errors import DataFormatError

CST = timezone(timedelta(hours=8))


class StockCache:
    """Bound memory: store verified grids locally; replay only the requested date prefix."""

    def __init__(self, prepared: runner_data.Prepared, root: Path) -> None:
        self.prepared = prepared
        self.root = root
        self.keys: list[tuple[str, str]] = []
        self.date_inventories: dict[str, list[dict[str, Any]]] = {"single": [], "main": []}
        self.quality: dict[str, Any] = {
            "splice": [],
            "exclusions": {},
            "stock_days": {},
            "listing": [],
            "last_bars": {},
            "exrights": [],
        }

    def prepare(self) -> None:
        exclusions: dict[str, Counter] = {}
        stock_days: Counter = Counter()
        bar_quality: Counter = Counter()
        for stock, evidence in runner_data.iter_stocks(self.prepared):
            key = stock.exchange, stock.symbol
            self.quality["splice"].append(evidence["splice"] | {"lc1": evidence["lc1"]})
            outputs.add_date_inventory(self.date_inventories, key, evidence["lc1"]["main"])
            self.quality["listing"].append({"key": key, **evidence["listing"]})
            if evidence["exrights"]["checked"] or evidence["exrights"]["uncheckable"]:
                self.quality["exrights"].append({"key": key, **evidence["exrights"]})
            has_bar = np.flatnonzero(np.any(np.isfinite(stock.o), axis=1))
            if has_bar.size:
                self.quality["last_bars"][key] = stock.dates[has_bar[-1]]
            reasons = evidence["exclusions"]
            stock_days.update(reasons["stock_days"])
            for year, counts in reasons["all"].items():
                exclusions.setdefault(year, Counter()).update(counts)
            bar_quality.update(
                {
                    name: evidence[name]
                    for name in ("outside_dates", "missing_bars", "bar_ok_failed")
                }
            )
            if not np.any(stock.day_kind == sim.OK):
                continue
            np.savez(
                self.root / f"{key[0]}{key[1]}.npz",
                o=stock.o,
                h=stock.h,
                l=stock.l,
                c=stock.c,
                v=stock.v,
                a=stock.a,
                day_kind=stock.day_kind,
                st=stock.st,
            )
            self.keys.append(key)
        self.quality["exclusions"] = exclusions
        self.quality["stock_days"] = stock_days
        self.quality["bar_quality"] = bar_quality

    def stocks(self, segments: list[sim.Segment]) -> Iterator[sim.StockInput]:
        dates = self.prepared.dates
        end = bisect_right(dates, segments[-1].end)
        start = next(i for i, day in enumerate(dates) if day >= segments[0].start)
        for exchange, symbol in self.keys:
            with np.load(self.root / f"{exchange}{symbol}.npz", allow_pickle=False) as grid:
                kinds = grid["day_kind"][:end]
                if not np.any(kinds[start:] == sim.OK):
                    continue
                yield sim.StockInput(
                    exchange,
                    symbol,
                    dates[:end],
                    *[grid[name][:end] for name in "ohlcva"],
                    kinds,
                    grid["st"][:end],
                    [
                        e
                        for e in self.prepared.events.get((exchange, symbol), [])
                        if e.ex_date <= dates[end - 1]
                    ],
                )


def _check_leg(leg: sim.Leg, dates: list[date], segment: sim.Segment) -> None:
    if not segment.start <= dates[leg.entry_day] <= segment.end:
        raise DataFormatError("leg entered outside its assigned segment")
    if segment.embargo and dates[leg.entry_day] == segment.end:
        raise DataFormatError("entry during embargo")
    if leg.entry_slot <= leg.trigger_slot:
        raise DataFormatError("entry preceded its signal")
    if leg.exit_day is not None and (
        dates[leg.exit_day] > segment.end
        or leg.exit_slot is None
        or (leg.exit_day, leg.exit_slot) <= (leg.exit_trigger_day, leg.exit_trigger_slot)
    ):
        raise DataFormatError("exit crossed the segment or preceded its signal")


def _check_execution(market: sim.Market, leg: sim.Leg) -> None:
    stock, params = market.stock, market.params
    d, t = leg.entry_day, leg.trigger_slot
    signal_price = float(stock.c[d, t])
    if abs(signal_price / market.pc[d] - 1) > params.trend_abs_pct:
        raise DataFormatError("entry violated point-in-time trend gate")
    if leg.q != rules.lot_floor(market.board, params.notional, signal_price):
        raise DataFormatError("entry quantity not frozen at signal close")
    if leg.impact_bp_frozen != rules.impact_bp(leg.participation_pct):
        raise DataFormatError("wrong frozen impact tier")
    buy_first = leg.direction == "buy_first"
    if not market.can_fill(d, leg.entry_slot, leg.q, buy_first):
        raise DataFormatError("entry violated bar capacity or price limits")
    if leg.exit_day is None or leg.exit_slot is None or leg.exit_price is None:
        return
    if not market.can_fill(leg.exit_day, leg.exit_slot, leg.q, not buy_first):
        raise DataFormatError("exit violated bar capacity or price limits")
    sell_day, sell_price = (leg.exit_day, leg.exit_price) if buy_first else (d, leg.entry_price)
    expected_stamp = sell_price * leg.q * rules.stamp_duty_rate(stock.dates[sell_day])
    expected_commission = sum(
        rules.commission(price * leg.q, params.commission_rate)
        for price in (leg.entry_price, leg.exit_price)
    )
    if not np.isclose(leg.stamp, expected_stamp, rtol=0, atol=1e-9) or not np.isclose(
        leg.commission, expected_commission, rtol=0, atol=1e-9
    ):
        raise DataFormatError("settled leg violated dated stamp duty or commission floor")


def _batch(cache: StockCache, config: data.Summary) -> exp.Batch:
    options = config["stats"]

    def run(
        candidates: Sequence[exp.Candidate], segments: list[sim.Segment], random: bool
    ) -> dict[str, exp.Trial]:
        trials = {c.name: exp.Trial(c, [], elapsed_seconds=0.0) for c in candidates}
        by_name = {segment.name: segment for segment in segments}
        for stock in cache.stocks(segments):
            market = sim.Market(stock, candidates[0].params)
            for candidate in candidates:
                started = perf_counter()
                params = candidate.params
                legs = sim.simulate(stock, params, segments, market=market)
                controls = (
                    sim.simulate_random(
                        stock,
                        params,
                        segments,
                        legs,
                        draws=options["r_draws"],
                        seed=options["seed"],
                        market=market,
                    )
                    if random and candidate.name == "selected_A"
                    else [None] * len(legs)
                )
                trial = trials[candidate.name]
                occupied_until = -1
                for leg, control in zip(legs, controls, strict=True):
                    if leg.entry_day <= occupied_until:
                        raise DataFormatError("a stock opened a leg while occupied")
                    occupied_until = leg.entry_day if leg.exit_day is None else leg.exit_day
                    _check_leg(leg, stock.dates, by_name[leg.segment])
                    _check_execution(market, leg)
                    trial.rows.append(
                        exp.Observed(stock.exchange, stock.dates[leg.entry_day], leg, control)
                    )
                trial.elapsed_seconds = (trial.elapsed_seconds or 0) + perf_counter() - started
        for trial in trials.values():
            if not trial.rows:
                trial.status = "no_legs"
        return trials

    return run


def _phase_days(phase: exp.Phase, dates: list[date]) -> list[date]:
    return [day for day in dates if phase.segments[0].start <= day <= phase.segments[-1].end]


def _stat(trial: exp.Trial, days: list[date], config: data.Summary) -> dict[str, Any]:
    index = {day: i for i, day in enumerate(days)}
    index_by_row = np.array([index[row.entry_date] for row in trial.rows], dtype=np.int64)
    values = np.array([row.leg.pnl_bp for row in trial.rows])
    options = config["stats"]
    lo, hi = stats.block_bootstrap_mean(
        index_by_row,
        values,
        len(days),
        options["bootstrap_block"],
        options["bootstrap_reps"],
        options["seed"],
    )
    return {
        "n": len(values),
        "cover_days": len(set(index_by_row)),
        "mean_bp": trial.mean_bp,
        "ci_low_bp": lo,
        "ci_high_bp": hi,
    }


def _trial_rows(
    phases: list[exp.Phase], dates: list[date], config: data.Summary, started_at: datetime
) -> Iterator[dict[str, Any]]:
    for phase in phases:
        days = _phase_days(phase, dates)
        for trial in phase.trials:
            observed = _stat(trial, days, config)
            observed.pop("cover_days")
            yield {
                "trial_id": f"{phase.name}/{trial.candidate.name}",
                "group": trial.candidate.base,
                "phase": phase.name,
                "segment": "/".join(s.name for s in phase.segments),
                "start": days[0],
                "end": days[-1],
                "params": asdict(trial.candidate.params),
                "holm_family": phase.name == "training_final",
                "selected": trial.selected,
                "status": trial.status,
                "started_at": started_at,
                "elapsed_seconds": trial.elapsed_seconds,
                **observed,
            }


def _source(day: date) -> str:
    if day <= splice.HF_END:
        return "HF"
    return "vipdoc_single" if day == splice.SINGLE_DAY else "vipdoc_main"


def _leg_rows(phases: list[exp.Phase], dates: list[date]) -> Iterator[dict[str, Any]]:
    for phase in phases:
        for trial in phase.trials:
            for row in trial.rows:
                leg = row.leg
                record = asdict(leg)
                exit_day = record.pop("exit_day")
                exit_trigger_day = record.pop("exit_trigger_day")
                record.pop("entry_day")
                entry_source = _source(row.entry_date)
                exit_source = _source(dates[exit_day]) if exit_day is not None else entry_source
                yield {
                    **record,
                    "trial_id": f"{phase.name}/{trial.candidate.name}",
                    "group": trial.candidate.base,
                    "exchange": row.exchange,
                    "entry_date": row.entry_date,
                    "exit_date": dates[exit_day] if exit_day is not None else None,
                    "exit_trigger_date": dates[exit_trigger_day],
                    "data_source": entry_source if entry_source == exit_source else "cross_splice",
                }


def _freeze(
    paths: runner_data.ResearchPaths,
    prepared: runner_data.Prepared,
    config: data.Summary,
    choice: exp.Choice,
    candidates: Sequence[exp.Candidate],
    scope: dict[str, Any],
) -> None:
    identity = {
        "plan": config["plan"],
        "hf": prepared.evidence["hf"],
        "vipdoc_single": prepared.evidence["vipdoc_single"],
        "vipdoc_main": prepared.evidence["vipdoc_main"],
    }
    fingerprint = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    lock = paths.data_root / "retest-holdout" / f"{fingerprint}.json"
    lock.parent.mkdir(exist_ok=True)
    # Exclusive creation before evaluation is durable. A failed attempt still
    # consumes this holdout identity; a new output name cannot bypass the lock.
    with lock.open("x", encoding="utf-8", newline="\n") as stream:
        import os

        json.dump(
            {
                "identity": identity,
                "choice": asdict(choice),
                "candidates": [asdict(c) for c in candidates],
                "training_scope": outputs._json_value(scope),
            },
            stream,
            allow_nan=False,
        )
        stream.flush()
        os.fsync(stream.fileno())


def _phase_list(result: exp.WalkForward) -> list[exp.Phase]:
    result_phases = [*result.training, *result.evaluations]
    if result.sensitivities:
        result_phases.append(result.sensitivities)
    if result.holdout:
        result_phases.append(result.holdout)
    return result_phases


def _checks(cache: StockCache, phases: list[exp.Phase]) -> dict[str, Any]:
    legs = [row.leg for phase in phases for trial in phase.trials for row in trial.rows]
    settled = sum(leg.exit_day is not None for leg in legs)
    counts = {"legs": len(legs), "settled": settled}
    executed = "runtime_asserted" if legs else "no_eligible_legs"
    return {
        "L1": {"evidence": "synthetic prefix/elapsed checks"},
        "L2": {"state": executed, **counts},
        "L3": {"state": executed, "basis": "signal close / prior close"},
        "L4": {"evidence": "prior completed days only; synthetic lookback checks"},
        "L5": {"state": executed, "settled": settled, "dated_stamp": True},
        "L6": {"state": executed, "base_inventory": "assumed sellable; buy_first sells old shares"},
        "L7": {"state": "phase_isolated", "holdout_runs": sum(p.name == "holdout" for p in phases)},
        "L8": {"state": executed, "basis": "signal lot and impact; realized commission floor"},
        "L9": {
            "pool": cache.prepared.evidence["stock_pool"],
            "stock_days": cache.quality["stock_days"],
            "status_by_year": cache.quality["exclusions"],
        },
        "L10": {"evidence": "minute features only; daily index used only for P7"},
        "L11": {"events_after_phase_end": "excluded", "snapshot_revisions": "unable_to_verify"},
        "L12": {
            "diagnostic_only": True,
            "reference_checks": cache.quality["exrights"],
            "unvaluable_legs": sum(leg.reason == "unvaluable_exdate" for leg in legs),
        },
        "L13": {"state": executed, "basis": "previous completed bar volume; zero-volume exception"},
        "L14": {"stocks_checked": len(cache.quality["splice"]), "one_source_per_stock_day": True},
        "bar_quality": cache.quality["bar_quality"],
    }


def run(paths: runner_data.ResearchPaths, destination: Path, *, workers: int = 8) -> Path:
    if not destination.parent.resolve().is_relative_to(paths.data_root.resolve()):
        raise DataFormatError("results must stay under the offline data root")
    config = data.load_config(Path(__file__).with_name("config.yaml"))
    started_at = datetime.now(UTC).astimezone(CST)
    stage = "inputs"
    try:
        prepared = runner_data.preflight(paths, config, workers=workers)
        with tempfile.TemporaryDirectory(prefix=".t-r58-grids-", dir=paths.data_root) as working:
            stage = "splice"
            cache = StockCache(prepared, Path(working))
            cache.prepare()
            stage = "walk_forward"
            result = exp.walk_forward(
                _batch(cache, config),
                config,
                prepared.segments,
                prepared.dates,
                lambda choice, candidates, scope: _freeze(
                    paths, prepared, config, choice, candidates, scope
                ),
            )
            stage = "write_results"
            phases = _phase_list(result)
            # Promotion requires the independent P1–P10 judgement, supplied by the judgement layer.
            from .judgement import evaluate

            verdict = evaluate(result, prepared, config, last_bars=cache.quality["last_bars"])
            return outputs.publish_run(
                destination,
                trials=_trial_rows(phases, prepared.dates, config, started_at),
                legs=_leg_rows(phases, prepared.dates),
                date_inventories=cache.date_inventories if paths.live_vipdoc is not None else None,
                summary={
                    "plan": config["plan"],
                    "data": prepared.evidence,
                    "segments": prepared.evidence["segments"],
                    "seed": config["stats"]["seed"],
                    "splice": cache.quality["splice"],
                    "exclusions": cache.quality["exclusions"],
                    "checks": _checks(cache, phases),
                    **verdict,
                },
            )
    except (DataFormatError, OSError) as exc:
        failure = exc if isinstance(exc, DataFormatError) else DataFormatError(type(exc).__name__)
        outputs.publish_failure(destination, stage=stage, error=failure)
        raise


def check_data(paths: runner_data.ResearchPaths, destination: Path, *, workers: int = 8) -> Path:
    if not destination.parent.resolve().is_relative_to(paths.data_root.resolve()):
        raise DataFormatError("results must stay under the offline data root")
    config = data.load_config(Path(__file__).with_name("config.yaml"))
    stage = "inputs"
    checks: dict[str, Any] = {"strategy_run": False, "stocks_checked": 0, "splice": []}
    try:
        prepared = runner_data.preflight(paths, config, workers=workers)
        checks["data"] = prepared.evidence
        stage = "splice"
        for _, evidence in runner_data.iter_stocks(prepared):
            checks["splice"].append(evidence["splice"] | {"lc1": evidence["lc1"]})
            checks["stocks_checked"] += 1
        return outputs._publish(
            destination,
            failed=False,
            write=lambda directory: outputs._json(directory / "preflight.json", checks),
        )
    except (DataFormatError, OSError) as exc:
        failure = exc if isinstance(exc, DataFormatError) else DataFormatError(type(exc).__name__)
        outputs.publish_failure(destination, stage=stage, error=failure)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data-root", "calendar", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in (
        "st-history",
        "listing-history",
        "securities",
        "delisting-list",
        "vipdoc",
        "single-package",
        "main-package",
    ):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--execute", action="store_true", help="Run strategy after validation.")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    paths = runner_data.ResearchPaths(
        args.data_root,
        args.single_package,
        args.main_package,
        args.calendar,
        args.st_history,
        args.listing_history,
        args.securities,
        args.delisting_list,
        args.vipdoc,
    )
    try:
        action = run if args.execute else check_data
        result = action(paths, args.output, workers=args.workers)
    except (DataFormatError, OSError):
        print(json.dumps({"status": "blocked", "failure": str(outputs.failure_path(args.output))}))
        return 1
    print(json.dumps({"status": "written", "output": str(result)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
