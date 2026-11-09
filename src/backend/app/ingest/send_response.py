"""Bounded product response reading with the shared product envelope grammar."""

from __future__ import annotations

import codecs
import http.client
import json
from typing import Any

from app.ingest.send_limits import EnvelopeSniffer, sniff_envelope


class ResponseBodyError(RuntimeError):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


def read_body(response: http.client.HTTPResponse) -> Any:  # noqa: ANN401 - vendor JSON shape
    maximum, head_size = 16 * 1024 * 1024, 4096
    payload = bytearray()
    total = 0
    sniff = EnvelopeSniffer()
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    read_chunk = getattr(response, "read1", None)
    while True:
        count = min(head_size, maximum + 1 - total)
        chunk = read_chunk(count) if read_chunk is not None else response.read(maximum + 1 - total)
        total += len(chunk)
        payload.extend(chunk)
        # Every byte already read goes through the same grammar, including long
        # fields and incomplete error strings; no separate 64KiB blind spot.
        code = sniff.feed(decoder.decode(chunk, final=not chunk))
        if total > maximum:
            if code is None:
                code = sniff_envelope(bytes(payload).decode("utf-8", errors="replace"))
            raise ResponseBodyError("response_too_large", code=code)
        if code is not None:
            return code
        if not chunk or read_chunk is None:
            break
    raw = bytes(payload).strip()
    if raw in {b"103", b"429"}:
        return raw.decode("ascii")
    try:
        return json.loads(payload)
    except (ValueError, UnicodeError):
        return payload.decode("utf-8", errors="replace")
