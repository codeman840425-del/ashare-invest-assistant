# ruff: noqa: S101
"""T-T84 independent runner publication tests; only synthetic inputs and tmp_path.

preflight/iter_stocks are injected at the data boundary; runner, strategy no-sample
path, projections, summary writer, CSV writer, atomic publication are real.
"""
from __future__ import annotations

import csv
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from retest.t_r58 import data, inputs, outputs, runner, runner_data, sim, splice
from retest.t_r58.errors import DataFormatError


def builders():
    spec = importlib.util.spec_from_file_location("tt84_synthetic", Path(__file__).with_name("test_splice_validation.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source(root: Path) -> runner_data.ResearchPaths:
    return runner_data.ResearchPaths(root, root / "single", root / "main", root / "calendar")


def fake_inputs(root: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    dates = [date(2024, 3, 1) + timedelta(days=i) for i in range(12)]
    segments = [sim.Segment(f"fold{i + 1}", dates[2 * i], dates[2 * i + 1]) for i in range(5)]
    segments.append(sim.Segment("holdout", dates[10], dates[11], embargo=False))
    package = inputs.VipdocInput(root, {}, "", "", "")
    prepared = runner_data.Prepared(dates, segments, [], root, {}, package, package, root, "", {},
        dict.fromkeys(dates, 10.0), {}, {}, {}, {"segments": {}, "stock_pool": {"delisted_hf": 0}})
    monkeypatch.setattr(runner_data, "preflight", lambda *a, **k: prepared)
    monkeypatch.setattr(runner_data, "iter_stocks", lambda _: iter(()))
    return {"dates": dates, "prepared": prepared}


def strict_json(path: Path) -> dict:
    def forbidden(value: str) -> None:
        pytest.fail("non-standard JSON number: " + value)
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=forbidden)


def test_tt84_actual_runner_writes_three_files_and_full_family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_inputs(tmp_path, monkeypatch)
    target = tmp_path / "complete"
    assert runner.run(source(tmp_path), target) == target
    assert {p.name for p in target.iterdir()} == {"trials.csv", "legs.csv", "summary.json"}
    summary = strict_json(target / "summary.json")
    assert summary.keys() >= outputs.SUMMARY_FIELDS
    assert summary["conclusion"]["status"] == "data_insufficient"
    assert summary["conclusion"]["promote"] is False
    assert summary["splice"] == []  # accurately records no synthetic stocks, not fabricated success
    for filename, fields in (("trials.csv", outputs.TRIAL_FIELDS), ("legs.csv", outputs.LEG_FIELDS)):
        with (target / filename).open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            assert tuple(reader.fieldnames) == fields
            rows = list(reader)
        if filename == "trials.csv":
            assert len([r for r in rows if r["holm_family"] == "True"]) == 34
            assert all(r["phase"] != "holdout" for r in rows)
        else:
            assert rows == []
    assert list(tmp_path.glob(".t-r58-*")) == []
    assert not outputs.failure_path(target).exists()


def test_tt84_real_splice_payload_flows_to_runner_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import numpy as np
    bld = builders()
    HfBuilder, Lc1Builder = bld.HfBuilder, bld.Lc1Builder
    hf_anchor, HF_END, VIP_SINGLE_DAY = bld.hf_anchor, bld.HF_END, bld.VIP_SINGLE_DAY
    dates = fake_inputs(tmp_path, monkeypatch)["dates"]
    hf = HfBuilder()
    hf.add_day(HF_END, "600000")
    builder = Lc1Builder()
    builder.add_day(VIP_SINGLE_DAY)
    single, _ = splice.decode_lc1(builder.write(tmp_path / "bars", "sh", "600000"), "SH", "600000")
    verified = splice.check_splice(hf.table(), single, splice.empty_table(), hf_anchor(),
                                   exchange="SH", symbol="600000", require_overlap=False)["splice"]
    shape = (len(dates), 240)
    price = np.full(shape, 10.)
    stock = sim.StockInput("SH", "600000", dates, price, price + .01, price - .01, price,
        np.full(shape, 10000.), np.full(shape, 100000.), np.full(len(dates), sim.EXCLUDED),
        np.zeros(len(dates), dtype=bool), [])
    evidence = {"splice": verified, "lc1": {"main": {"source_sha256": "synthetic"}},
        "listing": {}, "exrights": {"checked": 0, "uncheckable": 0},
        "exclusions": {"stock_days": {}, "all": {}}, "outside_dates": 0,
        "missing_bars": 0, "bar_ok_failed": 0}
    monkeypatch.setattr(runner_data, "iter_stocks", lambda _: iter([(stock, evidence)]))
    target = tmp_path / "splice-success"
    runner.run(source(tmp_path), target)
    saved = strict_json(target / "summary.json")
    assert len(saved["splice"]) == 1
    assert saved["splice"][0]["ok"] is True
    assert saved["splice"][0]["single_day"] == verified["single_day"]


def test_tt84_missing_input_publishes_only_failure(tmp_path: Path) -> None:
    target = tmp_path / "missing"
    with pytest.raises(DataFormatError):
        runner.run(source(tmp_path), target)
    assert not target.exists()
    failed = outputs.failure_path(target)
    assert {p.name for p in failed.iterdir()} == {"failure.json"}
    assert strict_json(failed / "failure.json")["stage"] == "inputs"


def test_tt84_real_splice_failure_is_separate_and_never_simulates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bld = builders()
    HfBuilder, Lc1Builder = bld.HfBuilder, bld.Lc1Builder
    hf_anchor, HF_END, VIP_SINGLE_DAY = bld.hf_anchor, bld.HF_END, bld.VIP_SINGLE_DAY
    fake_inputs(tmp_path, monkeypatch)
    hf = HfBuilder()
    hf.add_day(HF_END, "600000")
    b = Lc1Builder()
    b.add_day(VIP_SINGLE_DAY, base=20)
    single, _ = splice.decode_lc1(b.write(tmp_path / "bars", "sh", "600000"), "SH", "600000")
    def broken(_):
        splice.check_splice(hf.table(), single, splice.empty_table(), hf_anchor(),
                             exchange="SH", symbol="600000", require_overlap=False)
        pytest.fail("bad splice accepted")
    def forbidden(*a, **k):
        pytest.fail("walk_forward called after splice failure")
    monkeypatch.setattr(runner_data, "iter_stocks", broken)
    monkeypatch.setattr(runner.exp, "walk_forward", forbidden)
    target = tmp_path / "blocked"
    with pytest.raises(splice.SpliceError) as error:
        runner.run(source(tmp_path), target)
    assert not target.exists()
    failed = outputs.failure_path(target)
    assert {p.name for p in failed.iterdir()} == {"failure.json"}
    saved = strict_json(failed / "failure.json")
    assert saved["stage"] == "splice" and saved["status"] == "blocked"
    assert saved["splice"] == error.value.summary["splice"]
    assert saved["splice"]["failures"]
    assert list(tmp_path.glob(".t-r58-*")) == []


@pytest.mark.parametrize("bad_file", ["trials.csv", "legs.csv", "summary.json"])
def test_tt84_invalid_schema_never_publishes_partial_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_file: str) -> None:
    fake_inputs(tmp_path, monkeypatch)
    if bad_file == "summary.json":
        from retest.t_r58 import judgement
        monkeypatch.setattr(judgement, "evaluate", lambda *a, **k: {})
    else:
        function = "_trial_rows" if bad_file == "trials.csv" else "_leg_rows"
        monkeypatch.setattr(runner, function, lambda *a, **k: iter([{"unexpected": 1}]))
    target = tmp_path / "schema"
    with pytest.raises(DataFormatError):
        runner.run(source(tmp_path), target)
    assert not target.exists()
    failed = outputs.failure_path(target)
    assert {p.name for p in failed.iterdir()} == {"failure.json"}
    assert strict_json(failed / "failure.json")["stage"] == "write_results"
    assert list(tmp_path.glob(".t-r58-*")) == []
    assert not list(tmp_path.glob(".*.publishing"))


@pytest.mark.parametrize("first_failed", [False, True])
def test_tt84_output_names_cannot_mix_success_and_failure(tmp_path: Path, first_failed: bool) -> None:
    target = tmp_path / "once"
    payload = dict.fromkeys(outputs.SUMMARY_FIELDS) | {"splice": {"ok": True}}
    def success():
        return outputs.publish_run(target, trials=[], legs=[], summary=payload)
    def failure():
        return outputs.publish_failure(target, stage="splice", error=DataFormatError("synthetic"))
    first, second = (failure, success) if first_failed else (success, failure)
    written = first()
    before = {p.name: p.read_bytes() for p in written.iterdir()}
    with pytest.raises(FileExistsError):
        second()
    assert {p.name: p.read_bytes() for p in written.iterdir()} == before
    assert target.exists() is (not first_failed)
    assert outputs.failure_path(target).exists() is first_failed
