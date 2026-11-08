"""T-A53 shared, fail-closed live gate. Standard library only; no credentials or I/O on import.

The operator mounts ONE private POSIX directory into ingest and every probe runner.
An exclusive lease survives crashes. Only an explicitly authorized operator may remove
STOP, halt or an uncertain lease; this module has no reset/initialization command.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import ipaddress
import json
import os
import re
import stat
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = "mairui-shared/v1"
LOCK_KEY = "ingest:single-egress"
SOURCES = {"product_daily", "product_verify", "probe_tb05", "probe_tb86"}


class GateClosedError(RuntimeError):
    """Fixed diagnostic only; never include upstream text, URLs or credentials."""


def limit_code(status: int | None, body: object) -> str | None:
    if status in {103, 429}:
        return str(status)
    if isinstance(body, dict):
        for key, value in body.items():
            if str(key).lower() in {"code", "error_code", "status"} and str(value) in {
                "103",
                "429",
            }:
                return str(value)
            result = limit_code(None, value)
            if result:
                return result
    elif isinstance(body, list):
        for value in body:
            result = limit_code(None, value)
            if result:
                return result
    elif isinstance(body, str):
        match = re.search(r"(?<!\d)(103|429)(?!\d)", body)
        if match:
            return match[1]
    return None


def public_egress() -> str:
    connection = http.client.HTTPSConnection("myip.ipip.net", timeout=10)
    try:
        connection.request("GET", "/", headers={"Connection": "close"})
        response = connection.getresponse()
        if response.status != 200:
            raise GateClosedError("egress_check_failed")
        body = response.read(4096).decode("utf-8", errors="replace")
        for candidate in re.findall(r"[0-9A-Fa-f:.]{7,45}", body):
            try:
                return str(ipaddress.ip_address(candidate.strip(".:")))
            except ValueError:
                continue
        raise GateClosedError("egress_check_failed")
    except Exception:  # noqa: BLE001 - do not expose transport errors
        raise GateClosedError("egress_check_failed") from None
    finally:
        connection.close()


def _read(path: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or (os.name != "nt" and info.st_mode & 0o022)
        ):
            raise GateClosedError("shared_state_not_regular")
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            raise GateClosedError("shared_state_invalid")
        return obj
    except (OSError, ValueError):
        raise GateClosedError("shared_state_unavailable") from None


def _sync_directory(path: Path) -> None:
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _write(path: Path, obj: dict[str, Any], *, exclusive: bool = False) -> None:
    temporary = path if exclusive else path.with_name("." + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(obj, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        if not exclusive:
            os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if not exclusive and temporary.exists():
            temporary.unlink()


def write_stop(path: Path) -> None:
    """Latch a fixed diagnostic durably, never read/copy historical STOP contents."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write("operator_review_required\n")
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(path.parent)


def map_legacy_stop(path: Path) -> bool:
    if not path.exists():
        return False
    raw = os.environ.get("MAIRUI_SHARED_STATE_DIR", "")
    root = Path(raw)
    if not raw or not root.is_dir() or root.is_symlink():
        raise GateClosedError("shared_directory_required")
    if os.name != "nt" and root.stat().st_mode & 0o007:
        raise GateClosedError("shared_directory_must_be_private")
    write_stop(root / "STOP")
    return True


def bound_halt(root: Path, licence_id: uuid.UUID) -> Path:
    binding = root / (str(licence_id) + ".binding.json")
    if not binding.exists():
        return root / (str(licence_id) + ".halt.json")
    key = _read(binding).get("certificate_id")
    if not isinstance(key, str) or not re.fullmatch(r"certificate-[0-9a-f]{64}", key):
        raise GateClosedError("shared_certificate_binding_invalid")
    return root / (key + ".halt.json")


def related_licences(root: Path, licence_id: uuid.UUID) -> list[uuid.UUID]:
    target = bound_halt(root, licence_id).name
    result = {licence_id}
    for path in root.glob("*.binding.json"):
        try:
            ident = uuid.UUID(path.name.removesuffix(".binding.json"))
        except ValueError:
            raise GateClosedError("shared_certificate_binding_invalid") from None
        if bound_halt(root, ident).name == target:
            result.add(ident)
    return list(result)


class SharedGate:
    def __init__(self, root: Path, licence_id: uuid.UUID, source: str) -> None:
        if source not in SOURCES or not root.is_dir() or root.is_symlink():
            raise GateClosedError("shared_directory_required")
        if os.name != "nt" and root.stat().st_mode & 0o007:
            raise GateClosedError("shared_directory_must_be_private")
        self.root, self.licence_id, self.source = root, str(licence_id), source
        self.policy = _read(root / "policy.json")
        if self.policy.get("schema") != SCHEMA:
            raise GateClosedError("shared_policy_invalid")
        try:
            policy = self.policy["licences"][self.licence_id]
            self.limit = policy["per_minute_limit"]
            self.expected_ip = str(ipaddress.ip_address(self.policy["egress_ip"]))
            if type(self.limit) is not int or not 1 <= self.limit <= 5400:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise GateClosedError("shared_licence_policy_missing") from None
        self.stop = root / "STOP"
        self.halt_path = bound_halt(root, licence_id)
        self.state_path = self.halt_path.with_name(
            self.halt_path.name.replace(".halt.json", ".requests.json")
        )
        self.certificate_confirmed = False
        self.lock_path = root / "single-egress.lease.json"
        self.probe_waiting = root / "probe-waiting.lease.json"
        self.owns_priority = False
        self.token: str | None = None
        self.egress_confirmed = False
        self.inflight = False

    @classmethod
    def from_environment(cls, licence_id: uuid.UUID | None, source: str) -> SharedGate:
        raw = os.environ.get("MAIRUI_SHARED_STATE_DIR", "")
        if not raw:
            raise GateClosedError("shared_directory_not_configured")
        try:
            ident = licence_id or uuid.UUID(os.environ.get("MAIRUI_SOURCE_LICENCE_ID", ""))
        except ValueError:
            raise GateClosedError("shared_licence_id_required") from None
        return cls(Path(raw), ident, source)

    def bind_certificate(self, secret: str) -> None:
        if self.token is None or not secret:
            raise GateClosedError("shared_lease_and_certificate_required")
        # A private, domain-separated opaque identity survives row replacement and deletion.
        # It is never returned in API responses/logs; no DB HMAC or master key is read.
        key = "certificate-" + hashlib.sha256(b"mairui-shared/v1\0" + secret.encode()).hexdigest()
        binding = self.root / (self.licence_id + ".binding.json")
        if binding.exists() and _read(binding).get("certificate_id") != key:
            raise GateClosedError("shared_certificate_binding_changed")
        if not binding.exists():
            _write(binding, {"certificate_id": key}, exclusive=True)
        self.halt_path = self.root / (key + ".halt.json")
        self.state_path = self.root / (key + ".requests.json")
        self.certificate_confirmed = True
        self.check()

    def check(self) -> None:
        if self.stop.exists():
            raise GateClosedError("shared_STOP")
        if self.halt_path.exists():
            raise GateClosedError("shared_licence_halted")
        # An unbound v1 UUID latch cannot be safely attributed after row replacement.
        # Preserve it and fail closed pending authorized operator migration.
        if any(
            re.fullmatch(r"[0-9a-f-]{36}\.halt\.json", path.name)
            for path in self.root.glob("*.halt.json")
        ):
            raise GateClosedError("shared_legacy_licence_halted")
        for path in self.root.glob("*.requests.json"):
            if re.fullmatch(r"[0-9a-f-]{36}\.requests\.json", path.name):
                legacy = _read(path)
                if legacy.get("inflight") or legacy.get("last_finished", 0) > time.time() - 60:
                    raise GateClosedError("shared_legacy_budget_requires_review")
        if self.token is not None and _read(self.lock_path).get("token") != self.token:
            raise GateClosedError("shared_lease_replaced")

    def acquire(self) -> None:
        self.check()
        token = uuid.uuid4().hex
        if self.source.startswith("probe_"):
            try:
                _write(self.probe_waiting, {"token": token}, exclusive=True)
                self.owns_priority = True
            except FileExistsError:
                raise GateClosedError("shared_egress_busy_or_uncertain") from None
        try:
            if self.source.startswith("product_") and self.probe_waiting.exists():
                raise GateClosedError("shared_egress_busy_or_uncertain")
            _write(
                self.lock_path,
                {
                    "key": LOCK_KEY,
                    "token": token,
                    "source": self.source,
                    "licence_id": self.licence_id,
                },
                exclusive=True,
            )
            self.token = token
            self.check()
            if self.source.startswith("product_") and self.probe_waiting.exists():
                self.release()
                raise GateClosedError("shared_egress_busy_or_uncertain")
        except (FileExistsError, GateClosedError):
            if self.owns_priority and _read(self.probe_waiting).get("token") == token:
                self.probe_waiting.unlink()
                self.owns_priority = False
            raise GateClosedError("shared_egress_busy_or_uncertain") from None

    def confirm_egress(self, observed: str) -> None:
        if observed != self.expected_ip:
            self.trip("egress_mismatch")
            raise GateClosedError("shared_egress_mismatch")
        self.egress_confirmed = True

    def product_delay(self, now: float) -> float:
        self.check()
        if not self.state_path.exists():
            return 0.0
        state = _read(self.state_path)
        if state.get("inflight"):
            raise GateClosedError("shared_prior_request_uncertain")
        if now < state.get("last_finished", 0):
            raise GateClosedError("shared_clock_reversed")
        return max(0.0, 60 - (now - state.get("last_finished", 0)))

    def reserve(self, *, now: float | None = None, limit: int | None = None) -> None:
        self.check()
        if self.token is None or not self.egress_confirmed or not self.certificate_confirmed:
            raise GateClosedError("shared_lease_egress_and_certificate_required")
        timestamp = time.time() if now is None else now
        state = (
            _read(self.state_path) if self.state_path.exists() else {"calls": [], "inflight": False}
        )
        if state.get("inflight"):
            raise GateClosedError("shared_prior_request_uncertain")
        calls = state.get("calls")
        if not isinstance(calls, list) or any(type(value) not in {int, float} for value in calls):
            raise GateClosedError("shared_budget_state_invalid")
        if any(value > timestamp for value in calls):
            raise GateClosedError("shared_clock_reversed")
        calls = [value for value in calls if timestamp - value < 60]
        maximum = min(self.limit, limit) if limit is not None else self.limit
        if len(calls) >= maximum:
            raise GateClosedError("shared_minute_budget_exhausted")
        if self.source.startswith("product_") and timestamp - state.get("last_finished", 0) < 60:
            raise GateClosedError("shared_product_interval_not_elapsed")
        calls.append(timestamp)
        _write(
            self.state_path,
            {"calls": calls, "inflight": True, "last_finished": state.get("last_finished", 0)},
        )
        self.inflight = True

    def complete(self, *, now: float | None = None) -> None:
        state = _read(self.state_path)
        _write(
            self.state_path,
            state | {"inflight": False, "last_finished": time.time() if now is None else now},
        )
        self.inflight = False

    def trip(self, code: str) -> uuid.UUID:
        allowed = {"103", "429", "uncertain", "egress_mismatch"}
        if code not in allowed:
            raise GateClosedError("shared_halt_code_invalid")
        with contextlib.suppress(FileExistsError):
            _write(
                self.halt_path,
                {
                    "id": str(uuid.uuid4()),
                    "source": self.source,
                    "code": code,
                    "at": time.time(),
                    "licence_id": self.licence_id,
                },
                exclusive=True,
            )
        return uuid.UUID(_read(self.halt_path)["id"])

    def release(self) -> None:
        if self.token is None:
            return
        if self.inflight:
            self.trip("uncertain")
            return  # Lease and write-ahead reservation persist across crash/uncertainty.
        if _read(self.lock_path).get("token") != self.token:
            raise GateClosedError("shared_lease_replaced")
        self.lock_path.unlink()
        if self.owns_priority and _read(self.probe_waiting).get("token") == self.token:
            self.probe_waiting.unlink()
            self.owns_priority = False
        _sync_directory(self.root)
        self.token = None

    def __enter__(self) -> SharedGate:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        with contextlib.suppress(OSError):
            self.release()
