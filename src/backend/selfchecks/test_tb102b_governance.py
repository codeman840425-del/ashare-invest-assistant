"""T-B102b product-only R1/R2/R3/R5 boundary negatives, real POSIX files, zero HTTP."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any

import pytest

from app.ingest import daily_lists, send_control
from app.ingest.shared_gate import GateClosedError, SharedGate
from selfchecks import test_tb102_governance as previous
from selfchecks.test_tb102_governance import dispatch, logs, records

env = previous.env


def private(path: Any, value: Any) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    os.chmod(path, 0o600)


@pytest.mark.parametrize("enforce", [True, False])
@pytest.mark.parametrize("case", ["103", "429", "symlink", "dangling", "corrupt"])
def test_tb102b_r2_any_probe_halt_stops_or_observes(env: Any, enforce: bool, case: str) -> None:
    e = env
    halt = e.root / "unrelated-source.halt.json"
    if case in {"symlink", "dangling"}:
        target = e.root / "halt-target"
        if case == "symlink":
            private(target, {"code": "unrelated"})
        halt.symlink_to(target)
    elif case == "corrupt":
        halt.write_text("{truncated", encoding="utf-8")
        os.chmod(halt, 0o600)
    else:
        private(halt, {"code": int(case), "licence_id": "must-not-be-parsed"})
    before = halt.lstat()
    if enforce:
        with pytest.raises(GateClosedError, match="stop_refused"):
            dispatch(e)
        assert e.calls == []
    else:
        dispatch(e, enforce=False)
        assert len(e.calls) == 1
    assert halt.lstat().st_ino == before.st_ino
    assert len(records(e)) == 1
    hit = logs(e)[0]
    assert hit["code"] == ("blocked_stop" if enforce else "bypass_stop_would_block")
    assert hit["snapshot"]["reason"] == "probe_halt_present"
    assert hit["snapshot"]["probe_halt_present"] is True
    assert "must-not-be-parsed" not in e.caplog.text


def test_tb102b_r2_nonlimit_halt_does_not_stop(env: Any) -> None:
    private(env.root / "source.halt.json", {"code": "102"})
    dispatch(env)
    assert len(env.calls) == 1
    assert logs(env) == []


@pytest.mark.parametrize("enforce", [True, False])
@pytest.mark.parametrize("case", ["inflight", "minute", "interval"])
def test_tb102b_r3_minute_guards_and_bypass_accounting(env: Any, enforce: bool, case: str) -> None:
    e = env
    now = e.now[0].timestamp()
    state = {"calls": [], "inflight": case == "inflight", "last_finished": 0}
    if case == "minute":
        state["calls"] = [now - 1] * 150
    if case == "interval":
        state["last_finished"] = now - 59
    path = e.root / f"{e.lid}.requests.json"
    private(path, state)
    before = path.read_bytes()
    if enforce:
        with pytest.raises(GateClosedError):
            dispatch(e)
        assert e.calls == records(e) == []
        assert path.read_bytes() == before
    else:
        dispatch(e, enforce=False)
        after = json.loads(path.read_text())
        assert after["calls"] == state["calls"] + [now]
        assert after["inflight"] is (case == "inflight")
        assert after["last_finished"] == now
        assert len(e.calls) == len(records(e)) == 1
    reason = {
        "inflight": "shared_prior_request_uncertain",
        "minute": "shared_minute_budget_exhausted",
        "interval": "shared_product_interval_not_elapsed",
    }[case]
    hit = logs(e)[0]
    assert hit["snapshot"]["reason"] == reason
    assert hit["code"] == (
        ("blocked_daily" if enforce else "bypass_daily_would_block")
        if case == "interval"
        else ("skipped_lock" if enforce else "bypass_lock_would_block")
    )


def test_tb102b_r3_sixty_second_equal_boundary_and_policy_limit(env: Any) -> None:
    e = env
    now = e.now[0].timestamp()
    path = e.root / f"{e.lid}.requests.json"
    private(path, {"calls": [now - 60] * 150, "inflight": False, "last_finished": now - 60})
    dispatch(e)
    assert json.loads(path.read_text())["calls"] == [now]
    e.now[0] += dt.timedelta(seconds=60)
    dispatch(e, dataset="bj_list")
    assert len(e.calls) == 2


@pytest.mark.parametrize("enforce", [True, False])
@pytest.mark.parametrize("case", ["symlink", "dangling", "mode", "hardlink"])
def test_tb102b_r1_unsafe_lease_always_closed(env: Any, enforce: bool, case: str) -> None:
    e = env
    lease = e.root / "single-egress.lease.json"
    if case in {"symlink", "dangling"}:
        target = e.root / "lease-target"
        if case == "symlink":
            private(target, {"source": "probe_f21"})
        lease.symlink_to(target)
    else:
        private(lease, {"source": "probe_f21"})
        if case == "mode":
            os.chmod(lease, 0o644)
        else:
            os.link(lease, e.root / "lease-copy")
    with pytest.raises(GateClosedError, match="shared_control_lease_invalid"):
        dispatch(e, enforce=enforce)
    assert records(e) == e.calls == []


@pytest.mark.parametrize("enforce", [True, False])
@pytest.mark.parametrize("name", ["single-egress.lease.json", "probe-waiting.lease.json"])
def test_tb102b_r1_probe_lease_busy_even_in_bypass(env: Any, enforce: bool, name: str) -> None:
    e = env
    private(e.root / name, {"source": "probe_f21", "token": "synthetic"})
    with pytest.raises(GateClosedError, match="shared_control_busy"):
        dispatch(e, enforce=enforce)
    assert records(e) == e.calls == []
    assert logs(e)[0]["snapshot"]["legacy_lease_present"] is True


def test_tb102b_r1_wire_requires_the_same_owned_inode(env: Any, monkeypatch: Any) -> None:
    e = env
    gate = SharedGate(e.root, e.lid, "product_verify")
    gate.inflight = True
    monkeypatch.setenv("MAIRUI_MODE", "live")
    context = daily_lists.WIRE_GATE.set(gate)
    try:
        with pytest.raises(GateClosedError, match="shared_control_not_owned"):
            daily_lists.wire("/tcalendar/list/2031/", "synthetic")
        with send_control.critical(e.root):
            (e.root / "single-egress.lease.json").symlink_to(e.root / "missing")
            with pytest.raises(GateClosedError, match="lease_invalid"):
                daily_lists.wire("/tcalendar/list/2031/", "synthetic")
    finally:
        daily_lists.WIRE_GATE.reset(context)


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102b_r5_two_ledger_columns_readonly_in_both_modes(env: Any, enforce: bool) -> None:
    e = env
    path = e.root / "mairui-batch-T-B86.count"
    private(
        path,
        {
            "schema": "T-B86/v1",
            "total": 1,
            "halted": False,
            "records": [
                {
                    "id": "synthetic.one",
                    "segment": "f21_trading_window",
                    "interface": "transaction",
                },
            ],
        },
    )
    before = path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns
    dispatch(e, enforce=enforce)
    rows = [
        json.loads(r.getMessage().split("send_governance ", 1)[1])
        for r in e.caplog.records
        if r.name == "app.ingest.send_governance"
    ]
    snapshot = rows[-1]["snapshot"]
    assert rows[-1]["code"] == "send_snapshot"
    assert snapshot["ledger128_total"] == 1
    assert snapshot["ledger_total"] == 0
    assert snapshot["ledger_total_after"] == 1
    assert (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102b_r3_unknown_minute_state_not_reset(env: Any, enforce: bool) -> None:
    e = env
    path = e.root / f"{e.lid}.requests.json"
    private(path, {"calls": "unknown", "inflight": False})
    before = path.read_bytes()
    with pytest.raises(GateClosedError, match="minute_state_unavailable"):
        dispatch(e, enforce=enforce)
    assert path.read_bytes() == before
    assert records(e) == e.calls == []
