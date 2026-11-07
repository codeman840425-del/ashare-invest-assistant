"""Reviewed calendar seed and DB-only market clock (T-A12, seed e916d0b).

No weekday fallback, provider fetch, runtime JSON reads or automatic production writes.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Connection, func, select
from sqlalchemy.dialects.postgresql import insert

from app.aggregates.models import MarketClock
from app.common.errors import AppError, ErrorCode
from app.config_files import MarketRulesConfig
from app.db.tables.market import trading_calendar
from app.reference_files import CalendarReference
from app.schemas.enums import MarketSession

BEIJING = dt.timezone(dt.timedelta(hours=8))


def seed_calendar(conn: Connection, seed: CalendarReference) -> int:
    start, end = (
        dt.date.fromisoformat(seed.coverage_start),
        dt.date.fromisoformat(seed.coverage_end),
    )
    opens = set(seed.open_days)
    dates = [start + dt.timedelta(days=index) for index in range((end - start).days + 1)]
    stmt = insert(trading_calendar).values(
        [{"date": day, "is_open": day.isoformat() in opens} for day in dates]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[trading_calendar.c.date],
        set_={"is_open": stmt.excluded.is_open},
        where=trading_calendar.c.is_open.is_distinct_from(stmt.excluded.is_open),
    )
    return len(conn.execute(stmt.returning(trading_calendar.c.date)).scalars().all())


def market_clock(conn: Connection, now: dt.datetime, rules: MarketRulesConfig) -> MarketClock:
    if now.tzinfo is None:
        raise ValueError("market clock requires an aware instant")
    local = now.astimezone(BEIJING)
    day = local.date()
    lo, hi = conn.execute(
        select(func.min(trading_calendar.c.date), func.max(trading_calendar.c.date))
    ).one()
    detail = {
        "date": day.isoformat(),
        "coverage_start": lo.isoformat() if lo else None,
        "coverage_end": hi.isoformat() if hi else None,
    }
    if lo is None or hi is None or not lo <= day <= hi:
        raise AppError(ErrorCode.CALENDAR_NOT_COVERED, details=detail)
    row = conn.execute(
        select(trading_calendar.c.is_open).where(trading_calendar.c.date == day)
    ).first()
    if row is None:  # a hole is not a non-trading day
        raise AppError(ErrorCode.CALENDAR_NOT_COVERED, details=detail)
    if not row.is_open:
        previous = conn.execute(
            select(func.max(trading_calendar.c.date)).where(
                trading_calendar.c.date < day, trading_calendar.c.is_open
            )
        ).scalar_one()
        if previous is None:
            raise AppError(ErrorCode.CALENDAR_NOT_COVERED, details=detail)
        return MarketClock(trade_date=previous, session=MarketSession.NON_TRADING_DAY)
    segment = rules.segment_for(day)
    if segment is None:
        raise AppError(ErrorCode.MAINTENANCE, details={"issue": "market_rule_segment_missing"})
    periods = segment.sessions
    time = local.time().replace(tzinfo=None)
    for name in ("call_auction", "morning", "afternoon", "closing_auction"):
        start, end = getattr(periods, name)
        if start <= time < end:
            return MarketClock(trade_date=day, session=MarketSession(name))
    if time < periods.morning[0]:
        state = MarketSession.PRE_OPEN
    elif periods.morning[1] <= time < periods.afternoon[0]:
        state = MarketSession.LUNCH_BREAK
    else:
        state = MarketSession.CLOSED
    return MarketClock(trade_date=day, session=state)
