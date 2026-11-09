"""Product full/prefix grammar alignment, long fields, chunk boundaries and false positives."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import io
import json
from typing import Any

import pytest

from app.ingest import daily_lists, verification
from app.ingest.send_limits import EnvelopeSniffer, limit_code, sniff_envelope
from app.ingest.send_response import ResponseBodyError, read_body
from app.ingest.upstream import Signal


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"error": "103: limited"}, "103"),
        ({"error": {"error": "429: limited"}}, "429"),
        ({"error": {"code": 103}}, "103"),
        ({"status": "429"}, "429"),
        ({"code": 103.0}, None),
        ({"data": {"error": "103: business"}}, None),
        ({"data": [{"code": 103}]}, None),
        ({"error": "价格103元"}, None),
        ({"error": "103.0 元"}, None),
        ({"message": 'quoted {"error":"103:"}'}, None),
        ({"error": {"data": [{"code": 429}]}}, None),
        ([{"code": 103}], None),
    ],
)
def test_tb102f_full_body_and_prefix_use_one_product_grammar(body: Any, code: str | None) -> None:
    raw = json.dumps(body, ensure_ascii=False)
    assert limit_code(200, body) == code
    assert sniff_envelope(raw) == code
    assert daily_lists.limited(200, body) is (code is not None)
    assert daily_lists.limit_code is verification.limit_code is limit_code
    assert daily_lists.classify is verification.classify
    assert (daily_lists.classify(200, body) == Signal.IP_LIMITED) is (code is not None)


@pytest.mark.parametrize("size", [1, 17, 4096])
@pytest.mark.parametrize(
    "ending",
    [
        '"error":"103:unfinished',
        '"error":{"status":"429"}',
        '"error":"\\u0031\\u0030\\u0033:unfinished',
    ],
)
def test_tb102f_all_read_long_fields_and_incomplete_error_strings(size: int, ending: str) -> None:
    raw = '{"padding":"' + "x" * (128 * 1024) + '",' + ending
    sniff = EnvelopeSniffer()
    code = None
    for at in range(0, len(raw), size):
        code = sniff.feed(raw[at : at + size])
        if at < 65536:
            assert code is None
    assert code == ("429" if "429" in ending else "103")
    assert len(sniff.raw) <= 257  # Long unknown values do not accumulate token memory.


@pytest.mark.parametrize("chunk_size", [1, 4096])
def test_tb102f_leading_space_cannot_reclassify_business_chunk_as_plain_limit(
    chunk_size: int,
) -> None:
    raw = " " * 8192 + '{"data":"' + " " * 8192 + '103:business"}'
    sniff = EnvelopeSniffer()
    for at in range(0, len(raw), chunk_size):
        assert sniff.feed(raw[at : at + chunk_size]) is None


@pytest.mark.parametrize("code", ["103", "429"])
def test_tb102f_overlimit_incomplete_text_error_preserves_fixed_code(code: str) -> None:
    raw = b'{"padding":"' + b"x" * 131072 + b'","error":"' + code.encode() + b":"
    payload = raw + b"x" * (16 * 1024 * 1024)
    response = type("Whole", (), {"read": lambda self, count: payload[:count]})()
    with pytest.raises(ResponseBodyError, match="response_too_large") as caught:
        read_body(response)
    assert caught.value.code == code
    # Chunked real HTTPResponse shape reaches the same signal without waiting for closure.
    assert read_body(io.BytesIO(payload)) == code


@pytest.mark.parametrize("raw", ['{"code":103.', '{"error":{"code":103.0,', '{"error":"103.0'])
def test_tb102f_partial_numbers_never_count_as_limit(raw: str) -> None:
    assert sniff_envelope(raw) is None


@pytest.mark.parametrize("location", ["plain", "error"])
def test_tb102f_whitespace_never_hides_an_already_read_control_prefix(location: str) -> None:
    raw = "103" + " " * 4096 + ":" if location == "plain" else '{"error":"' + " " * 4096 + "103:"
    sniff = EnvelopeSniffer()
    for at in range(0, len(raw), 17):
        code = sniff.feed(raw[at : at + 17])
    assert code == "103"
