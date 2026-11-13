"""Offline C2 calendar planning and readiness; never sends or reads a credential."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, select

from app.db.tables.market import daily_bars, trading_calendar
from app.marketdata.daily_snapshot import FINAL_AFTER

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
    return set(days) <= ready
