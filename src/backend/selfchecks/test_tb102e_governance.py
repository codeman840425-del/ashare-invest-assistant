"""T-B102e bounded transport and durable cleanup proof failures, zero external I/O."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import io
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.ingest import daily_lists, send_control
from app.ingest.send_cleanup import CleanupProofError, UnsentCleanup
from app.ingest.send_response import ResponseBodyError, read_body
from app.ingest.send_state import MinuteLedger
from selfchecks import test_tb102_governance as previous

env = previous.env
MAXIMUM = 16 * 1024 * 1024


def prefix(case: str) -> bytes:
    start = b'{"message":"' + b"x" * 12000 + b'",'
    if case == "nested103":
        return start + b'"error":{"code":103,"tail":"'
    if case == "nested429":
        return start + b'"error":{"status":"429","tail":"'
    if case == "data":
        return start + b'"data":{"code":103,"tail":"'
    if case == "number":
        return start + b'"error":{"code":103.0,"tail":"'
    if case == "string":
        return start + b'"message2":"\\"error\\":{\\"code\\":103},'
    if case == "outside":
        return b'{"message":"' + b"x" * 65536 + b'","error":{"code":103,"tail":"'
    raise AssertionError(case)


@pytest.mark.parametrize("case", ["nested103", "nested429", "data", "number", "string", "outside"])
def test_tb102e_oversize_sniffs_incomplete_read_prefix_before_failure(case: str) -> None:
    body = prefix(case) + b"x" * MAXIMUM
    response = SimpleNamespace(read=lambda count: body[:count])
    with pytest.raises(ResponseBodyError, match="response_too_large") as caught:
        read_body(response)
    assert caught.value.code == {"nested103": "103", "nested429": "429"}.get(case)


@pytest.mark.parametrize("case", ["nested103", "nested429", "data", "number", "string", "outside"])
def test_tb102e_real_wire_oversize_persists_stop_before_sanitized_failure(
    env: Any, monkeypatch: Any, case: str
) -> None:
    e = env
    monkeypatch.setenv("MAIRUI_MODE", "live")
    body = prefix(case) + b"x" * MAXIMUM
    closed: list[bool] = []

    class Connection:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_debuglevel(self, value: int) -> None:
            pass

        def request(self, *args: Any, **kwargs: Any) -> None:
            pass

        def getresponse(self) -> Any:
            return SimpleNamespace(status=200, read=lambda count: body[:count])

        def close(self) -> None:
            closed.append(True)
            assert (e.root / "STOP").exists() is case.startswith("nested")
            assert send_control.owned(e.root)

    monkeypatch.setattr(daily_lists.http.client, "HTTPSConnection", Connection)
    with (
        pytest.raises(daily_lists.DailyHaltError, match="transport_or_response_failed_no_retry"),
        previous.governance(e).dispatch(
            token=uuid.uuid4(), dataset="hslt_list", expected_day=e.now[0].date(), trading_day=True
        ) as permit,
    ):
        daily_lists.send(permit, daily_lists.wire, "/hslt/list/", "synthetic")
    assert closed == [True]
    assert len(previous.records(e)) == 1  # Real/unknown HTTP must never be refunded.


@pytest.mark.parametrize("content", [b" ", b"\t\r\n "])
def test_tb102e_infinite_whitespace_stops_at_total_byte_limit(content: bytes) -> None:
    class Stream:
        total = 0
        reads = 0

        def read1(self, count: int) -> bytes:
            assert count > 0
            self.reads += 1
            result = (content * (count // len(content) + 1))[:count]
            self.total += len(result)
            assert self.total <= MAXIMUM + 1
            return result

    stream = Stream()
    with pytest.raises(ResponseBodyError, match="response_too_large") as caught:
        read_body(stream)
    assert caught.value.code is None
    assert stream.total == MAXIMUM + 1
    assert stream.reads == MAXIMUM // 4096 + 1


@pytest.mark.parametrize("padding", [0, 128 * 1024])
def test_tb102e_chunked_json_and_bare_limit_compatible(padding: int) -> None:
    for body, expected in [(b'{"data":[103.0]}', {"data": [103.0]}), (b"103", "103")]:
        stream = io.BytesIO(b" " * padding + body)
        assert read_body(stream) == expected


@pytest.mark.parametrize("point", ["open", "file_fsync", "directory_fsync"])
def test_tb102e_new_proof_failure_keeps_specific_error_and_reservations(
    env: Any, monkeypatch: Any, point: str
) -> None:
    e = env
    cleanup = UnsentCleanup(e.root, uuid.uuid4())
    assert not cleanup.exists()  # Exercise first creation, not recovery of an existing proof.
    minute = MinuteLedger(e.root, e.lid)
    opened = os.open
    fsync = os.fsync
    from app.ingest import shared_gate

    sync = shared_gate._sync_directory

    def open_at(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if Path(path) == cleanup.path:
            raise PermissionError("synthetic private proof unavailable")
        return opened(path, flags, *args, **kwargs)

    def sync_at(fd: int) -> None:
        if Path(os.readlink(f"/proc/self/fd/{fd}")) == cleanup.path:
            raise OSError("synthetic proof fsync failure")
        fsync(fd)

    def directory_at(path: Path) -> None:
        if cleanup.exists():
            raise OSError("synthetic proof directory fsync failure")
        sync(path)

    def create_proof() -> None:
        with send_control.critical(e.root):
            minute.reserve(e.now[0].timestamp())
            if point == "open":
                monkeypatch.setattr(os, "open", open_at)
            elif point == "file_fsync":
                monkeypatch.setattr(os, "fsync", sync_at)
            else:
                monkeypatch.setattr(shared_gate, "_sync_directory", directory_at)
            cleanup.create(minute, kind="verify", owner=e.lid)

    with pytest.raises(CleanupProofError, match="unsent_cleanup_proof_unavailable"):
        create_proof()
    assert not send_control.owned(e.root)
    assert minute.read(e.now[0].timestamp())["inflight"] is True
    assert len(minute.read(e.now[0].timestamp())["calls"]) == 1
    assert cleanup.exists() is (point != "open")
    assert e.calls == []


def test_tb102e_mutex_does_not_reclassify_caller_oserror(env: Any) -> None:
    with (
        pytest.raises(PermissionError, match="synthetic caller failure"),
        send_control.critical(env.root),
    ):
        raise PermissionError("synthetic caller failure")
    assert not send_control.owned(env.root)
    with send_control.critical(env.root, blocking=False):
        assert send_control.owned(env.root)
