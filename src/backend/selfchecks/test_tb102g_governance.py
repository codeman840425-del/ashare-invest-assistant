"""T-B102g complete/prefix parity, root JSON text, whitespace and cleanup I/O guards."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import errno
import io
import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.ingest import daily_lists
from app.ingest.send_cleanup import CleanupPendingError, UnsentCleanup
from app.ingest.send_limits import EnvelopeSniffer, classify_response, limit_code, sniff_envelope
from app.ingest.send_response import ResponseBodyError, read_body
from app.ingest.upstream import Signal, classify
from selfchecks import test_tb102_governance as baseline

env = baseline.env


@pytest.mark.parametrize("code", ["103", "429"])
@pytest.mark.parametrize("shape", ["root", "field", "nested"])
def test_tb102g_root_json_text_and_whitespace_share_product_decision(code: str, shape: str) -> None:
    body: Any = f" {code}:限流" if shape == "root" else {"code": f" {code} "}
    if shape == "nested":
        body = {"padding": "x" * 131072, "error": {"status": f" {code} "}}
    raw = json.dumps(body, ensure_ascii=False)
    assert limit_code(200, body) == code
    assert sniff_envelope(raw) == code
    sniff = EnvelopeSniffer()
    for at in range(0, len(raw), 17):
        found = sniff.feed(raw[at : at + 17])
    assert found == code
    assert classify_response(200, body) == Signal.IP_LIMITED


@pytest.mark.parametrize("body", [{"error": "错误103"}, {"error": {"code": " 103 "}}])
def test_tb102g_legacy_stricter_classification_is_not_downgraded(body: Any) -> None:
    assert classify(200, body) == Signal.IP_LIMITED
    assert classify_response(200, body) == Signal.IP_LIMITED
    assert daily_lists.limited(200, body)


@pytest.mark.parametrize("code", ["103", "429"])
def test_tb102g_oversized_root_string_stops_before_failure(
    env: Any, monkeypatch: Any, code: str
) -> None:
    e = env
    prefix = b'"' + code.encode() + b":"
    payload = prefix + b"x" * (17 * 1024 * 1024)
    with pytest.raises(ResponseBodyError, match="response_too_large") as caught:
        read_body(SimpleNamespace(read=lambda count: payload[:count]))
    assert caught.value.code == code
    assert read_body(io.BytesIO(payload)) == code
    monkeypatch.setenv("MAIRUI_MODE", "live")

    class Connection:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_debuglevel(self, value: int) -> None:
            pass

        def request(self, *args: Any) -> None:
            pass

        def getresponse(self) -> Any:
            return SimpleNamespace(status=200, read=lambda count: payload[:count])

        def close(self) -> None:
            assert (e.root / "STOP").exists()

    monkeypatch.setattr(daily_lists.http.client, "HTTPSConnection", Connection)
    with (
        pytest.raises(daily_lists.LimitResponseError),
        baseline.governance(e).dispatch(
            token=uuid.uuid4(), dataset="hslt_list", expected_day=e.now[0].date(), trading_day=True
        ) as permit,
    ):
        daily_lists.send(permit, daily_lists.wire, "/hslt/list/", "synthetic")


@pytest.mark.parametrize("error", [errno.EACCES, errno.EIO])
def test_tb102g_cleanup_lstat_io_is_pending_not_missing(
    env: Any, monkeypatch: Any, error: int
) -> None:
    cleanup = UnsentCleanup(env.root, uuid.uuid4())
    cls = type(cleanup.path)
    original = cls.lstat

    def fail(path: Any, *args: Any, **kwargs: Any) -> Any:
        if path == cleanup.path:
            raise OSError(error, "synthetic cleanup lstat unavailable")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(cls, "lstat", fail)
    with pytest.raises(CleanupPendingError, match="probe_unavailable"):
        cleanup.exists()
