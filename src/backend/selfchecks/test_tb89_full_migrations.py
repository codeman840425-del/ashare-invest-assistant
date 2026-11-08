"""T-B89: full Alembic environment, not bare Operations.context.

Run only with a deliberately provisioned network=none B89 PostgreSQL whose Unix
socket is /tmp/tb89-pg-socket. Every database is created by this fixture and dropped
in finally; no existing database is migrated. No environment secrets are read.
"""

# ruff: noqa: S101, S108, ANN401
from __future__ import annotations

import datetime as dt
import hashlib
import socket
import uuid
from argparse import Namespace
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from psycopg import sql
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.config_files import SecuritiesMaster
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
from app.master.mairui_snapshot import DATASETS, DailyNames, apply_delivery, read_flags
from app.master.sync import BEIJING

ROOT = Path(__file__).resolve().parents[3]
SOCKET = "/tmp/tb89-pg-socket"
DAY = dt.date(2031, 1, 2)
AT = dt.datetime.combine(DAY, dt.time(18), BEIJING)
CODES = ("688018.SH", "688073.SH", "300364.SZ", "301218.SZ")
NAMES = dict(zip(CODES, ("合成Alpha", "合成Beta", "合成Gamma", "合成Delta"), strict=True))


@pytest.fixture(autouse=True)
def no_ip_network(monkeypatch: pytest.MonkeyPatch) -> None:
    original = socket.socket.connect

    def guarded(sock: socket.socket, address: Any) -> Any:
        if sock.family != socket.AF_UNIX:
            raise AssertionError("B89 permits only dedicated Unix-socket PostgreSQL")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture
def fresh_db() -> Iterator[tuple[str, Config]]:
    assert Path(SOCKET + "/.s.PGSQL.5432").exists(), "explicit isolated B89 PG setup required"
    name = "tb89_" + uuid.uuid4().hex
    with psycopg.connect(dbname="postgres", user="postgres", host=SOCKET, autocommit=True) as admin:
        assert admin.execute("SHOW listen_addresses").fetchone() == ("",)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            config = Config()
            config.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
            config.cmd_opts = Namespace(
                x=["url=postgresql+psycopg://postgres@/" + name + "?host=" + SOCKET]
            )
            yield name, config
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def snapshot(conn: Any, source: str = "sse_list") -> int:
    return int(
        conn.execute(
            insert(master_snapshots)
            .values(
                source=source,
                url="synthetic:tb89",
                fetched_at=AT - dt.timedelta(days=1),
                trade_date=DAY - dt.timedelta(days=1),
                row_count=4,
                sha256=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
                parse_status="ok",
            )
            .returning(master_snapshots.c.id)
        ).scalar_one()
    )


def seed(conn: Any) -> dict[str, Any]:
    sid = snapshot(conn)
    for code, name in NAMES.items():
        conn.execute(
            insert(securities).values(
                code=code,
                type="stock",
                name=name,
                exchange=code[-2:],
                board="star" if code in CODES[:2] else "chinext",
                listing_status="listed",
                field_sources={"name": "exchange"},
            )
        )
        conn.execute(
            insert(risk).values(
                code=code, risk_flag=None, valid_from=DAY - dt.timedelta(days=1), snapshot_id=sid
            )
        )
        conn.execute(
            insert(listing).values(
                code=code,
                listing_status="listed",
                reason="exchange_list",
                valid_from=DAY - dt.timedelta(days=1),
                snapshot_id=sid,
            )
        )
    rid = int(
        conn.execute(
            insert(master_runs)
            .values(trigger="manual", status="ok", snapshot_ids=[sid], stats={"synthetic": "B89"})
            .returning(master_runs.c.id)
        ).scalar_one()
    )
    return {"sid": sid, "rid": rid, "before": preserved(conn, sid, rid)}


def preserved(conn: Any, sid: int, rid: int) -> dict[str, Any]:
    return {
        "securities": [
            tuple(r)
            for r in conn.execute(
                select(securities).where(securities.c.code.in_(CODES)).order_by(securities.c.code)
            )
        ],
        "snapshot": tuple(
            conn.execute(select(master_snapshots).where(master_snapshots.c.id == sid)).one()
        ),
        "run": tuple(conn.execute(select(master_runs).where(master_runs.c.id == rid)).one()),
        "risk": [
            tuple(r)
            for r in conn.execute(select(risk).where(risk.c.code.in_(CODES)).order_by(risk.c.code))
        ],
        "listing": [
            tuple(r)
            for r in conn.execute(
                select(listing).where(listing.c.code.in_(CODES)).order_by(listing.c.code)
            )
        ],
    }


def deploy_grants(conn: Any) -> None:
    # Execute EXISTING deployment ACL SQL unchanged except psql syntax and the
    # three password placeholders -> NULL in this passwordless synthetic cluster.
    # No production credential, deployment edit or extra privilege is supplied.
    grants = (ROOT / "deploy/db/roles/grants.sql").read_text()
    grants = grants.replace("\\set ON_ERROR_STOP on", "")
    for key in ("api_pw", "ingest_pw", "maint_pw"):
        grants = grants.replace(":'" + key + "'", "NULL")
    conn.connection.driver_connection.execute(grants)


def assert_worker(conn: Any, root: Path) -> None:
    assert conn.execute(text("SELECT current_user")).scalar_one() == "aia_api"
    assert conn.execute(text("SELECT session_user")).scalar_one() == "aia_api"
    assert (
        conn.execute(
            text(
                "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls "
                "FROM pg_roles WHERE rolname=current_user"
            )
        ).scalar_one()
        is False
    )
    assert (
        conn.execute(
            text("SELECT has_database_privilege(current_user,current_database(),'CREATE')")
        ).scalar_one()
        is False
    )
    for schema in ("app", "market", "ops"):
        assert (
            conn.execute(
                text("SELECT has_schema_privilege(current_user,:s,'CREATE')"), {"s": schema}
            ).scalar_one()
            is False
        )
    for table in (
        "securities",
        "master_snapshots",
        "master_runs",
        "security_risk_flag_history",
        "security_listing_status_history",
    ):
        for privilege in (
            ("SELECT", "UPDATE") if table == "securities" else ("SELECT", "INSERT", "UPDATE")
        ):
            assert (
                conn.execute(
                    text("SELECT has_table_privilege(current_user,:t,:p)"),
                    {"t": "market." + table, "p": privilege},
                ).scalar_one()
                is True
            )
        assert (
            conn.execute(
                text("SELECT has_table_privilege(current_user,:t,'TRUNCATE')"),
                {"t": "market." + table},
            ).scalar_one()
            is False
        )
    for seq in ("master_snapshots_id_seq", "master_runs_id_seq"):
        assert (
            conn.execute(
                text("SELECT has_sequence_privilege(current_user,:s,'USAGE')"),
                {"s": "market." + seq},
            ).scalar_one()
            is True
        )
    with (
        pytest.raises(ProgrammingError, match="permission denied for schema market"),
        conn.begin_nested(),
    ):
        conn.execute(text("CREATE TABLE market.tb89_forbidden (n integer)"))
    cfg = SecuritiesMaster(
        fetch_times=("18:00", "07:30"),
        reject_drop_pct=30,
        reject_key_missing_pct=1,
        missing_after_snapshots=2,
        vendor_stale_alert_days=5,
        field_mismatch_alert_rows=10,
        crosscheck_weekday=6,
    )
    rid = apply_delivery(
        conn,
        DailyNames({**NAMES, CODES[0]: "ST合成Alpha"}, AT, DATASETS),
        now=AT,
        cfg=cfg,
        root=root,
    )
    run = conn.execute(select(master_runs).where(master_runs.c.id == rid)).one()
    assert run.status == "ok"
    assert read_flags(conn, CODES[0], DAY, as_of=AT + dt.timedelta(days=1))["f.is_st"] is True


@pytest.mark.parametrize("path", ["A_empty_to_head", "B_0019_seed_to_head"])
def test_full_alembic_upgrade_preserves_rows_checks_and_worker(
    fresh_db: Any, tmp_path: Path, path: str
) -> None:
    name, config = fresh_db
    url = "postgresql+psycopg://postgres@/" + name + "?host=" + SOCKET
    engine = create_engine(url)
    try:
        script = ScriptDirectory.from_config(config)
        assert script.get_heads() == ["0023"]
        assert [r.revision for r in script.walk_revisions()][:4] == ["0023", "0022", "0020", "0019"]
        original = None
        if path.startswith("B_"):
            command.upgrade(config, "0019")
            with engine.begin() as conn:
                assert (
                    conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                    == "0019"
                )
                original = seed(conn)
        command.upgrade(config, "head")  # Real env.py metadata/naming + all ancestors.
        with engine.begin() as conn:
            assert (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0023"
            )
            if original is not None:
                assert preserved(conn, original["sid"], original["rid"]) == original["before"]
            else:
                assert (
                    conn.execute(text("SELECT count(*) FROM market.master_snapshots")).scalar_one()
                    == 0
                )
                seed(conn)
            constraints = set(
                conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint WHERE conrelid IN "
                        "('market.master_snapshots'::regclass,"
                        "'market.security_listing_status_history'::regclass)"
                    )
                ).scalars()
            )
            assert "ck_master_snapshots_source" in constraints
            assert "ck_security_listing_status_history_reason" in constraints
            assert not any(
                "ck_master_snapshots_ck_" in c or "ck_security_listing_status_history_ck_" in c
                for c in constraints
            )
            for source in (
                "sse_list",
                "sse_delist",
                "szse_list",
                "szse_delist",
                "szse_rename",
                "bse_list",
                "bse_delist",
                "bse_code_map",
                "cninfo",
                "akshare",
                "mairui_list",
            ):
                snapshot(conn, source)
            for source in ("unknown_source", ""):
                with pytest.raises(IntegrityError) as rejected, conn.begin_nested():
                    snapshot(conn, source)
                assert (
                    getattr(getattr(rejected.value.orig, "diag", None), "constraint_name", None)
                    == "ck_master_snapshots_source"
                )
            with pytest.raises(IntegrityError) as rejected_reason, conn.begin_nested():
                conn.execute(
                    insert(listing).values(
                        code=CODES[0],
                        listing_status="listed",
                        reason="unknown_reason",
                        valid_from=DAY - dt.timedelta(days=2),
                        valid_until=DAY - dt.timedelta(days=1),
                        snapshot_id=1,
                    )
                )
            assert (
                getattr(getattr(rejected_reason.value.orig, "diag", None), "constraint_name", None)
                == "ck_security_listing_status_history_reason"
            )
            conn.execute(insert(trading_calendar).values(date=DAY, is_open=True))
            deploy_grants(conn)
        worker_engine = create_engine(url.replace("postgres@/", "aia_api@/"))
        try:
            with worker_engine.begin() as worker_conn:
                assert_worker(worker_conn, tmp_path / path)
        finally:
            worker_engine.dispose()
        # Final state must survive a new real DB connection, not just a savepoint.
        with engine.connect() as conn:
            assert (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0023"
            )
            assert (
                conn.execute(
                    select(securities.c.risk_flag).where(securities.c.code == CODES[0])
                ).scalar_one()
                == "st"
            )
    finally:
        engine.dispose()


def test_original_unmarked_name_failure_rolls_whole_upgrade_back_to_0019(
    fresh_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, config = fresh_db
    engine = create_engine("postgresql+psycopg://postgres@/" + name + "?host=" + SOCKET)
    try:
        command.upgrade(config, "0019")
        with engine.begin() as conn:
            saved = seed(conn)
        # Reproduce precisely the old helper's unmarked-name semantics in the
        # real migration environment; do NOT change any migration file/history.
        with monkeypatch.context() as patch:
            patch.setattr(Operations, "f", lambda self, name: name)
            with pytest.raises(
                ProgrammingError, match="ck_master_snapshots_ck_master_snapshots_source"
            ):
                command.upgrade(config, "head")
        with engine.connect() as conn:
            assert (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0019"
            )
            assert preserved(conn, saved["sid"], saved["rid"]) == saved["before"]
            assert (
                conn.execute(
                    text("SELECT to_regclass('market.master_vendor_batches')")
                ).scalar_one()
                is None
            )
        # The fixed command can retry the SAME database without schema repair.
        command.upgrade(config, "head")
        with engine.connect() as conn:
            assert (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0023"
            )
            assert preserved(conn, saved["sid"], saved["rid"]) == saved["before"]
    finally:
        engine.dispose()
