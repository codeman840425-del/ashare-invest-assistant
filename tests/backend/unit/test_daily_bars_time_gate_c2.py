"""Protected history window through DB intents and synthetic Redis/transport only."""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from app.db.tables.daily_bars import outbox
from app.db.tables.market import trading_calendar
from app.ingest import daily_bars as fetcher
from app.ingest.daily_bars_plan import BEIJING
from sqlalchemy import delete, select, update
from tests.backend.unit.test_daily_bars_consumer_c2 import DAY, NOW, facts, implementation, queue, world  # noqa: F401
from tests.backend.unit.test_daily_bars_window_consumer_c2 import history  # noqa: F401


def at(hour, minute=0, second=0):
    return dt.datetime.combine(DAY, dt.time(hour, minute, second), BEIJING)


class Redis:
    def __init__(self):
        self.delayed = {}
        self.queued = []

    def zadd(self, key, mapping):
        assert key == "jobs:delayed"
        self.delayed.update(mapping)

    def zrangebyscore(self, key, lower, upper):
        return [key for key, score in self.delayed.items() if lower <= score <= upper]

    def zrem(self, key, raw):
        return int(self.delayed.pop(raw, None) is not None)

    def lpush(self, key, raw):
        self.queued.insert(0, raw)


@pytest.fixture
def gated(history):
    history.grant = replace(history.grant, start=at(16), end=at(20))
    history.redis = Redis()
    history.stamp = at(17)
    return history


def tick(state, *, k=2):
    return implementation().tick(
        state.engine, redis_client=state.redis, transport=state.transport,
        grant_reader=lambda _: state.grant, clock=lambda: state.stamp,
        stop=state.root / "STOP", halt=state.root / "HALTED", page_days=k,
    )


@pytest.mark.parametrize("kind,window", [("backfill", None), ("daily", 5), ("daily", 1)])
@pytest.mark.parametrize("stamp", [at(17), at(17, 15), at(17, 44, 59)])
def test_first_history_batch_is_delayed_with_no_attempt_or_receipt(gated, kind, window, stamp):
    bid = queue(gated, kind=kind, window=window)
    gated.stamp = stamp
    gated.grant = None
    assert tick(gated) == 0
    items, runs, count = facts(gated)
    assert items[0].id == bid and items[0].status == "pending"
    assert items[0].attempted_at is None and runs[0].status == "running"
    assert count == 0 and gated.calls == []
    assert list(gated.redis.delayed.values()) == [at(17, 45).timestamp()]
    assert tick(gated) == 0 and len(gated.redis.delayed) == 1


def test_exact_1745_releases_and_duplicate_wakeup_never_replays(gated, monkeypatch):
    from app.workers import jobs
    queue(gated, window=5)
    assert tick(gated) == 0
    monkeypatch.setattr(jobs, "slot_jobs", lambda *_: [])
    assert jobs.beat_slots(SimpleNamespace(), client=gated.redis, now=at(17, 44, 59)) == []
    assert len(gated.redis.delayed) == 1 and gated.redis.queued == []
    assert jobs.beat_slots(SimpleNamespace(), client=gated.redis, now=at(17, 45)) == ["daily_bars_fetch"]
    assert len(gated.redis.queued) == 1 and gated.redis.delayed == {}
    wake = json.loads(gated.redis.queued[0])
    assert wake["args"]["trade_date"] == DAY.isoformat() and wake["args"]["batch_seq"] == 0
    gated.stamp = at(17, 45)
    assert tick(gated) == 1 and len(gated.calls) == 6 and facts(gated)[2] == 10
    assert tick(gated) == 0 and len(gated.calls) == 6


def test_1715_daily_can_pass_history_at_front_of_db_queue(gated):
    queue(gated, window=5)
    queue(gated, seq=1)
    gated.stamp = at(17, 15)
    assert tick(gated) == 1
    items, runs, count = facts(gated)
    assert items[0].status == "pending" and items[1].status == "done"
    assert len(gated.calls) == count == 2 and len(gated.redis.delayed) == 1
    assert all(start == end == DAY for _, start, end in gated.calls)


@pytest.mark.parametrize("cutoff_page", [1, 3])
def test_running_batch_stops_at_1700_commits_completed_pages_and_delays_rest(gated, cutoff_page):
    queue(gated, window=5, kind="backfill")
    # History started before today's close must target the preceding open day.
    from app.db.tables.realtime import pipeline_runs
    from sqlalchemy import insert
    prior = DAY - dt.timedelta(days=1)
    first = DAY - dt.timedelta(days=7)
    gated.days = (first, *gated.days[:-1])
    with gated.engine.begin() as conn:
        conn.execute(insert(trading_calendar).values(date=first, is_open=True))
        conn.execute(update(outbox).values(trade_date=prior))
        conn.execute(update(pipeline_runs).values(run_date=prior))
    gated.stamp = at(16, 59, 58)
    original = gated.transport

    def send(*args):
        result = original(*args)
        if len(gated.calls) == cutoff_page:
            gated.stamp = at(17)
        return result

    gated.transport = send
    assert tick(gated) == 1
    items, runs, count = facts(gated)
    assert len(items) == len(runs) == 1 and items[0].status == "done"
    assert items[0].error_code == "daily_bars_resume_pending"
    assert runs[0].status == "partial" and "daily_bars_quota_deferred" in runs[0].stats["issues"]
    assert "daily_bars_resume_stalled" not in runs[0].stats["issues"]
    assert len(gated.calls) == cutoff_page and count == (2 if cutoff_page == 1 else 5)
    assert len(gated.redis.delayed) == 1 and tick(gated) == 0
    gated.stamp = at(17, 45)
    assert tick(gated) == 1 and facts(gated)[2] == 10
    assert tick(gated) == 0
    # A completed code is not resent; an incomplete code recomputes its full plan.
    assert len(gated.calls) == (7 if cutoff_page == 1 else 6)
    assert len(facts(gated)[0]) == 2


@pytest.mark.parametrize("signal", ["STOP", "HALTED", 103, 429])
def test_stop_halt_and_limit_take_precedence_over_time_continuation(gated, signal):
    queue(gated, window=5)
    gated.stamp = at(16, 59, 58)
    original = gated.transport

    def send(*args):
        result = original(*args)
        gated.stamp = at(17)
        if isinstance(signal, str):
            (gated.root / signal).touch()
            return result
        return signal, None

    gated.transport = send
    assert tick(gated) == 1
    items, runs, count = facts(gated)
    assert len(items) == 1 and items[0].status == "halted" and count == 0
    assert len(gated.calls) == 1 and gated.redis.delayed == {}
    gated.stamp = at(17, 45)
    assert tick(gated) == 0 and len(gated.calls) == 1


def test_redis_failure_after_zadd_keeps_database_intent_and_recovers(gated):
    import redis
    queue(gated, window=5)
    original = gated.redis.zadd

    def crash(*args):
        original(*args)
        raise redis.ConnectionError("synthetic lost acknowledgement")

    gated.redis.zadd = crash
    assert tick(gated) == 0 and tick(gated) == 0
    assert len(gated.redis.delayed) == 1 and facts(gated)[0][0].status == "pending"
    gated.redis.delayed.clear()  # Redis lost entirely; DB poll still releases at 17:45.
    gated.stamp = at(17, 45)
    assert tick(gated) == 1 and facts(gated)[2] == 10
    assert tick(gated) == 0


def test_closed_day_does_not_apply_open_day_window(gated):
    with gated.engine.begin() as conn:
        conn.execute(update(trading_calendar).where(trading_calendar.c.date == DAY).values(is_open=False))
    # Trade date remains the previous open day, not the closed wall-clock date.
    prior = DAY - dt.timedelta(days=1)
    queue(gated, window=1)
    with gated.engine.begin() as conn:
        conn.execute(update(outbox).values(trade_date=prior))
        from app.db.tables.realtime import pipeline_runs
        conn.execute(update(pipeline_runs).values(run_date=prior))
    assert tick(gated) == 1 and gated.redis.delayed == {}
    assert gated.calls and all(start == end == prior for _, start, end in gated.calls)


def test_missing_today_calendar_refuses_send_and_preserves_intent(gated):
    from app.common.errors import AppError
    queue(gated, window=5)
    with gated.engine.begin() as conn:
        conn.execute(delete(trading_calendar).where(trading_calendar.c.date == DAY))
    with pytest.raises(AppError):
        tick(gated)
    assert facts(gated)[0][0].status == "pending" and gated.calls == []


def test_both_budgets_unset_short_circuits_without_db_redis_or_grant(monkeypatch):
    monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 0)
    monkeypatch.setattr(fetcher, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 0)
    assert implementation().tick(object(), redis_client=object(), transport=lambda *_: pytest.fail("send"),
                                 grant_reader=lambda _: pytest.fail("receipt")) == 0


def test_worker_task_carries_explicit_batch_kind_and_sequence(world, monkeypatch):
    from app.marketdata.daily_bars import daily_bars_fetch_task
    from app.marketdata import daily_bars_outbox
    from app.workers import jobs
    monkeypatch.setattr(jobs, "_engine", lambda _: world.engine)
    monkeypatch.setattr(daily_bars_outbox, "utcnow", lambda: NOW)
    monkeypatch.setattr(fetcher, "read_daily_bars_grant", lambda **_: world.grant)
    assert daily_bars_fetch_task(SimpleNamespace(daily_bars_source="mairui"), DAY.isoformat(),
                                str(world.grant.user_id), batch_kind="backfill", batch_seq=4) == 0
    items, runs, count = facts(world)
    assert items[0].batch_kind == "backfill" and items[0].batch_seq == 4
    assert len(items) == len(runs) == 1 and count == 0 and world.calls == []


@pytest.mark.parametrize("stamp,expected", [(at(17, 44, 59), 1), (at(17, 45), 0)])
def test_cli_apply_half_open_window_and_explicit_backfill(world, monkeypatch, capsys, stamp, expected):
    from app.cli import daily_bars_backfill as cli
    from app.workers import jobs
    monkeypatch.setattr(jobs, "_engine", lambda _: world.engine)
    monkeypatch.setattr(cli, "backfill_window_days", lambda *_: 5)
    monkeypatch.setattr(cli, "_universe_size", lambda *_: 2)
    client = Redis()
    code = cli.main(["--years", "3", "--trade-date", DAY.isoformat(), "--apply"],
                    now=stamp, redis_client=client, settings=SimpleNamespace())
    assert code == expected
    if not expected:
        assert len(client.queued) == 1
        assert json.loads(client.queued[0])["args"] == {
            "trade_date": DAY.isoformat(), "window_trading_days": 5, "batch_kind": "backfill"}
    else:
        assert client.queued == []
    assert facts(world)[2] == 0 and world.calls == []
    capsys.readouterr()


def test_uncertain_attempt_during_window_fails_without_being_delayed(gated):
    bid = queue(gated, window=5)
    with gated.engine.begin() as conn:
        conn.execute(update(outbox).where(outbox.c.id == bid).values(status="running", attempted_at=NOW))
    assert tick(gated) == 1
    item = facts(gated)[0][0]
    assert item.status == "failed" and item.error_code == "daily_bars_uncertain_attempt_no_retry"
    assert gated.calls == [] and gated.redis.delayed == {}


def test_expired_batch_during_window_is_failed_without_new_delay(gated):
    queue(gated, window=5)
    gated.stamp += dt.timedelta(days=1)
    assert tick(gated) == 1
    item = facts(gated)[0][0]
    assert item.status == "failed" and item.error_code == "daily_bars_batch_expired"
    assert gated.calls == [] and gated.redis.delayed == {}


def test_first_batch_stop_in_window_is_persisted_instead_of_delayed(gated):
    queue(gated, window=5)
    (gated.root / "STOP").touch()
    assert tick(gated) == 1
    assert facts(gated)[0][0].status == "halted" and gated.calls == []
    assert gated.redis.delayed == {}


def test_worker_commits_intent_before_redis_delay_and_db_survives_loss(world, monkeypatch):
    from app.marketdata import daily_bars_outbox
    from app.workers import jobs
    from app.marketdata.daily_bars import daily_bars_fetch_task
    state = {"clock": at(17)}
    world.grant = replace(world.grant, start=at(16), end=at(20))
    monkeypatch.setattr(jobs, "_engine", lambda _: world.engine)
    monkeypatch.setattr(jobs, "dt", SimpleNamespace(UTC=dt.UTC,
                         datetime=SimpleNamespace(now=lambda _: state["clock"])))
    monkeypatch.setattr(daily_bars_outbox, "utcnow", lambda: state["clock"])
    monkeypatch.setattr(fetcher, "read_daily_bars_grant", lambda **_: world.grant)
    monkeypatch.setitem(jobs.TASKS, "daily_bars_fetch", daily_bars_fetch_task)
    monkeypatch.setattr(jobs, "MAX_JOBS_PER_TICK", 1)
    client = Redis()
    client.locks = {}
    client.rpop = lambda _: client.queued.pop() if client.queued else None
    client.set = lambda key, value, **_: client.locks.setdefault(key, value.encode()) is not None
    client.get = lambda key: client.locks.get(key)
    client.delete = lambda key: client.locks.pop(key, None)
    original = client.zadd

    def check_commit(key, mapping):
        items, runs, count = facts(world)
        assert len(items) == len(runs) == 1 and items[0].status == "pending"
        assert items[0].attempted_at is None and count == 0
        return original(key, mapping)

    client.zadd = check_commit
    args = {"trade_date": DAY.isoformat(), "user_id": str(world.grant.user_id),
            "window_trading_days": 1}
    jobs._push(client, "daily_bars_fetch", args)
    assert jobs.worker_tick(SimpleNamespace(daily_bars_source="mairui"), client=client) == [("daily_bars_fetch", "delayed")]
    assert len(client.delayed) == 1 and world.calls == []
    client.delayed.clear()
    state["clock"] = at(17, 45)
    assert implementation().tick(world.engine, transport=world.transport,
        grant_reader=lambda _: world.grant, clock=lambda: state["clock"],
        stop=world.root / "STOP", halt=world.root / "HALTED") == 1
    assert facts(world)[2] == 2


def test_clock_reaches_window_during_receipt_recheck_before_first_send(gated):
    queue(gated, window=5)
    gated.stamp = at(16, 59, 59)
    reads = []

    def read(_):
        reads.append(1)
        if len(reads) == 3:
            gated.stamp = at(17)
        return gated.grant

    module = implementation()
    assert module.tick(gated.engine, redis_client=gated.redis, transport=gated.transport,
        grant_reader=read, clock=lambda: gated.stamp, stop=gated.root / "STOP",
        halt=gated.root / "HALTED", page_days=2) == 1
    items, runs, count = facts(gated)
    assert items[0].attempted_at is None and count == 0 and gated.calls == []
    assert items[0].error_code == "daily_bars_resume_pending" and len(gated.redis.delayed) == 1
    assert "daily_bars_resume_stalled" not in runs[0].stats["issues"]
    gated.stamp = at(17, 45)
    assert tick(gated) == 1 and facts(gated)[2] == 10


def test_commit_before_delayed_publish_crash_recovers_stable_wakeup(gated, monkeypatch):
    queue(gated, window=5)
    gated.stamp = at(16, 59, 59)
    original = gated.transport

    def send(*args):
        result = original(*args)
        gated.stamp = at(17)
        return result

    gated.transport = send
    module = implementation()
    wake = module.wake_delayed
    calls = []
    class Crash(BaseException):
        pass

    def crash(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise Crash()
        return wake(*args, **kwargs)

    monkeypatch.setattr(module, "wake_delayed", crash)
    with pytest.raises(Crash):
        tick(gated)
    assert len(gated.calls) == 1 and gated.redis.delayed == {}
    assert facts(gated)[0][0].error_code == "daily_bars_resume_pending"
    monkeypatch.setattr(module, "wake_delayed", wake)
    assert tick(gated) == 0 and tick(gated) == 0
    assert len(gated.redis.delayed) == 1 and len(gated.calls) == 1


def test_redis_failure_before_zadd_preserves_intent(gated):
    import redis
    queue(gated, window=5)
    original = gated.redis.zadd
    def fail(*args):
        raise redis.ConnectionError("synthetic unavailable Redis")
    gated.redis.zadd = fail
    assert tick(gated) == 0 and facts(gated)[0][0].attempted_at is None
    assert gated.redis.delayed == {} and gated.calls == []
    gated.redis.zadd = original
    assert tick(gated) == 0 and len(gated.redis.delayed) == 1


def test_cli_past_trade_date_respects_1700_start(gated, monkeypatch, capsys):
    from app.cli import daily_bars_backfill as cli
    from app.workers import jobs
    monkeypatch.setattr(jobs, "_engine", lambda _: gated.engine)
    monkeypatch.setattr(cli, "backfill_window_days", lambda *_: 5)
    monkeypatch.setattr(cli, "_universe_size", lambda *_: 2)
    args = ["--years", "3", "--trade-date", (DAY - dt.timedelta(days=1)).isoformat(), "--apply"]
    for stamp, expected in [(at(16, 59, 59), 0), (at(17), 1), (at(17, 44, 59), 1), (at(17, 45), 0)]:
        client = Redis()
        assert cli.main(args, now=stamp, redis_client=client, settings=SimpleNamespace()) == expected
        assert len(client.queued) == int(not expected)
    assert gated.calls == [] and facts(gated)[2] == 0
    capsys.readouterr()


def test_task_signature_preserves_old_arguments_and_safe_batch_defaults():
    import inspect
    from app.marketdata.daily_bars import daily_bars_fetch_task
    signature = inspect.signature(daily_bars_fetch_task)
    assert list(signature.parameters) == [
        "settings", "trade_date", "user_id", "window_trading_days", "batch_kind", "batch_seq"]
    assert signature.parameters["batch_kind"].default == "daily"
    assert signature.parameters["batch_seq"].default == 0
    assert type(signature.parameters["batch_seq"].default) is int
    assert "fetched_at" not in signature.parameters
