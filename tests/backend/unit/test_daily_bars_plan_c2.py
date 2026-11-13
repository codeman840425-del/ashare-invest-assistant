"""C2 planning: genuine calendar coverage, non-overlapping segments and owned readiness."""

from __future__ import annotations

import datetime as dt
import importlib
import importlib.util
import uuid
from collections.abc import Iterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from app.db.tables.market import daily_bars, trading_calendar
from psycopg import sql
from sqlalchemy import create_engine, delete, insert, text
from sqlalchemy.engine import make_url

DAY = dt.date(2026, 11, 12)
NOW = dt.datetime(2026, 11, 12, 9, 20, tzinfo=dt.UTC)
LID = uuid.UUID(int=202)
CODE = "999991.SH"


@pytest.fixture
def world(pg_url: str) -> Iterator[Any]:
    url = make_url(pg_url)
    assert url.host in {"localhost", "127.0.0.1", "::1", "postgres"}
    name = "c2_plan_" + uuid.uuid4().hex
    admin = psycopg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False),
        autocommit=True,
    )
    engine = None
    try:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        engine = create_engine(url.set(drivername="postgresql+psycopg", database=name))
        yield SimpleNamespace(engine=engine)
    finally:
        if engine is not None:
            engine.dispose()
        assert name.startswith("c2_plan_") and len(name) == 40
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name))
        )
        assert (
            admin.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (name,)
            ).fetchone()
            is None
        )
        admin.close()


def implementation() -> Any:
    name = "app.ingest.daily_bars_plan"
    assert importlib.util.find_spec(name), "C2 window/readiness planner missing"
    return importlib.import_module(name)


def seed_calendar(conn: Any) -> list[dt.date]:
    start = DAY - dt.timedelta(days=6)
    days = [start + dt.timedelta(days=i) for i in range(7)]
    conn.execute(text("CREATE SCHEMA market"))
    trading_calendar.create(conn)
    daily_bars.create(conn)
    conn.execute(
        insert(trading_calendar),
        [{"date": day, "is_open": day.weekday() < 5} for day in days],
    )
    return [day for day in days if day.weekday() < 5]


def test_history_segments_cover_each_open_day_once_without_overlap() -> None:
    module = implementation()
    days = tuple(DAY - dt.timedelta(days=n) for n in (6, 3, 2, 1, 0))
    chunks = module.segments(days, 2)
    assert chunks == ((days[0], days[1]), (days[2], days[3]), (days[4], days[4]))
    covered = [day for start, end in chunks for day in days if start <= day <= end]
    assert covered == list(days) and len(set(covered)) == len(days)


def test_history_size_unverified_is_rejected_but_single_day_needs_no_guess() -> None:
    module = implementation()
    assert module.segments((DAY,), None) == ((DAY, DAY),)
    with pytest.raises(module.DailyBarsPlanError, match="history_page_size_unverified"):
        module.segments((DAY - dt.timedelta(days=1), DAY), None)


@pytest.mark.parametrize("size", [0, -1, True])
def test_history_invalid_page_size_is_rejected(size: Any) -> None:
    module = implementation()
    with pytest.raises(ValueError):
        module.segments((DAY,), size)


def test_window_uses_actual_open_days_and_refuses_missing_calendar(world: Any) -> None:
    module = implementation()
    with world.engine.begin() as conn:
        open_days = seed_calendar(conn)
        assert module.window_days(conn, DAY, 5) == tuple(open_days)
        assert module.window_days(conn, DAY, None) == (DAY,)
        with pytest.raises(module.DailyBarsPlanError, match="calendar_not_covered"):
            module.window_days(conn, DAY, 6)
        conn.execute(
            delete(trading_calendar).where(
                trading_calendar.c.date == DAY - dt.timedelta(days=4)
            )
        )
        with pytest.raises(module.DailyBarsPlanError, match="calendar_not_covered"):
            module.window_days(conn, DAY, 5)


@pytest.mark.parametrize(
    "source,lid,suspended,close,stamp,expected",
    [
        ("mairui", LID, False, Decimal(10), NOW, True),
        ("mairui", LID, True, None, NOW, True),
        ("tdx_local", LID, False, Decimal(10), NOW, False),
        ("fake", LID, False, Decimal(10), NOW, False),
        (None, LID, False, Decimal(10), NOW, False),
        ("mairui", uuid.UUID(int=303), False, Decimal(10), NOW, False),
        ("mairui", LID, False, None, NOW, False),
        ("mairui", LID, False, Decimal(10), NOW - dt.timedelta(minutes=20), False),
        ("mairui", LID, False, Decimal(10), NOW + dt.timedelta(seconds=1), False),
    ],
)
def test_ready_only_complete_final_owned_mairui_rows(
    world: Any,
    source: str | None,
    lid: uuid.UUID,
    suspended: bool,
    close: Decimal | None,
    stamp: dt.datetime,
    expected: bool,
) -> None:
    module = implementation()
    with world.engine.begin() as conn:
        seed_calendar(conn)
        conn.execute(
            insert(daily_bars).values(
                code=CODE,
                trade_date=DAY,
                adj_type="none",
                source=source,
                source_licence_id=lid,
                fetched_at=stamp,
                is_suspended=suspended,
                open=None if suspended else Decimal(10),
                high=None if suspended else Decimal(11),
                low=None if suspended else Decimal(9),
                close=close,
                volume=None if suspended else Decimal(100),
                amount=None if suspended else Decimal(1000),
            )
        )
        assert module.ready_for_window(conn, CODE, LID, (DAY,), now=NOW) is expected


def test_backfill_readiness_requires_every_day_not_just_a_latest_bar(
    world: Any,
) -> None:
    module = implementation()
    with world.engine.begin() as conn:
        days = seed_calendar(conn)
        for day in days[1:]:
            conn.execute(
                insert(daily_bars).values(
                    code=CODE,
                    trade_date=day,
                    adj_type="none",
                    source="mairui",
                    source_licence_id=LID,
                    fetched_at=NOW,
                    is_suspended=True,
                )
            )
        assert module.ready_for_window(conn, CODE, LID, tuple(days), now=NOW) is False
        conn.execute(
            insert(daily_bars).values(
                code=CODE,
                trade_date=days[0],
                adj_type="none",
                source="mairui",
                source_licence_id=LID,
                fetched_at=NOW,
                is_suspended=True,
            )
        )
        assert module.ready_for_window(conn, CODE, LID, tuple(days), now=NOW) is True
