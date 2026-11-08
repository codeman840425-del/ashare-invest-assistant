"""T-B85b: synthetic inputs, REAL Unix-socket PostgreSQL/Redis; no live intake.

The four public identifiers carry only fictional names/states/dates here. A
DeepSeek mechanical draft supplied names; deterministic expectations are local.
The transaction facade only rolls back test data, not any pipeline computation.
"""

# ruff: noqa: S101, S108, ANN401
from __future__ import annotations

import datetime as dt
import importlib
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import redis
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db.tables.market import (
    master_runs,
    master_snapshots,
    securities,
    trading_calendar,
)
from app.db.tables.market import (
    security_listing_status_history as listing,
)
from app.db.tables.market import (
    security_risk_flag_history as risk,
)
from app.master.mairui_snapshot import (
    DATASETS,
    TASK,
    DailyNames,
    apply_delivery,
    latest_visible_flags,
    read_flags,
)
from app.master.public_sources import PublicSourceGapError
from app.master.sync import BEIJING
from app.replay.baseline import require_isolated
from app.workers import jobs
from selfchecks.test_tb70_replay import DB, REDIS, no_network  # noqa: F401

DAY = dt.date(2031, 1, 2)  # Deliberately synthetic calendar; not an exchange claim.
CODES = ("688018.SH", "688073.SH", "300364.SZ", "301218.SZ")
NAMES = dict(
    zip(CODES, ("虚构智芯科技", "合成幻境微电子", "合成云梦传媒", "合成星野精密"), strict=True)
)


def at(offset: int = 0, hour: int = 18, minute: int = 0) -> dt.datetime:
    return dt.datetime.combine(DAY + dt.timedelta(days=offset), dt.time(hour, minute), BEIJING)


def delivery(names: dict[str, str] | None = None, offset: int = 0) -> DailyNames:
    return DailyNames(dict(NAMES) if names is None else names, at(offset), DATASETS)


@pytest.fixture
def db_conn() -> Any:
    if not Path("/tmp/tb70-pg-socket/.s.PGSQL.5432").exists():
        pytest.fail("dedicated isolated PostgreSQL must be started explicitly")
    engine = create_engine(DB)
    try:
        with engine.connect() as conn, conn.begin():
            require_isolated(conn, app_env="test")
            conn.execute(text("SET LOCAL lock_timeout='3s'"))
            assert (
                conn.execute(text("select version_num from alembic_version")).scalar_one() == "0020"
            )
            yield conn
            conn.rollback()
    finally:
        engine.dispose()


@pytest.fixture
def env(db_conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    conn = db_conn
    migration = importlib.import_module("migrations.versions.0023_t_b85b_mairui_source")
    with Operations.context(MigrationContext.configure(conn)):
        migration.upgrade()
    assert set(
        conn.execute(select(securities.c.code).where(securities.c.code.in_(CODES))).scalars()
    ) == set(CODES)
    for table in (risk, listing):
        conn.execute(delete(table).where(table.c.code.in_(CODES)))
    conn.execute(
        update(securities)
        .where(securities.c.code.in_(CODES))
        .values(listing_status="listed", risk_flag=None, field_sources={})
    )
    for offset in range(-1, 5):
        conn.execute(
            pg_insert(trading_calendar)
            .values(
                date=DAY + dt.timedelta(days=offset),
                is_open=True,
            )
            .on_conflict_do_update(index_elements=["date"], set_={"is_open": True})
        )
    settings = Settings(_env_file=None, app_env="test", master_snapshot_path=tmp_path)

    @contextmanager
    def begin() -> Any:
        with conn.begin_nested():
            yield conn

    @contextmanager
    def connect() -> Any:
        yield conn

    namespace = "T-B85b:" + uuid.uuid4().hex + ":"
    r = redis.Redis.from_url(REDIS)
    monkeypatch.setattr(jobs, "_engine", lambda _: SimpleNamespace(begin=begin, connect=connect))
    monkeypatch.setattr(jobs, "QUEUE_KEY", namespace + "queue")
    monkeypatch.setattr(jobs, "SLOT_PREFIX", namespace + "slot:")
    monkeypatch.setattr(jobs, "LOCK_PREFIX", namespace + "lock:")
    monkeypatch.setattr(jobs, "_now", lambda: at())
    try:
        yield SimpleNamespace(
            conn=conn,
            settings=settings,
            cfg=settings.business.securities.master,
            root=tmp_path,
            redis=r,
            migration=migration,
        )
    finally:
        keys = list(r.scan_iter(match=namespace + "*"))
        if keys:
            r.delete(*keys)
        r.close()


def apply(e: Any, value: DailyNames | None, offset: int = 0) -> int:
    return apply_delivery(e.conn, value, now=at(offset), cfg=e.cfg, root=e.root)


def flags(
    e: Any, offset: int = 0, code: str = CODES[0], as_of: dt.datetime | None = None
) -> dict[str, Any]:
    return read_flags(
        e.conn, code, DAY + dt.timedelta(days=offset), as_of=as_of or at(offset + 1, 9)
    )


def test_real_queue_worker_persistence_pit_and_consumer(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = env
    monkeypatch.setattr(
        jobs, "_mairui_delivery", lambda *_: delivery({**NAMES, CODES[0]: "*ST合成智芯"})
    )
    assert jobs.beat_slots(e.settings, client=e.redis, now=at()) == [TASK]
    assert jobs.beat_slots(e.settings, client=e.redis, now=at()) == []
    assert jobs.worker_tick(e.settings, client=e.redis) == [(TASK, "ok")]
    run = e.conn.execute(
        select(master_runs).where(master_runs.c.stats["task"].astext == TASK)
    ).one()
    assert run.status == "ok"
    assert flags(e)["f.is_st"] is True
    assert flags(e)["f.is_delisting_period"] is False
    from app.strategy.horizon import inputs

    monkeypatch.setattr(inputs, "now_utc", lambda: at(1, 9))
    out = inputs.collect(e.conn, uuid.uuid4(), CODES[0], ["f.is_st", "f.is_delisting_period"])
    assert out.values == {"f.is_st": True, "f.is_delisting_period": False}
    assert out.sources["f.is_st"]["provider"] == "mairui_list"
    assert flags(e, as_of=at(0, 23))["f.is_st"] is None
    assert flags(e, as_of=at(0, 17))["f.is_st"] is None
    assert flags(e, -1)["f.is_st"] is None
    snap = e.conn.execute(
        select(master_snapshots).where(master_snapshots.c.id == run.snapshot_ids[0])
    ).one()
    assert Path(snap.raw_path).is_file()
    assert snap.source == "mairui_list"
    assert "/hslt/list" in snap.url
    assert snap.fetched_at == at()
    row = e.conn.execute(select(securities).where(securities.c.code == CODES[0])).one()
    assert row.field_sources["risk_flag"] == "mairui_list"
    assert row.name != "*ST合成智芯"  # Public master identity/name NOT overwritten.
    assert TASK not in jobs.RETRY_TASKS


def test_fail_closed_worker_without_authorization_or_input(env: Any) -> None:
    e = env
    jobs.beat_slots(e.settings, client=e.redis, now=at())
    assert jobs.worker_tick(e.settings, client=e.redis) == [(TASK, "ok")]
    run = e.conn.execute(
        select(master_runs).where(master_runs.c.stats["task"].astext == TASK)
    ).one()
    assert run.status == "failed"
    assert run.stats["alert"] == "master.snapshot_rejected"
    assert (
        run.stats["sources"]["mairui_list"]["reason"]
        == "daily_list_authorization_or_delivery_required"
    )
    assert flags(e)["f.is_st"] is None
    assert (
        e.conn.execute(
            select(func.count()).select_from(risk).where(risk.c.code.in_(CODES))
        ).scalar_one()
        == 0
    )
    with pytest.raises(PublicSourceGapError, match="official_public_download_not_verified"):
        jobs._master_fetcher()


def test_diff_idempotence_immutable_snapshot_and_no_backfill(env: Any) -> None:
    e = env
    rid = apply(e, delivery())
    assert apply(e, delivery()) == rid
    old = e.conn.execute(
        select(master_snapshots).where(master_snapshots.c.source == "mairui_list")
    ).one()
    apply(e, delivery(offset=1), 1)
    assert (
        e.conn.execute(
            select(func.count()).select_from(risk).where(risk.c.code.in_(CODES))
        ).scalar_one()
        == 4
    )
    assert flags(e)["f.is_st"] is False
    changed = {**NAMES, CODES[0]: "ST合成智芯", CODES[1]: "合成退市示例"}
    apply(e, delivery(changed, 2), 2)
    rows = e.conn.execute(
        select(risk).where(risk.c.code == CODES[0]).order_by(risk.c.valid_from)
    ).all()
    assert [(x.valid_from, x.valid_until, x.risk_flag) for x in rows] == [
        (DAY, DAY + dt.timedelta(days=2), None),
        (DAY + dt.timedelta(days=2), None, "st"),
    ]
    assert flags(e, 2)["f.is_st"] is True
    assert flags(e, 2, CODES[1])["f.is_delisting_period"] is True
    old_again = e.conn.execute(
        select(master_snapshots).where(master_snapshots.c.id == old.id)
    ).one()
    assert old_again.fetched_at == old.fetched_at
    assert old_again.trade_date == old.trade_date
    with pytest.raises(ValueError, match="already_accepted_day"):
        apply(e, delivery(changed))
    assert flags(e, -1)["f.is_st"] is None


@pytest.mark.parametrize(
    "bad", ["empty", "partial", "malformed", "drop", "absent", "late", "future"]
)
def test_failed_day_null_alert_old_interval_survives(env: Any, bad: str) -> None:
    e = env
    apply(e, delivery())
    value: DailyNames | None = delivery(offset=1)
    if bad == "empty":
        value = delivery({}, 1)
    if bad == "partial":
        value = DailyNames(dict(NAMES), at(1), frozenset({"hslt_list"}))
    if bad == "malformed":
        value = delivery({**NAMES, CODES[0]: ""}, 1)
    if bad == "drop":
        value = delivery({CODES[0]: NAMES[CODES[0]]}, 1)
    if bad == "absent":
        value = None
    if bad == "late":
        value = DailyNames(dict(NAMES), at(0), DATASETS)
    if bad == "future":
        value = DailyNames(dict(NAMES), at(1, 19), DATASETS)
    rid = apply(e, value, 1)
    run = e.conn.execute(select(master_runs).where(master_runs.c.id == rid)).one()
    assert run.status == "failed"
    assert run.stats["alert"]
    assert flags(e, 1)["f.is_st"] is None
    from app.master.alerts import master_alerts

    assert "master.snapshot_rejected" in {x["key"] for x in master_alerts(e.conn, e.cfg)}
    assert latest_visible_flags(e.conn, CODES[0], as_of=at(2, 9))["f.is_st"] is None
    assert all(
        row.valid_until is None
        for row in e.conn.execute(select(risk).where(risk.c.code.in_(CODES)))
    )
    apply(e, delivery(offset=2), 2)
    assert flags(e, 2)["f.is_st"] is False
    assert flags(e, 1)["f.is_st"] is None


def test_missing_membership_does_not_delist_and_delisted_never_revived(env: Any) -> None:
    e = env
    before = e.conn.execute(select(func.count()).select_from(securities)).scalar_one()
    apply(e, delivery())
    # One omission is below configured rejection threshold; preserve master, but null this code.
    value = {k: v for k, v in NAMES.items() if k != CODES[3]}
    cfg = e.cfg.model_copy(update={"reject_drop_pct": 90.0})
    apply_delivery(e.conn, delivery(value, 1), now=at(1), cfg=cfg, root=e.root)
    assert flags(e, 1, CODES[3])["f.is_st"] is None
    assert (
        e.conn.execute(
            select(securities.c.listing_status).where(securities.c.code == CODES[3])
        ).scalar_one()
        == "listed"
    )
    e.conn.execute(
        update(securities).where(securities.c.code == CODES[2]).values(listing_status="delisted")
    )
    e.conn.execute(
        update(securities)
        .where(securities.c.code == CODES[3])
        .values(listing_status="missing_from_list")
    )
    apply(e, delivery(offset=2), 2)
    assert flags(e, 2, CODES[2])["f.is_st"] is None
    assert flags(e, 2, CODES[3])["f.is_delisting_period"] is None
    assert (
        e.conn.execute(
            select(securities.c.listing_status).where(securities.c.code == CODES[2])
        ).scalar_one()
        == "delisted"
    )
    assert e.conn.execute(select(func.count()).select_from(securities)).scalar_one() == before


def test_source_cutover_opens_equal_value_interval_without_rewrite(env: Any) -> None:
    e = env
    sid = e.conn.execute(
        insert(master_snapshots)
        .values(
            source="sse_list",
            url="synthetic:official",
            fetched_at=at(-1),
            trade_date=DAY - dt.timedelta(days=1),
            row_count=4,
            sha256=uuid.uuid4().hex * 2,
            parse_status="ok",
        )
        .returning(master_snapshots.c.id)
    ).scalar_one()
    for table, key, val in [(risk, "risk_flag", None), (listing, "listing_status", "listed")]:
        args = {"reason": "exchange_list"} if table is listing else {}
        e.conn.execute(
            insert(table).values(
                code=CODES[0],
                valid_from=DAY - dt.timedelta(days=1),
                snapshot_id=sid,
                **{key: val},
                **args,
            )
        )
    apply(e, delivery())
    rows = e.conn.execute(
        select(risk).where(risk.c.code == CODES[0]).order_by(risk.c.valid_from)
    ).all()
    assert len(rows) == 2
    assert rows[0].snapshot_id == sid
    assert rows[0].valid_until == DAY
    assert rows[1].valid_from == DAY
    assert flags(e)["f.is_st"] is False
    assert flags(e, -1)["f.is_st"] is None


def test_same_day_history_conflict_rolls_back_all_fields(env: Any) -> None:
    e = env
    sid = e.conn.execute(
        insert(master_snapshots)
        .values(
            source="sse_list",
            url="synthetic:official",
            fetched_at=at(),
            trade_date=DAY,
            row_count=4,
            sha256=uuid.uuid4().hex * 2,
            parse_status="ok",
        )
        .returning(master_snapshots.c.id)
    ).scalar_one()
    e.conn.execute(
        insert(risk).values(code=CODES[1], valid_from=DAY, snapshot_id=sid, risk_flag=None)
    )
    rid = apply(e, delivery({**NAMES, CODES[0]: "ST合成示例"}))
    run = e.conn.execute(select(master_runs).where(master_runs.c.id == rid)).one()
    assert run.status == "failed"
    assert run.stats["sources"]["mairui_list"]["reason"] == "history_conflict"
    assert (
        e.conn.execute(
            select(securities.c.risk_flag).where(securities.c.code == CODES[0])
        ).scalar_one()
        is None
    )
    assert (
        e.conn.execute(
            select(func.count()).select_from(risk).where(risk.c.code.in_(CODES))
        ).scalar_one()
        == 1
    )


def test_calendar_slot_and_no_legacy_official_retry(env: Any) -> None:
    e = env
    assert jobs.slot_jobs(e.settings, at(0, 7, 30)) == []
    assert jobs.slot_jobs(e.settings, at(0, 17, 59)) == []
    assert jobs.slot_jobs(e.settings, at().astimezone(dt.UTC))[0][0] == TASK
    e.conn.execute(
        update(trading_calendar).where(trading_calendar.c.date == DAY).values(is_open=False)
    )
    assert jobs.slot_jobs(e.settings, at()) == []
    with pytest.raises(ValueError, match="not_trading_day"):
        apply(e, delivery())
    e.conn.execute(delete(trading_calendar).where(trading_calendar.c.date == DAY))
    from app.common.errors import AppError

    with pytest.raises(AppError):
        jobs.slot_jobs(e.settings, at())
    with pytest.raises(ValueError, match="CALENDAR_NOT_COVERED"):
        apply(e, delivery())


def test_additive_check_migration_rejects_unknown_source(env: Any) -> None:
    e = env
    with pytest.raises(IntegrityError), e.conn.begin_nested():
        e.conn.execute(
            insert(master_snapshots).values(
                source="unknown",
                url="synthetic",
                fetched_at=at(),
                trade_date=DAY,
                row_count=1,
                sha256="1" * 64,
                parse_status="ok",
            )
        )
    # Test reversible constraints before new-source rows exist. No version stamp,
    # no existing migration edit, and no real/shared database connection.
    with Operations.context(MigrationContext.configure(e.conn)):
        e.migration.downgrade()
        e.migration.upgrade()
    apply(e, delivery())
    with (
        pytest.raises(IntegrityError),
        e.conn.begin_nested(),
        Operations.context(MigrationContext.configure(e.conn)),
    ):
        e.migration.downgrade()
    assert flags(e)["f.is_st"] is False


def test_old_day_not_backfilled_and_diff_is_traceable(env: Any) -> None:
    e = env
    apply(e, delivery(offset=1), 1)
    rejected = apply(e, delivery(), 0)
    run = e.conn.execute(select(master_runs).where(master_runs.c.id == rejected)).one()
    assert run.status == "failed"
    assert run.stats["sources"]["mairui_list"]["reason"] == "out_of_order_delivery"
    assert flags(e, 0)["f.is_st"] is None
    assert {r.valid_from for r in e.conn.execute(select(risk).where(risk.c.code.in_(CODES)))} == {
        DAY + dt.timedelta(days=1)
    }
    rid = apply(e, delivery({**NAMES, CODES[0]: "ST合成智芯"}, 2), 2)
    changed = e.conn.execute(
        select(master_runs.c.stats).where(master_runs.c.id == rid)
    ).scalar_one()
    assert changed["changed_count"] == 1
    assert changed["changes"] == [
        {
            "code": CODES[0],
            "before": {"risk_flag": None, "listing_status": "listed"},
            "after": {"risk_flag": "st", "listing_status": "listed"},
        }
    ]


def test_known_calendar_hole_and_expired_slot_fail_closed(env: Any) -> None:
    e = env
    apply(e, delivery())
    # An uncovered intermediate day is NOT silently assumed to be a holiday.
    e.conn.execute(
        delete(trading_calendar).where(trading_calendar.c.date == DAY + dt.timedelta(days=1))
    )
    assert latest_visible_flags(e.conn, CODES[0], as_of=at(2, 9))["f.is_st"] is None
    assert latest_visible_flags(e.conn, CODES[0], as_of=at(10, 9))["f.is_st"] is None
    with pytest.raises(ValueError, match="snapshot_slot_expired"):
        jobs.mairui_snapshot_task(e.settings, str(DAY - dt.timedelta(days=1)))
    with pytest.raises(ValueError, match="before_beijing_1800"):
        apply_delivery(e.conn, delivery(), now=at(0, 17), cfg=e.cfg, root=e.root)
    with pytest.raises(ValueError, match="timezone_required"):
        read_flags(e.conn, CODES[0], DAY, as_of=at().replace(tzinfo=None))


def test_no_known_eligible_rows_cannot_create_or_revive_master(env: Any) -> None:
    e = env
    before = e.conn.execute(select(func.count()).select_from(securities)).scalar_one()
    e.conn.execute(
        update(securities).where(securities.c.code.in_(CODES)).values(listing_status="delisted")
    )
    rid = apply(e, delivery())
    run = e.conn.execute(select(master_runs).where(master_runs.c.id == rid)).one()
    assert run.status == "failed"
    assert run.stats["sources"]["mairui_list"]["reason"] == "no_known_active_securities"
    assert e.conn.execute(select(func.count()).select_from(securities)).scalar_one() == before
    assert (
        e.conn.execute(
            select(func.count()).select_from(risk).where(risk.c.code.in_(CODES))
        ).scalar_one()
        == 0
    )
    assert flags(e)["f.is_st"] is None


@pytest.mark.parametrize("allow_missing", [False, True])
def test_key_missing_uses_existing_threshold_without_inventing_flag(
    env: Any, allow_missing: bool
) -> None:
    e = env
    apply(e, delivery())
    cfg = e.cfg.model_copy(
        update={"reject_key_missing_pct": 30 if allow_missing else 1, "reject_drop_pct": 90}
    )
    rid = apply_delivery(
        e.conn, delivery({**NAMES, CODES[3]: ""}, 1), now=at(1), cfg=cfg, root=e.root
    )
    run = e.conn.execute(select(master_runs).where(master_runs.c.id == rid)).one()
    assert run.status == ("ok" if allow_missing else "failed")
    assert flags(e, 1, CODES[3])["f.is_st"] is None
    snap = e.conn.execute(
        select(master_snapshots).where(master_snapshots.c.id == run.snapshot_ids[0])
    ).one()
    assert snap.reject_reason == (None if allow_missing else "key_missing")
