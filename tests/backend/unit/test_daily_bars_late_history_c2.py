"""Explicit source confirmations, durable per-code evidence and conservative readiness."""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import replace

import pytest
from app.db.tables.daily_bars import outbox
from app.db.tables.market import daily_bars
from app.db.tables.realtime import pipeline_runs
from app.ingest import daily_bars as fetcher
from app.ingest.daily_bars_plan import ready_for_window
from app.marketdata import daily_bars as models
from sqlalchemy import delete, update
from tests.backend.unit.test_daily_bars_consumer_c2 import CODES, DAY, NOW, facts, implementation, queue, world  # noqa: F401
from tests.backend.unit.test_daily_bars_window_consumer_c2 import history  # noqa: F401


def confirmation(state, **changes):
    fields = {"code": CODES[0], "window": (state.days[0], state.days[-1]),
              "first": state.days[2], "no_earlier": True, **changes}
    return models.HistoryConfirmation(**fields)


@pytest.fixture
def late(history, monkeypatch):
    monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 3)
    monkeypatch.setattr(fetcher, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 3)
    original = history.transport
    history.confirmation = confirmation(history)
    history.first = history.days[2]

    def send(code, start, end):
        status, result = original(code, start, end)
        if code == CODES[0]:
            result = replace(result, bars=tuple(bar for bar in result.bars if bar.trade_date >= history.first))
            object.__setattr__(result, "history_confirmation", history.confirmation)
        return status, result

    history.transport = send
    return history


def tick(state):
    return implementation().tick(state.engine, transport=state.transport,
        grant_reader=lambda _: state.grant, clock=lambda: NOW, page_days=2,
        stop=state.root / "STOP", halt=state.root / "HALTED")


def ready(state, *, owner=None, licence=None, days=None):
    with state.engine.connect() as conn:
        return ready_for_window(conn, CODES[0], licence or state.grant.licence_id,
                                days or state.days, now=NOW, user_id=owner or state.grant.user_id)


def mutate_run(state, change):
    item, runs, _ = facts(state)
    stats = dict(runs[0].stats)
    evidence = dict(stats["history_evidence"])
    entry = dict(evidence[CODES[0]])
    change(entry)
    evidence[CODES[0]] = entry
    with state.engine.begin() as conn:
        conn.execute(update(pipeline_runs).where(pipeline_runs.c.id == runs[0].id)
                     .values(stats={**stats, "history_evidence": evidence}))


def test_late_code_in_partial_batch_is_progress_and_does_not_send_again(late):
    queue(late, window=5)
    assert tick(late) == 1
    items, runs, count = facts(late)
    assert len(items) == len(runs) == 2 and count == 3
    run = next(run for run in runs if run.id == items[0].pipeline_run_id)
    assert run.status == "partial" and run.stats["missing"] == 0
    assert "daily_bars_resume_stalled" not in run.stats["issues"]
    evidence = run.stats["history_evidence"][CODES[0]]
    assert evidence["status"] == "ok" and evidence["no_earlier"] is True
    assert evidence["window"] == [day.isoformat() for day in late.days]
    assert evidence["first"] == late.first.isoformat()
    assert evidence["user_id"] == str(late.grant.user_id)
    assert evidence["source_licence_id"] == str(late.grant.licence_id)
    assert ready(late) is True
    assert tick(late) == 1 and facts(late)[2] == 8
    assert [code for code, *_ in late.calls] == [CODES[0]] * 3 + [CODES[1]] * 3
    assert tick(late) == 0


def test_late_confirmation_can_finish_whole_run_ok(late, monkeypatch):
    monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 6)
    queue(late, window=5)
    assert tick(late) == 1
    items, runs, count = facts(late)
    assert len(items) == len(runs) == 1 and count == 8
    assert runs[0].status == "ok" and runs[0].stats["missing"] == 0
    assert ready(late) is True
    queue(late, seq=1, window=5)
    assert tick(late) == 1 and len(late.calls) == 6


@pytest.mark.parametrize("change", [
    {"no_earlier": False}, {"no_earlier": 1}, {"code": "999999.SH"},
    {"window": (DAY, DAY)}, {"window": None}, {"first": DAY + dt.timedelta(days=1)},
    {"first": "2026-11-10"}, {"first": NOW},
])
def test_invalid_or_nonexplicit_confirmation_never_relaxes_missing_rows(late, change):
    late.confirmation = confirmation(late, **change)
    queue(late, window=5)
    assert tick(late) == 1
    items, runs, count = facts(late)
    assert len(items) == len(runs) == 1 and count == 3
    assert not runs[0].stats.get("history_evidence")
    assert runs[0].stats["missing"] == 2 and "daily_bars_resume_stalled" in runs[0].stats["issues"]
    assert tick(late) == 0


def test_no_confirmation_does_not_infer_listing_from_earliest_row(late):
    late.confirmation = None
    queue(late, window=5)
    assert tick(late) == 1
    assert len(facts(late)[0]) == 1 and not facts(late)[1][0].stats.get("history_evidence")
    assert "daily_bars_resume_stalled" in facts(late)[1][0].stats["issues"]


@pytest.mark.parametrize("mode", ["failed_page", "missing_tail", "earlier_row", "conflicting", "empty"])
def test_only_complete_successful_code_plan_can_create_evidence(late, mode):
    original = late.transport

    def send(code, start, end):
        status, result = original(code, start, end)
        if mode == "failed_page" and end < late.first:
            return 503, result
        if mode == "missing_tail":
            result = replace(result, bars=tuple(bar for bar in result.bars if bar.trade_date != DAY))
        if mode == "empty":
            result = replace(result, bars=())
        if mode == "earlier_row":
            result = replace(result, history_confirmation=confirmation(late, first=late.days[3]))
        if mode == "conflicting" and end == DAY:
            result = replace(result, history_confirmation=confirmation(late, first=late.days[3]))
        return status, result

    late.transport = send
    queue(late, window=5)
    assert tick(late) == 1
    items, runs, _ = facts(late)
    assert len(items) == len(runs) == 1 and not runs[0].stats.get("history_evidence")
    assert "daily_bars_resume_stalled" in runs[0].stats["issues"]


@pytest.mark.parametrize("field,value", [
    ("status", "partial"), ("no_earlier", False), ("no_earlier", 1), ("code", "999999.SH"),
    ("user_id", str(uuid.UUID(int=9991))), ("source_licence_id", str(uuid.UUID(int=9992))),
    ("window", []), ("first", DAY.isoformat()), ("first", "invalid-date"),
])
def test_persisted_evidence_is_bound_and_revalidated(late, field, value):
    queue(late, window=5)
    assert tick(late) == 1 and ready(late)
    mutate_run(late, lambda entry: entry.update({field: value}))
    assert ready(late) is False


@pytest.mark.parametrize("target", ["other_owner", "other_licence", "other_window", "failed_run", "future_run", "unfinished_run", "halted_outbox", "wrong_kind"])
def test_other_or_unfinished_runs_never_supply_readiness(late, target):
    queue(late, window=5)
    assert tick(late) == 1
    item = facts(late)[0][0]
    with late.engine.begin() as conn:
        if target == "failed_run":
            conn.execute(update(pipeline_runs).where(pipeline_runs.c.id == item.pipeline_run_id).values(status="failed"))
        elif target == "future_run":
            conn.execute(update(pipeline_runs).where(pipeline_runs.c.id == item.pipeline_run_id).values(finished_at=NOW + dt.timedelta(seconds=1)))
        elif target == "unfinished_run":
            conn.execute(update(pipeline_runs).where(pipeline_runs.c.id == item.pipeline_run_id).values(finished_at=None))
        elif target == "halted_outbox":
            conn.execute(update(outbox).where(outbox.c.id == item.id).values(status="halted"))
        elif target == "wrong_kind":
            conn.execute(update(pipeline_runs).where(pipeline_runs.c.id == item.pipeline_run_id).values(step="other"))
    kwargs = {"owner": uuid.UUID(int=9991)} if target == "other_owner" else {}
    if target == "other_licence":
        kwargs = {"licence": uuid.UUID(int=9992)}
    if target == "other_window":
        kwargs = {"days": late.days[1:]}
    assert ready(late, **kwargs) is False


@pytest.mark.parametrize("change", ["tdx", "future", "incomplete", "missing_tail", "earliest_changed"])
def test_confirmation_never_replaces_actual_final_owned_tail_rows(late, change):
    queue(late, window=5)
    assert tick(late) == 1 and ready(late)
    with late.engine.begin() as conn:
        where = daily_bars.c.code == CODES[0]
        if change == "tdx":
            conn.execute(update(daily_bars).where(where).values(source="tdx_local"))
        elif change == "future":
            conn.execute(update(daily_bars).where(where).values(fetched_at=NOW + dt.timedelta(seconds=1)))
        elif change == "incomplete":
            conn.execute(update(daily_bars).where(where).values(close=None))
        elif change == "missing_tail":
            conn.execute(delete(daily_bars).where(where, daily_bars.c.trade_date == DAY))
        else:
            conn.execute(delete(daily_bars).where(where, daily_bars.c.trade_date == late.first))
    assert ready(late) is False


@pytest.mark.parametrize("signal", ["STOP", "HALTED", 103, 429])
def test_halted_partial_code_has_no_durable_evidence(late, signal):
    original = late.transport

    def send(*args):
        status, result = original(*args)
        if len(late.calls) == 2:
            if isinstance(signal, str):
                (late.root / signal).touch()
            else:
                return signal, result
        return status, result

    late.transport = send
    queue(late, window=5)
    assert tick(late) == 1
    items, runs, count = facts(late)
    assert count == 0 and items[0].status == "halted" and not runs[0].stats.get("history_evidence")
    assert tick(late) == 0


def test_evidence_and_bars_rollback_together_on_terminal_update_failure(late, monkeypatch):
    from sqlalchemy import event
    queue(late, window=5)
    once = []
    def fail(conn, cursor, statement, parameters, context, many):
        if "UPDATE app.daily_bars_outbox" in statement and "finished_at" in statement and not once:
            once.append(1)
            raise RuntimeError("synthetic terminal failure")
    event.listen(late.engine, "before_cursor_execute", fail)
    try:
        assert tick(late) == 1
    finally:
        event.remove(late.engine, "before_cursor_execute", fail)
    items, runs, count = facts(late)
    assert items[0].status == "failed" and count == 0
    assert not runs[0].stats.get("history_evidence") and ready(late) is False


@pytest.mark.parametrize("change", [{"no_earlier": False}, {"code": "999999.SH"}, {"first": "invalid"}])
def test_one_invalid_explicit_confirmation_invalidates_other_pages(late, change):
    original = late.transport
    def send(code, start, end):
        status, result = original(code, start, end)
        if end == DAY:
            result = replace(result, history_confirmation=confirmation(late, **change))
        return status, result
    late.transport = send
    queue(late, window=5)
    assert tick(late) == 1
    assert not facts(late)[1][0].stats.get("history_evidence") and len(facts(late)[0]) == 1


@pytest.mark.parametrize("kind", ["revoked", "hold"])
def test_replacement_evidence_requires_current_available_licence(late, kind):
    from app.db.tables.licences import user_data_licence_holds as holds
    from sqlalchemy import insert, text
    queue(late, window=5)
    assert tick(late) == 1 and ready(late)
    with late.engine.begin() as conn:
        if kind == "revoked":
            conn.execute(text("UPDATE app.user_data_licence_status SET status='revoked'"))
        else:
            conn.execute(insert(holds).values(user_id=late.grant.user_id, paused_at=NOW))
    assert ready(late) is False


@pytest.mark.parametrize("kind", ["envelope", "entry", "top_owner", "top_window", "first_type"])
def test_malformed_persisted_evidence_is_ignored(late, kind):
    queue(late, window=5)
    assert tick(late) == 1
    item, runs, _ = facts(late)
    stats = dict(runs[0].stats)
    if kind == "envelope":
        stats["history_evidence"] = []
    elif kind == "entry":
        stats["history_evidence"] = {CODES[0]: "invalid"}
    elif kind == "top_owner":
        stats["user_id"] = str(uuid.UUID(int=9999))
    elif kind == "top_window":
        stats["window_trading_days"] = 4
    else:
        stats["history_evidence"][CODES[0]]["first"] = 1
    with late.engine.begin() as conn:
        conn.execute(update(pipeline_runs).where(pipeline_runs.c.id == item[0].pipeline_run_id).values(stats=stats))
    assert ready(late) is False


def test_suspended_tail_counts_as_complete_with_explicit_source_confirmation(late):
    original = late.transport
    def send(*args):
        status, result = original(*args)
        return status, replace(result, bars=tuple(replace(bar, is_suspended=True,
            open=None, high=None, low=None, close=None, volume=None, amount=None) for bar in result.bars))
    late.transport = send
    queue(late, window=5)
    assert tick(late) == 1 and ready(late) is True
    assert len(facts(late)[0]) == 2
    assert tick(late) == 1 and len(late.calls) == 6 and facts(late)[2] == 8


@pytest.mark.parametrize("mode", ["incomplete", "nonfinal"])
def test_incomplete_or_nonfinal_payload_cannot_record_per_code_ok_evidence(late, mode):
    if mode == "incomplete":
        original = late.transport
        def send(*args):
            status, result = original(*args)
            return status, replace(result, bars=tuple(replace(bar, close=None) for bar in result.bars))
        late.transport = send
    stamp = NOW if mode == "incomplete" else NOW - dt.timedelta(hours=1, minutes=1)
    late.grant = replace(late.grant, start=NOW - dt.timedelta(hours=2))
    bid = queue(late, window=5)
    assert implementation().process(late.engine, bid, transport=late.transport,
        grant_reader=lambda _: late.grant, clock=lambda: stamp, page_days=2,
        stop=late.root / "STOP", halt=late.root / "HALTED") == "done"
    assert not facts(late)[1][0].stats.get("history_evidence")
