"""Unique Mairui HTTP egress for the ingest process (T-A87 / M-1, api-contract §7.11.5).

Only this module may open a socket to Mairui. Callers pass a fake ``transport``
in tests; production uses :func:`_https_get`. HALT / ``upstream_halted`` are never
cleared here.
"""

from __future__ import annotations

import datetime as dt
import http.client
import json
import os
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import Engine, select, text

from app.db.tables.licences import user_data_licence_status
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


class EgressDenied(Exception):
    """Fail-closed refusal before any Mairui socket. ``code`` is a fixed token."""

    def __init__(self, code: str) -> None:
        if code not in EGRESS_DENIED_CODES:
            raise ValueError("invalid EgressDenied code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class EgressLease:
    held: bool


@dataclass(frozen=True)
class EgressResult:
    status: int
    body: object
    signal: Signal
    transitions: list[Transition]


@contextmanager
def single_egress(engine: Engine) -> Iterator[EgressLease | None]:
    """Non-blocking session advisory lock ``ingest:single-egress`` (outermost)."""
    with engine.connect() as lock:
        locked = lock.execute(
            text("SELECT pg_try_advisory_lock(hashtext('ingest:single-egress'))")
        ).scalar_one()
        lock.commit()
        if not locked:
            yield None
            return
        try:
            yield EgressLease(held=True)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(hashtext('ingest:single-egress'))"))
            lock.commit()


def _https_get(path: str, secret: str) -> tuple[int, object]:
    """Real Mairui transport. No retries, no redirects. Never log secret/URL."""
    from app.ingest.daily_lists import DailyHaltError

    conn = http.client.HTTPSConnection(HOST, timeout=20)
    conn.set_debuglevel(0)
    try:
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
    except Exception:  # noqa: BLE001 - sanitize; never chain upstream/credential detail
        raise DailyHaltError("transport_or_response_failed_no_retry") from None
    finally:
        conn.close()


def _write_halt(halt: Path) -> None:
    try:
        fd = os.open(halt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, b"limit_103_or_429")
            os.fsync(fd)
        finally:
            os.close(fd)
    except FileExistsError:
        pass


def _load_active_licence(
    engine: Engine, *, licence_id: uuid.UUID, user_id: uuid.UUID, now: dt.datetime
) -> tuple[DataLicenceTier, DataLicenceStatus, dt.date | None]:
    with engine.connect() as conn:
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

    now = clock()
    if stop.exists() or halt.exists():
        raise EgressDenied("halt_present")
    if lease is None or not lease.held:
        raise EgressDenied("single_egress_not_held")
    if core is None:
        raise EgressDenied("core_unavailable")

    tier, status, expires_on = _load_active_licence(
        engine, licence_id=licence_id, user_id=user_id, now=now
    )
    core.upsert(
        licence_id,
        user_id=user_id,
        tier=tier,
        status=status,
        expires_on=expires_on,
        now=now,
    )
    core.rehydrate(user_id, now)

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
        status_code, body = transport(path, secret)
    except DailyHaltError:
        core.complete(dispatched, Signal.NETWORK, clock())
        raise
    except Exception:  # noqa: BLE001
        core.complete(dispatched, Signal.NETWORK, clock())
        raise DailyHaltError("transport_or_response_failed_no_retry") from None

    if limited(status_code, body) or classify(status_code, body) == Signal.IP_LIMITED:
        _write_halt(halt)
        signal = Signal.IP_LIMITED
    else:
        signal = classify(status_code, body)

    transitions = core.complete(dispatched, signal, clock())
    return EgressResult(status=status_code, body=body, signal=signal, transitions=transitions)

