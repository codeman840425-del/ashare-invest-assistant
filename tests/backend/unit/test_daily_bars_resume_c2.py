"""C2 durable continuation: synthetic PG and injected transport, no live services."""
from __future__ import annotations

import datetime as dt
from dataclasses import replace

import pytest
from app.db.tables.daily_bars import outbox
from app.ingest import daily_bars as fetcher
from sqlalchemy import select
from tests.backend.unit.test_daily_bars_consumer_c2 import DAY, NOW, facts, implementation, process, queue, world  # noqa: F401
from tests.backend.unit.test_daily_bars_window_consumer_c2 import history  # noqa: F401

CODES = [f"99999{i}.SH" for i in range(5)]


@pytest.fixture
def batch(world, monkeypatch):
    monkeypatch.setattr(fetcher, "daily_universe", lambda *_: CODES)
    monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 3)
    monkeypatch.setattr(fetcher, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 3)
    return world


def tick(batch, *, clock=lambda: NOW, page_days=None):
    return implementation().tick(
        batch.engine, transport=batch.transport, grant_reader=lambda _: batch.grant,
        clock=clock, stop=batch.root / "STOP", halt=batch.root / "HALTED", page_days=page_days,
    )


def runs_by_id(batch):
    items, runs, count = facts(batch)
    return items, {run.id: run for run in runs}, count


@pytest.mark.parametrize("kind", ["daily", "backfill"])
def test_batch_cap_defers_rest_and_continues(batch, kind):
    queue(batch, kind=kind)
    assert tick(batch) == 1
    items, runs, count = runs_by_id(batch)
    assert len(items) == len(runs) == 2 and count == 3
    assert [item.batch_seq for item in items] == [0, 1]
    assert [item.status for item in items] == ["done", "pending"]
    assert all(item.batch_kind == kind and item.trade_date == DAY for item in items)
    assert runs[items[0].pipeline_run_id].status == "partial"
    assert runs[items[0].pipeline_run_id].stats["issues"].count("daily_bars_quota_deferred") == 2
    assert items[1].attempted_at is None
    assert tick(batch) == 1 and batch.calls == CODES
    assert tick(batch) == 0
    items, runs, count = runs_by_id(batch)
    assert len(items) == len(runs) == 2 and count == 5
    assert runs[items[1].pipeline_run_id].status == "ok"
    assert all(item.status == "done" for item in items)
    assert process(batch, items[0].id) == "noop" and batch.calls == CODES


def test_resume_stalled_no_infinite_loop(batch):
    batch.transport = lambda code, *_: (batch.calls.append(code) or 200, None)
    queue(batch)
    assert tick(batch) == 1
    items, runs, count = facts(batch)
    assert len(items) == len(runs) == 1 and count == 0
    assert "daily_bars_resume_stalled" in runs[0].stats["issues"]
    assert runs[0].stats["missing"] == 3
    assert tick(batch) == 0 and len(batch.calls) == 3


def test_partial_progress_can_continue_until_later_batch_stalls(batch):
    original = batch.transport

    def send(code, start, end):
        if code == CODES[0]:
            return original(code, start, end)
        batch.calls.append(code)
        return 200, None

    batch.transport = send
    queue(batch)
    assert tick(batch) == 1 and tick(batch) == 1
    items, runs, count = runs_by_id(batch)
    assert len(items) == len(runs) == 2 and count == 1
    assert "daily_bars_resume_stalled" in runs[items[1].pipeline_run_id].stats["issues"]
    assert batch.calls == CODES[:3] + CODES[1:4]
    assert tick(batch) == 0


@pytest.mark.parametrize("signal", ["STOP", "HALTED", 103, 429])
def test_halt_never_creates_continuation(batch, signal):
    original = batch.transport

    def send(code, start, end):
        if len(batch.calls) == 1:
            if isinstance(signal, str):
                (batch.root / signal).touch()
            else:
                batch.calls.append(code)
                return signal, None
        return original(code, start, end)

    batch.transport = send
    queue(batch)
    assert tick(batch) == 1
    items, runs, count = facts(batch)
    assert len(items) == len(runs) == 1 and items[0].status == "halted" and count == 0
    assert tick(batch) == 0 and len(batch.calls) == 2


class Crash(BaseException):
    pass


def crash_after_commit(batch, monkeypatch):
    module = implementation()
    original = getattr(module, "_resume", None)
    assert original is not None, "durable quota continuation missing"

    def crash(*args, **kwargs):
        with batch.engine.connect() as conn:
            pending = conn.execute(select(outbox.c.id).where(outbox.c.error_code == "daily_bars_resume_pending")).first()
        if pending:
            raise Crash()
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "_resume", crash)
    queue(batch)
    with pytest.raises(Crash):
        tick(batch)
    monkeypatch.setattr(module, "_resume", original)
    return module


def test_committed_progress_recovers_after_tick_crash_without_replaying(batch, monkeypatch):
    crash_after_commit(batch, monkeypatch)
    items, runs, count = facts(batch)
    assert count == 3 and len(items) == len(runs) == 1
    assert items[0].status == "done" and items[0].error_code == "daily_bars_resume_pending"
    assert tick(batch) == 1 and batch.calls == CODES
    assert tick(batch) == 0 and facts(batch)[2] == 5


def test_resume_rechecks_stop_and_persists_halt_before_queue(batch, monkeypatch):
    crash_after_commit(batch, monkeypatch)
    (batch.root / "STOP").touch()
    assert tick(batch) == 0
    items, runs, count = facts(batch)
    assert len(items) == len(runs) == 1 and count == 3
    assert items[0].status == "halted"
    (batch.root / "STOP").unlink()
    assert tick(batch) == 0 and batch.calls == CODES[:3]


def test_resume_rechecks_exact_receipt_and_owner_before_queue(batch, monkeypatch):
    crash_after_commit(batch, monkeypatch)
    batch.grant = replace(batch.grant, digest="changed-synthetic-receipt")
    assert tick(batch) == 0
    items, runs, count = facts(batch)
    assert len(items) == len(runs) == 1 and count == 3
    assert "data_licence_unavailable" in runs[0].stats["issues"]
    assert tick(batch) == 0 and batch.calls == CODES[:3]


def test_resume_budget_unset_preserves_pending_without_reading_grant(batch, monkeypatch):
    crash_after_commit(batch, monkeypatch)
    monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 0)
    monkeypatch.setattr(fetcher, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 0)
    batch.grant = None
    assert tick(batch) == 0
    assert facts(batch)[0][0].error_code == "daily_bars_resume_pending"
    assert batch.calls == CODES[:3]


def test_next_batch_creation_failure_is_retryable_without_replaying_completed_io(batch, monkeypatch):
    module = crash_after_commit(batch, monkeypatch)
    from app.marketdata import daily_bars_outbox
    original = daily_bars_outbox.enqueue

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic enqueue failure")

    monkeypatch.setattr(daily_bars_outbox, "enqueue", fail)
    with pytest.raises(RuntimeError):
        tick(batch)
    assert facts(batch)[0][0].error_code == "daily_bars_resume_pending"
    monkeypatch.setattr(daily_bars_outbox, "enqueue", original)
    assert tick(batch) == 1 and batch.calls == CODES
    assert module is implementation()


def test_continuation_deduplicates_existing_next_sequence(batch):
    queue(batch)
    queue(batch, seq=1)
    assert tick(batch) == 1
    assert len(facts(batch)[0]) == len(facts(batch)[1]) == 2
    assert tick(batch) == 1 and batch.calls == CODES
    assert tick(batch) == 0


def test_cross_day_pending_continuation_expires_without_io(batch, monkeypatch):
    crash_after_commit(batch, monkeypatch)
    assert tick(batch, clock=lambda: NOW + dt.timedelta(days=1)) == 0
    items, runs, count = facts(batch)
    assert len(items) == len(runs) == 1 and count == 3
    assert "daily_bars_batch_expired" in runs[0].stats["issues"]
    assert batch.calls == CODES[:3]


def test_history_whole_code_budget_continues_without_repeating_ready_pages(history, monkeypatch):
    monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 5)
    queue(history, window=5)
    assert tick(history, page_days=2) == 1
    items, runs, count = facts(history)
    assert len(items) == len(runs) == 2 and count == 5
    assert items[1].window_trading_days == 5 and items[1].batch_kind == "daily"
    assert tick(history, page_days=2) == 1
    assert len(history.calls) == 6 and facts(history)[2] == 10
    assert tick(history, page_days=2) == 0


def test_history_partial_rows_are_not_progress_even_when_inserted(history, monkeypatch):
    from app.marketdata.daily_bars import DailyBarsResult
    monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 5)
    original = history.transport

    def send(*args):
        status, result = original(*args)
        return status, DailyBarsResult(bars=result.bars[:1])

    history.transport = send
    queue(history, window=5)
    assert tick(history, page_days=2) == 1
    items, runs, count = facts(history)
    assert len(items) == len(runs) == 1 and count == 3
    assert "daily_bars_resume_stalled" in runs[0].stats["issues"]
    assert tick(history, page_days=2) == 0


def test_budget_smaller_than_one_code_stalls_without_transport(history, monkeypatch):
    monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 2)
    queue(history, window=5)
    assert tick(history, page_days=2) == 1
    items, runs, count = facts(history)
    assert len(items) == len(runs) == 1 and count == 0 and history.calls == []
    assert "daily_bars_resume_stalled" in runs[0].stats["issues"]
    assert tick(history, page_days=2) == 0


def test_continuation_has_no_fixed_batch_count_ceiling(batch, monkeypatch):
    monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 1)
    queue(batch)
    assert [tick(batch) for _ in CODES] == [1] * len(CODES)
    items, runs, count = facts(batch)
    assert len(items) == len(runs) == count == len(CODES)
    assert [item.batch_seq for item in items] == list(range(len(CODES)))
    assert batch.calls == CODES and tick(batch) == 0


def test_resume_io_busy_keeps_pending_intent_and_committed_bars(batch, monkeypatch):
    module = crash_after_commit(batch, monkeypatch)
    original = module._resume

    def busy(*args, **kwargs):
        raise PermissionError("synthetic gate IO denial")

    monkeypatch.setattr(module, "_resume", busy)
    assert tick(batch) == 0
    assert facts(batch)[0][0].error_code == "daily_bars_resume_pending"
    assert batch.calls == CODES[:3]
    monkeypatch.setattr(module, "_resume", original)
    assert tick(batch) == 1 and batch.calls == CODES


def test_resume_halt_fsync_failure_has_durable_db_backstop(batch, monkeypatch):
    crash_after_commit(batch, monkeypatch)
    monkeypatch.setattr(fetcher, "persist_halt", lambda *_: False)
    (batch.root / "STOP").touch()
    assert tick(batch) == 0
    item = facts(batch)[0][0]
    assert item.status == "halted" and item.error_code == "daily_bars_halt_persist_failed"
    (batch.root / "STOP").unlink()
    assert tick(batch) == 0 and batch.calls == CODES[:3]


def test_already_queued_continuation_expires_next_day_before_sending(batch):
    queue(batch)
    assert tick(batch) == 1 and len(facts(batch)[0]) == 2
    assert tick(batch, clock=lambda: NOW + dt.timedelta(days=1)) == 1
    items, runs, count = runs_by_id(batch)
    assert count == 3 and batch.calls == CODES[:3]
    assert items[1].status == "failed" and items[1].attempted_at is None
    assert runs[items[1].pipeline_run_id].error == "daily_bars_batch_expired"


def test_stop_created_during_resume_receipt_read_prevents_queue(batch, monkeypatch):
    module = crash_after_commit(batch, monkeypatch)

    def read(_):
        (batch.root / "STOP").touch()
        return batch.grant

    assert module.tick(batch.engine, transport=batch.transport, grant_reader=read,
                       clock=lambda: NOW, stop=batch.root / "STOP", halt=batch.root / "HALTED") == 0
    assert len(facts(batch)[0]) == 1 and facts(batch)[0][0].status == "halted"
    assert batch.calls == CODES[:3]


def test_resume_lock_busy_keeps_marker_without_queue_or_send(batch, monkeypatch):
    from app.ingest.egress import single_egress
    crash_after_commit(batch, monkeypatch)
    with single_egress(batch.engine) as lease:
        assert lease is not None
        assert tick(batch) == 0
    assert facts(batch)[0][0].error_code == "daily_bars_resume_pending"
    assert batch.calls == CODES[:3]
    assert tick(batch) == 1 and batch.calls == CODES


def test_resume_gate_lstat_denial_is_busy_and_keeps_marker(batch, monkeypatch):
    from pathlib import Path
    crash_after_commit(batch, monkeypatch)
    original = Path.lstat
    with monkeypatch.context() as patch:
        def denied(path, *args, **kwargs):
            if path == batch.root / "STOP":
                raise PermissionError("synthetic gate unreadable")
            return original(path, *args, **kwargs)
        patch.setattr(Path, "lstat", denied)
        assert tick(batch) == 0
    assert facts(batch)[0][0].error_code == "daily_bars_resume_pending"
    assert tick(batch) == 1 and batch.calls == CODES


def test_expiry_never_bypasses_original_run_owner_identity_guard(batch):
    from app.db.tables.realtime import pipeline_runs
    from sqlalchemy import update
    queue(batch)
    item, runs, _ = facts(batch)
    with batch.engine.begin() as conn:
        conn.execute(update(pipeline_runs).where(pipeline_runs.c.id == item[0].pipeline_run_id)
                     .values(stats={**runs[0].stats, "user_id": "synthetic-wrong-owner"}))
    with pytest.raises(RuntimeError, match="daily_bars_run_identity_changed"):
        tick(batch, clock=lambda: NOW + dt.timedelta(days=1))
    items, runs, count = facts(batch)
    assert items[0].status == "pending" and items[0].attempted_at is None
    assert runs[0].status == "running" and count == 0 and batch.calls == []


def test_do_nothing_on_future_rows_is_not_new_readiness_progress(batch):
    from app.db.tables.market import daily_bars
    from sqlalchemy import update
    first = queue(batch)
    assert process(batch, first) == "done" and facts(batch)[2] == 3
    with batch.engine.begin() as conn:
        conn.execute(update(daily_bars).values(fetched_at=NOW + dt.timedelta(days=1)))
    queue(batch, seq=1)
    assert tick(batch) == 1
    items, runs, count = runs_by_id(batch)
    assert len(items) == len(runs) == 2 and count == 3
    assert "daily_bars_resume_stalled" in runs[items[1].pipeline_run_id].stats["issues"]
    assert batch.calls == CODES[:3] * 2 and tick(batch) == 0
