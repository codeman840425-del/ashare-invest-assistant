# ruff: noqa: S101
"""Audit R controls from synthetic legs; never open research data or rerun holdout."""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path
from statistics import mean
from types import SimpleNamespace

import pytest

from retest.t_r58 import data, judgement, outputs, runner, sim
from retest.t_r58 import experiments as exp
from selfchecks import tb136_retest as synthetic


@pytest.fixture
def observation() -> exp.Observed:
    stock = synthetic._stock([*synthetic._base(), synthetic._sell_day(), synthetic._flat_day()])
    leg = sim.simulate(stock, synthetic.PB, synthetic._seg(stock))[0]
    return exp.Observed(stock.exchange, stock.dates[leg.entry_day], leg)


def phase(rows: list[exp.Observed]) -> exp.Phase:
    segment = sim.Segment("holdout", rows[0].entry_date, rows[-1].entry_date, embargo=False)
    candidate = exp.Candidate("selected_A", synthetic.PB, (0,), "A")
    return exp.Phase("holdout", [segment], [exp.Trial(candidate, rows)])


def verdict(rows: list[exp.Observed], draws: int = 20) -> dict:
    held = phase(rows)
    choice = exp.Choice(held.trials[0].candidate, None, None, None, ("sell_first",), False)
    result = exp.WalkForward([held], [], choice, held, None)
    prepared = SimpleNamespace(
        dates=sorted({row.entry_date for row in rows}),
        index_close=dict.fromkeys((row.entry_date for row in rows), 10.0),
        meta={},
        pool=[],
        evidence={"stock_pool": {"delisted_hf": 0}},
    )
    config = data.load_config(Path(data.__file__).with_name("config.yaml"))
    config["stats"].update(r_draws=draws, bootstrap_reps=20)
    return judgement.evaluate(result, prepared, config)


@pytest.mark.parametrize(
    ("control_mean", "n_ok", "expected_mean", "expected_count"),
    [
        (1.2345678901234567, 20, "1.2345678901234567", "20"),
        (-2.5, 19, "-2.5", "19"),
        (float("nan"), 0, "", "0"),
        (None, None, "", ""),
    ],
)
def test_b01_control_columns_round_trip_without_losing_precision(
    tmp_path: Path,
    observation: exp.Observed,
    control_mean: float | None,
    n_ok: int | None,
    expected_mean: str,
    expected_count: str,
) -> None:
    control = (
        sim.RLeg(observation.leg.entry_day, observation.leg.direction, control_mean, -9.0, n_ok)
        if n_ok is not None
        else None
    )
    row = replace(observation, control=control)
    projected = list(runner._leg_rows([phase([row])], [row.entry_date] * 40))
    destination = tmp_path / "synthetic"
    summary = dict.fromkeys(outputs.SUMMARY_FIELDS)
    outputs.publish_run(destination, trials=[], legs=projected, summary=summary)
    with (destination / "legs.csv").open(encoding="utf-8", newline="") as stream:
        saved = next(csv.DictReader(stream))
    assert saved["control_mean_bp"] == expected_mean
    assert saved["control_n_ok"] == expected_count
    assert saved["pnl_bp"] == str(row.leg.pnl_bp)
    assert saved["control_mean_bp"] != "-9.0"  # P5 uses pnl_bp, not conservative marking.


@pytest.mark.parametrize("incomplete", [False, True])
def test_b01_p5_control_summary_reconciles_with_saved_complete_pairs(
    tmp_path: Path, observation: exp.Observed, incomplete: bool
) -> None:
    rows = []
    cases = [(10.25, 2.25, 20), (2.75, -5.75, 20)]
    if incomplete:
        cases.extend([(1000.0, 999.0, 19), (0.0, 0.0, None)])
    for i, (pnl, control_mean, n_ok) in enumerate(cases):
        leg = replace(observation.leg, symbol=f"{600010 + i}", pnl_bp=pnl)
        control = (
            sim.RLeg(leg.entry_day, leg.direction, control_mean, -9.0, n_ok)
            if n_ok is not None
            else None
        )
        rows.append(replace(observation, leg=leg, control=control))
    summary = verdict(rows)
    p5 = summary["criteria"]["P5"]
    destination = tmp_path / "synthetic"
    outputs.publish_run(
        destination,
        trials=[],
        legs=runner._leg_rows([phase(rows)], [observation.entry_date] * 40),
        summary=dict.fromkeys(outputs.SUMMARY_FIELDS) | summary,
    )
    with (destination / "legs.csv").open(encoding="utf-8", newline="") as stream:
        complete = [row for row in csv.DictReader(stream) if row["control_n_ok"] == "20"]
    assert p5["paired"]["n"] == len(complete) == 2
    assert p5["paired"]["mean"] == mean(
        float(row["pnl_bp"]) - float(row["control_mean_bp"]) for row in complete
    )
    assert p5["control_mean_bp"] == mean(float(row["control_mean_bp"]) for row in complete)
    assert p5["control_n_ok"] == sum(int(row["control_n_ok"]) for row in complete) == 40
    assert p5["control_n_ok_unit"] == "successful_random_draws"
    assert p5["status"] == ("unknown" if incomplete else "pass")
    saved = json.loads((destination / "summary.json").read_text(encoding="utf-8"))
    assert saved["criteria"]["P5"] == p5


@pytest.mark.parametrize("n_ok", [None, 0, 19])
def test_b01_p5_without_complete_pairs_remains_unknown(
    observation: exp.Observed, n_ok: int | None
) -> None:
    control = (
        sim.RLeg(observation.leg.entry_day, observation.leg.direction, float("nan"), -9.0, n_ok)
        if n_ok is not None
        else None
    )
    p5 = verdict([replace(observation, control=control)])["criteria"]["P5"]
    assert p5["control_mean_bp"] is None
    assert p5["control_n_ok"] == p5["paired"]["n"] == 0
    assert p5["status"] == "unknown"


@pytest.mark.parametrize("field", ["entry_day", "direction"])
def test_b01_refuses_to_publish_a_control_paired_to_a_different_leg(
    tmp_path: Path, observation: exp.Observed, field: str
) -> None:
    control = sim.RLeg(observation.leg.entry_day, observation.leg.direction, 1.0, 1.0, 20)
    control = replace(control, **{field: -1 if field == "entry_day" else "buy_first"})
    row = replace(observation, control=control)
    target = tmp_path / "synthetic"
    with pytest.raises(data.DataFormatError, match="R control does not match its leg"):
        outputs.publish_run(
            target,
            trials=[],
            legs=runner._leg_rows([phase([row])], [row.entry_date] * 40),
            summary=dict.fromkeys(outputs.SUMMARY_FIELDS),
        )
    assert list(tmp_path.iterdir()) == []
