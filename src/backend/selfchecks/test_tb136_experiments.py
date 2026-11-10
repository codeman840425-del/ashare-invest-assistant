# ruff: noqa: S101
"""Training grid accounting and one-way split isolation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from retest.t_r58 import data, experiments, sim
from retest.t_r58.errors import DataFormatError
from selfchecks import tb136_retest as synthetic


def test_tb136_experiments_accounts_for_34_trials_without_training_data() -> None:
    config = data.load_config(Path(data.__file__).with_name("config.yaml"))
    days = [date(2024, 1, 2), date(2024, 1, 3)]
    training = [sim.Segment("fold1", *days)]
    batches = []

    def run(
        candidates: Sequence[experiments.Candidate], segments: list[sim.Segment], random: bool
    ) -> dict[str, experiments.Trial]:
        assert not random
        assert segments == training
        batches.append(len(candidates))
        return {c.name: experiments.Trial(c, [], status="no_legs") for c in candidates}

    picked, trials = experiments.choose(run, config, training, days)
    assert batches == [26]
    assert picked.main() is None
    assert len(trials) == len({t.candidate.name for t in trials}) == 34
    assert sum(t.status == "base_unselected" for t in trials) == 8


def test_tb136_experiments_refuses_holdout_before_calling_simulator() -> None:
    config = data.load_config(Path(data.__file__).with_name("config.yaml"))
    days = [date(2024, 1, 2), date(2024, 1, 3)]

    def forbidden(*args: object) -> dict[str, experiments.Trial]:
        pytest.fail("selection entered the holdout simulator")

    holdout = sim.Segment("holdout", *days, embargo=False)
    with pytest.raises(DataFormatError, match="selection cannot consume holdout"):
        experiments.choose(forbidden, config, [holdout], days)


def test_tb136_experiments_freezes_once_before_only_holdout_call() -> None:
    config = data.load_config(Path(data.__file__).with_name("config.yaml"))
    config["grid"]["min_legs_select"] = 1
    config["stats"]["bootstrap_reps"] = 20
    stock = synthetic._stock([*synthetic._base(), synthetic._sell_day(), synthetic._flat_day()])
    leg = sim.simulate(stock, synthetic.PB, synthetic._seg(stock))[0]
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(12)]
    segments = [sim.Segment(f"fold{i + 1}", days[2 * i], days[2 * i + 1]) for i in range(5)]
    segments.append(sim.Segment("holdout", days[10], days[11], embargo=False))
    actions = []

    def run(
        candidates: Sequence[experiments.Candidate], windows: list[sim.Segment], random: bool
    ) -> dict[str, experiments.Trial]:
        actions.append(tuple(w.name for w in windows))
        rows = [
            experiments.Observed(stock.exchange, w.start, replace(leg, pnl_bp=10.0))
            for w in windows
        ]
        if windows == segments[-1:]:
            assert actions[-2] == "freeze"
            assert random
            assert {c.name for c in candidates} == {
                "selected_A",
                "selected_B",
                "p8_notional_10000",
                "p8_commission_0.0003",
            }
        return {c.name: experiments.Trial(c, rows) for c in candidates}

    def freeze(
        choice: experiments.Choice, candidates: Sequence[experiments.Candidate], scope: dict
    ) -> None:
        assert set(scope) == {"X", "Y"}
        assert scope["X"]["bracket"] is None
        assert scope["Y"]["bracket"] is None
        assert choice.directions == ("sell_first",)
        assert not choice.use_volume
        assert all(c.params.directions == choice.directions for c in candidates)
        actions.append("freeze")

    result = experiments.walk_forward(run, config, segments, days, freeze)
    assert [len(t.trials) for t in result.training] == [34] * 5
    assert [phase.segments for phase in result.evaluations] == [[s] for s in segments[1:5]]
    assert result.holdout is not None
    assert actions.count(("holdout",)) == actions.count("freeze") == 1


def test_tb136_experiments_refines_bounds_only_from_training_results() -> None:
    config = data.load_config(Path(data.__file__).with_name("config.yaml"))
    stock = synthetic._stock([*synthetic._base(), synthetic._sell_day(), synthetic._flat_day()])
    segments = synthetic._seg(stock)
    leg = sim.simulate(stock, synthetic.PB, segments)[0]
    main = experiments.base_grid(config)[0]
    seen = []

    def run(
        candidates: Sequence[experiments.Candidate], windows: list[sim.Segment], random: bool
    ) -> dict[str, experiments.Trial]:
        assert windows == segments
        assert not random
        seen.extend(c.name for c in candidates)
        result = {}
        for c in candidates:
            pnl = (c.params.notional - 40000) / 1000 + (0.00027 - c.params.commission_rate) * 1e6
            row = experiments.Observed(
                stock.exchange, stock.dates[leg.entry_day], replace(leg, pnl_bp=pnl)
            )
            result[c.name] = experiments.Trial(c, [row])
        return result

    candidates = [
        replace(main, name="p8_primary"),
        *experiments.sensitivity(config, main, holdout=False),
    ]
    phase = experiments.Phase(
        "sensitivity_train", segments, list(run(candidates, segments, False).values())
    )
    result = experiments._refine_scope(run, segments, phase, main)
    x = result["X"]["bracket"]
    y = result["Y"]["bracket"]
    assert x[0] <= 20000 <= x[1]
    assert x[1] - x[0] <= 100
    assert y[0] <= 0.00028 <= y[1]
    assert y[1] - y[0] <= 1e-6
    assert result["X"]["bound"] == x[1]
    assert result["Y"]["bound"] == y[0]
    assert len(phase.trials) == len(seen)
