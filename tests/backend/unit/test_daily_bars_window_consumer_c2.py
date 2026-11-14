"""C2 windows through the real DB consumer with synthetic bars and fake transport."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from app.db.tables.market import daily_bars, trading_calendar
from app.ingest import daily_bars as fetcher
from app.marketdata.daily_bars import DailyBar, DailyBarsResult
from sqlalchemy import delete, event, insert
from tests.backend.unit.test_daily_bars_consumer_c2 import CODES, DAY, GRANT, NOW, facts, implementation, queue, world  # noqa: F401


@pytest.fixture
def history(world, monkeypatch):
    monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 7)
    monkeypatch.setattr(fetcher, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 7)
    start = DAY - dt.timedelta(days=6)
    calendar = [(start + dt.timedelta(days=n)) for n in range(7)]
    with world.engine.begin() as conn:
        conn.execute(delete(trading_calendar))
        conn.execute(
            insert(trading_calendar),
            [{"date": day, "is_open": day.weekday() < 5} for day in calendar],
        )
    world.days = tuple(day for day in calendar if day.weekday() < 5)
    world.calls = []

    def send(code, start, end):
        world.calls.append((code, start, end))
        value = Decimal("1")
        return 200, DailyBarsResult(
            bars=tuple(
                DailyBar(code, day, "none", value, value, value, value, value, value, value, False)
                for day in world.days
                if start <= day <= end
            )
        )

    world.transport = send
    return world


def consume(history, bid, *, k=2, transport=None):
    return implementation().process(
        history.engine,
        bid,
        page_days=k,
        transport=transport or history.transport,
        grant_reader=lambda _: history.grant,
        clock=lambda: NOW,
        stop=history.root / "STOP",
        halt=history.root / "HALTED",
    )


def test_history_real_calendar_pages_original_run_and_idempotent(history):
    bid = queue(history, window=5)
    assert consume(history, bid) == "done"
    expected = [(history.days[0], history.days[1]), (history.days[2], history.days[3]), (DAY, DAY)]
    assert history.calls == [(code, first, last) for code in CODES for first, last in expected]
    items, runs, bars = facts(history)
    assert bars == 10 and len(runs) == 1
    assert items[0].pipeline_run_id == runs[0].id and runs[0].status == "ok"
    assert consume(history, bid) == "noop"
    second = queue(history, seq=1, window=5)
    assert consume(history, second) == "done"
    assert len(history.calls) == 6
    assert facts(history)[2] == 10


def test_history_quota_does_not_start_partial_next_code(history, monkeypatch):
    monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 5)
    assert consume(history, queue(history, window=5)) == "done"
    assert [call[0] for call in history.calls] == [CODES[0]] * 3
    items, runs, bars = facts(history)
    assert bars == 5 and runs[0].status == "partial"
    assert runs[0].stats["issues"].count("daily_bars_quota_deferred") == 1
    assert items[0].status == "done"


@pytest.mark.parametrize("missing", ["left", "middle"])
def test_calendar_hole_never_reserves_or_sends(history, missing):
    with history.engine.begin() as conn:
        day = history.days[0] if missing == "left" else DAY - dt.timedelta(days=4)
        conn.execute(delete(trading_calendar).where(trading_calendar.c.date == day))
    assert consume(history, queue(history, window=5)) == "failed"
    items, runs, bars = facts(history)
    assert history.calls == [] and bars == 0
    assert items[0].attempted_at is None
    assert runs[0].error == "calendar_not_covered"


@pytest.mark.parametrize("signal", ["STOP", "HALTED", 103, 429])
def test_stop_on_second_history_page_rolls_back_and_blocks_next_tick(history, monkeypatch, signal):
    original = history.transport

    def send(code, start, end):
        result = original(code, start, end)
        if len(history.calls) == 2:
            if isinstance(signal, str):
                (history.root / signal).touch()
            else:
                return signal, None
        return result

    monkeypatch.setattr(fetcher, "persist_halt", lambda *args: False)
    assert consume(history, queue(history, window=5), transport=send) == "halted"
    assert len(history.calls) == 2
    assert facts(history)[2] == 0
    assert facts(history)[0][0].error_code == "daily_bars_halt_persist_failed"
    if isinstance(signal, str):
        (history.root / signal).unlink()
    assert consume(history, queue(history, seq=1, window=5)) == "halted"
    assert len(history.calls) == 2


def test_second_page_exception_keeps_original_failed_run_and_no_bars(history):
    original = history.transport

    def send(code, start, end):
        result = original(code, start, end)
        if len(history.calls) == 2:
            raise RuntimeError("synthetic second page failure")
        return result

    assert consume(history, queue(history, window=5), transport=send) == "failed"
    items, runs, bars = facts(history)
    assert bars == 0 and len(runs) == 1 and runs[0].status == "failed"
    assert items[0].attempted_at is not None
    assert len(history.calls) == 2


def test_partial_historical_rows_do_not_count_as_ready(history):
    assert consume(history, queue(history, window=5)) == "done"
    with history.engine.begin() as conn:
        conn.execute(
            delete(daily_bars).where(
                daily_bars.c.code == CODES[0], daily_bars.c.trade_date == history.days[0]
            )
        )
    history.calls.clear()
    assert consume(history, queue(history, seq=1, window=5)) == "done"
    assert [call[0] for call in history.calls] == [CODES[0]] * 3
    assert facts(history)[2] == 10


def test_window_tick_forwards_verified_page_size_without_redis(history):
    queue(history, window=5)
    assert (
        implementation().tick(
            history.engine,
            page_days=2,
            transport=history.transport,
            grant_reader=lambda _: GRANT,
            clock=lambda: NOW,
            stop=history.root / "STOP",
            halt=history.root / "HALTED",
        )
        == 1
    )
    assert facts(history)[2] == 10


def test_history_halted_payload_blocks_even_with_status_200(history):
    def send(*args):
        history.calls.append(args)
        return 200, DailyBarsResult(halted="synthetic")

    assert consume(history, queue(history, window=5), transport=send) == "halted"
    assert len(history.calls) == 1 and facts(history)[2] == 0


@pytest.mark.parametrize("fail_second_chunk", [False, True])
def test_existing_1000_row_chunks_stay_in_original_run_transaction(
    history, monkeypatch, fail_second_chunk
):
    history.days = tuple(DAY - dt.timedelta(days=n) for n in reversed(range(1201)))
    monkeypatch.setattr(fetcher, "daily_universe", lambda *args: [CODES[0]])
    with history.engine.begin() as conn:
        conn.execute(delete(trading_calendar))
        conn.execute(
            insert(trading_calendar), [{"date": day, "is_open": True} for day in history.days]
        )
    statements = []

    def before_cursor(conn, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO market.daily_bars "):
            statements.append(statement)
            if fail_second_chunk and len(statements) == 2:
                raise RuntimeError("synthetic chunk rollback")

    event.listen(history.engine, "before_cursor_execute", before_cursor)
    try:
        result = consume(history, queue(history, window=1201), k=700)
    finally:
        event.remove(history.engine, "before_cursor_execute", before_cursor)
    assert len(statements) == 2
    items, runs, bars = facts(history)
    assert len(runs) == 1
    assert bars == (0 if fail_second_chunk else 1201)
    assert result == ("failed" if fail_second_chunk else "done")
    assert runs[0].status == ("failed" if fail_second_chunk else "ok")


def test_grant_revoked_between_pages_never_sends_next_page(history):
    from dataclasses import replace

    original = history.transport

    def send(code, start, end):
        result = original(code, start, end)
        history.grant = replace(GRANT, end=NOW)
        return result

    assert consume(history, queue(history, window=5), transport=send) == "failed"
    assert len(history.calls) == 1 and facts(history)[2] == 0


def test_foreign_history_bar_fails_original_run_and_rolls_back(history):
    from dataclasses import replace

    original = history.transport

    def send(code, start, end):
        status, result = original(code, start, end)
        return status, DailyBarsResult(bars=(replace(result.bars[0], code="999999.SH"),))

    assert consume(history, queue(history, window=5), transport=send) == "failed"
    items, runs, bars = facts(history)
    assert bars == 0 and len(runs) == 1 and runs[0].status == "failed"
    assert items[0].attempted_at is not None and len(history.calls) == 1
