"""T-A58 product dispatch boundary: F1/F2/F4, with accounting in both modes.

Product lists use only daily_lists.count (mairui-daily/v1). No code here creates,
resets, truncates history, or borrows the probe T-B86 128 ledger. The future daily-K
caller must supply its separately authorized batch reservation at this boundary;
this task creates neither a daily-K sender nor a batch allowance.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import ipaddress
import json
import logging
import os
import stat
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ingest import send_control
from app.ingest.shared_gate import GateClosedError, _read, stop_present

logger = logging.getLogger(__name__)
BEIJING = dt.timezone(dt.timedelta(hours=8))
DATASETS = ("hslt_list", "bj_list", "kc_list")
LIST_PATHS = dict(zip(DATASETS, ("/hslt/list/", "/bj/list/all/", "/kc/list/all/"), strict=True))
SCHEMA = "mairui-daily/v1"
MAX_BYTES = 2 * 1024 * 1024


def _instant(raw: object) -> dt.datetime:
    if not isinstance(raw, str):
        raise ValueError("daily_state_unknown")
    at = dt.datetime.fromisoformat(raw)
    if at.tzinfo is None:
        raise ValueError("daily_state_unknown")
    return at


def _validate(obj: object) -> dict[str, Any]:
    if not isinstance(obj, dict) or set(obj) != {"schema", "records"} or obj["schema"] != SCHEMA:
        raise ValueError("daily_state_unknown")
    records = obj["records"]
    if not isinstance(records, list):
        raise ValueError("daily_state_unknown")
    seen = set()
    previous: dt.datetime | None = None
    for row in records:
        if not isinstance(row, dict) or set(row) != {"id", "day", "dataset", "at", "finished_at"}:
            raise ValueError("daily_state_unknown")
        token = str(uuid.UUID(row["id"]))
        at = _instant(row["at"])
        finished = _instant(row["finished_at"]) if row["finished_at"] is not None else None
        if finished is not None and finished < at:
            raise ValueError("daily_state_unknown")
        if (
            token != row["id"]
            or token in seen
            or row["dataset"] not in DATASETS
            or row["day"] != at.astimezone(BEIJING).date().isoformat()
            or (previous is not None and at < previous)
        ):
            raise ValueError("daily_state_unknown")
        seen.add(token)
        previous = at
    return obj


def _identity(fd: int, path: Path) -> None:
    opened, current = os.fstat(fd), path.lstat()
    if (
        not stat.S_ISREG(opened.st_mode)
        or stat.S_IMODE(opened.st_mode) != 0o600
        or opened.st_uid != os.geteuid()
        or opened.st_nlink != 1
        or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        or stat.S_ISLNK(current.st_mode)
    ):
        raise GateClosedError("daily_counter_private_required")


@contextlib.contextmanager
def _ledger(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    """Same inode/flock/fsync discipline as tb86_offline; never O_CREAT or reset."""
    import fcntl

    fd = None
    try:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
        _identity(fd, path)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _identity(fd, path)
        raw = os.read(fd, MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("daily_state_unknown")
        state = _validate(json.loads(raw))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        if fd is not None:
            os.close(fd)
        raise GateClosedError("daily_counter_unavailable") from None
    except BaseException:
        if fd is not None:
            os.close(fd)
        raise
    try:
        yield fd, state
    finally:
        os.close(fd)


def _persist(fd: int, path: Path, obj: dict[str, Any]) -> None:
    # Rewrite the JSON in place under flock, retaining every previous record.
    # A crash/partial write becomes unknown state, never an implicit zero counter.
    try:
        _identity(fd, path)
        raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        if len(raw) > MAX_BYTES:
            raise GateClosedError("daily_counter_full")
        os.lseek(fd, 0, os.SEEK_SET)
        while raw:
            written = os.write(fd, raw)
            if written <= 0:
                raise GateClosedError("daily_counter_write_failed")
            raw = raw[written:]
        os.ftruncate(fd, os.lseek(fd, 0, os.SEEK_CUR))
        os.fsync(fd)  # Never bypassed, must complete before even constructing HTTPSConnection.
        _identity(fd, path)
    except OSError:
        raise GateClosedError("daily_counter_write_failed") from None


def _lock_holder(root: Path, owned: bool) -> int | str | None:
    """Only a PID, never lease tokens, licence IDs or arbitrary file contents."""
    if owned:
        return os.getpid()
    try:
        info = (root / "send-control.lock").stat()
        device = (os.major(info.st_dev), os.minor(info.st_dev), info.st_ino)
        with Path("/proc/locks").open(encoding="ascii") as stream:
            for line in stream:
                fields = line.split()
                if len(fields) < 6 or fields[1] != "FLOCK":
                    continue
                major, minor, inode = fields[5].split(":")
                if (int(major, 16), int(minor, 16), int(inode)) == device:
                    return int(fields[4])
    except (OSError, ValueError):
        return "unknown"
    return None


@dataclass
class Permit:
    governance: Governance
    snapshot: dict[str, Any]
    fd: int
    dataset: str
    inflight: bool = True
    sent: bool = False

    def claim(self, path: str) -> None:
        if self.sent or not self.inflight or path != LIST_PATHS[self.dataset]:
            raise GateClosedError("product_dispatch_path_or_replay_refused")
        self.check()
        self.sent = True

    def check(self) -> None:
        _identity(self.fd, self.governance.counter)
        self.governance.check_stop(self.snapshot)


class Governance:
    def __init__(
        self,
        root: Path,
        *,
        enforce: bool,
        clock: Callable[[], dt.datetime],
        legacy_stops: tuple[Path, ...] = (),
    ) -> None:
        self.root, self.enforce, self.clock = root, enforce, clock
        self.counter = root / "daily_lists.count"
        self.stops = (root / "STOP", *legacy_stops)
        self._observed: set[tuple[str, str, str]] = set()

    def _record(self, kind: str, snapshot: dict[str, Any], *, reason: str) -> None:
        key = (str(snapshot["reservation_id"]), kind, reason)
        if key in self._observed:
            return
        self._observed.add(key)
        code = (
            {
                "lock": "skipped_lock",
                "stop": "blocked_stop",
                "daily": "blocked_daily",
                "budget": "blocked_budget",
            }[kind]
            if self.enforce
            else f"bypass_{kind}_would_block"
        )
        # The object is built from allowlisted counts/booleans/PIDs/UUIDs only.
        logger.info(
            "send_governance %s",
            json.dumps(
                {
                    "code": code,
                    "would_block": True,
                    "ts": self.clock().astimezone(BEIJING).isoformat(),
                    "snapshot": {**snapshot, "reason": reason},
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        )

    def _decision(self, kind: str, snapshot: dict[str, Any], reason: str) -> None:
        self._record(kind, snapshot, reason=reason)
        if self.enforce:
            raise GateClosedError("send_governance_" + kind + "_refused")

    def check_stop(self, snapshot: dict[str, Any]) -> bool:
        stopped = False
        for index, path in enumerate(self.stops):
            try:
                present = stop_present(path)
            except GateClosedError:
                present = True
            snapshot["stop_" + str(index)] = present
            stopped |= present
        if stopped:
            self._decision("stop", snapshot, "STOP_present_or_unknown")
        return stopped

    @contextlib.contextmanager
    def dispatch(
        self,
        *,
        token: uuid.UUID,
        dataset: str,
        expected_day: dt.date,
        trading_day: bool,
    ) -> Iterator[Permit]:
        if dataset not in DATASETS or self.clock().tzinfo is None:
            raise GateClosedError("daily_dispatch_invalid")
        if send_control.owned(self.root):
            raise GateClosedError("shared_control_reentry_refused")
        snapshot: dict[str, Any] = {
            "ledger_total": None,
            "daily_count": None,
            "reservation_id": str(token),
            "lock_holder": "unknown",
            "stop_0": None,
        }
        with contextlib.ExitStack() as stack:
            try:
                stack.enter_context(send_control.critical(self.root, blocking=False))
                locked = True
            except GateClosedError as exc:
                if str(exc) != "shared_control_busy":
                    raise  # Invalid filesystem/permissions are not a safe observation mode.
                locked = False
            snapshot["lock_holder"] = _lock_holder(self.root, locked)
            for index, path in enumerate(self.stops):
                snapshot["stop_" + str(index)] = self._stop_flag(path)
            legacy_busy = any(
                os.path.lexists(self.root / name)
                for name in (
                    "single-egress.lease.json",
                    "probe-waiting.lease.json",
                )
            )
            snapshot["legacy_lease_present"] = legacy_busy
            try:
                fd, state = stack.enter_context(_ledger(self.counter))
            except GateClosedError:
                if not locked or legacy_busy:
                    self._record("lock", snapshot, reason="send_lock_or_uncertain_lease")
                self._record(
                    "budget",
                    {**snapshot, "accounting_unavailable": True},
                    reason="daily_counter_unavailable",
                )
                raise  # Chief: accounting failure is hard in BOTH modes.
            now = self.clock().astimezone(BEIJING)
            records = state["records"]
            today = [row for row in records if row["day"] == now.date().isoformat()]
            snapshot.update(
                ledger_total=len(records),
                daily_count=len(today),
                unfinished=sum(row["finished_at"] is None for row in records),
            )
            # Identity dedup is unconditional, including in observation mode.
            if any(row["id"] == str(token) for row in records):
                raise GateClosedError("daily_reservation_already_consumed")
            if not locked or legacy_busy or any(row["finished_at"] is None for row in records):
                self._decision("lock", snapshot, "send_lock_or_uncertain_lease")
            # F2 is evaluated/logged ahead of F4. Defer the strong STOP exception until
            # after reservation so STOP attempts are accounted without sending HTTP.
            stop_blocked = any(self._stop_flag(path) for path in self.stops)
            for index, path in enumerate(self.stops):
                snapshot["stop_" + str(index)] = self._stop_flag(path)
            if stop_blocked:
                self._record("stop", snapshot, reason="STOP_present_or_unknown")
            reasons = []
            if (
                not trading_day
                or now.date() != expected_day
                or not dt.time(18) <= now.time() < dt.time(23, 59, 59)
            ):
                reasons.append("outside_daily_window")
            if len(today) >= 3:
                reasons.append("daily_budget_exhausted")
            if any(row["dataset"] == dataset for row in today):
                reasons.append("daily_endpoint_already_reserved")
            if len(today) < 3 and dataset != DATASETS[len(today)]:
                reasons.append("daily_endpoint_out_of_order")
            if (
                today
                and (now - _instant(today[-1]["finished_at"] or today[-1]["at"])).total_seconds()
                < 60
            ):
                reasons.append("daily_interval_not_elapsed")
            if records and now < _instant(records[-1]["at"]):
                self._record("budget", snapshot, reason="clock_reversed")
                raise GateClosedError("daily_clock_reversed")
            if reasons:
                self._decision("daily", snapshot, reasons[0])
            records.append(
                {
                    "id": str(token),
                    "day": now.date().isoformat(),
                    "dataset": dataset,
                    "at": now.isoformat(),
                    "finished_at": now.isoformat() if stop_blocked and self.enforce else None,
                }
            )
            try:
                _persist(fd, self.counter, state)
            except GateClosedError:
                self._record(
                    "budget",
                    {**snapshot, "accounting_unavailable": True},
                    reason="daily_counter_write_failed",
                )
                raise
            snapshot.update(ledger_total_after=len(records), daily_count_after=len(today) + 1)
            if stop_blocked and self.enforce:
                raise GateClosedError("send_governance_stop_refused")
            permit = Permit(self, snapshot, fd, dataset)
            try:
                permit.check()
                yield permit  # Both inode locks remain held through dispatch and response.
            except BaseException:
                # The reservation remains without completion. F1 treats this as unknown
                # in-flight next time; no reset/automatic retry is provided.
                raise
            else:
                records[-1]["finished_at"] = self.clock().astimezone(BEIJING).isoformat()
                _persist(fd, self.counter, state)
            finally:
                permit.inflight = False

    @staticmethod
    def _stop_flag(path: Path) -> bool:
        try:
            return stop_present(path)
        except GateClosedError:
            return True


def expected_egress(root: Path, licence_id: uuid.UUID) -> str:
    policy = _read(root / "policy.json")
    try:
        if policy["schema"] != "mairui-shared/v1" or str(licence_id) not in policy["licences"]:
            raise ValueError
        return str(ipaddress.ip_address(policy["egress_ip"]))
    except (KeyError, TypeError, ValueError):
        raise GateClosedError("shared_policy_invalid") from None
