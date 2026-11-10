"""Ingest-process network audit hook (T-A91 §7.11.5 ①b, plan A).

State (allow-list, egress window, approved IPs) lives only in the ``install()``
closure. The hook cannot be uninstalled. Repeat ``install()`` is a no-op.
"""

from __future__ import annotations

import ipaddress
import logging
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

logger = logging.getLogger("app.ingest.netguard")

MAIRUI_DOMAIN = "mairuiapi.com"


class EgressBlocked(RuntimeError):  # noqa: N818
    """Runtime hook refusal. Not an ``EgressDenied`` code."""


def _normalize_host(host: object) -> str:
    if host is None:
        return ""
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    text = str(host).rstrip(".").lower()
    if not text:
        return ""
    try:
        return text.encode("ascii").decode("idna")
    except (UnicodeError, UnicodeDecodeError, AttributeError):
        return text


def _is_mairui_host(host: object) -> bool:
    name = _normalize_host(host)
    return name == MAIRUI_DOMAIN or name.endswith("." + MAIRUI_DOMAIN)


def _as_ip(value: object) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if value is None:
        return None
    if isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return value
    raw = value.decode("ascii", "replace") if isinstance(value, bytes) else str(value)
    if raw.startswith("/") or raw.startswith("@"):
        return None
    try:
        return ipaddress.ip_address(raw)
    except ValueError:
        return None


# Contract §7.11.5 ①b: AF_UNIX / loopback / RFC1918 / ULA / link-local only.
# Do not use ipaddress.is_private — CPython 3.12 treats TEST-NET 203.0.113.0/24
# (and 192.0.2.0/24, 198.51.100.0/24) as private, but A1r ④ requires those denied.
_RFC1918 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
_ULA = ipaddress.ip_network("fc00::/7")


def _is_private_or_loopback(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback or ip.is_link_local:
        return True
    if ip.version == 4:
        return any(ip in net for net in _RFC1918)
    return ip in _ULA


def _audit_log(event: str, category: str, *, in_window: bool) -> None:
    logger.warning(
        "netguard_block event=%s category=%s window=%s",
        event,
        category,
        "held" if in_window else "none",
    )


def _bind() -> tuple[
    Callable[[], None],
    Callable[[object, Callable[[], bool] | None], AbstractContextManager[None]],
    Callable[[object], None],
]:
    installed = False
    # thread id → set of approved public IPs for the current window
    windows: dict[int, set[str]] = {}

    def in_window() -> bool:
        return threading.get_ident() in windows

    def hook(event: str, args: tuple[Any, ...]) -> None:
        tid = threading.get_ident()
        held = tid in windows
        if event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex"}:
            host = args[0] if args else None
            if _is_mairui_host(host) and not held:
                _audit_log(event, "mairui_dns", in_window=held)
                raise EgressBlocked("mairui_dns")
            return
        if event in {"socket.connect", "socket.connect_ex"}:
            address = args[1] if len(args) > 1 else None
            if isinstance(address, str) or (
                isinstance(address, bytes) and address[:1] in {b"/", b"@"}
            ):
                return  # AF_UNIX path
            host = address[0] if isinstance(address, tuple) and address else address
            ip = _as_ip(host)
            if ip is None:
                # hostname in connect: treat mairui as DNS rule, else allow
                # (getaddrinfo usually happens first). Public hostname still
                # rejected at connect if it is already an IP.
                if _is_mairui_host(host) and not held:
                    _audit_log(event, "mairui_dns", in_window=held)
                    raise EgressBlocked("mairui_dns")
                return
            if _is_private_or_loopback(ip):
                return
            approved = windows.get(tid, set())
            if held and str(ip) in approved:
                return
            _audit_log(event, "public_ip", in_window=held)
            raise EgressBlocked("public_ip")
        if event in {
            "subprocess.Popen",
            "os.system",
            "os.exec",
            "os.posix_spawn",
            "os.spawn",
            "os.fork",
            "os.forkpty",
        }:
            _audit_log(event, "subprocess", in_window=held)
            raise EgressBlocked("subprocess")
        if event == "ctypes.dlopen":
            # CPython's `import ctypes` does PyDLL(None) for pythonapi; allow that
            # only. Named libraries (libc, etc.) stay denied (①b / R19).
            path = args[0] if args else None
            if path is None:
                return
            _audit_log(event, "ctypes", in_window=held)
            raise EgressBlocked("ctypes")

    def install() -> None:
        nonlocal installed
        if installed:
            return
        sys.addaudithook(hook)
        installed = True

    @contextmanager
    def egress_window(
        lease: object, validate: Callable[[], bool] | None = None
    ) -> Iterator[None]:
        # Contract form: `with _egress_window(lease):`. Optional validate re-checks
        # the lease when the caller supplies one (mairui_get).
        check = validate if validate is not None else (lambda: True)
        if not check():
            raise EgressBlocked("lease")
        tid = threading.get_ident()
        windows[tid] = set()
        try:
            yield
        finally:
            windows.pop(tid, None)

    def register_resolved_ip(value: object) -> None:
        ip = _as_ip(value)
        if ip is None:
            return
        tid = threading.get_ident()
        approved = windows.get(tid)
        if approved is None:
            return
        if not _is_private_or_loopback(ip):
            approved.add(str(ip))

    return install, egress_window, register_resolved_ip


install, egress_window, register_resolved_ip = _bind()
_egress_window = egress_window


def netguard_blocks() -> int:
    """Optional heartbeat counter placeholder; hook logs are the source of truth."""
    return 0


