"""C2 consumer: disposable PG, synthetic receipts and injected transport only."""

from __future__ import annotations

import datetime as dt
import importlib
import importlib.util
import socket
import uuid
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import psycopg
import pytest
from app.db.tables.daily_bars import outbox
from app.db.tables.licences import user_data_licence_holds as holds
from app.db.tables.market import daily_bars, trading_calendar
from app.db.tables.realtime import pipeline_runs
from app.db.tables.users import users
from app.ingest import daily_bars as fetcher
from app.ingest.egress import single_egress
from app.marketdata.daily_bars import DailyBar
from app.marketdata.daily_bars_outbox import enqueue
from psycopg import sql
from sqlalchemy import create_engine, func, insert, select, text, update
from sqlalchemy.engine import make_url

DAY = dt.date(2026, 11, 12)
NOW = dt.datetime(2026, 11, 12, 10, tzinfo=dt.UTC)
OWNER, LID, RID = (uuid.UUID(int=n) for n in (811, 812, 813))
CODES = ["999991.SH", "999992.SH"]
GRANT = fetcher.DailyBarsGrant(
    OWNER,
    LID,
    RID,
    NOW - dt.timedelta(hours=1),
    NOW + dt.timedelta(hours=1),
    "synthetic-consumer-receipt",
)


def implementation():
    name = "app.ingest.daily_bars_consumer"
    assert importlib.util.find_spec(name), "C2 ingest consumer missing"
    return importlib.import_module(name)


@pytest.fixture
def world(pg_url, monkeypatch, tmp_path):
    url = make_url(pg_url)
    assert url.host in {"127.0.0.1", "localhost", "::1", "postgres"}
    name = "c2_consume_" + uuid.uuid4().hex
    admin = psycopg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False), autocommit=True
    )
    engine = None
    try:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        engine = create_engine(url.set(drivername="postgresql+psycopg", database=name))
        with engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA app"))
            conn.execute(text("CREATE SCHEMA market"))
            for table in (users, pipeline_runs, outbox, holds, trading_calendar, daily_bars):
                table.create(conn)
            # Nonsecret status projection only; no credential table or ciphertext exists.
            conn.execute(
                text(
                    "CREATE TABLE app.user_data_licence_status (id uuid, user_id uuid, status text, paused_until timestamptz, expires_on date, deleted_at timestamptz)"
                )
            )
            conn.execute(
                insert(users).values(
                    id=OWNER,
                    username="synthetic_consumer",
                    display_name="synthetic",
                    role="user",
                    status="approved",
                    password_hash="unusable",
                )
            )
            conn.execute(
                text(
                    "INSERT INTO app.user_data_licence_status(id,user_id,status) VALUES (:id,:owner,'active')"
                ),
                {"id": LID, "owner": OWNER},
            )
            conn.execute(insert(trading_calendar).values(date=DAY, is_open=True))
        state = SimpleNamespace(engine=engine, root=tmp_path, calls=[], grant=GRANT)
        monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 5)
        monkeypatch.setattr(fetcher, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 5)
        monkeypatch.setattr(fetcher, "daily_universe", lambda *_: CODES)

        def forbidden(*args, **kwargs):
            pytest.fail("consumer attempted real egress or credentials")

        from app.ingest import daily_lists, egress

        monkeypatch.setattr(egress, "mairui_get", forbidden)
        monkeypatch.setattr(daily_lists, "credential", forbidden)
        original_connect = socket.socket.connect

        def connect(sock, address):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                assert address[0] in {"127.0.0.1", "::1"}, "external socket forbidden"
            return original_connect(sock, address)

        monkeypatch.setattr(socket.socket, "connect", connect)

        def transport(code, start, end):
            state.calls.append(code)
            assert start == end == DAY
            price = Decimal("1")
            return 200, DailyBar(
                code, DAY, "none", price, price, price, price, price, price, price, False
            )

        state.transport = transport
        yield state
    finally:
        if engine is not None:
            engine.dispose()
        assert name.startswith("c2_consume_") and len(name) == 43
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        assert (
            admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone() is None
        )
        admin.close()


def queue(world, seq=0, window=None, kind="daily"):
    with world.engine.begin() as conn:
        enqueue(
            conn,
            trade_date=DAY,
            user_id=OWNER,
            batch_seq=seq,
            batch_kind=kind,
            window_trading_days=window,
            grant_reader=lambda _: GRANT,
            now=NOW,
        )
        return conn.execute(select(outbox.c.id).where(outbox.c.batch_seq == seq)).scalar_one()


def process(world, bid, transport=None):
    return implementation().process(
        world.engine,
        bid,
        transport=transport or world.transport,
        grant_reader=lambda _: world.grant,
        clock=lambda: NOW,
        stop=world.root / "STOP",
        halt=world.root / "HALTED",
    )


def facts(world):
    with world.engine.connect() as conn:
        return (
            conn.execute(select(outbox).order_by(outbox.c.batch_seq)).all(),
            conn.execute(select(pipeline_runs).order_by(pipeline_runs.c.started_at)).all(),
            conn.scalar(select(func.count()).select_from(daily_bars)),
        )


def test_consumer_finishes_original_run_and_redelivery_never_sends(world):
    bid = queue(world)
    assert process(world, bid) == "done"
    items, runs, count = facts(world)
    assert count == 2 and len(runs) == 1 and runs[0].id == items[0].pipeline_run_id
    assert runs[0].status == "ok" and runs[0].finished_at and items[0].attempted_at
    assert process(world, bid) == "noop" and world.calls == CODES


def test_mairui_rerun_idempotent_no_extra_calls(world):
    assert process(world, queue(world)) == "done"
    assert process(world, queue(world, seq=1)) == "done"
    items, runs, count = facts(world)
    assert world.calls == CODES and count == 2 and len(runs) == 2
    assert items[1].attempted_at is None and all(run.status == "ok" for run in runs)


def test_crash_after_persisted_attempt_is_not_replayed_on_next_tick(world):
    class Crash(BaseException):
        pass

    def crash(*args):
        world.calls.append("uncertain")
        raise Crash()

    bid = queue(world)
    with pytest.raises(Crash):
        process(world, bid, crash)
    items, runs, count = facts(world)
    assert items[0].attempted_at and items[0].status == "running" and count == 0
    assert process(world, bid) == "failed"
    items, runs, count = facts(world)
    assert items[0].error_code == "daily_bars_uncertain_attempt_no_retry"
    assert runs[0].status == "failed" and len(runs) == 1 and world.calls == ["uncertain"]


def test_send_observes_attempt_already_committed_from_another_connection(world):
    bid = queue(world)

    def send(*args):
        with world.engine.connect() as conn:
            assert conn.execute(
                select(outbox.c.attempted_at).where(outbox.c.id == bid)
            ).scalar_one()
        return world.transport(*args)

    assert process(world, bid, send) == "done"


def test_business_failure_rolls_back_bars_and_finishes_same_run_separately(world):
    def fail(*args):
        if world.calls:
            raise RuntimeError("synthetic body must not enter audit error")
        return world.transport(*args)

    assert process(world, queue(world), fail) == "failed"
    items, runs, count = facts(world)
    assert count == 0 and len(runs) == 1 and runs[0].status == "failed"
    assert items[0].error_code == "daily_bars_collection_failed_no_retry"
    assert "synthetic body" not in str(runs[0].error)


@pytest.mark.parametrize("signal", ["STOP", "HALTED", 103, 429])
def test_each_send_rechecks_stop_and_rate_limit_halts_without_continuation(world, signal):
    def send(*args):
        if isinstance(signal, str):
            (world.root / signal).write_text("synthetic stop", encoding="utf-8")
            return world.transport(*args)
        world.calls.append("limited")
        return signal, None

    assert process(world, queue(world), send) == "halted"
    assert len(world.calls) == 1
    items, runs, count = facts(world)
    assert items[0].status == "halted" and runs[0].status == "failed" and count == 0


def test_halt_file_failure_remains_durable_across_the_next_consumer(world, monkeypatch):
    monkeypatch.setattr(fetcher, "persist_halt", lambda *_: False)
    assert process(world, queue(world), lambda *_: (429, None)) == "halted"
    assert not (world.root / "HALTED").exists()
    bid = queue(world, seq=1)
    assert process(world, bid) == "halted" and world.calls == []
    items, _, _ = facts(world)
    assert items[1].status == "pending" and items[1].attempted_at is None


@pytest.mark.parametrize("bad", ["owner", "licence", "receipt", "digest", "expired", "held"])
def test_revalidate_exact_receipt_and_current_owner_status_before_attempt(world, bad):
    bid = queue(world)
    changes = {
        "owner": {"user_id": uuid.UUID(int=899)},
        "licence": {"licence_id": uuid.UUID(int=899)},
        "receipt": {"receipt_id": uuid.UUID(int=899)},
        "digest": {"digest": "changed"},
        "expired": {"end": NOW},
    }
    if bad == "held":
        with world.engine.begin() as conn:
            conn.execute(insert(holds).values(user_id=OWNER))
    else:
        world.grant = replace(GRANT, **changes[bad])
    assert process(world, bid) == "failed" and world.calls == []
    assert facts(world)[0][0].attempted_at is None


def test_pause_between_sends_blocks_second_attempt(world):
    def send(*args):
        result = world.transport(*args)
        with world.engine.begin() as conn:
            conn.execute(insert(holds).values(user_id=OWNER))
        return result

    assert process(world, queue(world), send) == "failed"
    assert len(world.calls) == 1


@pytest.mark.parametrize("kind", ["daily", "backfill"])
def test_list_and_both_daily_bar_batch_types_use_the_same_egress_lease(world, kind):
    bid = queue(world, kind=kind)
    with single_egress(world.engine) as lease:
        assert lease is not None
        assert process(world, bid) == "busy"
    assert facts(world)[0][0].attempted_at is None and world.calls == []


def test_unknown_multiday_page_size_fails_without_sending_or_guessing(world):
    assert process(world, queue(world, window=3)) == "failed"
    assert world.calls == [] and facts(world)[0][0].attempted_at is None


def test_zero_budgets_short_circuit_tick_before_any_resource(monkeypatch):
    module = implementation()
    monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 0)
    monkeypatch.setattr(fetcher, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 0)
    assert module.tick(object()) == 0


def test_ready_codes_do_not_consume_http_quota(world, monkeypatch):
    assert process(world, queue(world)) == "done"
    extra = CODES + ["999993.SH", "999994.SH"]
    monkeypatch.setattr(fetcher, "daily_universe", lambda *_: extra)
    monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 2)
    assert process(world, queue(world, seq=1)) == "done"
    assert world.calls == extra and facts(world)[2] == 4


def test_wrong_pipeline_identity_is_rejected_without_mutating_that_run(world):
    bid = queue(world)
    with world.engine.begin() as conn:
        conn.execute(update(pipeline_runs).values(step="synthetic.other_task"))
    with pytest.raises(RuntimeError, match="run_identity_changed"):
        process(world, bid)
    items, runs, _ = facts(world)
    assert runs[0].status == "running" and items[0].status == "pending"
    assert world.calls == [] and items[0].attempted_at is None


@pytest.mark.parametrize("source", ["off", "fake", "mairui"])
@pytest.mark.parametrize("paused", [False, True])
def test_heartbeat_hooks_only_matching_source_with_zero_default_io(monkeypatch, source, paused):
    module = implementation()
    from app.ingest import daily_lists, runtime
    from app.workers import ingest as worker

    monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 0)
    monkeypatch.setattr(fetcher, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 0)
    engine = object()
    events = []
    client = SimpleNamespace(
        set=lambda *a, **k: events.append("heartbeat"),
        exists=lambda *_: paused,
        close=lambda: events.append("closed"),
    )
    monkeypatch.setattr(worker.redis.Redis, "from_url", lambda *a, **k: client)
    monkeypatch.setattr(runtime, "get_ingest_core", lambda: SimpleNamespace(engine=engine))
    monkeypatch.setattr(runtime, "tick_ingest_core", lambda: events.append("core"))
    monkeypatch.setattr(daily_lists, "tick", lambda *a, **k: events.append("lists"))
    actual_tick = module.tick

    def observed_tick(arg):
        assert arg is engine
        events.append("bars")
        return actual_tick(arg)

    monkeypatch.setattr(module, "tick", observed_tick)
    settings = SimpleNamespace(
        redis_url="redis://synthetic.invalid",
        health_check_timeout_s=1,
        ingest_heartbeat_key="synthetic:heartbeat",
        ingest_paused_key="synthetic:paused",
        daily_bars_source=source,
        business=SimpleNamespace(ingest=SimpleNamespace(heartbeat=SimpleNamespace(ttl_s=30))),
    )
    worker.write_heartbeat(settings)
    assert events.count("bars") == int(source == "mairui" and not paused)
    assert events[-2:] == ["core", "closed"]


def test_tick_consumes_durable_pending_without_a_redis_delivery(world):
    bid = queue(world)
    module = implementation()
    assert (
        module.tick(
            world.engine,
            transport=world.transport,
            grant_reader=lambda _: GRANT,
            clock=lambda: NOW,
            stop=world.root / "STOP",
            halt=world.root / "HALTED",
        )
        == 1
    )
    assert process(world, bid) == "noop" and world.calls == CODES
