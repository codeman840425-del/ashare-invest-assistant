"""Product-only limit grammar shared by complete envelopes and streamed prefixes.

Frozen probe/shared_gate rules stay unchanged. Only root control fields and nested
``error`` objects/strings are inspected; business containers are skipped entirely.
"""

from __future__ import annotations

import json
import re

from app.ingest.upstream import Signal
from app.ingest.upstream import classify as legacy_classify

_CODES = frozenset({"103", "429"})
_FIELDS = frozenset({"code", "error_code", "status"})
_TEXT = frozenset({"error", "msg", "message"})
_PLAIN = re.compile(r"^\s*(103|429)\s*[:：]")
_DELIMITERS = " \t\r\n{}[]:,"
_MAX_TOKEN = 256


def _text_code(value: str, *, complete: bool) -> str | None:
    """Only a leading limit token in a text field counts; '涨了103元' never matches."""
    match = re.match(r"^\s*(103|429)\s*(?:[:：]|$)", value)
    if match is None:
        return None
    if complete or match.end() < len(value) or value.rstrip().endswith((":", "：")):
        return match[1]
    # An unfinished '103' may still grow a ':' in the next chunk.
    return None


class EnvelopeSniffer:
    """Incremental JSON control scanner with bounded token memory.

    A single instance may be fed arbitrarily many chunks (including a whole
    complete body); every byte that has been read participates in the decision.
    """

    def __init__(self) -> None:
        self.code: str | None = None
        self.frames: list[dict[str, str]] = []
        self.skip = 0
        self.started = False
        self.done = False
        self.mode = ""
        self.raw = ""
        self.overflow = False
        self.escaped = False
        self.head = ""

    # -- token handling -------------------------------------------------
    def _token(self, kind: str, value: str = "") -> None:
        if self.skip:
            if kind in {"{", "["}:
                self.skip += 1
            elif kind in {"}", "]"}:
                self.skip -= 1
            return
        if not self.started:
            self.started = True
            if kind == "{":
                self.frames.append({"phase": "key", "key": ""})
            else:
                self.done = True
            return
        if not self.frames:
            self.done = True
            return
        frame = self.frames[-1]
        if frame["phase"] == "key":
            if kind == "}":
                self.frames.pop()
            elif kind == "string":
                frame["key"], frame["phase"] = value.lower(), "colon"
            else:
                self.done = True
        elif frame["phase"] == "colon":
            if kind == ":":
                frame["phase"] = "value"
            else:
                self.done = True
        elif frame["phase"] == "value":
            frame["phase"] = "comma"
            key = frame["key"]
            if kind == "{" and key == "error" and len(self.frames) < 8:
                self.frames.append({"phase": "key", "key": ""})
            elif kind in {"{", "["}:
                self.skip = 1
            elif kind in {"string", "scalar"}:
                if key in _FIELDS and value in _CODES:
                    self.code = value
                elif key in _TEXT and kind == "string" and value:
                    self.code = _text_code(value, complete=True)
            else:
                self.done = True
        elif kind == ",":
            frame["phase"] = "key"
        elif kind == "}":
            self.frames.pop()
        else:
            self.done = True

    def _text_field_value(self, *, complete: bool) -> str:
        if self.overflow:
            return ""
        try:
            return_value = json.loads(self.raw if complete else self.raw + '"')
        except (ValueError, UnicodeError):
            return ""
        return return_value if isinstance(return_value, str) else ""

    # -- incremental feed -----------------------------------------------
    def feed(self, chunk: str) -> str | None:
        """Return the limit code as soon as it is unambiguous in what was read."""
        if self.code is not None or not chunk:
            return self.code
        if len(self.head) < 32:
            for char in chunk:
                if not self.head and char.isspace():
                    continue
                if char.isspace() and self.head and self.head[-1].isspace():
                    continue
                if len(self.head) >= 32:
                    break
                self.head += char
        plain = _PLAIN.match(self.head)
        if plain is not None:
            self.code = plain[1]
            return self.code
        if self.done:
            return None
        for char in chunk:
            if self.mode == "string":
                if (
                    char == " "
                    and not self.escaped
                    and not self.overflow
                    and (self.raw == '"' or self.raw.endswith(" "))
                    and self._in_text_field()
                ):
                    continue  # Whitespace cannot consume the bounded error-prefix token.
                if len(self.raw) <= _MAX_TOKEN:
                    self.raw += char
                else:
                    self.overflow = True
                if self.escaped:
                    self.escaped = False
                elif char == "\\":
                    self.escaped = True
                elif char == '"':
                    self._token("string", self._text_field_value(complete=True))
                    self.mode = ""
                elif not self.overflow and self._in_text_field():
                    self.code = _text_code(self._text_field_value(complete=False), complete=False)
                    if self.code is not None:
                        return self.code
            elif self.mode == "scalar":
                if char not in _DELIMITERS:
                    if len(self.raw) <= _MAX_TOKEN:
                        self.raw += char
                    else:
                        self.overflow = True
                    continue
                self._token("scalar", "" if self.overflow else self.raw)
                self.mode = ""
                self._dispatch(char)
            else:
                self._dispatch(char)
            if self._finished():
                break
        return self.code

    def _finished(self) -> bool:
        return self.code is not None or self.done

    def _in_text_field(self) -> bool:
        return bool(
            self.frames
            and self.frames[-1]["phase"] == "value"
            and self.frames[-1]["key"] in _TEXT
            and not self.skip
        )

    def _dispatch(self, char: str) -> None:
        if char in " \t\r\n":
            return
        if char == '"':
            self.mode, self.raw, self.overflow, self.escaped = "string", '"', False, False
        elif char in "{}[]:,":
            try:
                self._token(char)
            except RecursionError:
                self.done = True
        else:
            self.mode, self.raw, self.overflow = "scalar", char, False


def sniff_envelope(prefix: str) -> str | None:
    return EnvelopeSniffer().feed(prefix)


def limit_code(status: int | None, body: object) -> str | None:
    """One product judgment for complete bodies; the same grammar serves prefixes."""
    if status in {103, 429}:
        return str(status)
    if isinstance(body, dict):
        try:
            encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        except (ValueError, TypeError, RecursionError):
            return None
        return EnvelopeSniffer().feed(encoded)
    if isinstance(body, str):
        return _text_code(body, complete=True) or sniff_envelope(body)
    if isinstance(body, list):
        return None  # Business data arrays never decide a limit.
    return None


def classify_response(status: int, body: object) -> Signal:
    if limit_code(status, body) is not None:
        return Signal.IP_LIMITED
    signal = legacy_classify(status, body)
    if signal == Signal.IP_LIMITED:
        # Legacy error-text substring matching must not turn a product grammar
        # negative (e.g. 103.0 in business text) into a limit through another path.
        return Signal.CLIENT_ERROR if status == 200 else legacy_classify(status)
    return signal
