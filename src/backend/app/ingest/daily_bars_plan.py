"""Offline C2 calendar planning and readiness; never sends or reads a credential."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, select

from app.db.tables.daily_bars import outbox
from app.db.tables.market import daily_bars, trading_calendar
from app.db.tables.realtime import pipeline_runs
from app.marketdata.daily_snapshot import FINAL_AFTER
from app.master.vendor import licence_available

BEIJING = ZoneInfo("Asia/Shanghai")


class DailyBarsPlanError(ValueError):
    """Fixed issue token; no upstream body or credential material."""


def window_days(conn: Connection, trade_date: dt.date, window: int | None) -> tuple[dt.date, ...]:
    if window is not None and (type(window) is not int or window <= 0):
        raise ValueError("window_trading_days must be positive")
    opened = conn.execute(
        select(trading_calendar.c.is_open).where(trading_calendar.c.date == trade_date)
    ).scalar_one_or_none()
    if opened is None:
        raise DailyBarsPlanError("calendar_not_covered")
    if not opened:
        return ()
    count = 1 if window is None else window
    recent = tuple(
        conn.execute(
            select(trading_calendar.c.date)
            .where(trading_calendar.c.date <= trade_date, trading_calendar.c.is_open.is_(True))
            .order_by(trading_calendar.c.date.desc())
            .limit(count)
        ).scalars()
    )
    if len(recent) != count:
        raise DailyBarsPlanError("calendar_not_covered")
    first = recent[-1]
    present = set(
        conn.execute(
            select(trading_calendar.c.date).where(
                trading_calendar.c.date >= first, trading_calendar.c.date <= trade_date
            )
        ).scalars()
    )
    expected = {first + dt.timedelta(days=n) for n in range((trade_date - first).days + 1)}
    if present != expected:
        raise DailyBarsPlanError("calendar_not_covered")
    return tuple(reversed(recent))


def segments(days: Sequence[dt.date], page_days: int | None) -> tuple[tuple[dt.date, dt.date], ...]:
    """Page only actual open days; unknown k never guesses a multi-day production page."""
    if page_days is None:
        if len(days) > 1:
            raise DailyBarsPlanError("daily_bars_history_page_size_unverified")
        page_days = 1
    if type(page_days) is not int or page_days <= 0:
        raise ValueError("page_days must be positive")
    if tuple(days) != tuple(sorted(set(days))):
        raise ValueError("open days must be unique and increasing")
    return tuple(
        (days[offset], days[min(offset + page_days, len(days)) - 1])
        for offset in range(0, len(days), page_days)
    )


def ready_for_window(
    conn: Connection,
    code: str,
    licence_id: uuid.UUID,
    days: Sequence[dt.date],
    *,
    now: dt.datetime,
    user_id: uuid.UUID | None = None,
) -> bool:
    """Caller supplies the current validated grant's licence; other sources never count."""
    if not days:
        return False
    if now.tzinfo is None:
        raise ValueError("now must include timezone")
    rows = conn.execute(
        select(daily_bars).where(
            daily_bars.c.code == code,
            daily_bars.c.trade_date.in_(days),
            daily_bars.c.adj_type == "none",
            daily_bars.c.source == "mairui",
            daily_bars.c.source_licence_id == licence_id,
            daily_bars.c.fetched_at <= now,
        )
    ).all()
    ready = {
        row.trade_date
        for row in rows
        if row.fetched_at >= dt.datetime.combine(row.trade_date, FINAL_AFTER, BEIJING)
        and (
            row.is_suspended is True
            or (
                row.is_suspended is False
                and all(
                    getattr(row, field) is not None
                    for field in ("open", "high", "low", "close", "volume", "amount")
                )
            )
        )
    }
    if set(days) <= ready:
        return True
    if user_id is None or len(days) < 2 or not ready:
        return False
    if not licence_available(conn, licence_id, now):
        return False
    candidates = conn.execute(
        select(pipeline_runs.c.stats)
        .select_from(
            pipeline_runs.join(
                outbox,
                outbox.c.pipeline_run_id == pipeline_runs.c.id,
            )
        )
        .where(
            pipeline_runs.c.kind == "daily_batch",
            pipeline_runs.c.step == "daily_bars.fetch",
            pipeline_runs.c.run_date == days[-1],
            pipeline_runs.c.status.in_(["ok", "partial"]),
            pipeline_runs.c.finished_at <= now,
            pipeline_runs.c.started_at <= pipeline_runs.c.finished_at,
            outbox.c.kind == "mairui_daily_bars",
            outbox.c.status.in_(["running", "done"]),
            outbox.c.user_id == user_id,
            outbox.c.source_licence_id == licence_id,
            outbox.c.trade_date == days[-1],
            outbox.c.window_trading_days == len(days),
        )
    ).scalars()
    for stats in candidates:
        if (
            not isinstance(stats, dict)
            or stats.get("user_id") != str(user_id)
            or stats.get("window_trading_days") != len(days)
        ):
            continue
        evidence = stats.get("history_evidence")
        entry = evidence.get(code) if isinstance(evidence, dict) else None
        if not isinstance(entry, dict) or (
            entry.get("status") != "ok"
            or entry.get("code") != code
            or entry.get("no_earlier") is not True
            or entry.get("user_id") != str(user_id)
            or entry.get("source_licence_id") != str(licence_id)
            or entry.get("window") != [day.isoformat() for day in days]
        ):
            continue
        first = entry.get("first")
        if not isinstance(first, str):
            continue
        try:
            earliest = dt.date.fromisoformat(first)
        except ValueError:
            continue
        if (
            earliest in days
            and earliest > days[0]
            and earliest == min(row.trade_date for row in rows)
            and {day for day in days if day >= earliest} <= ready
        ):
            return True
    return False
