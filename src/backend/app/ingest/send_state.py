"""Product-side file readers; no dependency on the excluded probe package.

The T-B86/v1 validator is vendored from the frozen offline ledger. Its caps and
schema remain unchanged. This module never reserves or writes that probe ledger.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
import uuid
from pathlib import Path
from typing import Any

from app.ingest.shared_gate import GateClosedError, _write

CAPS = {
    "history_actions": {"daily": 2, "jnfh": 2},
    "history_suspension": {"daily": 2},
    "f23_completeness": {"announcements": 10},
    "f21_trading_window": {"transaction": 10},
    "f23_freshness": {"announcements": 100},
}
IDENTIFIER = re.compile(r"[a-z][a-z0-9_.-]{0,79}\Z")


def private_json(path: Path, *, maximum: int = 2 * 1024 * 1024) -> dict[str, Any]:
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        opened = os.fstat(fd)
        current = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or stat.S_ISLNK(current.st_mode)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise ValueError
        raw = os.read(fd, maximum + 1)
        if len(raw) > maximum:
            raise ValueError
        obj = json.loads(raw)
        final = path.lstat()
        if not isinstance(obj, dict) or (opened.st_dev, opened.st_ino) != (
            final.st_dev,
            final.st_ino,
        ):
            raise ValueError
        return obj
    except (OSError, ValueError, TypeError):
        raise GateClosedError("shared_observation_unavailable") from None
    finally:
        if fd is not None:
            os.close(fd)


def ledger128_total(path: Path) -> int | None:
    try:
        state = private_json(path, maximum=131072)
        if set(state) != {"schema", "total", "records", "halted"} or state["schema"] != "T-B86/v1":
            raise ValueError
        if (
            type(state["total"]) is not int
            or type(state["halted"]) is not bool
            or not isinstance(state["records"], list)
            or state["total"] != len(state["records"])
            or not 0 <= state["total"] <= 128
        ):
            raise ValueError
        seen: set[str] = set()
        counts: dict[tuple[str, str], int] = {}
        for row in state["records"]:
            if not isinstance(row, dict) or set(row) != {"id", "segment", "interface"}:
                raise ValueError
            if any(
                not isinstance(value, str) or not IDENTIFIER.fullmatch(value)
                for value in row.values()
            ):
                raise ValueError
            identifier, segment, interface = row["id"], row["segment"], row["interface"]
            if identifier in seen or interface not in CAPS.get(segment, {}):
                raise ValueError
            seen.add(identifier)
            key = segment, interface
            counts[key] = counts.get(key, 0) + 1
            if counts[key] > CAPS[segment][interface]:
                raise ValueError
        return int(state["total"])
    except (GateClosedError, ValueError, KeyError, TypeError):
        return None


def halt_present(root: Path) -> bool:
    try:
        for path in root.glob("*.halt.json"):
            halt = private_json(path)
            code = halt.get("code")
            if type(code) not in {str, int} or not re.fullmatch(
                r"(?:[1-5][0-9]{2}|uncertain|egress_mismatch)", str(code)
            ):
                return True
            if str(code) in {"103", "429"}:
                return True
    except (GateClosedError, OSError):
        return True
    return False


class MinuteLedger:
    """T-O44 bound state-* paths first; legacy UUID files remain conservative inputs.

    All discovered sources contribute to decisions. Writes go to the first bound
    state file, or the current UUID file when no bound state exists. No binding or
    probe state is renamed, removed, or initialized with a new bound identity.
    """

    def __init__(self, root: Path, licence_id: uuid.UUID) -> None:
        self.root = root
        self.legacy = root / f"{licence_id}.requests.json"
        self.path = self.legacy
        self.original: dict[str, Any] = {"calls": [], "inflight": False, "last_finished": 0}
        self.pending: dict[str, Any] | None = None

    def read(self, now: float) -> dict[str, Any]:
        try:
            bound = sorted(self.root.glob("state-*.requests.json"))
            legacy = sorted(
                path
                for path in self.root.glob("*.requests.json")
                if re.fullmatch(r"[0-9a-f-]{36}\.requests\.json", path.name)
            )
            self.path = bound[0] if bound else self.legacy
            states = []
            for path in (*bound, *legacy):
                state = private_json(path)
                calls, finished = state["calls"], state.get("last_finished", 0)
                if (
                    type(state["inflight"]) is not bool
                    or not isinstance(calls, list)
                    or any(
                        type(v) not in {int, float} or not math.isfinite(v) or v > now
                        for v in calls
                    )
                    or type(finished) not in {int, float}
                    or not math.isfinite(finished)
                    or finished > now
                ):
                    raise ValueError
                states.append(state)
                if path == self.path:
                    self.original = state
            return {
                "calls": [call for state in states for call in state["calls"]],
                "inflight": any(state["inflight"] for state in states),
                "last_finished": max(
                    (state.get("last_finished", 0) for state in states), default=0
                ),
            }
        except (GateClosedError, OSError, ValueError, KeyError, TypeError):
            raise GateClosedError("shared_minute_state_unavailable") from None

    def _current(self) -> dict[str, Any]:
        try:
            self.path.lstat()
        except FileNotFoundError:
            return {"calls": [], "inflight": False, "last_finished": 0}
        state = private_json(self.path)
        if (
            not isinstance(state.get("calls"), list)
            or any(type(v) not in {int, float} or not math.isfinite(v) for v in state["calls"])
            or type(state.get("inflight")) is not bool
            or type(state.get("last_finished", 0)) not in {int, float}
            or not math.isfinite(state.get("last_finished", 0))
        ):
            raise GateClosedError("shared_minute_state_unavailable")
        return state

    def reserve(self, now: float) -> None:
        # Re-read after the aggregate check; never roll a newly added probe call back.
        self.original = self._current()
        self.pending = self.original | {
            "calls": [v for v in self.original["calls"] if now - v < 60] + [now],
            "inflight": True,
        }
        _write(self.path, self.pending)

    def complete(self, now: float) -> None:
        if self.pending is None:
            raise GateClosedError("shared_minute_reservation_required")
        current = self._current()
        if self.pending["calls"][-1] not in current["calls"]:
            return  # Another writer replaced this entry: preserve its entire current state.
        unchanged = current == self.pending
        _write(
            self.path,
            current
            | {
                "inflight": self.original["inflight"] if unchanged else current["inflight"],
                "last_finished": max(current.get("last_finished", 0), now),
            },
        )

    def cancel_unsent(self) -> None:
        if self.pending is None:
            return
        current = self._current()
        token = self.pending["calls"][-1]
        if token not in current["calls"]:
            self.pending = None
            return  # Never restore an older snapshot when another writer has replaced us.
        unchanged = current == self.pending
        calls = list(current["calls"])
        calls.remove(token)  # Exactly one occurrence, preserving every other writer's entry.
        _write(
            self.path,
            current
            | {
                "calls": calls,
                "inflight": self.original["inflight"] if unchanged else current["inflight"],
            },
        )
        self.pending = None
