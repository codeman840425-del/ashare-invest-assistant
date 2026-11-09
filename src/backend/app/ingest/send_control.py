"""One physical POSIX mutex for dispatch and every supported STOP/pause writer.

The permanent lock inode must never be unlinked/replaced. There is no TTL that
can expire during HTTP. Crash outcomes remain latched by the existing lease.
"""

from __future__ import annotations

import contextlib
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
            raise GateClosedError("shared_control_busy") from None
        current = (root / "send-control.lock").lstat()
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise GateClosedError("shared_control_replaced")
        _local.owner = (os.getpid(), name)
        _sync_directory(root)
        yield
    except OSError:
        raise GateClosedError("shared_control_unavailable") from None
    finally:
        if fd is not None:
            if getattr(_local, "owner", None) == (os.getpid(), name):
                _local.owner = None
            os.close(fd)
