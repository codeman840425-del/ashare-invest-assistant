"""One physical POSIX mutex for dispatch and every supported STOP/pause writer.

The permanent lock inode must never be unlinked/replaced. There is no TTL that
can expire during HTTP. Crash outcomes remain latched by the existing lease.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import stat
import threading
from collections.abc import Iterator
from pathlib import Path

_local = threading.local()


def root_from_environment() -> Path:
    from app.ingest.shared_gate import GateClosedError

    raw = os.environ.get("MAIRUI_SHARED_STATE_DIR", "")
    if not raw:
        raise GateClosedError("shared_directory_not_configured")
    return Path(raw)


def owned(root: Path) -> bool:
    return getattr(_local, "owner", None) == (os.getpid(), str(root.resolve()))


def wire_started(root: Path) -> bool:
    return owned(root) and bool(getattr(_local, "wire_started", False))


def begin_wire(root: Path) -> None:
    from app.ingest.shared_gate import GateClosedError

    if not owned(root):
        raise GateClosedError("shared_control_not_owned")
    _local.wire_started = True


def stop_flag(path: Path) -> bool:
    from app.ingest.shared_gate import GateClosedError, stop_present

    try:
        return stop_present(path)
    except GateClosedError:
        return True


def check_stops(root: Path, halt_path: Path | None = None) -> None:
    from app.ingest.shared_gate import GateClosedError

    paths = (root / "STOP",) + ((halt_path,) if halt_path is not None else ())
    if any(stop_flag(path) for path in paths):
        raise GateClosedError("shared_STOP")


def check_product(gate: object) -> None:
    from app.ingest.shared_gate import SharedGate

    if not isinstance(gate, SharedGate):
        raise TypeError("product_gate_required")
    check_stops(gate.root, gate.halt_path)
    gate.check()


def legacy_leases(root: Path, *, own_token: str | None = None) -> tuple[bool, bool]:
    """One product-side lease check, including dangling links and owned verify leases.

    Probe leases remain authoritative busy signals until T-B103. Unknown regular
    leases are observed by governance; unsafe filesystem objects are always closed.
    """
    from app.ingest.shared_gate import GateClosedError

    present = probe = False
    for name in ("single-egress.lease.json", "probe-waiting.lease.json"):
        path = root / name
        fd = None
        try:
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid()
            ):
                raise GateClosedError("shared_control_lease_invalid")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            opened = os.fstat(fd)
            current = path.lstat()
            if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino) or (
                opened.st_dev,
                opened.st_ino,
            ) != (current.st_dev, current.st_ino):
                raise GateClosedError("shared_control_lease_replaced")
            try:
                value = json.loads(os.read(fd, 65537))
            except (ValueError, UnicodeError):
                value = None
            if (
                isinstance(value, dict)
                and own_token is not None
                and value.get("token") == own_token
            ):
                continue
            present = True
            probe |= name == "probe-waiting.lease.json" or (
                isinstance(value, dict) and str(value.get("source", "")).startswith("probe_")
            )
        except OSError:
            raise GateClosedError("shared_control_lease_unavailable") from None
        finally:
            if fd is not None:
                os.close(fd)
    return present, probe


def transport(root: Path, *, own_token: str | None = None) -> None:
    """Every product wire call must own the physical mutex and pass the same lease checks."""
    from app.ingest.shared_gate import GateClosedError

    if not owned(root):
        raise GateClosedError("shared_control_not_owned")
    _, probe = legacy_leases(root, own_token=own_token)
    if probe:
        raise GateClosedError("shared_control_busy")


@contextlib.contextmanager
def critical(root: Path, *, blocking: bool = True) -> Iterator[None]:
    from app.ingest.shared_gate import GateClosedError, _sync_directory

    if os.name != "posix":
        raise GateClosedError("shared_control_requires_POSIX")
    import fcntl

    if (
        not root.is_dir()
        or root.is_symlink()
        or root.resolve() != root.absolute()
        or root.stat().st_mode & 0o007
    ):
        raise GateClosedError("shared_control_directory_invalid")
    name = str(root.resolve())
    if getattr(_local, "owner", None) is not None:
        # A same-thread writer injected after a check cannot block on itself or
        # silently write inside dispatch. Refuse before reaching the transport.
        raise GateClosedError("shared_control_reentry_refused")
    fd = None
    try:
        try:
            fd = os.open(root / "send-control.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid()
            ):
                raise GateClosedError("shared_control_private_required")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError:
                logging.getLogger(__name__).info(
                    'send_control {"code":"shared_control_busy","would_block":true}'
                )
                raise GateClosedError("shared_control_busy") from None
            current = (root / "send-control.lock").lstat()
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                raise GateClosedError("shared_control_replaced")
            _local.owner = (os.getpid(), name)
            _local.wire_started = False
            _sync_directory(root)
        except OSError:
            raise GateClosedError("shared_control_unavailable") from None
        # Caller failures belong to their operation, not mutex acquisition.
        yield
    finally:
        if fd is not None:
            if getattr(_local, "owner", None) == (os.getpid(), name):
                _local.owner = None
            os.close(fd)
