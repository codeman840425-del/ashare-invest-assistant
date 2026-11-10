# ruff: noqa: S101
"""T-R58d output contract and failure isolation, with synthetic payloads."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from retest.t_r58 import outputs, splice
from retest.t_r58.errors import DataFormatError


def summary() -> dict:
    return dict.fromkeys(outputs.SUMMARY_FIELDS) | {"seed": 136, "criteria": {"P5": float("nan")}}


def test_tb136_output_three_files_and_strict_json(tmp_path: Path) -> None:
    destination = tmp_path / "success"
    trial = dict.fromkeys(outputs.TRIAL_FIELDS) | {"trial_id": "a01", "mean_bp": float("nan")}
    leg = dict.fromkeys(outputs.LEG_FIELDS) | {"trial_id": "a01", "entry_price": 10.30}
    outputs.publish_run(destination, trials=[trial], legs=[leg], summary=summary())
    assert {p.name for p in destination.iterdir()} == {"summary.json", "legs.csv", "trials.csv"}
    assert json.loads((destination / "summary.json").read_text(encoding="utf-8"))["criteria"] == {
        "P5": None
    }
    with (destination / "trials.csv").open(encoding="utf-8", newline="") as stream:
        assert next(csv.DictReader(stream))["mean_bp"] == ""
    with (destination / "legs.csv").open(encoding="utf-8", newline="") as stream:
        assert next(csv.DictReader(stream))["entry_price"] == "10.3"
    with pytest.raises(FileExistsError):
        outputs.publish_failure(destination, stage="splice", error=DataFormatError("failure"))
    assert not outputs.failure_path(destination).exists()


def test_tb136_output_failed_splice_payload_has_no_success_artifacts(tmp_path: Path) -> None:
    destination = tmp_path / "run"
    error = splice.SpliceError("600000", {"failures": ["single_day.daily_close"], "ok": False})
    failure = outputs.publish_failure(destination, stage="splice", error=error)
    assert not destination.exists()
    assert {p.name for p in failure.iterdir()} == {"failure.json"}
    payload = json.loads((failure / "failure.json").read_text(encoding="utf-8"))
    assert payload["splice"] == error.summary["splice"]
    assert payload["status"] == "blocked"
    with pytest.raises(FileExistsError):
        outputs.publish_run(destination, trials=[], legs=[], summary=summary())


def test_tb136_output_incomplete_write_leaves_no_partial_artifact(tmp_path: Path) -> None:
    destination = tmp_path / "run"
    with pytest.raises(DataFormatError, match=r"columns for legs\.csv"):
        outputs.publish_run(destination, trials=[], legs=[{"bad": 1}], summary=summary())
    assert list(tmp_path.iterdir()) == []


def test_tb136_output_shared_reservation_blocks_both_publishers(tmp_path: Path) -> None:
    destination = tmp_path / "run"
    (tmp_path / ".run.publishing").mkdir()
    with pytest.raises(FileExistsError):
        outputs.publish_run(destination, trials=[], legs=[], summary=summary())
    with pytest.raises(FileExistsError):
        outputs.publish_failure(destination, stage="splice", error=DataFormatError("failure"))
    assert not destination.exists()
    assert not outputs.failure_path(destination).exists()
