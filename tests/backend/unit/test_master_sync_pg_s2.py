"""Exercise master synchronization against real PostgreSQL in one disposable owned database."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from app.config_files import SecuritiesMaster
from app.db.tables import market as m
from app.master import sync
from app.master.sources import CodeMapRow, Part, RenameRow
from psycopg import sql
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import make_url

DAY = dt.date(2024, 1, 8)
NOW = dt.datetime(2024, 1, 8, 12, tzinfo=dt.UTC)
CFG = SecuritiesMaster(
    fetch_times=("18:00", "07:30"),
    reject_drop_pct=50,
    reject_key_missing_pct=0,
    missing_after_snapshots=2,
    vendor_stale_alert_days=3,
    field_mismatch_alert_rows=10,
    crosscheck_weekday=5,
)
TABLES = (
    m.securities,
    m.master_snapshots,
    m.master_runs,
    m.security_name_history,
    m.security_code_history,
    m.security_risk_flag_history,
    m.security_listing_status_history,
)


@pytest.fixture(scope="module")
def owned_engine(pg_url):
    """The standard test PG supplies a server; create/drop only this UUID-named database."""
    base = make_url(pg_url)
    if base.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("master sync tests require the local standard test PG endpoint")
    name = "s2sync_" + uuid4().hex
    admin_url = base.set(drivername="postgresql").render_as_string(hide_password=False)
    target_url = base.set(drivername="postgresql+psycopg", database=name)
    engine = None
    created = False
    try:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            created = True
        engine = create_engine(target_url)
        with engine.begin() as conn:
            assert conn.scalar(text("SELECT current_database()")) == name
            conn.execute(text("CREATE EXTENSION btree_gist"))
            conn.execute(text("CREATE SCHEMA market"))
            for table in TABLES:
                table.create(conn)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            assert name.startswith("s2sync_") and len(name) == 39
            with psycopg.connect(admin_url, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
                assert (
                    admin.execute(
                        "SELECT count(*) FROM pg_database WHERE datname = %s", (name,)
                    ).fetchone()[0]
                    == 0
                )


@pytest.fixture
def conn(owned_engine):
    with owned_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


def fetched(names, *, source="sse_list", dates=True):
    rows = [
        {
            "STOCK_TYPE": "1",
            "A_STOCK_CODE": code,
            "SEC_NAME_CN": name,
            "LIST_DATE": "20200102" if dates else "",
        }
        for code, name in names
    ]
    return sync.Fetched(
        source,
        [
            Part(
                "https://example.invalid/synthetic",
                json.dumps({"result": rows}).encode(),
            )
        ],
    )


def run(conn, tmp_path, items, *, day=DAY, trigger="manual"):
    return sync.apply_run(
        conn,
        items,
        CFG,
        trigger=trigger,
        trade_date=day,
        now=dt.datetime.combine(day, dt.time(12), dt.UTC),
        raw_root=tmp_path,
    )


def security(conn, code="600101.SH"):
    return conn.execute(select(m.securities).where(m.securities.c.code == code)).one()


def seed(conn, code, *, name="合成证券", exchange="SH", **values):
    conn.execute(
        insert(m.securities).values(
            code=code,
            type="stock",
            name=name,
            exchange=exchange,
            listing_status="listed",
            **values,
        )
    )


def test_apply_consumes_bytes_and_persists_snapshot_history_and_real_audit_file(
    conn, tmp_path
):
    result = run(
        conn, tmp_path, [fetched([("600101", "合成证券")])], trigger="bootstrap"
    )
    assert result.status == "ok"
    assert result.stats["added"] == 1
    row = security(conn)
    assert (row.name, row.listing_status, row.list_date_basis, row.last_seen_on) == (
        "合成证券",
        "listed",
        "listing",
        DAY,
    )
    snap = conn.execute(select(m.master_snapshots)).one()
    raw = (tmp_path / snap.raw_path).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == snap.sha256
    assert json.loads(raw)["format"] == "aia-master-raw/1"
    assert (snap.parse_status, snap.row_count) == ("ok", 1)
    period = conn.execute(select(m.security_name_history)).one()
    assert (period.name, period.valid_from, period.valid_until, period.snapshot_id) == (
        row.name,
        DAY,
        None,
        snap.id,
    )
    recorded = conn.execute(select(m.master_runs)).one()
    assert recorded.snapshot_ids == [snap.id]
    assert recorded.stats == result.stats
    assert (
        conn.scalar(select(text("count(*)")).select_from(m.security_risk_flag_history))
        == 0
    )


def test_snapshot_dedup_same_day_update_and_next_day_half_open_period(conn, tmp_path):
    first = run(conn, tmp_path, [fetched([("600101", "合成初名")])])
    again = run(conn, tmp_path, [fetched([("600101", "合成初名")])])
    assert again.snaps["sse_list"].snapshot_id == first.snaps["sse_list"].snapshot_id
    assert again.snaps["sse_list"].is_new is False
    changed = run(conn, tmp_path, [fetched([("600101", "ST合成")])])
    assert changed.stats["renamed"] == 1
    assert conn.execute(select(m.security_name_history.c.name)).scalars().all() == [
        "ST合成"
    ]
    assert security(conn).risk_flag == "st"
    later = run(
        conn,
        tmp_path,
        [fetched([("600101", "合成新名")])],
        day=DAY + dt.timedelta(days=1),
    )
    assert later.stats["risk_changed"] == 1
    periods = conn.execute(
        select(m.security_name_history).order_by(m.security_name_history.c.valid_from)
    ).all()
    assert [(r.name, r.valid_from, r.valid_until) for r in periods] == [
        ("ST合成", DAY, DAY + dt.timedelta(days=1)),
        ("合成新名", DAY + dt.timedelta(days=1), None),
    ]
    flags = conn.execute(
        select(m.security_risk_flag_history).order_by(
            m.security_risk_flag_history.c.valid_from
        )
    ).all()
    assert [(r.risk_flag, r.valid_until) for r in flags] == [
        ("st", DAY + dt.timedelta(days=1)),
        (None, None),
    ]


@pytest.mark.parametrize(
    "case,reason",
    [
        ("empty", "empty"),
        ("missing", "key_missing"),
        ("parse", "parse_error"),
        ("drop", "drop_pct"),
    ],
)
def test_rejected_snapshot_preserves_prior_security_and_records_reason(
    conn, tmp_path, case, reason
):
    names = [(f"60010{i}", f"合成{i}") for i in range(4)]
    run(conn, tmp_path, [fetched(names)])
    if case == "empty":
        bad = fetched([])
    elif case == "missing":
        bad = fetched(names, dates=False)
    elif case == "parse":
        bad = sync.Fetched(
            "sse_list", [Part("https://example.invalid/synthetic", b"not-json")]
        )
    else:
        bad = fetched(names[:1])
    result = run(conn, tmp_path, [bad], day=DAY + dt.timedelta(days=1))
    assert result.status == "failed"
    assert result.snaps["sse_list"].reason == reason
    assert result.snaps["sse_list"].rows == ()
    assert conn.execute(
        select(m.securities.c.name).order_by(m.securities.c.code)
    ).scalars().all() == [f"合成{i}" for i in range(4)]
    assert all(r.last_seen_on == DAY for r in conn.execute(select(m.securities)))
    assert result.stats["rejected"] == ["sse_list"]


def test_failed_fetch_and_partial_run_only_apply_successful_source(
    conn, tmp_path, caplog
):
    def fetch(source):
        if source == "szse_list":
            raise RuntimeError("SYNTHETIC_BODY_MUST_NOT_APPEAR")
        return fetched([("600101", "合成证券")]).parts

    with caplog.at_level("WARNING", logger="app.master.sync"):
        collected = sync.collect(fetch, ["sse_list", "szse_list"])
    assert collected[1].error == "RuntimeError"
    assert "SYNTHETIC_BODY_MUST_NOT_APPEAR" not in caplog.text
    assert "RuntimeError" in caplog.text
    result = run(conn, tmp_path, collected)
    assert result.status == "partial"
    assert result.snaps["szse_list"].snapshot_id is None
    assert result.snaps["szse_list"].reason == "RuntimeError"
    assert security(conn).name == "合成证券"
    assert set(sync.sources_to_retry(conn, DAY)) == set(sync.DAILY_SOURCES) - {
        "sse_list"
    }


def test_missing_counts_distinct_success_days_then_reappears(conn, tmp_path):
    names = [("600101", "合成一"), ("600102", "合成二")]
    run(conn, tmp_path, [fetched(names)])
    day2 = DAY + dt.timedelta(days=1)
    pending = run(conn, tmp_path, [fetched(names[:1])], day=day2)
    assert pending.stats["missing_pending"] == 1
    assert security(conn, "600102.SH").listing_status == "listed"
    repeated = run(conn, tmp_path, [fetched(names[:1])], day=day2)
    assert repeated.stats["missing_set"] == 0
    missing = run(conn, tmp_path, [fetched(names[:1])], day=DAY + dt.timedelta(days=2))
    assert missing.stats["missing_set"] == 1
    assert security(conn, "600102.SH").listing_status == "missing_from_list"
    restored = run(conn, tmp_path, [fetched(names)], day=DAY + dt.timedelta(days=3))
    assert restored.stats["status_changed"] == 1
    assert security(conn, "600102.SH").missing_since is None


def test_cross_exchange_duplicate_does_not_create_either_security(conn, tmp_path):
    sh = fetched([("600101", "合成沪")])
    bj = sync.Fetched(
        "bse_list",
        [
            Part(
                "https://example.invalid/synthetic",
                b'callback([{"content":[{"xxzqdm":"600101","xxzqjc":"synthetic","fxssrq":"20200102"}]}])',
            )
        ],
    )
    result = run(conn, tmp_path, [sh, bj])
    assert result.stats["exchange_conflicts"] == ["600101"]
    assert conn.execute(select(m.securities)).all() == []


def test_bse_pre_open_listing_basis_and_prefix_warning_do_not_override_board(
    conn, tmp_path
):
    doc = [
        {"content": [{"xxzqdm": "830101", "xxzqjc": "合成北", "fxssrq": "20200102"}]}
    ]
    result = run(
        conn,
        tmp_path,
        [
            sync.Fetched(
                "bse_list",
                [
                    Part(
                        "https://example.invalid/synthetic",
                        ("callback(" + json.dumps(doc) + ")").encode(),
                    )
                ],
            ),
            fetched([("000101", "合成前缀")]),
        ],
    )
    assert security(conn, "830101.BJ").list_date_basis == "neeq_select"
    assert security(conn, "000101.SH").board == "main"
    assert result.stats["prefix_mismatch"] == ["000101.SH"]


def test_delist_current_list_wins_and_future_date_does_not_apply(conn, tmp_path):
    seed(conn, "600102.SH")
    rows = [
        {"A_STOCK_CODE": code, "COMPANY_ABBR": "合成退", "DELIST_DATE": date}
        for code, date in [
            ("600101", "2024-01-05"),
            ("600102", "2024-01-09"),
            ("689101", "2024-01-05"),
        ]
    ]
    item = sync.Fetched(
        "sse_delist",
        [
            Part(
                "https://example.invalid/synthetic",
                json.dumps({"result": rows}).encode(),
            )
        ],
    )
    result = run(conn, tmp_path, [fetched([("600101", "合成在市")]), item])
    assert security(conn).listing_status == "listed"
    assert security(conn, "600102.SH").listing_status == "listed"
    assert security(conn, "689101.SH").type == "cdr"
    assert security(conn, "689101.SH").listing_status == "delisted"
    assert result.stats["delisted"] == 1
    second = run(conn, tmp_path, [item], day=DAY + dt.timedelta(days=1))
    assert second.stats["delisted"] == 2
    assert security(conn, "600102.SH").delist_date == DAY + dt.timedelta(days=1)


def test_set_period_unchanged_future_guard_and_skip_initial_null(conn):
    seed(conn, "600101.SH")
    table = m.security_risk_flag_history
    assert (
        sync.set_period(
            conn, table, "600101.SH", DAY, "risk_flag", None, skip_initial_null=True
        )
        is False
    )
    assert sync.set_period(conn, table, "600101.SH", DAY, "risk_flag", "st") is True
    assert sync.set_period(conn, table, "600101.SH", DAY, "risk_flag", "st") is False
    assert (
        sync.set_period(
            conn, table, "600101.SH", DAY - dt.timedelta(days=1), "risk_flag", "star_st"
        )
        is False
    )
    assert conn.execute(select(table.c.risk_flag)).scalar_one() == "st"


def test_rename_history_rebuild_consumes_order_duplicates_and_current_name(conn):
    seed(
        conn, "000101.SZ", name="合成现名", exchange="SZ", list_date=dt.date(2020, 1, 2)
    )
    seed(conn, "000102.SZ", name="合成无警示", exchange="SZ")
    rows = (
        RenameRow(dt.date(2021, 1, 4), "000101", "合成初名", "ST合成"),
        RenameRow(dt.date(2022, 1, 4), "000101", "ST合成", "*ST合成"),
        RenameRow(dt.date(2022, 1, 4), "000101", "*ST合成", "合成末名"),
        RenameRow(dt.date(2022, 1, 4), "000102", "", "合成无警示"),
        RenameRow(dt.date(2022, 1, 4), "000103", "", "未知证券"),
        RenameRow(None, "000101", "", "忽略无日期"),
    )
    stats = sync.Stats()
    sync.rebuild_szse_names(
        conn, sync.Snap("szse_rename", "ok", rows=rows), trade_date=DAY, stats=stats
    )
    history = conn.execute(
        select(m.security_name_history)
        .where(m.security_name_history.c.code == "000101.SZ")
        .order_by(m.security_name_history.c.valid_from)
    ).all()
    assert [r.name for r in history] == ["合成初名", "ST合成", "合成末名", "合成现名"]
    assert [r.valid_until for r in history] == [
        dt.date(2021, 1, 4),
        dt.date(2022, 1, 4),
        DAY,
        None,
    ]
    flags = conn.execute(
        select(m.security_risk_flag_history)
        .where(m.security_risk_flag_history.c.code == "000101.SZ")
        .order_by(m.security_risk_flag_history.c.valid_from)
    ).all()
    assert [r.risk_flag for r in flags] == ["st", None]
    assert stats.name_history_rebuilt == 2


def test_code_map_replay_replace_and_skip_unknown_or_equal(conn):
    seed(conn, "920101.BJ", exchange="BJ")
    seed(conn, "920102.BJ", exchange="BJ")
    rows = (
        CodeMapRow("合成", None, "830101", "920101"),
        CodeMapRow("未知", None, "830102", "920103"),
        CodeMapRow("相同", None, "920101", "920101"),
    )
    stats = sync.Stats()
    snap = sync.Snap("bse_code_map", "ok", rows=rows)
    sync.merge_code_map(conn, snap, trade_date=DAY, stats=stats)
    sync.merge_code_map(conn, snap, trade_date=DAY, stats=stats)
    assert stats.code_map_rows == 1 and stats.code_map_skipped == 4
    replacement = sync.Snap(
        "bse_code_map", "ok", rows=(CodeMapRow("合成", DAY, "830101", "920102"),)
    )
    sync.merge_code_map(conn, replacement, trade_date=DAY, stats=stats)
    saved = conn.execute(select(m.security_code_history)).one()
    assert (saved.old_code, saved.code, saved.valid_from) == (
        "830101.BJ",
        "920102.BJ",
        DAY,
    )
    assert stats.code_map_rows == 2


def test_purge_only_owned_old_raw_and_orphans_preserves_escape_and_recent(
    conn, tmp_path
):
    result = run(conn, tmp_path, [fetched([("600101", "合成证券")])])
    snap = result.snaps["sse_list"]
    old = conn.execute(select(m.master_snapshots.c.raw_path)).scalar_one()
    outside = tmp_path.parent / ("outside-" + uuid4().hex + ".json")
    outside.write_text("synthetic outside", encoding="utf-8")
    try:
        conn.execute(
            insert(m.master_snapshots).values(
                source="sse_list",
                url="https://example.invalid/synthetic",
                sha256="f" * 64,
                fetched_at=NOW,
                trade_date=DAY,
                parse_status="rejected",
                reject_reason="parse_error",
                raw_path="../" + outside.name,
            )
        )
        orphan = tmp_path / "sse_list" / "orphan.json"
        orphan.write_text("synthetic orphan", encoding="utf-8")
        os.utime(orphan, (NOW.timestamp(), NOW.timestamp()))
        recent = tmp_path / "sse_list" / "recent.json"
        recent.write_text("synthetic recent", encoding="utf-8")
        end = NOW + dt.timedelta(days=100)
        os.utime(recent, (end.timestamp(), end.timestamp()))
        assert sync.purge_snapshots(conn, tmp_path, now=end) == 2
        assert not (tmp_path / old).exists() and not orphan.exists()
        assert outside.exists() and recent.exists()
        assert (
            conn.scalar(
                select(m.master_snapshots.c.raw_path).where(
                    m.master_snapshots.c.id == snap.snapshot_id
                )
            )
            is None
        )
    finally:
        outside.unlink(missing_ok=True)


def test_failed_run_error_length_empty_run_and_missing_root(conn, tmp_path):
    ident = sync.record_failed_run(conn, "manual", DAY, "X" * 100)
    recorded = conn.execute(
        select(m.master_runs).where(m.master_runs.c.id == ident)
    ).one()
    assert recorded.status == "failed" and recorded.stats["error"] == "X" * 64
    assert run(conn, tmp_path, []).status == "ok"
    with pytest.raises(sync.MasterRootMissingError, match="根目录不存在"):
        sync.purge_snapshots(conn, tmp_path / "missing")


@pytest.mark.parametrize(
    "stamp,expected",
    [
        ("2024-01-08T09:59:59+00:00", "2024-01-05"),
        ("2024-01-08T10:00:00+00:00", "2024-01-08"),
        ("2024-01-07T12:00:00+00:00", "2024-01-05"),
    ],
)
def test_snapshot_date_beijing_close_and_weekend(stamp, expected):
    assert sync.snapshot_trade_date(
        dt.datetime.fromisoformat(stamp)
    ) == dt.date.fromisoformat(expected)


def test_root_defaults_and_merge_runs():
    assert sync.resolve_master_root("/synthetic", "prod") == Path("/synthetic")
    assert sync.resolve_master_root(None, "prod") is None
    assert sync.resolve_master_root("", "test").name == "aia-master"
    assert sync._merge_runs(
        [(DAY, "a"), (DAY, "b"), (DAY + dt.timedelta(days=1), "b")]
    ) == [(DAY, "b")]
