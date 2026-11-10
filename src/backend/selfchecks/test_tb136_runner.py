# ruff: noqa: S101
"""Exercise the offline entry point through output publication with synthetic input."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from retest.t_r58 import data, experiments, outputs, runner, runner_data, sim, splice
from selfchecks import tb136_retest as synthetic


def paths(tmp_path: Path) -> runner_data.ResearchPaths:
    return runner_data.ResearchPaths(
        tmp_path, tmp_path / "single", tmp_path / "main", tmp_path / "cal"
    )


def test_tb136_runner_output_cannot_leave_offline_root(tmp_path: Path) -> None:
    offline = tmp_path / "offline"
    offline.mkdir()
    target = tmp_path / "outside"
    with pytest.raises(data.DataFormatError, match="offline data root"):
        runner.run(paths(offline), target)
    assert not target.exists()
    assert not outputs.failure_path(target).exists()


def test_tb136_runner_missing_input_publishes_only_failure(tmp_path: Path) -> None:
    target = tmp_path / "missing"
    with pytest.raises(data.DataFormatError, match="missing or unsafe"):
        runner.run(paths(tmp_path), target)
    assert not target.exists()
    failure = outputs.failure_path(target)
    assert {path.name for path in failure.iterdir()} == {"failure.json"}
    evidence = json.loads((failure / "failure.json").read_text(encoding="utf-8"))
    assert evidence["status"] == "blocked"
    assert evidence["stage"] == "inputs"


def test_tb136_runner_no_eligible_legs_writes_full_family_and_no_holdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    days = [date(2024, 3, 1) + timedelta(days=i) for i in range(12)]
    segments = [sim.Segment(f"fold{i + 1}", days[2 * i], days[2 * i + 1]) for i in range(5)]
    segments.append(sim.Segment("holdout", days[10], days[11], embargo=False))
    source = paths(tmp_path)
    empty = lambda root: runner_data.inputs.VipdocInput(root, {}, "", "", "")  # noqa: E731
    prepared = runner_data.Prepared(
        days,
        segments,
        [],
        tmp_path,
        {},
        empty(source.single_package),
        empty(source.main_package),
        tmp_path,
        "",
        {},
        dict.fromkeys(days, 10.0),
        {},
        {},
        {},
        {"segments": {}, "stock_pool": {"delisted_hf": 0}},
    )
    monkeypatch.setattr(runner_data, "preflight", lambda *a, **k: prepared)
    monkeypatch.setattr(runner_data, "iter_stocks", lambda _: iter(()))
    target = tmp_path / "synthetic"
    assert runner.run(source, target) == target
    assert not (tmp_path / "retest-holdout").exists()
    assert {path.name for path in target.iterdir()} == {"summary.json", "trials.csv", "legs.csv"}
    with (target / "trials.csv").open(newline="", encoding="utf-8") as stream:
        trials = list(csv.DictReader(stream))
    assert len([row for row in trials if row["holm_family"] == "True"]) == 34
    assert all(row["phase"] != "holdout" for row in trials)
    summary = json.loads((target / "summary.json").read_text(encoding="utf-8"))
    assert summary["criteria"]["P1"]["status"] == "fail"
    assert summary["conclusion"] == {
        "status": "data_insufficient",
        "promote": False,
        "reason": "P1 samples insufficient",
    }


def test_tb136_runner_leg_projection_matches_csv_schema() -> None:
    stock = synthetic._stock([*synthetic._base(), synthetic._sell_day(), synthetic._flat_day()])
    segments = synthetic._seg(stock)
    leg = sim.simulate(stock, synthetic.PB, segments)[0]
    candidate = experiments.Candidate("B01", synthetic.PB, (0,), "B")
    trial = experiments.Trial(
        candidate,
        [
            experiments.Observed(
                stock.exchange,
                stock.dates[leg.entry_day],
                leg,
            )
        ],
    )
    row = next(runner._leg_rows([experiments.Phase("evaluation", segments, [trial])], stock.dates))
    assert row.keys() == set(outputs.LEG_FIELDS)
    assert row["exit_trigger_date"] == stock.dates[leg.exit_trigger_day]
    assert row["entry_price"] == leg.entry_price


def test_tb136_runner_splice_failure_never_calls_walk_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "splice"

    def stop(_: object) -> None:
        raise splice.SpliceError("600001", {"ok": False, "failures": ["daily_open"]})

    def forbidden(*_: object) -> None:
        pytest.fail("strategy called after splice failure")

    monkeypatch.setattr(runner_data, "preflight", lambda *a, **k: object())
    monkeypatch.setattr(runner_data, "iter_stocks", stop)
    monkeypatch.setattr(experiments, "walk_forward", forbidden)
    with pytest.raises(splice.SpliceError):
        runner.run(paths(tmp_path), target)
    assert not target.exists()
    failure = outputs.failure_path(target)
    assert {path.name for path in failure.iterdir()} == {"failure.json"}
    evidence = json.loads((failure / "failure.json").read_text(encoding="utf-8"))
    assert evidence["stage"] == "splice"
    assert evidence["splice"]["failures"] == ["daily_open"]


def test_tb136_runner_holdout_reservation_survives_a_new_attempt(tmp_path: Path) -> None:
    prepared = SimpleNamespace(evidence={"hf": {}, "vipdoc_single": {}, "vipdoc_main": {}})
    config = {"plan": {"commit": "synthetic"}}
    candidate = experiments.Candidate("A", synthetic.PB, (0,), "A")
    choice = experiments.Choice(candidate, None, None, None, ("sell_first",), False)
    scope = {"X": {"bracket": [10000, 50000]}, "Y": {"bracket": None}}
    runner._freeze(paths(tmp_path), prepared, config, choice, [candidate], scope)
    with pytest.raises(FileExistsError):
        runner._freeze(paths(tmp_path), prepared, config, choice, [candidate], {})
    lock = next((tmp_path / "retest-holdout").glob("*.json"))
    assert json.loads(lock.read_text(encoding="utf-8"))["training_scope"] == scope
