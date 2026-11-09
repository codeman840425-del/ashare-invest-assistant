"""T-B102 F1/F2/F4 real POSIX inodes/locks/fsync, synthetic accounting, zero network.

F3 uses the unchanged probe module and its original schema/caps; product lists
never consume that ledger. These tests do not initialize or open real ledgers.
"""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import socket
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.config_files import SendGovernance
from app.ingest import daily_lists, send_control
from app.ingest.send_governance import BEIJING, DATASETS, Governance
from app.ingest.shared_gate import GateClosedError, SharedGate, write_stop
from probes import tb86_offline as batch


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: Any) -> Any:
    root = tmp_path / "shared"
    root.mkdir(mode=0o700)
    os.chmod(root, 0o700)
    counter = root / "daily_lists.count"
    counter.write_text(json.dumps({"schema": "mairui-daily/v1", "records": []}), encoding="utf-8")
    os.chmod(counter, 0o600)
    lid = uuid.uuid4()
    (root / "policy.json").write_text(
        json.dumps(
            {
                "schema": "mairui-shared/v1",
                "egress_ip": "192.0.2.10",
                "licences": {str(lid): {"per_minute_limit": 150}},
            }
        ),
        encoding="utf-8",
    )
    now = [dt.datetime(2031, 1, 2, 18, tzinfo=BEIJING)]
    caplog.set_level("INFO", logger="app.ingest.send_governance")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("external network forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    return SimpleNamespace(root=root, counter=counter, lid=lid, now=now, calls=[], caplog=caplog)


def records(e: Any) -> list[Any]:
    return json.loads(e.counter.read_text(encoding="utf-8"))["records"]


def governance(e: Any, *, enforce: bool = True) -> Governance:
    return Governance(
        e.root,
        enforce=enforce,
        clock=lambda: e.now[0],
        licence_id=e.lid,
        ledger128=e.root / "mairui-batch-T-B86.count",
    )


def dispatch(
    e: Any, *, enforce: bool = True, dataset: str = "hslt_list", **kwargs: Any
) -> uuid.UUID:
    token = kwargs.pop("token", uuid.uuid4())
    control = governance(e, enforce=enforce)
    with control.dispatch(
        token=token, dataset=dataset, expected_day=e.now[0].date(), trading_day=True, **kwargs
    ) as permit:
        permit.check()
        assert records(e)[-1]["id"] == str(token)
        e.calls.append(token)
    return token


def logs(e: Any) -> list[Any]:
    return [
        json.loads(record.getMessage().split("send_governance ", 1)[1])
        for record in e.caplog.records
        if record.name == "app.ingest.send_governance"
        and '"would_block":true' in record.getMessage()
    ]


def test_tb102_config_defaults_observe_and_rejects_coercion() -> None:
    assert SendGovernance().enforce is False
    assert Settings(_env_file=None, app_env="test").business.ingest.send_governance.enforce is False
    with pytest.raises(ValidationError):
        SendGovernance(enforce="false")


def test_tb102_three_order_and_fourth_refused_before_dispatch(env: Any) -> None:
    e = env
    for dataset in DATASETS:
        dispatch(e, dataset=dataset)
        e.now[0] += dt.timedelta(seconds=60)
    with pytest.raises(GateClosedError, match="daily_refused"):
        dispatch(e)
    assert len(e.calls) == len(records(e)) == 3
    assert logs(e)[-1]["snapshot"]["daily_count"] == 3


def test_tb102_failure_counts_and_duplicate_never_replays(env: Any) -> None:
    e = env
    token = uuid.uuid4()

    def fail() -> None:
        with governance(e).dispatch(
            token=token, dataset="hslt_list", expected_day=e.now[0].date(), trading_day=True
        ):
            raise RuntimeError("synthetic HTTP error")

    with pytest.raises(RuntimeError, match="synthetic HTTP"):
        fail()
    assert len(records(e)) == 1
    e.now[0] += dt.timedelta(seconds=60)
    for enforce in (True, False):
        with pytest.raises(GateClosedError, match="already_consumed"):
            dispatch(e, token=token, enforce=enforce)
    assert len(records(e)) == 1


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_stop_counts_and_observe_only_bypasses_refusal(env: Any, enforce: bool) -> None:
    e = env
    write_stop(e.root / "STOP")
    if enforce:
        with pytest.raises(GateClosedError, match="stop_refused"):
            dispatch(e)
        assert e.calls == []
    else:
        dispatch(e, enforce=False)
        assert len(e.calls) == 1
    assert len(records(e)) == 1
    row = logs(e)[0]
    assert row["code"] == ("blocked_stop" if enforce else "bypass_stop_would_block")
    assert row["would_block"] is True
    assert row["snapshot"]["stop_0"] is True
    assert row["snapshot"]["reservation_id"] == records(e)[0]["id"]


@pytest.mark.parametrize(
    "case", ["empty", "truncated", "bad_schema", "missing", "mode", "symlink", "hardlink", "fifo"]
)
@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_unknown_or_unsafe_accounting_never_bypassed(
    env: Any, case: str, enforce: bool
) -> None:
    e = env
    if case in {"empty", "truncated", "bad_schema"}:
        e.counter.write_text(
            {"empty": "", "truncated": "{", "bad_schema": "{}"}[case], encoding="utf-8"
        )
    elif case == "missing":
        e.counter.unlink()
    elif case == "mode":
        os.chmod(e.counter, 0o644)
    elif case == "symlink":
        target = e.root / "original"
        e.counter.rename(target)
        e.counter.symlink_to(target)
    elif case == "hardlink":
        os.link(e.counter, e.root / "extra")
    else:
        e.counter.unlink()
        os.mkfifo(e.counter, 0o600)
    with pytest.raises(GateClosedError):
        dispatch(e, enforce=enforce)
    assert e.calls == []
    assert logs(e)[-1]["snapshot"]["accounting_unavailable"] is True
    if case == "missing":
        assert not e.counter.exists()  # Never creates a replacement zero ledger.


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_fsync_failure_never_reaches_connection(
    env: Any, monkeypatch: pytest.MonkeyPatch, enforce: bool
) -> None:
    e = env
    original = os.fsync

    def fail_counter(fd: int) -> None:
        if os.fstat(fd).st_ino == e.counter.stat().st_ino:
            raise OSError("synthetic fsync failure")
        original(fd)

    monkeypatch.setattr(os, "fsync", fail_counter)
    with pytest.raises(GateClosedError, match="write_failed"):
        dispatch(e, enforce=enforce)
    assert e.calls == []


def test_tb102_locks_and_fsync_span_actual_transport_boundary(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = env
    monkeypatch.setenv("MAIRUI_MODE", "live")
    synced = []
    original = os.fsync

    def fsync(fd: int) -> None:
        original(fd)
        if os.fstat(fd).st_ino == e.counter.stat().st_ino:
            synced.append(True)

    monkeypatch.setattr(os, "fsync", fsync)

    class Connection:
        def __init__(self, host: str, timeout: int) -> None:
            assert synced == [True]
            assert send_control.owned(e.root)
            for name in ("send-control.lock", "daily_lists.count"):
                fd = os.open(e.root / name, os.O_RDWR | os.O_NOFOLLOW)
                try:
                    with pytest.raises(BlockingIOError):
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    os.close(fd)
            e.calls.append(host)

        def set_debuglevel(self, level: int) -> None:
            pass

        def request(self, *args: Any, **kwargs: Any) -> None:
            pass

        def getresponse(self) -> Any:
            return SimpleNamespace(status=200, read=lambda count: b'[{"dm":"600519"}]')

        def close(self) -> None:
            pass

    monkeypatch.setattr(daily_lists.http.client, "HTTPSConnection", Connection)
    with governance(e).dispatch(
        token=uuid.uuid4(), dataset="hslt_list", expected_day=e.now[0].date(), trading_day=True
    ) as permit:
        status, body = daily_lists.send(permit, daily_lists.wire, "/hslt/list/", "synthetic-secret")
        assert status == 200
        assert isinstance(body, list)
    assert len(e.calls) == 1


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_lock_contention_uses_same_inode_and_observation_logs(
    env: Any, enforce: bool
) -> None:
    e = env
    lock = e.root / "send-control.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(GateClosedError, match="shared_control_busy"):
            dispatch(e, enforce=enforce)
        assert e.calls == records(e) == []
    finally:
        os.close(fd)


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_same_thread_reentry_always_refused(env: Any, enforce: bool) -> None:
    e = env
    with send_control.critical(e.root), pytest.raises(GateClosedError, match="reentry"):
        dispatch(e, enforce=enforce)
    assert e.calls == []
    assert records(e) == []


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_legacy_inflight_preserved_and_observed(env: Any, enforce: bool) -> None:
    e = env
    lease = e.root / "single-egress.lease.json"
    lease.write_text('{"synthetic":"unresolved"}', encoding="utf-8")
    os.chmod(lease, 0o600)
    original = lease.read_bytes()
    if enforce:
        with pytest.raises(GateClosedError, match="lock_refused"):
            dispatch(e)
    else:
        dispatch(e, enforce=False)
    assert lease.read_bytes() == original
    assert logs(e)[0]["snapshot"]["reason"] == "send_lock_or_uncertain_lease"


@pytest.mark.parametrize("kind", ["early", "deadline", "closed", "other_day", "interval"])
@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_window_day_interval_same_rules_both_modes(
    env: Any, kind: str, enforce: bool
) -> None:
    e = env
    control = governance(e, enforce=enforce)
    expected, opened = e.now[0].date(), True
    dataset = "hslt_list"
    if kind == "early":
        e.now[0] -= dt.timedelta(seconds=1)
    elif kind == "deadline":
        e.now[0] = e.now[0].replace(hour=23, minute=59, second=59)
    elif kind == "closed":
        opened = False
    elif kind == "other_day":
        expected -= dt.timedelta(days=1)
    else:
        dispatch(e)
        dataset = "bj_list"
        e.now[0] += dt.timedelta(seconds=59)

    def run() -> None:
        with control.dispatch(
            token=uuid.uuid4(), dataset=dataset, expected_day=expected, trading_day=opened
        ):
            e.calls.append("sent")

    if kind != "interval":
        with pytest.raises(GateClosedError, match="daily_window_expired"):
            run()
        assert e.calls == records(e) == []
        assert logs(e)[-1]["code"] == "daily_window_expired"
    elif enforce:
        with pytest.raises(GateClosedError, match="daily_refused"):
            run()
        assert len(e.calls) == 1
        assert logs(e)[-1]["code"] == "blocked_daily"
    else:
        run()
        assert len(e.calls) == 2
        assert logs(e)[-1]["code"] == "bypass_daily_would_block"


def test_tb102_bypass_fourth_keeps_actual_four_and_next_day_does_not_reset_history(
    env: Any,
) -> None:
    e = env
    for index in range(4):
        dispatch(e, enforce=False, dataset=DATASETS[index % 3])
        e.now[0] += dt.timedelta(seconds=60)
    assert len(records(e)) == 4
    row = logs(e)[-1]
    assert row["code"] == "bypass_daily_would_block"
    assert row["snapshot"]["daily_count"] == 3
    assert row["snapshot"]["reservation_id"] == records(e)[-1]["id"]
    e.now[0] += dt.timedelta(days=1)
    dispatch(e)  # New day count is one, the original four records remain intact.
    assert len(records(e)) == 5
    assert len({row["day"] for row in records(e)}) == 2


def test_tb102_stop_writer_and_invalid_sentinel_fail_closed(env: Any) -> None:
    e = env
    (e.root / "STOP").symlink_to(e.root / "missing")
    with pytest.raises(GateClosedError):
        dispatch(e)
    assert len(records(e)) == 1
    assert e.calls == []
    assert logs(e)[0]["snapshot"]["stop_0"] is True


def test_tb102_probe_128_original_ledger_and_caps_unchanged(env: Any) -> None:
    e = env
    counter = e.root / "mairui-batch-T-B86.count"
    state = {"schema": batch.SCHEMA, "total": 0, "records": [], "halted": False}
    counter.write_text(json.dumps(state), encoding="utf-8")
    os.chmod(counter, 0o600)
    with batch.reservation(
        counter,
        e.root / "STOP",
        "f21_trading_window",
        "transaction",
        "synthetic.d",
        enabled_segments=frozenset({"f21_trading_window"}),
    ):
        assert json.loads(counter.read_text())["total"] == 1
    before = counter.read_bytes()
    for dataset in DATASETS:
        dispatch(e, dataset=dataset)
        e.now[0] += dt.timedelta(seconds=60)
    assert counter.read_bytes() == before  # Product list count never consumes probe allowance.
    assert batch.TOTAL_CAP == 128
    assert sum(sum(caps.values()) for caps in batch.CAPS.values()) == 126


def test_tb102_probe_failure_and_segment_cap_remain_fail_closed(env: Any) -> None:
    e = env
    counter = e.root / "mairui-batch-T-B86.count"
    rows = [
        {"id": "history." + str(i), "segment": "history_actions", "interface": "daily"}
        for i in range(2)
    ]
    state = {"schema": batch.SCHEMA, "total": 2, "records": rows, "halted": False}
    counter.write_text(json.dumps(state), encoding="utf-8")
    os.chmod(counter, 0o600)
    with (
        pytest.raises(batch.HaltError, match="budget_exhausted"),
        batch.reservation(
            counter,
            e.root / "STOP",
            "history_actions",
            "daily",
            "history.third",
            enabled_segments=frozenset({"history_actions"}),
        ),
    ):
        pytest.fail("must never dispatch")
    before = counter.read_bytes()
    with (
        pytest.raises(batch.HaltError),
        batch.reservation(
            counter,
            e.root / "STOP",
            "history_actions",
            "jnfh",
            "history.failed",
            enabled_segments=frozenset({"history_actions"}),
        ),
    ):
        raise RuntimeError("synthetic upstream failure")
    after = json.loads(counter.read_text())
    assert after["halted"] is True
    assert after["total"] == 3
    assert counter.read_bytes() != before


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_crashed_dispatch_unknown_inflight_is_observed_not_reset(
    env: Any, enforce: bool
) -> None:
    e = env

    def crash() -> None:
        with governance(e).dispatch(
            token=uuid.uuid4(), dataset="hslt_list", expected_day=e.now[0].date(), trading_day=True
        ):
            raise RuntimeError("synthetic worker crash")

    with pytest.raises(RuntimeError, match="worker crash"):
        crash()
    assert records(e)[0]["finished_at"] is None
    e.now[0] += dt.timedelta(seconds=60)
    if enforce:
        with pytest.raises(GateClosedError, match="lock_refused"):
            dispatch(e, dataset="bj_list")
        assert len(records(e)) == 1
    else:
        dispatch(e, enforce=False, dataset="bj_list")
        assert len(records(e)) == 2
        assert records(e)[0]["finished_at"] is None
    assert logs(e)[0]["snapshot"]["unfinished"] == 1


def test_tb102_interval_measured_from_response_completion(env: Any) -> None:
    e = env
    with governance(e).dispatch(
        token=uuid.uuid4(), dataset="hslt_list", expected_day=e.now[0].date(), trading_day=True
    ):
        e.now[0] += dt.timedelta(seconds=40)  # A non-instant HTTP response.
    e.now[0] += dt.timedelta(seconds=59)
    with pytest.raises(GateClosedError, match="daily_refused"):
        dispatch(e, dataset="bj_list")
    assert len(records(e)) == 1
    e.now[0] += dt.timedelta(seconds=1)
    dispatch(e, dataset="bj_list")
    assert len(records(e)) == 2


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_readable_out_of_order_has_same_observation_decision(env: Any, enforce: bool) -> None:
    e = env
    if enforce:
        with pytest.raises(GateClosedError, match="daily_refused"):
            dispatch(e, dataset="kc_list")
        assert e.calls == []
    else:
        dispatch(e, enforce=False, dataset="kc_list")
        assert len(e.calls) == 1
    assert logs(e)[0]["snapshot"]["reason"] == "daily_endpoint_out_of_order"


def test_tb102_stop_injected_after_reservation_before_connection_still_zero_http(env: Any) -> None:
    e = env

    def run() -> None:
        with governance(e).dispatch(
            token=uuid.uuid4(), dataset="hslt_list", expected_day=e.now[0].date(), trading_day=True
        ) as permit:
            # Unsupported writer simulation proves the last transport check, while
            # supported write_stop uses the same mutex and cannot interleave here.
            (e.root / "STOP").write_text("synthetic stop", encoding="utf-8")
            permit.check()
            e.calls.append("must not connect")

    with pytest.raises(GateClosedError, match="stop_refused"):
        run()
    assert e.calls == []
    assert len(records(e)) == 1


@pytest.mark.parametrize("case", ["missing", "mode", "link", "unknown", "total128", "halted"])
def test_tb102_probe_ledger_safety_not_relaxed_by_product_config(env: Any, case: str) -> None:
    e = env
    counter = e.root / "mairui-batch-T-B86.count"
    state = {"schema": batch.SCHEMA, "total": 0, "records": [], "halted": False}
    if case == "total128":
        state["total"] = 128  # Unknown/unreconciled total is never reinterpreted as allowance.
    if case == "halted":
        state["halted"] = True
    if case != "missing":
        counter.write_text("{" if case == "unknown" else json.dumps(state), encoding="utf-8")
        os.chmod(counter, 0o644 if case == "mode" else 0o600)
    if case == "link":
        os.link(counter, e.root / "batch-copy")

    def run() -> None:
        with batch.reservation(
            counter,
            e.root / "STOP",
            "history_actions",
            "daily",
            "safety.check",
            enabled_segments=frozenset({"history_actions"}),
        ):
            e.calls.append("must not send")

    with pytest.raises(batch.HaltError):
        run()
    assert e.calls == []
    if case == "missing":
        assert not counter.exists()


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_one_reservation_only_one_fixed_endpoint_send(env: Any, enforce: bool) -> None:
    e = env

    def upstream(path: str, secret: str) -> Any:
        e.calls.append(path)
        return 200, []

    with governance(e, enforce=enforce).dispatch(
        token=uuid.uuid4(), dataset="hslt_list", expected_day=e.now[0].date(), trading_day=True
    ) as permit:
        with pytest.raises(GateClosedError, match="path_or_replay"):
            daily_lists.send(permit, upstream, "/hsstock/history/", "synthetic")
        assert e.calls == []
        daily_lists.send(permit, upstream, "/hslt/list/", "synthetic")
        with pytest.raises(GateClosedError, match="path_or_replay"):
            daily_lists.send(permit, upstream, "/hslt/list/", "synthetic")
    with pytest.raises(GateClosedError, match="path_or_replay"):
        daily_lists.send(permit, upstream, "/hslt/list/", "synthetic")
    assert e.calls == ["/hslt/list/"]
    assert len(records(e)) == 1


@pytest.mark.parametrize("busy", [False, True])
def test_tb102_existing_transport_caller_also_holds_same_dispatch_inode(
    env: Any, busy: bool
) -> None:
    e = env
    lid = uuid.uuid4()
    (e.root / "policy.json").write_text(
        json.dumps(
            {
                "schema": "mairui-shared/v1",
                "egress_ip": "192.0.2.10",
                "licences": {str(lid): {"per_minute_limit": 150}},
            }
        ),
        encoding="utf-8",
    )
    lock_fd = None
    gate = SharedGate(e.root, lid, "product_verify")
    gate.acquire()
    gate.confirm_egress("192.0.2.10")
    gate.reserve(now=e.now[0].timestamp())

    def upstream(path: str, secret: str) -> Any:
        assert send_control.owned(e.root)
        e.calls.append(path)
        return 200, []

    try:
        if busy:
            lock_fd = os.open(e.root / "send-control.lock", os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(GateClosedError, match="control_busy"):
                daily_lists.send(gate, upstream, "/tcalendar/list/2031/", "synthetic")
            assert e.calls == []
        else:
            daily_lists.send(gate, upstream, "/tcalendar/list/2031/", "synthetic")
            gate.complete(now=e.now[0].timestamp())
            assert e.calls == ["/tcalendar/list/2031/"]
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        gate.release()
