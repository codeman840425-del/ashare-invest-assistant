"""T-A75: user-scoped IP-limit escalation via ops.data_licence_events.

Fail-closed: store errors → treat as escalated for pause_s (no outbound calls).
L-2: pending escalation mark is rewritten on the next successful store call (one attempt).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import Connection, insert, text

from app.db.tables.licences import data_licence_events
from app.schemas.enums import DataLicenceStatus

S = DataLicenceStatus


def _as_utc(t: dt.datetime) -> dt.datetime:
    if t.tzinfo is None:
        return t.replace(tzinfo=dt.UTC)
    return t.astimezone(dt.UTC)


@dataclass
class PendingEscalationWrite:
    """Fail-closed pause that still needs a durable ``paused`` mark in the store."""

    licence_id: uuid.UUID
    user_id: uuid.UUID
    from_status: str
    upstream_code: str
    at: dt.datetime


@dataclass
class UserIpLimitMemory:
    hits: deque[dt.datetime] = field(default_factory=deque)
    escalated_until: dt.datetime | None = None
    pending_escalation: PendingEscalationWrite | None = None


def later(a: dt.datetime | None, b: dt.datetime | None) -> dt.datetime | None:
    """Later of two timestamps; ``None`` loses. Compare in UTC."""
    if a is None:
        return b
    if b is None:
        return a
    return a if _as_utc(a) >= _as_utc(b) else b


def trim_hits(mem: UserIpLimitMemory, now: dt.datetime, window_s: int) -> None:
    start = now - dt.timedelta(seconds=window_s)
    while mem.hits and mem.hits[0] < start:
        mem.hits.popleft()


def _write_event(
    conn: Connection,
    *,
    licence_id: uuid.UUID,
    user_id: uuid.UUID,
    event: str,
    from_status: str | None,
    to_status: str | None,
    upstream_code: str | None,
    at: dt.datetime,
) -> None:
    conn.execute(
        insert(data_licence_events).values(
            licence_id=licence_id,
            user_id=user_id,
            event=event,
            actor="ingest",
            from_status=from_status,
            to_status=to_status,
            upstream_code=upstream_code,
            at=at,
        )
    )


def rehydrate(
    conn: Connection,
    user_id: uuid.UUID,
    *,
    window_s: int,
    pause_s: int,
    now: dt.datetime,
) -> UserIpLimitMemory:
    last_mark = conn.execute(
        text(
            "SELECT at FROM ops.data_licence_events "
            "WHERE user_id = :uid AND actor = 'ingest' AND event = 'paused' "
            "AND to_status = 'ip_limited' "
            "ORDER BY at DESC LIMIT 1"
        ),
        {"uid": user_id},
    ).scalar_one_or_none()
    escalated_until = (
        last_mark + dt.timedelta(seconds=pause_s) if last_mark is not None else None
    )
    window_start = now - dt.timedelta(seconds=window_s)
    if last_mark is None:
        hits_sql = (
            "SELECT at FROM ops.data_licence_events "
            "WHERE user_id = :uid AND actor = 'ingest' AND event = 'ip_limited' "
            "AND at >= :ws ORDER BY at ASC"
        )
        params: dict[str, object] = {"uid": user_id, "ws": window_start}
    else:
        hits_sql = (
            "SELECT at FROM ops.data_licence_events "
            "WHERE user_id = :uid AND actor = 'ingest' AND event = 'ip_limited' "
            "AND at >= :ws AND at > :mark ORDER BY at ASC"
        )
        params = {"uid": user_id, "ws": window_start, "mark": last_mark}
    hits = conn.execute(text(hits_sql), params).scalars()
    return UserIpLimitMemory(hits=deque(hits), escalated_until=escalated_until)


def merge_rehydrated(mem: UserIpLimitMemory, loaded: UserIpLimitMemory) -> None:
    """Apply DB snapshot into memory; never shorten an in-memory escalate deadline (B-1)."""
    mem.hits = loaded.hits
    mem.escalated_until = later(mem.escalated_until, loaded.escalated_until)


def apply_hit_memory(
    mem: UserIpLimitMemory,
    now: dt.datetime,
    *,
    window_s: int,
    count: int,
    pause_s: int,
    single_pause_s: int,
) -> tuple[bool, dt.datetime]:
    """Pure memory escalate; used when no DB store is wired."""
    trim_hits(mem, now, window_s)
    mem.hits.append(now)
    if len(mem.hits) >= count:
        mem.hits.clear()
        until = now + dt.timedelta(seconds=pause_s)
        mem.escalated_until = later(mem.escalated_until, until)
        return True, until
    until = now + dt.timedelta(seconds=single_pause_s)
    return False, until


def ip_limit_lock_key(user_id: uuid.UUID) -> str:
    """§4.1 advisory lock key (shared by record_hit / flush / tick)."""
    return f"ingest:ip_limit:{user_id}"


def acquire_ip_limit_lock(conn: Connection, user_id: uuid.UUID) -> None:
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": ip_limit_lock_key(user_id)},
    )


def try_acquire_ip_limit_lock(conn: Connection, user_id: uuid.UUID) -> bool:
    """Non-blocking §4.1 lock for tick/rehydrate flush (T-A84 L-10)."""
    got = conn.execute(
        text("SELECT pg_try_advisory_xact_lock(hashtext(:k))"),
        {"k": ip_limit_lock_key(user_id)},
    ).scalar()
    return bool(got)


def flush_pending_escalation(conn: Connection, mem: UserIpLimitMemory) -> bool:
    """Write pending pause mark (L-2). Does **not** clear pending (L-6).

    Caller must set ``mem.pending_escalation = None`` only after the surrounding
    transaction has committed successfully. Returns True if a write was issued.
    """
    p = mem.pending_escalation
    if p is None:
        return False
    # Hit then mark — same shape as a successful record_hit escalate.
    _write_event(
        conn,
        licence_id=p.licence_id,
        user_id=p.user_id,
        event="ip_limited",
        from_status=p.from_status,
        to_status=S.IP_LIMITED.value,
        upstream_code=p.upstream_code,
        at=p.at,
    )
    _write_event(
        conn,
        licence_id=p.licence_id,
        user_id=p.user_id,
        event="paused",
        from_status=S.IP_LIMITED.value,
        to_status=S.IP_LIMITED.value,
        upstream_code=p.upstream_code,
        at=p.at,
    )
    return True


def record_hit(
    conn: Connection,
    mem: UserIpLimitMemory,
    *,
    user_id: uuid.UUID,
    licence_id: uuid.UUID,
    from_status: str,
    upstream_code: str,
    now: dt.datetime,
    window_s: int,
    count: int,
    pause_s: int,
    single_pause_s: int,
) -> tuple[bool, dt.datetime]:
    acquire_ip_limit_lock(conn, user_id)
    flush_pending_escalation(conn, mem)
    fresh = rehydrate(conn, user_id, window_s=window_s, pause_s=pause_s, now=now)
    merge_rehydrated(mem, fresh)
    _write_event(
        conn,
        licence_id=licence_id,
        user_id=user_id,
        event="ip_limited",
        from_status=from_status,
        to_status=S.IP_LIMITED.value,
        upstream_code=upstream_code,
        at=now,
    )
    escalated, until = apply_hit_memory(
        mem,
        now,
        window_s=window_s,
        count=count,
        pause_s=pause_s,
        single_pause_s=single_pause_s,
    )
    if escalated:
        _write_event(
            conn,
            licence_id=licence_id,
            user_id=user_id,
            event="paused",
            from_status=S.IP_LIMITED.value,
            to_status=S.IP_LIMITED.value,
            upstream_code=upstream_code,
            at=now,
        )
    return escalated, until


def fail_closed_until(now: dt.datetime, pause_s: int) -> dt.datetime:
    return now + dt.timedelta(seconds=pause_s)


def queue_pending_escalation(
    mem: UserIpLimitMemory,
    *,
    licence_id: uuid.UUID,
    user_id: uuid.UUID,
    from_status: str,
    upstream_code: str,
    at: dt.datetime,
) -> None:
    """Remember a fail-closed pause for the next successful store call (L-2)."""
    mem.pending_escalation = PendingEscalationWrite(
        licence_id=licence_id,
        user_id=user_id,
        from_status=from_status,
        upstream_code=upstream_code,
        at=at,
    )
