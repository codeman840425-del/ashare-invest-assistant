"""daily-bars-backfill：默认只读演练；--apply 只入队一条 daily_bars_fetch，自己不取数。"""

from __future__ import annotations

import argparse
import datetime as dt
import math
from typing import cast
from zoneinfo import ZoneInfo

import redis
from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.common.errors import AppError
from app.config import Settings
from app.db.tables.market import trading_calendar
from app.db.tables.users import users
from app.marketdata.daily_bars import (
    DAILY_BARS_FETCH,
    UPSERT_BATCH_ROWS,
    backfill_window_days,
    daily_universe,
)
from app.reports.service import covered
from app.workers import jobs as jobs_mod

BEIJING = ZoneInfo("Asia/Shanghai")
_FINAL_CUTOFF = dt.time(17, 45)
_APPLY_LOCK_START = dt.time(17, 0)
_APPLY_LOCK_END = dt.time(17, 45)


def _is_open(conn: Connection, day: dt.date) -> bool:
    try:
        return bool(covered(conn, day))
    except AppError as exc:
        details = exc.details or {}
        if details.get("issue") == "CALENDAR_NOT_COVERED":
            return False
        raise


def _previous_open(conn: Connection, today: dt.date) -> dt.date | None:
    return conn.execute(
        select(trading_calendar.c.date)
        .where(trading_calendar.c.date < today, trading_calendar.c.is_open.is_(True))
        .order_by(trading_calendar.c.date.desc())
        .limit(1)
    ).scalar_one_or_none()


def _default_trade_date(conn: Connection, bj: dt.datetime) -> dt.date | None:
    today = bj.date()
    cutoff = dt.datetime.combine(today, _FINAL_CUTOFF, bj.tzinfo)
    if _is_open(conn, today) and bj >= cutoff:
        return today
    return _previous_open(conn, today)


def _universe_size(conn: Connection, trade_date: dt.date) -> int:
    owners = list(
        conn.execute(select(users.c.id).where(users.c.status == "approved")).scalars().all()
    )
    codes: set[str] = set()
    for owner in owners:
        codes.update(daily_universe(conn, owner, trade_date))
    return len(codes)


def main(
    argv: list[str] | None = None,
    *,
    now: dt.datetime | None = None,
    redis_client: object | None = None,
    settings: Settings | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="daily-bars-backfill",
        description="Compute a multi-year daily-bar backfill window; dry-run by default.",
    )
    parser.add_argument("--years", type=int, required=True)
    parser.add_argument("--trade-date", dest="trade_date", default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="enqueue one daily_bars_fetch task; default is dry-run",
    )
    args = parser.parse_args(argv)
    if type(args.years) is not int or args.years <= 0:
        print("years must be a positive integer")
        return 1

    cfg = settings if settings is not None else Settings()
    stamp = now if now is not None else dt.datetime.now(dt.UTC)
    if stamp.tzinfo is None:
        print("now must be timezone-aware")
        return 1
    bj = stamp.astimezone(BEIJING)

    engine = jobs_mod._engine(cfg)
    with engine.connect() as conn:
        chosen: dt.date | None
        if args.trade_date:
            try:
                chosen = dt.date.fromisoformat(args.trade_date)
            except ValueError:
                print("refused: --trade-date must be a past open trading day")
                return 1
            # 契约 §8.3：显式今天而当前「早于」17:45 时拒绝；17:45:00 起放行。
            cutoff = dt.datetime.combine(bj.date(), _FINAL_CUTOFF, bj.tzinfo)
            if chosen > bj.date() or not _is_open(conn, chosen):
                print("refused: --trade-date must be a past open trading day")
                return 1
            if chosen == bj.date() and bj < cutoff:
                print("refused: explicit trade-date is today before 17:45 Beijing")
                return 1
        else:
            chosen = _default_trade_date(conn, bj)
            if chosen is None:
                print("calendar_not_covered")
                return 1
        day = chosen

        if args.apply and _is_open(conn, bj.date()):
            lock_start = dt.datetime.combine(bj.date(), _APPLY_LOCK_START, bj.tzinfo)
            lock_end = dt.datetime.combine(bj.date(), _APPLY_LOCK_END, bj.tzinfo)
            if lock_start <= bj < lock_end:
                print("refused: open-day 17:00-17:45 Beijing lock window")
                return 1

        window = backfill_window_days(conn, day, args.years)
        if window is None:
            print("calendar_not_covered")
            return 1
        count = _universe_size(conn, day)

    rows = count * window
    statements = math.ceil(rows / UPSERT_BATCH_ROWS) if rows else 0
    # 一次 history 调用若能覆盖整个窗口，调用数等于标的数（k 未实测，不编造分段）。
    calls = count
    print(f"trade_date={day.isoformat()}")
    print(f"window_trading_days={window}")
    print(f"securities={count}")
    print(f"estimated_rows={rows}")
    print(f"estimated_statements={statements}")
    print(f"estimated_calls={calls}")
    if not args.apply:
        print("dry-run")
        return 0

    client = (
        jobs_mod._redis(cfg) if redis_client is None else cast(redis.Redis, redis_client)
    )
    try:
        jobs_mod._push(
            client,
            DAILY_BARS_FETCH,
            {
                "trade_date": day.isoformat(),
                "window_trading_days": window,
                "batch_kind": "backfill",
            },
        )
    finally:
        if redis_client is None:
            client.close()
    print("enqueued daily_bars_fetch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
