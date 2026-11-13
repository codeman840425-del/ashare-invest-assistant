"""C2 durable worker intent, using synthetic grants and disposable PostgreSQL only."""

from __future__ import annotations

import datetime as dt
import importlib
import importlib.util
import socket
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from app.config import Settings
from app.db.tables.realtime import pipeline_runs
from app.db.tables.users import users
from app.ingest import daily_bars as ingest
from app.marketdata.daily_bars import daily_bars_fetch_task
from psycopg import sql
from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.engine import make_url

DAY = dt.date(2026, 11, 12)
NOW = dt.datetime(2026, 11, 12, 9, 20, tzinfo=dt.UTC)
OWNER = uuid.UUID(int=102)
OTHER = uuid.UUID(int=103)


def implementation() -> Any:
    name = "app.marketdata.daily_bars_outbox"
    assert importlib.util.find_spec(name), "C2 durable outbox implementation missing"
    return importlib.import_module(name)


@pytest.fixture
def world(pg_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    url = make_url(pg_url)
    assert url.host in {"localhost", "127.0.0.1", "::1", "postgres"}
    name = "c2_outbox_" + uuid.uuid4().hex
    admin = psycopg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False),
        autocommit=True,
    )
    engine = None
    try:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        engine = create_engine(url.set(drivername="postgresql+psycopg", database=name))
        with engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA app"))
            users.create(conn)
            pipeline_runs.create(conn)
            conn.execute(
                insert(users),
                [
                    {
                        "id": uid,
                        "username": "synthetic_c2_" + str(uid.int),
                        "display_name": "synthetic",
                        "role": "user",
                        "status": "approved",
                        "password_hash": "unusable",
                    }
                    for uid in (OWNER, OTHER)
                ],
            )
        counters = {"mairui_get": 0, "credential": 0, "socket": 0}

        def forbidden_get(*args: Any, **kwargs: Any) -> None:
            counters["mairui_get"] += 1
            raise AssertionError("real egress forbidden")

        def forbidden_credential(*args: Any, **kwargs: Any) -> None:
            counters["credential"] += 1
            raise AssertionError("credential reads forbidden")

        original_connect = socket.socket.connect

        def guarded_connect(sock: socket.socket, address: Any) -> Any:
            if sock.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in {
                "127.0.0.1",
                "::1",
            }:
                counters["socket"] += 1
                raise AssertionError("external socket forbidden")
            return original_connect(sock, address)

        from app.ingest import daily_lists, egress

        monkeypatch.setattr(egress, "mairui_get", forbidden_get)
        monkeypatch.setattr(daily_lists, "credential", forbidden_credential)
        monkeypatch.setattr(socket.socket, "connect", guarded_connect)
        yield SimpleNamespace(engine=engine, counters=counters)
        assert counters == {"mairui_get": 0, "credential": 0, "socket": 0}
    finally:
        if engine is not None:
            engine.dispose()
        assert name.startswith("c2_outbox_") and len(name) == 42
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


def grant(owner: uuid.UUID) -> ingest.DailyBarsGrant:
    return ingest.DailyBarsGrant(
        owner,
        uuid.UUID(int=202),
        uuid.UUID(int=203),
        NOW - dt.timedelta(hours=1),
        NOW + dt.timedelta(hours=1),
        "synthetic-receipt-digest",
    )


def install_table(world: Any) -> Any:
    module = implementation()
    with world.engine.begin() as conn:
        module.outbox.create(conn)
    return module


@pytest.mark.parametrize(
    "value,batch_kind,expected",
    [
        (0, "daily", "unset"),
        (0, "backfill", "unset"),
        (1, "daily", "capped"),
        (500, "daily", "capped"),
        (501, "daily", "unset"),
        (2000, "daily", "unset"),
        (2000, "backfill", "capped"),
        (2001, "backfill", "unset"),
        (True, "daily", "unset"),
        ("unlimited", "backfill", "unset"),
        (-1, "daily", "unset"),
    ],
)
def test_batch_budget_rejects_unlimited_and_out_of_bounds(
    value: Any, batch_kind: str, expected: str
) -> None:
    assert hasattr(ingest, "daily_bars_batch_budget"), "C2 batch budget missing"
    assert ingest.DAILY_BARS_BATCH_LIMIT == ingest.DAILY_BARS_BACKFILL_BATCH_LIMIT == 0
    assert ingest.daily_bars_batch_budget(value, batch_kind).kind == expected


def test_worker_default_zero_never_reads_receipt_or_egress(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workers import jobs

    monkeypatch.setattr(jobs, "_engine", lambda settings: world.engine)
    monkeypatch.setattr(
        ingest,
        "read_daily_bars_grant",
        lambda *a, **k: pytest.fail("unset must not read receipt"),
    )
    settings = Settings.model_construct(daily_bars_source="mairui")
    assert daily_bars_fetch_task(settings, DAY.isoformat(), str(OWNER)) == 0
    with world.engine.connect() as conn:
        run = conn.execute(select(pipeline_runs)).one()
        assert run.status == "skipped"
        assert run.stats["issues"] == ["daily_bars_http_budget_unset"]


@pytest.mark.parametrize(
    "daily_limit,backfill_limit,batch_kind,expected",
    [
        (500, 0, "daily", "capped"),
        (0, 2000, "backfill", "capped"),
        (500, 0, "backfill", "unset"),
        (0, 2000, "daily", "unset"),
        (501, 2000, "daily", "unset"),
        (500, 2001, "backfill", "unset"),
    ],
)
def test_batch_kind_does_not_borrow_the_other_constant(
    monkeypatch: pytest.MonkeyPatch,
    daily_limit: int,
    backfill_limit: int,
    batch_kind: str,
    expected: str,
) -> None:
    module = implementation()
    monkeypatch.setattr(ingest, "DAILY_BARS_BATCH_LIMIT", daily_limit)
    monkeypatch.setattr(ingest, "DAILY_BARS_BACKFILL_BATCH_LIMIT", backfill_limit)
    assert module.batch_budget(batch_kind).kind == expected


def test_worker_nonunset_records_running_and_outbox_atomically(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = install_table(world)
    from app.workers import jobs

    monkeypatch.setattr(jobs, "_engine", lambda settings: world.engine)
    monkeypatch.setattr(ingest, "DAILY_BARS_BATCH_LIMIT", 2)
    monkeypatch.setattr(ingest, "read_daily_bars_grant", lambda *a, **k: grant(OWNER))
    monkeypatch.setattr(module, "utcnow", lambda: NOW)
    assert (
        daily_bars_fetch_task(
            Settings.model_construct(daily_bars_source="mairui"),
            DAY.isoformat(),
            str(OWNER),
        )
        == 0
    )
    with world.engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(pipeline_runs)) == 1
        run = conn.execute(select(pipeline_runs)).one()
        assert run.status == "running" and run.finished_at is None
        row = conn.execute(select(module.outbox)).one()
        assert row.pipeline_run_id == run.id and row.status == "pending"
        assert row.kind == "mairui_daily_bars" and row.user_id == OWNER
        assert row.source_licence_id == grant(OWNER).licence_id


def test_repeated_intent_creates_one_outbox_and_one_run(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = install_table(world)
    monkeypatch.setattr(ingest, "DAILY_BARS_BATCH_LIMIT", 2)
    for _ in range(2):
        with world.engine.begin() as conn:
            module.enqueue(
                conn, trade_date=DAY, user_id=OWNER, grant_reader=grant, now=NOW
            )
    with world.engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(module.outbox)) == 1
        assert conn.scalar(select(func.count()).select_from(pipeline_runs)) == 1


@pytest.mark.parametrize("bad", [None, "wrong_owner", "expired"])
def test_unavailable_receipt_never_builds_outbox(
    world: Any, monkeypatch: pytest.MonkeyPatch, bad: str | None
) -> None:
    module = install_table(world)
    monkeypatch.setattr(ingest, "DAILY_BARS_BATCH_LIMIT", 2)
    value = None if bad is None else grant(OTHER if bad == "wrong_owner" else OWNER)
    if bad == "expired":
        from dataclasses import replace

        value = replace(value, end=NOW)  # type: ignore[arg-type]
    with world.engine.begin() as conn:
        module.enqueue(
            conn,
            trade_date=DAY,
            user_id=OWNER,
            grant_reader=lambda owner: value,
            now=NOW,
        )
    with world.engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(module.outbox)) == 0
        run = conn.execute(select(pipeline_runs)).one()
        assert run.status == "skipped" and run.stats["issues"] == [
            "data_licence_unavailable"
        ]


def test_transaction_rollback_leaves_no_orphan_running_run(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = install_table(world)
    monkeypatch.setattr(ingest, "DAILY_BARS_BATCH_LIMIT", 2)
    with (
        pytest.raises(RuntimeError, match="injected rollback"),
        world.engine.begin() as conn,
    ):
        module.enqueue(conn, trade_date=DAY, user_id=OWNER, grant_reader=grant, now=NOW)
        raise RuntimeError("injected rollback")
    with world.engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(module.outbox)) == 0
        assert conn.scalar(select(func.count()).select_from(pipeline_runs)) == 0


def test_window_does_not_select_backfill_budget(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = install_table(world)
    monkeypatch.setattr(ingest, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 2000)
    with world.engine.begin() as conn:
        module.enqueue(
            conn,
            trade_date=DAY,
            user_id=OWNER,
            window_trading_days=3,
            grant_reader=grant,
            now=NOW,
        )
    with world.engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(module.outbox)) == 0
        assert conn.execute(select(pipeline_runs.c.status)).scalar_one() == "skipped"


@pytest.mark.parametrize("source", ["off", "fake"])
def test_other_sources_do_not_create_mairui_intent(
    world: Any, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    from app.marketdata import daily_bars
    from app.workers import jobs

    monkeypatch.setattr(jobs, "_engine", lambda settings: world.engine)
    monkeypatch.setattr(daily_bars, "fetch_and_record", lambda *a, **k: 0)
    monkeypatch.setattr(
        ingest, "read_daily_bars_grant", lambda *a, **k: pytest.fail("no receipt read")
    )
    assert (
        daily_bars_fetch_task(
            Settings.model_construct(daily_bars_source=source),
            DAY.isoformat(),
            str(OWNER),
        )
        == 0
    )


def test_migration_single_head_upgrade_downgrade_and_nonempty_refusal(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect

    backend = Path(__file__).resolve().parents[3] / "src/backend"
    config = Config()
    config.set_main_option("script_location", str(backend / "migrations"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0035"]
    revision = script.get_revision("0035")
    assert revision is not None and revision.down_revision == "0034"
    migration = revision.module
    module = implementation()
    monkeypatch.setattr(ingest, "DAILY_BARS_BATCH_LIMIT", 2)
    with (
        world.engine.begin() as conn,
        Operations.context(MigrationContext.configure(conn)),
    ):
        migration.upgrade()
        assert inspect(conn).has_table("daily_bars_outbox", schema="app")
        migration.downgrade()
        assert not inspect(conn).has_table("daily_bars_outbox", schema="app")
        migration.upgrade()
        module.enqueue(conn, trade_date=DAY, user_id=OWNER, grant_reader=grant, now=NOW)
        with pytest.raises(RuntimeError, match="not empty"):
            migration.downgrade()
        assert conn.scalar(select(func.count()).select_from(module.outbox)) == 1
        assert conn.scalar(select(func.count()).select_from(pipeline_runs)) == 1


@pytest.mark.parametrize("daily_limit", [501, 2000])
def test_daily_oversized_budget_never_builds_outbox(
    world: Any, monkeypatch: pytest.MonkeyPatch, daily_limit: int
) -> None:
    module = install_table(world)
    monkeypatch.setattr(ingest, "DAILY_BARS_BATCH_LIMIT", daily_limit)
    monkeypatch.setattr(ingest, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 2000)
    with world.engine.begin() as conn:
        module.enqueue(conn, trade_date=DAY, user_id=OWNER, grant_reader=grant, now=NOW)
    with world.engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(module.outbox)) == 0
        run = conn.execute(select(pipeline_runs)).one()
        assert run.status == "skipped"
        assert run.stats["issues"] == ["daily_bars_http_budget_unset"]
