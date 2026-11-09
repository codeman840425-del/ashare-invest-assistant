# ruff: noqa: S101, ANN401
"""Synthetic transport/credentials/ledger only. No live evidence acceptance claim."""

import fcntl
import json
import socket
import uuid
from pathlib import Path
from typing import Any

import pytest

from probes import tb86_history as probe


@pytest.fixture
def context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    def deny(*_args: object, **_kwargs: object) -> None:
        pytest.fail("live network forbidden")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o700)
    lid = uuid.uuid4()
    (shared / "policy.json").write_text(
        json.dumps(
            {
                "schema": "mairui-shared/v1",
                "egress_ip": "192.0.2.10",
                "licences": {str(lid): {"per_minute_limit": 150}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        probe.os,
        "environ",
        {
            "MAIRUI_LICENCE": "synthetic_" + uuid.uuid4().hex,
            "MAIRUI_SHARED_STATE_DIR": str(shared),
            "MAIRUI_SOURCE_LICENCE_ID": str(lid),
        },
    )
    monkeypatch.setattr(probe, "public_egress", lambda: "192.0.2.10")
    monkeypatch.setattr(probe.time, "sleep", lambda *_: None)
    monkeypatch.setattr(probe.logging, "disable", lambda *_: None)
    counter = tmp_path / "synthetic.count"
    counter.write_text(
        json.dumps({"schema": "T-B86/v1", "total": 0, "records": [], "halted": False})
    )
    counter.chmod(0o600)
    root = tmp_path / "results"
    (root / "official").mkdir(parents=True)
    (root / "official/manifest.json").write_text("[]")
    return {
        "counter": counter,
        "stop": tmp_path / "STOP",
        "secret_path": tmp_path / "synthetic.tmp",
        "root": root,
    }


class FakeConnection:
    status = 200
    body = b'[{"t":"synthetic","sf":0}]'
    calls = 0
    failure = False

    def request(self, _method: str, path: str, **_kwargs: object) -> None:
        type(self).calls += 1
        if self.failure:
            raise RuntimeError(path)  # deliberately includes synthetic URL credential

    def getresponse(self) -> Any:
        return self

    def read(self, _max_bytes: int) -> bytes:
        return self.body

    def close(self) -> None:
        pass


def enable_synthetic(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only synthetic control tests bypass document processing; actual runner does not.
    monkeypatch.setattr(probe, "validate_notices", lambda *_: None)
    monkeypatch.setattr(probe, "SingleConnection", FakeConnection)
    monkeypatch.setattr(FakeConnection, "calls", 0)
    monkeypatch.setattr(FakeConnection, "status", 200)
    monkeypatch.setattr(FakeConnection, "body", b'[{"t":"synthetic","sf":0}]')
    monkeypatch.setattr(FakeConnection, "failure", False)


def test_real_incomplete_notices_prevent_credential_access(
    context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Forbidden(dict):
        def get(self, key: str, default: object = None) -> object:
            if key == "MAIRUI_LICENCE":
                pytest.fail("credential must not be read")
            return super().get(key, default)

    monkeypatch.setattr(probe.os, "environ", Forbidden())
    result = probe.execute(**context)
    assert result["outcome"] == "official_notice_evidence_incomplete"
    assert result["new_reserved_calls"] == 0
    assert not context["secret_path"].exists()


def test_legacy_stop_after_reservation_prevents_history_http(
    context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_synthetic(monkeypatch)
    original = probe.SharedGate.reserve

    def reserve(gate: Any, **kwargs: Any) -> None:
        original(gate, **kwargs)
        context["stop"].touch()

    monkeypatch.setattr(probe.SharedGate, "reserve", reserve)
    result = probe.execute(**context)
    assert FakeConnection.calls == 0
    assert result["new_reserved_calls"] == 1
    assert result["outcome"] == "STOP_present"
    assert result["temporary_secret_deleted"]
    root = Path(probe.os.environ["MAIRUI_SHARED_STATE_DIR"])
    assert (root / "STOP").is_file()
    assert json.loads(context["counter"].read_text())["halted"]


def test_six_synthetic_calls_have_locked_ledger_and_cleanup(
    context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_synthetic(monkeypatch)
    original = FakeConnection.request

    def request(self: Any, method: str, path: str, **kwargs: object) -> None:
        state = json.loads(context["counter"].read_text())
        with context["counter"].open("r") as other, pytest.raises(BlockingIOError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert state["total"] == FakeConnection.calls + 1  # persisted BEFORE dispatch
        assert context["secret_path"].stat().st_mode & 0o777 == 0o600
        return original(self, method, path, **kwargs)

    monkeypatch.setattr(FakeConnection, "request", request)
    result = probe.execute(**context)
    assert result["outcome"] == "completed_history_collection_only"
    assert result["new_reserved_calls"] == 6
    assert result["batch_total"] == 6
    assert FakeConnection.calls == 6
    assert result["temporary_secret_deleted"]
    assert not context["secret_path"].exists()
    assert not json.loads(context["counter"].read_text())["halted"]
    repeated = probe.execute(**context)
    assert repeated["outcome"] == "history_already_started_no_automatic_resume"
    assert repeated["new_reserved_calls"] == 0
    assert FakeConnection.calls == 6


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (429, b"{}"),
        (103, b"{}"),
        (200, b'{"code":103}'),
        (200, b'{"error_code":429}'),
        (302, b"{}"),
    ],
)
def test_failure_stops_all_later_interfaces_and_cleans(
    context: Any, monkeypatch: pytest.MonkeyPatch, status: int, body: bytes
) -> None:
    enable_synthetic(monkeypatch)
    monkeypatch.setattr(FakeConnection, "status", status)
    monkeypatch.setattr(FakeConnection, "body", body)
    result = probe.execute(**context)
    assert FakeConnection.calls == 1
    assert result["new_reserved_calls"] == 1
    assert result["temporary_secret_deleted"]
    assert json.loads(context["counter"].read_text())["halted"]
    assert list(context["root"].glob("history-*/*.raw")) == []


def test_transport_exception_never_renders_url(
    context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_synthetic(monkeypatch)
    monkeypatch.setattr(FakeConnection, "failure", True)
    result = probe.execute(**context)
    assert result["outcome"] == "transport_failure_no_retry"
    assert result["temporary_secret_deleted"]
    assert probe.os.environ["MAIRUI_LICENCE"] not in json.dumps(result)
    assert probe.os.environ["MAIRUI_LICENCE"] not in context["counter"].read_text()


def test_response_credential_echo_not_saved(context: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    enable_synthetic(monkeypatch)
    monkeypatch.setattr(FakeConnection, "body", probe.os.environ["MAIRUI_LICENCE"].encode())
    result = probe.execute(**context)
    assert result["outcome"] == "credential_echo_not_saved"
    assert result["temporary_secret_deleted"]
    assert list(context["root"].glob("history-*/*.raw")) == []


def test_existing_temp_file_never_overwritten_or_deleted(
    context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_synthetic(monkeypatch)
    context["secret_path"].write_bytes(b"synthetic-owner-file")
    result = probe.execute(**context)
    assert not result["temporary_secret_created"]
    assert context["secret_path"].read_bytes() == b"synthetic-owner-file"
    assert FakeConnection.calls == 0


def test_stop_no_credential_file_or_request(context: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    enable_synthetic(monkeypatch)
    context["stop"].touch()
    result = probe.execute(**context)
    assert result["outcome"] == "STOP_present"
    assert result["new_reserved_calls"] == 0
    assert not context["secret_path"].exists()
    assert context["stop"].exists()


def test_missing_authorized_environment_no_fallback(
    context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_synthetic(monkeypatch)
    monkeypatch.delitem(probe.os.environ, "MAIRUI_LICENCE")
    result = probe.execute(**context)
    assert result["outcome"] == "authorized_environment_missing"
    assert result["new_reserved_calls"] == 0
    assert not context["secret_path"].exists()


def test_preflight_only_does_not_read_credential_or_dispatch(
    context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Forbidden(dict):
        def get(self, key: str, default: object = None) -> object:
            if key == "MAIRUI_LICENCE":
                pytest.fail("offline preflight must not read credentials")
            return super().get(key, default)

    monkeypatch.setattr(probe.os, "environ", Forbidden())
    monkeypatch.setattr(probe, "STOP", context["stop"])
    monkeypatch.setattr(probe, "execute", lambda **_: pytest.fail("offline preflight dispatched"))
    before = context["counter"].read_bytes()
    assert (
        probe.main(
            [
                "--preflight-only",
                "--counter",
                str(context["counter"]),
                "--secret-path",
                str(context["secret_path"]),
            ]
        )
        == 0
    )
    assert context["counter"].read_bytes() == before
    assert not context["secret_path"].exists()
    context["counter"].chmod(0o644)
    assert (
        probe.main(
            [
                "--preflight-only",
                "--counter",
                str(context["counter"]),
                "--secret-path",
                str(context["secret_path"]),
            ]
        )
        == 2
    )
    assert context["counter"].read_bytes() == before


def test_cli_runtime_paths_still_require_explicit_authorization_flag(
    context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def execute(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return {"outcome": "completed_history_collection_only", "temporary_secret_deleted": True}

    monkeypatch.setattr(probe, "execute", execute)
    paths = ["--counter", str(context["counter"]), "--secret-path", str(context["secret_path"])]
    assert probe.main(paths) == 2
    assert calls == []
    assert probe.main(["--execute-authorized-history", *paths]) == 0
    assert calls == [{"counter": context["counter"], "secret_path": context["secret_path"]}]


def test_connection_never_reconnects() -> None:
    connection = probe.SingleConnection()
    connection.connect_attempts = 1
    with pytest.raises(probe.HaltError, match="no_reconnect"):
        connection.connect()


def test_interrupt_also_cleans_and_consumes(context: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    enable_synthetic(monkeypatch)

    def interrupted(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(FakeConnection, "request", interrupted)
    result = probe.execute(**context)
    assert result["temporary_secret_deleted"]
    assert result["new_reserved_calls"] == 1
    assert json.loads(context["counter"].read_text())["halted"]


def test_http_limit_stops_before_response_body_read(
    context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_synthetic(monkeypatch)
    monkeypatch.setattr(FakeConnection, "status", 429)

    def unread(*_args: object) -> bytes:
        raise AssertionError("HTTP429 body must not delay the stop")

    monkeypatch.setattr(FakeConnection, "read", unread)
    result = probe.execute(**context)
    assert result["outcome"] == "rate_limit_103_or_429"
    assert result["temporary_secret_deleted"]
    assert FakeConnection.calls == 1
    from app.ingest.shared_gate import GateClosedError, SharedGate

    with pytest.raises(GateClosedError, match="halted"):
        SharedGate.from_environment(None, "product_daily").acquire()


def test_product_shared_lease_prevents_history_reservation_or_secret_file(
    context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ingest.shared_gate import SharedGate

    enable_synthetic(monkeypatch)
    with SharedGate.from_environment(None, "product_daily"):
        result = probe.execute(**context)
        assert result["new_reserved_calls"] == 0
        assert FakeConnection.calls == 0
        assert not context["secret_path"].exists()
    assert json.loads(context["counter"].read_text())["total"] == 0
