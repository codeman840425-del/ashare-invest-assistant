# ruff: noqa: S101, SIM117
"""Only synthetic ledger controls. No live runner, real counter, env or certificate."""

import json
import socket
import sys
from contextlib import AbstractContextManager
from pathlib import Path

import pytest

if sys.platform == "win32":
    pytest.skip("T-B86 offline requires POSIX flock and file permissions", allow_module_level=True)

from probes import tb86_offline as probe


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network forbidden in offline checks")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    path = tmp_path / "synthetic.count"
    # Known synthetic fixture only. Production module has no initializer/reset.
    path.write_text(
        json.dumps({"schema": probe.SCHEMA, "total": 0, "records": [], "halted": False})
    )
    path.chmod(0o600)
    return path


def reserve(ledger: Path, identifier: str = "synthetic-one") -> AbstractContextManager[int]:
    return probe.reservation(
        ledger,
        ledger.parent / "STOP",
        "history_actions",
        "daily",
        identifier,
        enabled_segments=frozenset({"history_actions"}),
    )


def test_default_disabled_and_main_no_side_effect(
    ledger: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(probe.HaltError, match="segment_not_released"):
        with probe.reservation(
            ledger, ledger.parent / "STOP", "history_actions", "daily", "synthetic"
        ):
            pytest.fail("unreleased")
    assert probe.main() == 2
    assert "offline_only_waiting_personal_authorization" in capsys.readouterr().out
    assert json.loads(ledger.read_text())["total"] == 0


def test_durable_reservation_consumed_and_no_replay(ledger: Path) -> None:
    with reserve(ledger) as number:
        assert number == 1
        assert json.loads(ledger.read_text())["total"] == 1
    with pytest.raises(probe.HaltError, match="already_consumed"), reserve(ledger):
        pytest.fail("retry")
    assert json.loads(ledger.read_text())["total"] == 1


def test_nonblocking_lock_covers_dispatch(ledger: Path) -> None:
    with reserve(ledger):
        with pytest.raises(probe.HaltError, match="unavailable"), reserve(ledger, "synthetic-two"):
            pytest.fail("parallel dispatch")
    assert json.loads(ledger.read_text())["total"] == 1


def test_stop_no_mutation(ledger: Path) -> None:
    stop = ledger.parent / "STOP"
    stop.touch()
    with pytest.raises(probe.HaltError, match="STOP_present"), reserve(ledger):
        pytest.fail("STOP")
    assert stop.exists()
    assert json.loads(ledger.read_text())["total"] == 0


def test_budget_no_reset_on_restart(ledger: Path) -> None:
    for i in range(2):
        with reserve(ledger, f"synthetic-{i}"):
            pass
    with (
        pytest.raises(probe.HaltError, match="budget_exhausted"),
        reserve(ledger, "synthetic-three"),
    ):
        pytest.fail("over budget")
    assert json.loads(ledger.read_text())["total"] == 2


@pytest.mark.parametrize("payload", ["0", "{}", "{broken", '{"total":4}'])
def test_unknown_counts_never_reset(ledger: Path, payload: str) -> None:
    ledger.write_text(payload)
    with pytest.raises(probe.HaltError), reserve(ledger):
        pytest.fail("unknown counter")
    assert ledger.read_text() == payload


def test_missing_counter_not_created(tmp_path: Path) -> None:
    path = tmp_path / "missing.count"
    with pytest.raises(probe.HaltError), reserve(path):
        pytest.fail("unknown missing state")
    assert not path.exists()


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (103, {}),
        (429, {}),
        (200, {"data": {"code": 103}}),
        (200, {"error_code": "429"}),
        (302, {}),
        (200, {"code": 500}),
        (200, {"status": "failed"}),
        (200, None),
    ],
)
def test_bad_response_halts_entire_batch_and_redacts(
    ledger: Path, status: int, body: object
) -> None:
    with pytest.raises(probe.HaltError, match="aborted_no_retry"), reserve(ledger):
        probe.validate_response(status, body)
    assert json.loads(ledger.read_text())["halted"]
    with pytest.raises(probe.HaltError, match="batch_halted"):
        with probe.reservation(
            ledger,
            ledger.parent / "STOP",
            "history_suspension",
            "daily",
            "later",
            enabled_segments=frozenset({"history_suspension"}),
        ):
            pytest.fail("continued other interface")
    assert json.loads(ledger.read_text())["total"] == 1


def test_untrusted_exception_not_saved_or_exposed(ledger: Path) -> None:
    with pytest.raises(probe.HaltError) as exc, reserve(ledger):
        raise RuntimeError("synthetic-sensitive-url-never-render")
    assert "synthetic-sensitive-url" not in str(exc.value)
    assert "synthetic-sensitive-url" not in ledger.read_text()
    assert exc.value.__suppress_context__


def test_fsync_precedes_dispatch_and_second_stop_consumes(
    ledger: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = probe.os.fsync
    calls = []

    def synced(fd: int) -> None:
        real(fd)
        calls.append("persisted")
        (ledger.parent / "STOP").touch()

    monkeypatch.setattr(probe.os, "fsync", synced)
    with pytest.raises(probe.HaltError, match="aborted_no_retry"), reserve(ledger):
        pytest.fail("STOP after reservation must prevent dispatch")
    assert calls
    assert json.loads(ledger.read_text())["total"] == 1
    assert json.loads(ledger.read_text())["halted"]
    assert (ledger.parent / "STOP").exists()


def test_no_budget_redistribution_and_deferred_defaults() -> None:
    assert probe.TOTAL_CAP == 128
    assert sum(sum(v.values()) for v in probe.CAPS.values()) == 126
    assert sum(probe.CAPS["history_actions"].values()) == 4
    assert sum(probe.CAPS["history_suspension"].values()) == 2
    assert probe.CAPS["f21_trading_window"]["transaction"] == 10
    assert probe.CAPS["f23_freshness"]["announcements"] == 100
    probe.validate_response(200, [{"synthetic": 1}])


@pytest.mark.parametrize("kind", ["wrong_permissions", "symlink", "hardlink"])
def test_unsafe_counter_rejected_without_modification(ledger: Path, kind: str) -> None:
    original = ledger.read_text()
    selected = ledger
    if kind == "wrong_permissions":
        ledger.chmod(0o644)
    elif kind == "symlink":
        selected = ledger.parent / "symbolic.count"
        selected.symlink_to(ledger)
    else:
        selected = ledger.parent / "hard.count"
        selected.hardlink_to(ledger)
    with pytest.raises(probe.HaltError), reserve(selected):
        pytest.fail("unsafe counter")
    assert ledger.read_text() == original


def test_offline_entrypoint_cannot_read_environment_or_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny(*_args: object, **_kwargs: object) -> None:
        pytest.fail("offline entrypoint accessed environment or filesystem")

    with monkeypatch.context() as scoped:
        scoped.setattr(probe.os, "open", deny)
        scoped.setattr(probe.os, "getenv", deny)
        scoped.setattr(Path, "open", deny)
        assert probe.main() == 2


def test_plan_has_no_released_live_segment() -> None:
    assert len(probe.EVIDENCE_PLAN) == 5
    assert all("pending" in state for _segment, _evidence, state in probe.EVIDENCE_PLAN)
    assert {row[0] for row in probe.EVIDENCE_PLAN} == set(probe.CAPS)


@pytest.mark.parametrize("body", [103, "429", "103", 429])
def test_scalar_limit_codes_halt(ledger: Path, body: object) -> None:
    with pytest.raises(probe.HaltError, match="aborted_no_retry"), reserve(ledger):
        probe.validate_response(200, body)
    assert json.loads(ledger.read_text())["halted"]
