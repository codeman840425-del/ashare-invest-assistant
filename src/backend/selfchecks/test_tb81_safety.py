# ruff: noqa: S101
"""Pure synthetic control checks; never loads a real credential or sends a request."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "tb81_probe", Path(__file__).resolve().parents[1] / "probes/tb81.py"
)
assert spec
assert spec.loader
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_stop_and_call_budget(tmp_path: Path) -> None:
    stop = tmp_path / "STOP"
    budget = probe.Budget()
    stop.touch()
    with pytest.raises(probe.HaltError, match="STOP_present"):
        budget.reserve("test", stop)
    assert budget.calls == 0
    stop.unlink()
    for i in range(30):
        budget.reserve(str(i), stop)
    with pytest.raises(probe.HaltError, match="budget_exhausted"):
        budget.reserve("extra", stop)
    assert budget.calls == 30


def test_family_limit_and_single_connection(tmp_path: Path) -> None:
    budget = probe.Budget()
    for _ in range(2):
        budget.reserve("daily", tmp_path / "STOP")
    with pytest.raises(probe.HaltError, match="budget_exhausted"):
        budget.reserve("daily", tmp_path / "STOP")
    budget.connect()
    with pytest.raises(probe.HaltError, match="single_connection_closed"):
        budget.connect()
    assert budget.connections == 1


@pytest.mark.parametrize(
    "body",
    [{"code": 103}, {"data": {"error_code": "429"}}, "103:limited", {"error": "103：limited"}],
)
def test_business_limits(body: object) -> None:
    assert probe.business_limit(body)


def test_small_plan_and_no_other_codes() -> None:
    assert len(probe.PLAN) == 11
    assert sum(row[1] == "daily" for row in probe.PLAN) == 2
    assert all(
        any(code in row[2] for code in ["688018", "300364", "000300"]) or row[1].endswith("catalog")
        for row in probe.PLAN
    )


_evidence_spec = importlib.util.spec_from_file_location(
    "tb81_evidence", Path(__file__).resolve().parents[1] / "probes/tb81_evidence.py"
)
assert _evidence_spec
assert _evidence_spec.loader
evidence = importlib.util.module_from_spec(_evidence_spec)
_evidence_spec.loader.exec_module(evidence)


def test_evidence_amount_scale() -> None:
    result = evidence.amount_check([{"a": 110000, "v": 100, "l": 10, "h": 12}])
    assert result["price_bounds_pass"]["1"] == 1
    assert sum(result["price_bounds_pass"].values()) == 1
    assert "independent absolute scales" in result["absolute_unit_caveat"]


def test_evidence_flow_missing_never_partial_sum() -> None:
    window = [f"2026-01-{i:02d}" for i in range(1, 21)]
    rows = [{"t": d, "zmbtdcje": 10, "zmbddcje": 3, "zmstdcje": 2, "zmsddcje": 1} for d in window]
    assert evidence.flow_check(rows, window)["sum_raw_units"] == "200"
    assert evidence.flow_check(rows[:-1], window)["sum_raw_units"] is None
    rows[-1]["zmbddcje"] = None
    assert evidence.flow_check(rows, window)["sum_raw_units"] is None


@pytest.mark.parametrize("stop_present", [True, False])
def test_cleanup_on_synthetic_abort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stop_present: bool,
) -> None:
    fake_secret = tmp_path / "authorized_synthetic.tmp"
    fake_secret.write_text("synthetic_never_real_value")
    fake_secret.chmod(0o600)
    stop = tmp_path / "STOP"
    if stop_present:
        stop.touch()
    monkeypatch.setattr(probe, "HERE", tmp_path)
    monkeypatch.setattr(probe, "SECRET", fake_secret)
    monkeypatch.setattr(probe, "STOP", stop)
    monkeypatch.setattr(probe.signal, "signal", lambda *_: None)
    monkeypatch.setattr(probe.logging, "disable", lambda *_: None)

    class SyntheticSession:
        def mount(self, *_: object) -> None:
            pass

        def get(self, *args: object, **_kwargs: object) -> None:
            raise RuntimeError(str(args))

        def close(self) -> None:
            raise RuntimeError("synthetic_close_error")

    monkeypatch.setattr(probe.requests, "Session", SyntheticSession)
    assert probe.main() == 2
    assert not fake_secret.exists()
    assert stop.exists() == stop_present
    output = capsys.readouterr().out
    assert "synthetic_never_real_value" not in output
    assert '"temporary_secret_deleted": true' in output
