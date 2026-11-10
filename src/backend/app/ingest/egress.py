"""Unique Mairui HTTP egress for the ingest process (T-A87 / M-1, api-contract §7.11.5).

Only this module may open a socket to Mairui. Callers pass a fake ``transport``
in tests; production uses :func:`_https_get`. HALT / ``upstream_halted`` are never
cleared here.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import socket
import ssl
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import Engine, insert, select, text, update
from sqlalchemy.engine import Connection

from app.db.tables.licences import data_licence_events, user_data_licence_status, user_data_licences
from app.ingest import ip_limit as ipl
from app.ingest import netguard as ng
from app.ingest.core import Call, IngestCore
from app.ingest.state import Priority, Transition
from app.ingest.upstream import Signal, classify
from app.schemas.enums import DataLicenceStatus, DataLicenceTier

HOST = "api.mairuiapi.com"
EGRESS_DENIED_CODES = frozenset(
    {
        "halt_present",
        "single_egress_not_held",
        "core_unavailable",
        "licence_unavailable",
        "core_denied",
    }
)
ADMIT_BUDGET_S = 2.8
HALT_PERSIST_FAILED = b"licence_status_persist_failed"
HALT_LIMIT = b"limit_103_or_429"
_FATAL_HALT_MESSAGE = "ingest 致命：证书状态与停机标志均无法持久化"


class EgressDenied(Exception):  # noqa: N818
    """Fail-closed refusal before any Mairui socket. ``code`` is a fixed token."""

    def __init__(self, code: str) -> None:
        if code not in EGRESS_DENIED_CODES:
            raise ValueError("invalid EgressDenied code")
        self.code = code
        super().__init__(code)


# Release records only (T-A91: not the admit criterion). Issued nonces live in the
# HMAC closure below; stuffing these dicts must not admit a forged lease.
_ISSUED_LEASES: dict[str, EgressLease] = {}
_LEASE_LOCK_CONN: dict[str, object] = {}

# Terminal / admin-paused / expired — must not be downgraded to active (M-2).
_STRICT_STATUSES = frozenset(
    {
        DataLicenceStatus.INVALID,
        DataLicenceStatus.PAUSED_BY_ADMIN,
        DataLicenceStatus.EXPIRED,
    }
)


@dataclass(frozen=True)
class EgressLease:
    held: bool
    nonce: str = ""
    thread_id: int = 0
    lock_pid: int = 0
    mac: bytes = b""


@dataclass(frozen=True)
class EgressResult:
    status: int
    body: object
    signal: Signal
    transitions: list[Transition]


def _bind_lease_auth() -> tuple[
    Callable[[object, int, int], EgressLease],
    Callable[[EgressLease | None, float | None], bool],
    Callable[[str], None],
]:
    key = secrets.token_bytes(32)
    issued: dict[str, object] = {}

    def _mac(nonce: str, thread_id: int, lock_pid: int) -> bytes:
        payload = f"{nonce}\n{thread_id}\n{lock_pid}".encode("ascii")
        return hmac.new(key, payload, hashlib.sha256).digest()

    def issue(lock: object, lock_pid: int, thread_id: int) -> EgressLease:
        nonce = secrets.token_hex(16)
        mac = _mac(nonce, thread_id, lock_pid)
        lease = EgressLease(
            held=True, nonce=nonce, thread_id=thread_id, lock_pid=lock_pid, mac=mac
        )
        issued[nonce] = lock
        _ISSUED_LEASES[nonce] = lease
        _LEASE_LOCK_CONN[nonce] = lock
        return lease

    def valid(lease: EgressLease | None, deadline: float | None = None) -> bool:
        if lease is None or not getattr(lease, "held", False):
            return False
        nonce = getattr(lease, "nonce", "") or ""
        thread_id = getattr(lease, "thread_id", 0)
        lock_pid = getattr(lease, "lock_pid", 0)
        mac = getattr(lease, "mac", b"") or b""
        if not nonce or not mac:
            return False
        expected = _mac(str(nonce), int(thread_id), int(lock_pid))
        if not hmac.compare_digest(mac, expected):
            return False
        if threading.get_ident() != int(thread_id):
            return False
        # ③ nonce still unreleased in the closure record — not module-dict membership.
        if nonce not in issued:
            return False
        if deadline is not None and (deadline - time.monotonic()) < 0.2:
            return False
        conn = issued[nonce]
        return _conn_holds_single_egress(conn)

    def release(nonce: str) -> None:
        issued.pop(nonce, None)
        _ISSUED_LEASES.pop(nonce, None)
        _LEASE_LOCK_CONN.pop(nonce, None)

    return issue, valid, release


_issue_lease, _lease_is_valid, _release_lease = _bind_lease_auth()


def _conn_holds_single_egress(conn: object) -> bool:
    """Session still holds ``ingest:single-egress`` (T-A91 M-a / pg_locks)."""
    execute = getattr(conn, "execute", None)
    if not callable(execute):
        return False
    try:
        held = execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM pg_locks"
                "  WHERE locktype = 'advisory' AND granted"
                "    AND pid = pg_backend_pid()"
                "    AND objsubid = 1"
                "    AND classid = ((hashtext('ingest:single-egress')::bigint) >> 32)::oid"
                "    AND objid = ((hashtext('ingest:single-egress')::bigint)"
                "                 & x'ffffffff'::bigint)::oid"
                ")"
            )
        ).scalar()
        return bool(held)
    except Exception:  # noqa: BLE001 — unreadable conn is not a held lease
        return False


@contextmanager
def single_egress(engine: Engine) -> Iterator[EgressLease | None]:
    """Non-blocking session advisory lock ``ingest:single-egress`` (outermost).

    Yields an HMAC-bound ``EgressLease``. Callers must not construct an equivalent
    lease; ``mairui_get`` rejects forgeries with ``single_egress_not_held``.
    """
    with engine.connect() as lock:
        locked = lock.execute(
            text("SELECT pg_try_advisory_lock(hashtext('ingest:single-egress'))")
        ).scalar_one()
        lock.commit()
        if not locked:
            yield None
            return
        lock_pid = int(lock.execute(text("SELECT pg_backend_pid()")).scalar_one())
        lock.commit()
        lease = _issue_lease(lock, lock_pid, threading.get_ident())
        try:
            yield lease
        finally:
            _release_lease(lease.nonce)
            lock.execute(text("SELECT pg_advisory_unlock(hashtext('ingest:single-egress'))"))
            lock.commit()


def _https_get(path: str, secret: str) -> tuple[int, object]:
    """Real Mairui transport. Resolve HOST, register IPs, connect by IP with SNI."""
    from app.ingest.daily_lists import DailyHaltError

    tls: ssl.SSLSocket | None = None
    try:
        infos = socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)
        if not infos:
            raise DailyHaltError("transport_or_response_failed_no_retry")
        sockaddr: tuple[object, ...] | None = None
        family: int = socket.AF_INET
        typ: int = socket.SOCK_STREAM
        proto = 0
        for fam, kind, pr, _canon, addr in infos:
            ng.register_resolved_ip(addr[0])
            if sockaddr is None:
                family, typ, proto, sockaddr = fam, kind, pr, addr
        if sockaddr is None:
            raise DailyHaltError("transport_or_response_failed_no_retry")
        raw = socket.socket(family, typ, proto)
        raw.settimeout(20)
        raw.connect(sockaddr)
        ctx = ssl.create_default_context()
        tls = ctx.wrap_socket(raw, server_hostname=HOST)
        conn = http.client.HTTPSConnection(HOST, timeout=20)
        conn.sock = tls
        conn.request("GET", path + quote(secret, safe=""))
        response = conn.getresponse()
        if response.status in (103, 429):
            return response.status, None
        payload = response.read(16 * 1024 * 1024 + 1)
        if len(payload) > 16 * 1024 * 1024:
            raise DailyHaltError("response_too_large")
        try:
            body = json.loads(payload)
        except (ValueError, UnicodeError):
            body = "103:" if re.search(rb"(?<!\d)(103|429)(?!\d)", payload) else None
        return response.status, body
    except DailyHaltError:
        raise
    except ng.EgressBlocked:
        raise
    except Exception:  # noqa: BLE001 - sanitize; never chain upstream/credential detail
        raise DailyHaltError("transport_or_response_failed_no_retry") from None
    finally:
        if tls is not None:
            with suppress(Exception):
                tls.close()


def _write_halt(halt: Path, payload: bytes = HALT_LIMIT) -> bool:
    """O_EXCL 0600 fsync. FileExistsError counts as success. Returns False on I/O error."""
    try:
        fd = os.open(halt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        return True
    except Exception:  # noqa: BLE001
        return False


def _halt_or_die(halt: Path) -> None:
    if _write_halt(halt, HALT_PERSIST_FAILED):
        return
    print(_FATAL_HALT_MESSAGE, file=sys.stderr)
    os._exit(74)


def _persist_licence_status(
    engine: Engine,
    *,
    licence_id: uuid.UUID,
    user_id: uuid.UUID,
    to_status: DataLicenceStatus,
    event: str,
    upstream_code: str | None,
    now: dt.datetime,
) -> None:
    """Write terminal/pause status to ``user_data_licences`` + event (T-A89 M-2).

    Uses existing columns/events only — no migration. Actor is ``ingest``.
    """
    with engine.begin() as conn:
        row = conn.execute(
            select(user_data_licences.c.id, user_data_licences.c.status).where(
                user_data_licences.c.id == licence_id,
                user_data_licences.c.user_id == user_id,
                user_data_licences.c.deleted_at.is_(None),
            )
        ).first()
        if row is None:
            raise RuntimeError("licence_row_missing")
        values: dict[str, object] = {
            "status": to_status.value,
            "status_changed_at": now,
            "updated_at": now,
        }
        if upstream_code is not None:
            values["last_error_code"] = upstream_code
            values["last_error_at"] = now
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == licence_id)
            .values(**values)
        )
        conn.execute(
            insert(data_licence_events).values(
                licence_id=licence_id,
                user_id=user_id,
                event=event,
                actor="ingest",
                from_status=row.status,
                to_status=to_status.value,
                upstream_code=upstream_code,
                at=now,
            )
        )


def _row_active_licence(
    conn: Connection,
    *,
    licence_id: uuid.UUID,
    user_id: uuid.UUID,
    now: dt.datetime,
) -> tuple[DataLicenceTier, DataLicenceStatus, dt.date | None]:
    row = conn.execute(
        select(
            user_data_licence_status.c.tier,
            user_data_licence_status.c.status,
            user_data_licence_status.c.expires_on,
            user_data_licence_status.c.paused_until,
            user_data_licence_status.c.deleted_at,
        ).where(
            user_data_licence_status.c.id == licence_id,
            user_data_licence_status.c.user_id == user_id,
        )
    ).first()
    if row is None or row.deleted_at is not None:
        raise EgressDenied("licence_unavailable")
    if row.status != DataLicenceStatus.ACTIVE.value:
        raise EgressDenied("licence_unavailable")
    if row.paused_until is not None and row.paused_until > now:
        raise EgressDenied("licence_unavailable")
    return DataLicenceTier(row.tier), DataLicenceStatus(row.status), row.expires_on


def _load_active_licence(
    engine: Engine, *, licence_id: uuid.UUID, user_id: uuid.UUID, now: dt.datetime
) -> tuple[DataLicenceTier, DataLicenceStatus, dt.date | None]:
    """Legacy helper (non-admit paths). Admit uses ``_row_active_licence`` on its txn."""
    with engine.connect() as conn:
        return _row_active_licence(conn, licence_id=licence_id, user_id=user_id, now=now)


def _mark_fail_closed(core: IngestCore, user_id: uuid.UUID, now: dt.datetime) -> None:
    mem = core._user_mem(user_id)
    mem.hits.clear()
    mem.escalated_until = ipl.later(
        mem.escalated_until,
        ipl.fail_closed_until(now, core.cfg.ip_limited_escalate.pause_s),
    )


def _admit(
    *,
    core: IngestCore,
    engine: Engine,
    licence_id: uuid.UUID,
    user_id: uuid.UUID,
    now: dt.datetime,
    deadline: float,
) -> tuple[DataLicenceTier, DataLicenceStatus, dt.date | None]:
    """Single connection, single transaction, one lock (T-A91 M-b)."""
    remain = deadline - time.monotonic()
    if remain < 0.2:
        _mark_fail_closed(core, user_id, now)
        raise EgressDenied("core_denied")
    flush_ok = False
    flush_needed = False
    try:
        with engine.connect() as conn, conn.begin():
            remain = deadline - time.monotonic()
            if remain < 0.2:
                raise TimeoutError("admit_deadline")
            remain_ms = max(1, int(remain * 1000))
            lock_ms = min(1000, remain_ms)
            conn.execute(text(f"SET LOCAL lock_timeout = '{lock_ms}ms'"))
            conn.execute(text(f"SET LOCAL statement_timeout = '{remain_ms}ms'"))
            ipl.acquire_ip_limit_lock(conn, user_id)
            tier, status, expires_on = _row_active_licence(
                conn, licence_id=licence_id, user_id=user_id, now=now
            )
            core.upsert(
                licence_id,
                user_id=user_id,
                tier=tier,
                status=status,
                expires_on=expires_on,
                now=now,
                hydrate=False,
            )
            flush_needed = core._user_mem(user_id).pending_escalation is not None
            flush_ok = core.rehydrate_locked(conn, user_id, now)
    except EgressDenied:
        raise
    except Exception:  # noqa: BLE001 — fail-closed
        _mark_fail_closed(core, user_id, now)
        raise EgressDenied("core_denied") from None
    if flush_ok:
        core._user_mem(user_id).pending_escalation = None
    elif flush_needed:
        # SAVEPOINT failed: pending kept, this call denies as escalated (M-b).
        _mark_fail_closed(core, user_id, now)
        raise EgressDenied("core_denied")
    return tier, status, expires_on


def mairui_get(
    *,
    lease: EgressLease | None,
    core: IngestCore | None,
    engine: Engine,
    licence_id: uuid.UUID,
    user_id: uuid.UUID,
    path: str,
    secret: str,
    priority: Priority,
    clock: Callable[[], dt.datetime],
    stop: Path,
    halt: Path,
    transport: Callable[[str, str], tuple[int, object]] = _https_get,
) -> EgressResult:
    """Admit via IngestCore then call ``transport``. Order is fixed (contract §7.11.5)."""
    from app.ingest.daily_lists import DailyHaltError, limited

    t0 = time.monotonic()
    deadline = t0 + ADMIT_BUDGET_S
    now = clock()
    if stop.exists() or halt.exists():
        raise EgressDenied("halt_present")
    if not _lease_is_valid(lease, deadline):
        raise EgressDenied("single_egress_not_held")
    if core is None:
        raise EgressDenied("core_unavailable")

    _tier, _status, _expires = _admit(
        core=core,
        engine=engine,
        licence_id=licence_id,
        user_id=user_id,
        now=now,
        deadline=deadline,
    )
    mem_status = core.state(licence_id).status
    if mem_status in _STRICT_STATUSES:
        raise EgressDenied("licence_unavailable")

    call = Call(endpoint=path)
    core.submit(licence_id, priority, call)
    dispatched = core.next_call(now)
    if (
        dispatched is None
        or dispatched.licence_id != licence_id
        or dispatched.item is not call
    ):
        core.scheduler.drop_licence(licence_id)
        raise EgressDenied("core_denied")

    if stop.exists() or halt.exists():
        core.scheduler.release(licence_id)
        core.scheduler.drop_licence(licence_id)
        raise EgressDenied("halt_present")

    try:
        with ng.egress_window(lease, lambda: _lease_is_valid(lease, None)):
            status_code, body = transport(path, secret)
    except ng.EgressBlocked:
        core.complete(dispatched, Signal.NETWORK, clock())
        raise DailyHaltError("transport_or_response_failed_no_retry") from None
    except BaseException as exc:
        # L-c: BaseException (KeyboardInterrupt / CancelledError) must complete too.
        core.complete(dispatched, Signal.NETWORK, clock())
        if isinstance(exc, DailyHaltError):
            raise
        if isinstance(exc, Exception):
            raise DailyHaltError("transport_or_response_failed_no_retry") from None
        raise

    if limited(status_code, body) or classify(status_code, body) == Signal.IP_LIMITED:
        _write_halt(halt)
        signal = Signal.IP_LIMITED
    elif status_code == 102:
        # T-A89 A25: upstream HTTP 102 → INVALID (classify body-text path may miss bare 102).
        signal = Signal.INVALID
    else:
        signal = classify(status_code, body)

    # T-A89 M-2: 102 / INVALID — persist to DB BEFORE complete; write fail → M-c.
    if signal == Signal.INVALID:
        try:
            _persist_licence_status(
                engine,
                licence_id=licence_id,
                user_id=user_id,
                to_status=DataLicenceStatus.INVALID,
                event="invalid",
                upstream_code="102",
                now=clock(),
            )
        except Exception:  # noqa: BLE001 — event/row write failure → core_denied
            _halt_or_die(halt)
            core.complete(dispatched, Signal.INVALID, clock())
            raise EgressDenied("core_denied") from None

    transitions = core.complete(dispatched, signal, clock())
    return EgressResult(status=status_code, body=body, signal=signal, transitions=transitions)
