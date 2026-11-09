"""T-B102d actual product STOP/stream/redaction and T-A61 interleaving guards."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
import fcntl
import json
import logging
import os
from typing import Any

import pytest

from app.common.logging import RedactFilter, redact
from app.ingest.send_control import check_product
from app.ingest.send_response import read_body, sniff_envelope
from app.ingest.send_state import MinuteLedger
from app.ingest.shared_gate import GateClosedError, SharedGate
from selfchecks import test_tb102_governance as previous
from selfchecks.test_tb102_governance import dispatch, logs, records
from selfchecks.test_tb102b_governance import private

env = previous.env


@pytest.mark.parametrize("value", [None, [], {}, True, ""])
@pytest.mark.parametrize("enforce", [True, False])
def test_tb102d_malformed_halt_always_stops_or_observes(
    env: Any, value: Any, enforce: bool
) -> None:
    private(env.root / "state-synthetic.halt.json", {"code": value})
    if enforce:
        with pytest.raises(GateClosedError, match="stop_refused"):
            dispatch(env)
        assert env.calls == []
    else:
        dispatch(env, enforce=False)
        assert len(env.calls) == 1
    assert logs(env)[0]["snapshot"]["reason"] == "probe_halt_present"


@pytest.mark.parametrize("shape", ["dangling", "symlink", "directory"])
def test_tb102d_verification_stop_uses_lstat_fail_closed(env: Any, shape: str) -> None:
    e = env
    stop = e.root / "STOP"
    if shape == "directory":
        stop.mkdir()
    else:
        target = e.root / "stop-target"
        if shape == "symlink":
            target.write_text("synthetic stop")
        stop.symlink_to(target)
    with pytest.raises(GateClosedError, match="shared_STOP"):
        check_product(SharedGate(e.root, e.lid, "product_verify"))


@pytest.mark.parametrize(
    "prefix",
    [
        b"103:",
        b'{"code":103,"padding":"',
        b'{"error":{"code":103,"padding":"',
        b'{"status":"429","padding":"',
    ],
)
def test_tb102d_oversized_stream_retains_early_envelope(prefix: bytes) -> None:
    class Stream:
        def __init__(self) -> None:
            self.padding = 128 * 1024  # Within total limit; keep the full sniff window.
            self.reads = 0

        def read1(self, count: int) -> bytes:
            self.reads += 1
            if self.padding:
                used = min(self.padding, count)
                self.padding -= used
                return b" " * used
            if self.reads > 6000:
                pytest.fail("must stop at the first error envelope, not consume oversized tail")
            return prefix + b"x" * (4096 - len(prefix))

    stream = Stream()
    assert read_body(stream) == ("429" if b"429" in prefix else "103")
    assert stream.reads == 128 * 1024 // 4096 + 1


@pytest.mark.parametrize(
    "body",
    [
        '{"data":[{"code":103}],"padding":"',
        '{"code":103.0,"padding":"',
        '{"data":{"price":103},"padding":"',
    ],
)
def test_tb102d_sniff_does_not_enter_business_data_or_partial_number(body: str) -> None:
    assert sniff_envelope(body) is None


def test_tb102d_redaction_preserves_json_with_numeric_placeholders(env: Any) -> None:
    e = env
    payload = {
        "id": str(e.lid),
        "snapshot": {
            "last_finished": e.now[0].timestamp(),
            "ledger_total": 3,
            "ledger128_total": 31,
            "account": "A" + "123456789",
        },
    }
    record = logging.LogRecord(
        "app.ingest.send_governance",
        logging.INFO,
        __file__,
        1,
        "send_governance %s",
        (json.dumps(payload),),
        None,
    )
    assert RedactFilter().filter(record)
    value = json.loads(record.getMessage().split("send_governance ", 1)[1])
    assert value["snapshot"]["last_finished"] == "***"
    assert value["snapshot"]["account"] == "***"
    assert value["snapshot"]["ledger_total"] == 3
    assert value["snapshot"]["ledger128_total"] == 31
    assert value["id"] == str(e.lid)
    assert redact("holder=A" + "123456789") == "holder=***"


@pytest.mark.parametrize(
    "operation", ["reserve", "cancel", "complete", "missing_cancel", "missing_complete"]
)
def test_tb102d_ta61_preserves_interleaved_probe_entries(env: Any, operation: str) -> None:
    e = env
    now = e.now[0].timestamp()
    path = e.root / "state-synthetic.requests.json"
    private(path, {"calls": [now - 10], "inflight": False, "last_finished": now - 70})
    minute = MinuteLedger(e.root, e.lid)
    minute.read(now)
    if operation == "reserve":
        private(path, {"calls": [now - 10, now - 1], "inflight": True, "last_finished": now - 70})
        minute.reserve(now)
        assert json.loads(path.read_text())["calls"] == [now - 10, now - 1, now]
        return
    minute.reserve(now)
    replacement = {"calls": [now - 10, now + 1], "inflight": True, "last_finished": now + 2}
    if not operation.startswith("missing"):
        replacement["calls"].insert(1, now)
    private(path, replacement)
    before = path.read_bytes(), path.stat().st_mtime_ns
    if "cancel" in operation:
        minute.cancel_unsent()
        minute.cancel_unsent()  # Retry is idempotent; no second writer's entry disappears.
    else:
        minute.complete(now + 1)
    result = json.loads(path.read_text())
    if operation.startswith("missing"):
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    elif operation == "cancel":
        assert result == {**replacement, "calls": [now - 10, now + 1]}
    else:
        assert result == replacement
    assert result["last_finished"] == now + 2
    assert result["inflight"] is True


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102d_busy_snapshot_counts_survive_real_redaction(env: Any, enforce: bool) -> None:
    e = env
    dispatch(e)
    e.now[0] += dt.timedelta(seconds=60)
    private(
        e.root / "mairui-batch-T-B86.count",
        {
            "schema": "T-B86/v1",
            "total": 1,
            "halted": False,
            "records": [
                {"id": "synthetic.one", "segment": "f21_trading_window", "interface": "transaction"}
            ],
        },
    )
    fd = os.open(e.root / "send-control.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(GateClosedError, match="shared_control_busy"):
            dispatch(e, enforce=enforce, dataset="bj_list")
        hit = logs(e)[-1]
        assert hit["code"] == "shared_control_busy"
        assert hit["snapshot"]["ledger_total"] == len(records(e)) == 1
        assert hit["snapshot"]["daily_count"] == 1
        assert hit["snapshot"]["ledger128_total"] == 1
        record = next(
            record
            for record in reversed(e.caplog.records)
            if '"code":"shared_control_busy"' in record.getMessage()
        )
        RedactFilter().filter(record)
        filtered = json.loads(record.getMessage().split("send_governance ", 1)[1])
        assert filtered["snapshot"]["ledger_total"] == filtered["snapshot"]["ledger128_total"] == 1
    finally:
        os.close(fd)
