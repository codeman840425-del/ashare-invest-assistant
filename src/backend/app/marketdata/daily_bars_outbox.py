"""Worker-side durable daily-bar intents. No HTTP, vault or Redis dependency."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from typing import TypeGuard

from sqlalchemy import Connection, insert, select, text

from app.db.tables.daily_bars import outbox
from app.db.tables.realtime import pipeline_runs
from app.ingest import daily_bars as ingest
from app.marketdata.daily_bars import _approved_owners, _empty_stats, _record_run

GrantReader = Callable[[uuid.UUID], ingest.DailyBarsGrant | None]


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def batch_budget(batch_kind: str) -> ingest.DailyBarsBudget:
    if batch_kind not in {"daily", "backfill"}:
        raise ValueError("invalid daily-bar batch kind")
    limit = (
        ingest.DAILY_BARS_BACKFILL_BATCH_LIMIT
        if batch_kind == "backfill"
        else ingest.DAILY_BARS_BATCH_LIMIT
    )
    return ingest.daily_bars_batch_budget(limit, batch_kind)


def valid_grant(
    grant: object, owner: uuid.UUID, now: dt.datetime
) -> TypeGuard[ingest.DailyBarsGrant]:
    return bool(
        isinstance(grant, ingest.DailyBarsGrant)
        and grant.user_id == owner
        and isinstance(grant.licence_id, uuid.UUID)
        and isinstance(grant.receipt_id, uuid.UUID)
        and grant.digest
        and grant.start.tzinfo is not None
        and grant.end.tzinfo is not None
        and grant.start <= now < grant.end
    )


def enqueue(
    conn: Connection,
    *,
    trade_date: dt.date,
    user_id: uuid.UUID | None = None,
    window_trading_days: int | None = None,
    batch_kind: str = "daily",
    batch_seq: int = 0,
    grant_reader: GrantReader | None = None,
    now: dt.datetime | None = None,
) -> int:
    """Commit intent and its running pipeline row together; DB is the durable queue.

    Budget is checked before receipt access. Callers own the transaction. A repeated
    intent returns the existing item without creating an orphan running pipeline row.
    """
    if window_trading_days is not None and (
        type(window_trading_days) is not int or window_trading_days <= 0
    ):
        raise ValueError("window_trading_days must be positive")
    if type(batch_seq) is not int or batch_seq < 0:
        raise ValueError("batch_seq must be nonnegative")
    stamp = now if now is not None else utcnow()
    if stamp.tzinfo is None:
        raise ValueError("now must include timezone")
    if batch_budget(batch_kind).kind == "unset":
        _record_run(
            conn,
            trade_date,
            user_id,
            window_trading_days,
            status="skipped",
            stats=_empty_stats(
                user_id, window_trading_days, issues=["daily_bars_http_budget_unset"]
            ),
        )
        return 0
    owners = [user_id] if user_id is not None else _approved_owners(conn)
    count = 0
    for owner in owners:
        grant = (
            grant_reader(owner)
            if grant_reader is not None
            else ingest.read_daily_bars_grant(now=stamp, user_id=owner)
        )
        if not valid_grant(grant, owner, stamp):
            _record_run(
                conn,
                trade_date,
                owner,
                window_trading_days,
                status="skipped",
                stats=_empty_stats(owner, window_trading_days, issues=["data_licence_unavailable"]),
            )
            continue
        key = f"{owner}:{trade_date}:{window_trading_days}:{batch_kind}:{batch_seq}"
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('daily_bars_outbox'), hashtext(:key))"),
            {"key": key},
        )
        if conn.execute(select(outbox.c.id).where(outbox.c.idempotency_key == key)).first():
            continue
        run_id = conn.execute(
            insert(pipeline_runs)
            .values(
                kind="daily_batch",
                step="daily_bars.fetch",
                run_date=trade_date,
                status="running",
                started_at=stamp,
                finished_at=None,
                stats=_empty_stats(owner, window_trading_days),
            )
            .returning(pipeline_runs.c.id)
        ).scalar_one()
        conn.execute(
            insert(outbox).values(
                pipeline_run_id=run_id,
                idempotency_key=key,
                kind=ingest.KIND,
                trade_date=trade_date,
                user_id=owner,
                window_trading_days=window_trading_days,
                batch_kind=batch_kind,
                batch_seq=batch_seq,
                source_licence_id=grant.licence_id,
                receipt_id=grant.receipt_id,
                receipt_digest=grant.digest,
                status="pending",
                created_at=stamp,
            )
        )
        count += 1
    if not owners:
        _record_run(
            conn,
            trade_date,
            user_id,
            window_trading_days,
            status="ok",
            stats=_empty_stats(user_id, window_trading_days),
        )
    return count
