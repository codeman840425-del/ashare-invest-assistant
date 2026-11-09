"""Bounded product response sniffing; retain early limit evidence on oversized bodies."""

from __future__ import annotations

import http.client
import json
import re
from typing import Any


class ResponseBodyError(RuntimeError):
    pass


def sniff_envelope(prefix: str) -> str | None:
    plain = re.match(r"^(103|429)[:：]", prefix)
    if plain:
        return plain[1]
    decoder = json.JSONDecoder()

    def control(at: int, depth: int) -> tuple[str | None, int]:
        if depth > 8 or at >= len(prefix) or prefix[at] != "{":
            raise ValueError
        at += 1
        while at < len(prefix):
            while at < len(prefix) and prefix[at].isspace():
                at += 1
            if at < len(prefix) and prefix[at] == "}":
                return None, at + 1
            key, at = decoder.raw_decode(prefix, at)
            if not isinstance(key, str):
                raise ValueError
            while at < len(prefix) and prefix[at].isspace():
                at += 1
            if at >= len(prefix) or prefix[at] != ":":
                raise ValueError
            at += 1
            while at < len(prefix) and prefix[at].isspace():
                at += 1
            if key.lower() == "error" and at < len(prefix) and prefix[at] == "{":
                code, at = control(at, depth + 1)
                if code:
                    return code, at
            else:
                value, at = decoder.raw_decode(prefix, at)
                while at < len(prefix) and prefix[at].isspace():
                    at += 1
                if at >= len(prefix) or prefix[at] not in {",", "}"}:
                    raise ValueError  # A partial 103.0 must never be mistaken for integer 103.
                if key.lower() in {"code", "error_code", "status"} and str(value) in {"103", "429"}:
                    return str(value), at
            while at < len(prefix) and prefix[at].isspace():
                at += 1
            if at >= len(prefix) or prefix[at] not in {",", "}"}:
                raise ValueError
            if prefix[at] == "}":
                return None, at + 1
            at += 1
        raise ValueError

    try:
        return control(0, 0)[0]
    except (ValueError, RecursionError):
        return None


def read_body(response: http.client.HTTPResponse) -> Any:  # noqa: ANN401 - vendor JSON shape
    maximum, head_size, sniff_size = 16 * 1024 * 1024, 4096, 64 * 1024
    payload = bytearray()
    read_chunk = getattr(response, "read1", None)
    while True:
        chunk = (
            read_chunk(min(head_size, maximum + 1 - len(payload)))
            if read_chunk is not None
            else response.read(maximum + 1)
        )
        content = chunk.lstrip(b" \t\r\n") if not payload else chunk
        before = len(payload)
        payload.extend(content)
        if before < sniff_size and (
            code := sniff_envelope(bytes(payload[:sniff_size]).decode("utf-8", errors="replace"))
        ):
            return code
        if len(payload) > maximum:
            raise ResponseBodyError("response_too_large")
        if not chunk or read_chunk is None:
            break
    raw = bytes(payload).strip()
    if raw in {b"103", b"429"}:
        return raw.decode("ascii")
    try:
        return json.loads(payload)
    except (ValueError, UnicodeError):
        return payload.decode("utf-8", errors="replace")
