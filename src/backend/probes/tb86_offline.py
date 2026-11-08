# ruff: noqa: BLE001
"""T-B86 OFFLINE ONLY: no transport, environment credential access or secret creation.

This prepares controls, not authorization. Importing/running this module cannot call
Mairui. A future explicitly authorized runner must reuse B81's serial Session,
zero retries/redirects, echo protection and exception redaction; set umask 077,
create the approved temporary certificate with mode 600, and delete it in finally.
Never invoke B81.main(): its plan/30-call authorization belongs to a finished task.
The real ledger is deliberately NOT initialized here. Missing/unknown state fails
closed and must be reconciled by the coordinator, never reset to zero.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


# Reuse B81's pure control logic without importing its live runner/requests stack.
class HaltError(Exception):
    """Fixed nonsecret reason only."""


def business_limit(value: Any) -> bool:  # noqa: ANN401
    if isinstance(value, dict):
        return any(
            (str(k).lower() in {"code", "error_code", "status"} and str(v) in {"103", "429"})
            or business_limit(v)
            for k, v in value.items()
        )
    if isinstance(value, list):
        return any(business_limit(v) for v in value)
    return isinstance(value, str) and bool(re.search(r"(?<!\d)(?:103|429)\s*[:：]", value))


COUNTER = Path("/workspace/team/runtime/mairui-batch-T-B86.count")
TEMP_SECRET = Path("/workspace/team/runtime/mairui-T-B86.tmp")
STOP = Path(__file__).resolve().parent / "results/STOP"
TOTAL_CAP = 128
# Latest dispatch reduces F21 from T-A19's 12 to 10: two calls stay unallocated.
CAPS = {
    "history_actions": {"daily": 2, "jnfh": 2},
    "history_suspension": {"daily": 2},
    "f23_completeness": {"announcements": 10},
    "f21_trading_window": {"transaction": 10},
    "f23_freshness": {"announcements": 100},
}
# Public/synthetic planning only; not an executable request manifest.
EVIDENCE_PLAN = (
    (
        "history_actions",
        "cash dividend + bonus-share event; daily/jnfh; official event dates required",
        "personal_authorization_pending",
    ),
    (
        "history_suspension",
        "official suspension notice + control daily; never infer suspension from missing bars",
        "personal_authorization_pending",
    ),
    (
        "f23_completeness",
        "at least ten independently known risk notices; zero misses",
        "T-R22_manifest_and_dispatch_pending",
    ),
    (
        "f21_trading_window",
        "five stocks, trading-day after 15:40 and next-session pre-open; unit/finality",
        "later_trading_dispatch_pending",
    ),
    (
        "f23_freshness",
        "20 stocks x five consecutive trading days; next-day Beijing 09:00; >=95%",
        "later_trading_dispatch_pending",
    ),
)
SCHEMA = "T-B86/v1"
IDENTIFIER = re.compile(r"[a-z][a-z0-9_.-]{0,79}\Z")


def validate_response(status: int, body: Any) -> None:  # noqa: ANN401
    """Reuse B81 business-limit detection, also check HTTP103 and all business codes."""
    if (
        status in {103, 429}
        or (isinstance(body, (str, int)) and str(body) in {"103", "429"})
        or business_limit(body)
    ):
        raise HaltError("rate_limit_103_or_429")
    if not 200 <= status < 300:
        raise HaltError("http_failure_no_retry")
    if not isinstance(body, (dict, list)):
        raise HaltError("invalid_json_or_payload_no_retry")
    if isinstance(body, dict):
        for key in ("code", "error_code", "status"):
            if key in body and str(body[key]).lower() not in {
                "0",
                "200",
                "true",
                "none",
                "ok",
                "success",
                "",
            }:
                raise HaltError("business_failure_no_retry")


def validate_state(state: Any) -> dict[str, Any]:  # noqa: ANN401
    if not isinstance(state, dict) or set(state) != {"schema", "total", "records", "halted"}:
        raise HaltError("counter_state_unknown")
    if (
        state["schema"] != SCHEMA
        or type(state["total"]) is not int
        or type(state["halted"]) is not bool
        or not isinstance(state["records"], list)
        or state["total"] != len(state["records"])
        or not 0 <= state["total"] <= TOTAL_CAP
    ):
        raise HaltError("counter_state_unknown")
    seen = set()
    counts: dict[tuple[str, str], int] = {}
    for row in state["records"]:
        if not isinstance(row, dict) or set(row) != {"id", "segment", "interface"}:
            raise HaltError("counter_state_unknown")
        if any(not isinstance(v, str) or not IDENTIFIER.fullmatch(v) for v in row.values()):
            raise HaltError("counter_state_unknown")
        identifier, segment, interface = row["id"], row["segment"], row["interface"]
        if identifier in seen or interface not in CAPS.get(segment, {}):
            raise HaltError("counter_state_unknown")
        seen.add(identifier)
        key = (segment, interface)
        counts[key] = counts.get(key, 0) + 1
        if counts[key] > CAPS[segment][interface]:
            raise HaltError("counter_state_unknown")
    return state


def _persist(fd: int, state: dict[str, Any]) -> None:
    raw = json.dumps(state, separators=(",", ":")).encode()
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    while raw:
        written = os.write(fd, raw)
        if written <= 0:
            raise HaltError("counter_write_failed")
        raw = raw[written:]
    os.fsync(fd)  # Must finish before any future dispatch. Corruption fails closed.


@contextmanager
def reservation(
    counter: Path,
    stop: Path,
    segment: str,
    interface: str,
    identifier: str,
    *,
    enabled_segments: frozenset[str] = frozenset(),
) -> Iterator[int]:
    """Hold the nonblocking process lock THROUGH dispatch; consume even on failure.

    No actual dispatch is implemented in this offline module. enabled_segments is
    empty by default and is NOT proof of user authorization. Tests use tmp files;
    a future runner may enable only the separately authorized/released segment.
    """
    if segment not in enabled_segments:
        raise HaltError("segment_not_released")
    if interface not in CAPS.get(segment, {}) or not IDENTIFIER.fullmatch(identifier):
        raise HaltError("invalid_reservation")
    if stop.exists():
        raise HaltError("STOP_present")
    fd = -1
    try:
        # Never O_CREAT: unknown/missing historic counts may not become zero.
        fd = os.open(counter, os.O_RDWR | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            raise HaltError("counter_permissions_invalid")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if os.fstat(fd).st_ino != counter.lstat().st_ino:
            raise HaltError("counter_replaced")
        raw = os.read(fd, 131073)
        if len(raw) > 131072:
            raise HaltError("counter_state_unknown")
        state = validate_state(json.loads(raw))
        if state["halted"]:
            raise HaltError("batch_halted")
        if stop.exists():
            raise HaltError("STOP_present")
        if any(row["id"] == identifier for row in state["records"]):
            raise HaltError("reservation_already_consumed")
        used = sum(
            row["segment"] == segment and row["interface"] == interface for row in state["records"]
        )
        if state["total"] >= TOTAL_CAP or used >= CAPS[segment][interface]:
            raise HaltError("budget_exhausted")
        state["records"].append({"id": identifier, "segment": segment, "interface": interface})
        state["total"] += 1
        _persist(fd, state)
        try:
            if stop.exists():
                raise HaltError("STOP_present")
            yield state["total"]
        except BaseException:
            state["halted"] = True
            _persist(fd, state)
            # Never propagate a transport exception/repr/URL, even from a future caller.
            raise HaltError("reserved_execution_aborted_no_retry") from None
    except HaltError:
        raise
    except BaseException:
        raise HaltError("counter_or_execution_unavailable_no_retry") from None
    finally:
        if fd >= 0:
            os.close(fd)


def main() -> int:
    print(
        json.dumps(
            {
                "task": "T-B86",
                "state": "offline_only_waiting_personal_authorization",
                "new_calls": 0,
            }
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
