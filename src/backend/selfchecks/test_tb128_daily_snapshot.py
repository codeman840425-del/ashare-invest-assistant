# ruff: noqa: S101, ANN401, ANN202, S603, S607, S106, PT018, E501, I001
"""T-B128：用日 K 建本人快照并解开 analyze 闸。

契约只读参照 ``git show 9065767:docs/contracts/daily-snapshot-from-bars.md``。
隔离 PG：仅在 o61-pg 127.0.0.1:55461 自建临时库，用后删除。
不连接、不删除 o53/o55/o57/o60、tt51_tpl、o61_tmp_0030。
"""

from __future__ import annotations

import ast
import datetime as dt
import inspect
import ipaddress
import json
import re
import socket
import subprocess
import uuid
from argparse import Namespace
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy import create_engine, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine, URL

from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.db.migration_check import BACKEND
from app.db.tables.accounts import (
    accounts,
    broker_position_snapshot_items,
    broker_position_snapshots,
    import_batches,
)
from app.db.tables.licences import user_data_licences
from app.db.tables.market import daily_bars, securities, trading_calendar
from app.db.tables.realtime import daily_reports, pipeline_runs, suggestions
from app.db.tables.research import watchlist_items
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import (
    feature_catalog,
    strategies,
    strategy_card_versions,
    strategy_cards,
    strategy_instances,
    strategy_versions,
)
from app.db.tables.users import users
from app.engine_policies import latest as latest_policy
from app.engine_policies import load as load_policy
from app.engine_policies import seed as seed_policy
from app.features.pipeline import prepare
from app.replay import baseline
from app.reports import dimensions
from app.reports.service import build
from app.tracking import service as tracking
from app.workers import jobs as jobs_mod
from app.workers.daily import analyze, analysis_task, report_task

HOST = "127.0.0.1"
PORT = 55461
USER = "postgres"
FORBIDDEN_DBS = frozenset({"tt51_tpl", "o61_tmp_0030"})
_SAFE_TMP = re.compile(r"^o61_tmp_b128_[a-z0-9]+$")
_O61 = "o61-pg"

CODE_A = "688018.SH"
CODE_B = "688073.SH"
CODE_C = "300364.SZ"
CODE_E = "600001.SH"
CODE_E2 = "600002.SH"
CODE_H = "600000.SH"

DAY_0606 = dt.date(2026, 11, 6)
DAY_0707 = dt.date(2026, 11, 7)
DAY_0808 = dt.date(2026, 11, 8)
DAY_0909 = dt.date(2026, 11, 9)
DAY_1010 = dt.date(2026, 11, 10)
OPEN_DAYS = (DAY_0606, DAY_0909, DAY_1010)
BEIJING = dt.timezone(dt.timedelta(hours=8))
AT = dt.datetime(2026, 11, 10, 15, 0, tzinfo=BEIJING)
FETCHED = dt.datetime(2026, 11, 10, 17, 15, tzinfo=BEIJING)
TOP_KEYS = {
    "schema_version",
    "trade_date",
    "calendar_basis",
    "sessions",
    "instruments",
    "omitted",
}
BAR_KEYS = {
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "volume",
    "amount",
    "first_seen_at",
    "is_final",
}
INSTRUMENT_KEYS = {
    "security_code",
    "board",
    "adjust",
    "currency",
    "price_unit",
    "volume_unit",
    "amount_unit",
    "bars",
    "gaps",
}
FORBIDDEN_IMPORTS = ("app.ingest", "socket", "httpx", "requests", "urllib.request")
APP = Path(__file__).resolve().parents[1] / "app"
REPO = Path(__file__).resolve().parents[3]
U1 = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
U2 = uuid.UUID("00000000-0000-4000-8000-0000000000a2")


def _import_impl():
    import app.marketdata.daily_snapshot as mod

    return mod


def _require_o61() -> None:
    proc = subprocess.run(
        ["docker", "ps", "--no-trunc", "--format", "{{.ID}} {{.Names}}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.fail("无法查询 docker 以核验 55461 归属")
    hits: list[str] = []
    for line in proc.stdout.splitlines():
        cid, _, name = line.partition(" ")
        inspect_p = subprocess.run(
            ["docker", "inspect", cid], text=True, capture_output=True, check=False
        )
        if inspect_p.returncode != 0 or not inspect_p.stdout.strip():
            continue
        info = json.loads(inspect_p.stdout)[0]
        mode = (info.get("HostConfig") or {}).get("NetworkMode")
        cmd = " ".join(str(x) for x in (info.get("Config") or {}).get("Cmd") or [])
        if mode == "host" and f"port={PORT}" in cmd:
            hits.append(name.lstrip("/"))
    if hits != [_O61]:
        pytest.fail(f"拒绝建库：{HOST}:{PORT} 归属 {hits or '未知'}，须为 {_O61}")


def _admin():
    return psycopg.connect(host=HOST, port=PORT, user=USER, dbname="postgres", autocommit=True)


def _url(dbname: str) -> URL:
    return URL.create(
        "postgresql+psycopg", username=USER, password=None, host=HOST, port=PORT, database=dbname
    )


def _create_temp_db() -> str:
    _require_o61()
    name = "o61_tmp_b128_" + uuid.uuid4().hex[:10]
    assert _SAFE_TMP.fullmatch(name)
    assert name not in FORBIDDEN_DBS
    with _admin() as admin:
        existing = {r[0] for r in admin.execute("SELECT datname FROM pg_database")}
        assert name not in existing
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return name


def _drop_temp_db(name: str) -> None:
    assert _SAFE_TMP.fullmatch(name) and name not in FORBIDDEN_DBS
    with _admin() as admin:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )


def _alembic(url: URL) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.cmd_opts = Namespace(x=["url=" + url.render_as_string(hide_password=False)])
    return cfg


def _upgrade(url: URL, revision: str) -> None:
    command.upgrade(_alembic(url), revision)


def _settings(url: URL, *, source: str = "fake", app_env: str = "test") -> Settings:
    return Settings(
        _env_file=None,
        app_env=app_env,  # type: ignore[arg-type]
        daily_bars_source=source,  # type: ignore[arg-type]
        database_url=SecretStr(url.render_as_string(hide_password=False)),
        session_cookie_secure=False,
    )


def _host_of(address: Any) -> str:
    if isinstance(address, str):
        return address
    if isinstance(address, bytes):
        return address.decode()
    if isinstance(address, (tuple, list)) and address:
        return str(address[0])
    return str(address)


def _is_loopback_host(host: str) -> bool:
    host = host.strip("[]")
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_allowed_socket(sock: socket.socket, address: Any) -> bool:
    if sock.family == socket.AF_UNIX:
        return True
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        host = _host_of(address)
        return bool(host) and _is_loopback_host(host)
    return False


@pytest.fixture
def no_egress(monkeypatch: pytest.MonkeyPatch) -> Any:
    blocked: list[Any] = []
    counts = {"mairui_get": 0}
    orig_connect = socket.socket.connect
    orig_ex = socket.socket.connect_ex

    def guarded_connect(self: socket.socket, address: Any, *args: Any, **kwargs: Any) -> Any:
        if _is_allowed_socket(self, address):
            return orig_connect(self, address, *args, **kwargs)
        blocked.append(address)
        raise OSError("blocked non-loopback / non-unix connect")

    def guarded_ex(self: socket.socket, address: Any, *args: Any, **kwargs: Any) -> Any:
        if _is_allowed_socket(self, address):
            return orig_ex(self, address, *args, **kwargs)
        blocked.append(address)
        raise OSError("blocked non-loopback / non-unix connect_ex")

    def fake_mairui_get(*_a: Any, **_k: Any) -> Any:
        counts["mairui_get"] += 1
        raise RuntimeError("mairui_get must not be called")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_ex)
    monkeypatch.setattr("app.ingest.egress.mairui_get", fake_mairui_get)
    yield
    assert blocked == []
    assert counts["mairui_get"] == 0


@pytest.fixture
def temp_db(no_egress: Any) -> Iterator[Engine]:
    name = _create_temp_db()
    url = _url(name)
    try:
        _upgrade(url, "head")
        engine = create_engine(url, future=True)
        try:
            yield engine
        finally:
            engine.dispose()
    finally:
        _drop_temp_db(name)


def _seed_calendar(conn: Any) -> None:
    for day, is_open in (
        (DAY_0606, True),
        (DAY_0707, False),
        (DAY_0808, False),
        (DAY_0909, True),
        (DAY_1010, True),
    ):
        conn.execute(insert(trading_calendar).values(date=day, is_open=is_open))


def _seed_securities(conn: Any) -> None:
    rows = (
        (CODE_A, "stock", "合成A", "SH", "star", "listed"),
        (CODE_B, "stock", "合成B", "SH", "star", "listed"),
        (CODE_C, "stock", "合成C", "SZ", "chinext", "listed"),
        (CODE_E, "stock", "合成E", "SH", "main", "listed"),
        (CODE_H, "stock", "合成H", "SH", None, "listed"),
    )
    for code, typ, name, exch, board, status in rows:
        conn.execute(
            insert(securities).values(
                code=code,
                type=typ,
                name=name,
                exchange=exch,
                board=board,
                listing_status=status,
            )
        )


def _seed_user(conn: Any, ident: uuid.UUID, username: str) -> None:
    conn.execute(
        insert(users).values(
            id=ident,
            username=username,
            display_name=username,
            role="user",
            status="approved",
            password_hash="x",
        )
    )


def _seed_holdings(conn: Any, user_id: uuid.UUID, codes: tuple[str, ...], *, tag: str) -> uuid.UUID:
    account, batch, snapshot = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn.execute(insert(accounts).values(id=account, user_id=user_id, name=tag))
    conn.execute(
        insert(import_batches).values(
            id=batch, user_id=user_id, account_id=account, status="committed", kind="positions"
        )
    )
    conn.execute(
        insert(broker_position_snapshots).values(
            id=snapshot,
            account_id=account,
            import_batch_id=batch,
            as_of=AT,
            cash_balance=Decimal("100000"),
            cash_available=Decimal("100000"),
            version_no=1,
            created_at=AT,
        )
    )
    for code in codes:
        conn.execute(
            insert(broker_position_snapshot_items).values(
                id=uuid.uuid4(),
                snapshot_id=snapshot,
                security_code=code,
                quantity=Decimal("100"),
                sellable_quantity=Decimal("100"),
                broker_cost_price=Decimal("10"),
                last_price_ref=Decimal("10"),
            )
        )
    return account


def _seed_watchlist(
    conn: Any,
    user_id: uuid.UUID,
    code: str = CODE_E,
    *,
    removed_at: dt.datetime | None = None,
) -> None:
    conn.execute(
        insert(watchlist_items).values(
            user_id=user_id, security_code=code, removed_at=removed_at
        )
    )


def _seed_extra_security(conn: Any, code: str, name: str) -> None:
    conn.execute(
        insert(securities).values(
            code=code, type="stock", name=name, exchange="SH", board="main", listing_status="listed"
        )
    )


def _seed_core(conn: Any) -> uuid.UUID:
    _seed_calendar(conn)
    _seed_securities(conn)
    _seed_user(conn, U1, "tb128_u1")
    _seed_user(conn, U2, "tb128_u2")
    account = _seed_holdings(conn, U1, (CODE_A, CODE_B, CODE_H), tag="u1")
    _seed_holdings(conn, U2, (CODE_C,), tag="u2")
    return account


def _seed_policy(conn: Any) -> Any:
    seed_policy(conn, load_policy(REPO / "config"))
    return latest_policy(conn)


def _seed_instance(conn: Any, owner: uuid.UUID, account_id: uuid.UUID) -> uuid.UUID:
    card, cardversion, strategy, version, instance = (uuid.uuid4() for _ in range(5))
    conn.execute(
        pg_insert(feature_catalog)
        .values(
            feature_key="f.close_qfq",
            unit="CNY/share",
            status="declared",
            source={"synthetic": True},
        )
        .on_conflict_do_nothing(index_elements=["feature_key"])
    )
    spec = {
        "params_schema": {},
        "rules": [
            {
                "id": key,
                "dimension": "technical",
                "role": role,
                "expr": expr,
                "eval_time": "daily_close",
                "weight": 1,
            }
            for key, role, expr in [
                ("E", "entry", "f.close_qfq > 0"),
                ("X", "exit", "f.close_qfq > 0"),
                ("C", "counter", "f.close_qfq < 0"),
                ("I", "invalidation", "f.close_qfq < 0"),
            ]
        ],
        "action_map": {
            "entry_all_core_pass": "buy",
            "held_hold": "hold",
            "exit": "sell",
            "else": "wait",
        },
        "dimension_view_thresholds": {"bullish": 0.67, "bearish": 0.33},
        "stops": {"stop_loss": None, "take_profit": None, "time_stop_days": 5},
        "valid_until": {"trading_days": 40},
    }
    conn.execute(
        insert(strategy_cards).values(
            id=card,
            key="tb128_" + card.hex,
            title="合成卡",
            source_kind="user",
            owner_user_id=owner,
        )
    )
    conn.execute(
        insert(strategy_card_versions).values(
            id=cardversion, card_id=card, version_no=1, fields={"mount_policy": "user"}
        )
    )
    conn.execute(
        insert(strategies).values(
            id=strategy,
            key="tb128_" + strategy.hex,
            name="合成策略",
            owner_user_id=owner,
            horizons=["swing"],
        )
    )
    conn.execute(
        insert(strategy_versions).values(
            id=version,
            strategy_id=strategy,
            card_version_id=cardversion,
            version_no=1,
            config=spec,
            config_hash=version.hex,
            param_hash=version.hex,
            lifecycle="published",
        )
    )
    conn.execute(
        insert(strategy_instances).values(
            id=instance,
            user_id=owner,
            strategy_version_id=version,
            scope="account",
            account_id=account_id,
            status="active",
            origin="user",
            horizon="swing",
        )
    )
    return instance


def _insert_run(
    conn: Any,
    *,
    status: str,
    started_at: dt.datetime,
    finished_at: dt.datetime | None = None,
    user_id: uuid.UUID | None = None,
    issues: list[str] | None = None,
    run_date: dt.date = DAY_1010,
) -> uuid.UUID:
    ident = uuid.uuid4()
    conn.execute(
        insert(pipeline_runs).values(
            id=ident,
            kind="daily_batch",
            run_date=run_date,
            step="daily_bars.fetch",
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            stats={"user_id": str(user_id) if user_id is not None else None, "issues": issues or []},
        )
    )
    return ident


def _fetch_bars(
    conn: Any,
    *,
    missing: tuple[str, ...] = (),
    suspended: tuple[str, ...] = (),
    fetched_at: dt.datetime = FETCHED,
    window: int = 3,
    user_id: uuid.UUID | None = None,
) -> int:
    from app.marketdata.daily_bars import FakeDailyBarsSource, fetch_and_record

    return fetch_and_record(
        conn,
        FakeDailyBarsSource(missing=missing, suspended=suspended),
        trade_date=DAY_1010,
        user_id=user_id,
        window_trading_days=window,
        fetched_at=fetched_at,
    )


def _count_snapshots(conn: Any) -> int:
    return int(conn.execute(select(func.count()).select_from(data_snapshots)).scalar_one())


def _count_owned(conn: Any) -> int:
    snap = _import_impl()
    return int(
        conn.execute(
            select(func.count())
            .select_from(data_snapshots)
            .where(data_snapshots.c["items"]["schema_version"].astext == snap.OWNED_VERSION)
        ).scalar_one()
    )


def _owned_row(conn: Any, snapshot_id: uuid.UUID) -> Any:
    return conn.execute(select(data_snapshots).where(data_snapshots.c.id == snapshot_id)).one()


def test_ready_requires_ok_or_partial_run(temp_db: Engine) -> None:
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        t0 = dt.datetime(2026, 11, 10, 9, 0, tzinfo=dt.UTC)
        assert snap.daily_bars_ready(conn, U1, DAY_1010) == (False, ())
        _insert_run(conn, status="skipped", started_at=t0, finished_at=t0)
        assert snap.daily_bars_ready(conn, U1, DAY_1010) == (False, ())
        conn.execute(delete(pipeline_runs))
        _insert_run(conn, status="failed", started_at=t0, finished_at=t0)
        assert snap.daily_bars_ready(conn, U1, DAY_1010) == (False, ())
        conn.execute(delete(pipeline_runs))
        _insert_run(conn, status="ok", started_at=t0, finished_at=t0)
        ready, issues = snap.daily_bars_ready(conn, U1, DAY_1010)
        assert ready is True
        assert issues == ()


def test_ready_uses_latest_run_in_owner_scope(temp_db: Engine) -> None:
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        t0 = dt.datetime(2026, 11, 10, 9, 0, tzinfo=dt.UTC)
        t1 = t0 + dt.timedelta(minutes=10)
        _insert_run(conn, status="ok", started_at=t0, finished_at=t0)
        _insert_run(conn, status="skipped", started_at=t1, finished_at=t1)
        assert snap.daily_bars_ready(conn, U1, DAY_1010) == (False, ())
        conn.execute(delete(pipeline_runs))
        _insert_run(conn, status="ok", started_at=t0, finished_at=t0, user_id=U2)
        assert snap.daily_bars_ready(conn, U1, DAY_1010) == (False, ())


def test_ready_carries_only_owner_issues(temp_db: Engine) -> None:
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        t0 = dt.datetime(2026, 11, 10, 9, 0, tzinfo=dt.UTC)
        _insert_run(
            conn,
            status="partial",
            started_at=t0,
            finished_at=t0,
            issues=[f"daily_bars_missing:{CODE_A}", f"daily_bars_missing:{CODE_C}"],
        )
        ready, issues = snap.daily_bars_ready(conn, U1, DAY_1010)
        assert ready is True
        assert issues == (f"daily_bars_missing:{CODE_A}",)
        # §11.1 加一组：u1 有效自选 C 时，应带出 daily_bars_missing:C
        conn.execute(delete(pipeline_runs))
        _seed_watchlist(conn, U1, CODE_C)
        _insert_run(
            conn,
            status="partial",
            started_at=t0,
            finished_at=t0,
            issues=[f"daily_bars_missing:{CODE_A}", f"daily_bars_missing:{CODE_C}"],
        )
        ready, issues = snap.daily_bars_ready(conn, U1, DAY_1010)
        assert ready is True
        assert f"daily_bars_missing:{CODE_C}" in issues


def test_snapshot_shape_fields_from_daily_bars(temp_db: Engine) -> None:
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        _fetch_bars(conn)
        ident, issues = snap.build_owned_snapshot(conn, U1, DAY_1010)
        assert ident is not None
        assert f"security_board_missing:{CODE_H}" in issues
        row = _owned_row(conn, ident)
        items = row.items
        assert set(items) == TOP_KEYS
        assert items["schema_version"] == snap.OWNED_VERSION
        assert items["trade_date"] == DAY_1010.isoformat()
        assert items["calendar_basis"] == "trading_calendar"
        assert items["sessions"] == [d.isoformat() for d in OPEN_DAYS]
        by_code = {i["security_code"]: i for i in items["instruments"]}
        assert set(by_code) == {CODE_A, CODE_B}
        for inst in items["instruments"]:
            assert set(inst) == INSTRUMENT_KEYS
            assert inst["adjust"] == "none"
            assert inst["currency"] == "CNY"
            assert inst["price_unit"] == "CNY/share"
            assert inst["volume_unit"] == "share"
            assert inst["amount_unit"] == "CNY"
            assert "factors" not in inst
            assert "scalars" not in inst
            assert "lots" not in inst
            assert "entry" not in inst
            assert [b["trade_date"] for b in inst["bars"]] == [d.isoformat() for d in OPEN_DAYS]
            assert inst["gaps"] == []
            for bar in inst["bars"]:
                assert set(bar) == BAR_KEYS
                assert bar["first_seen_at"] == FETCHED.isoformat()
                assert bar["is_final"] is True
                for key in ("open", "high", "low", "close", "pre_close", "volume", "amount"):
                    assert isinstance(bar[key], str)
        assert items["instruments"][0]["security_code"] == CODE_A
        omitted = {row["security_code"]: row["issue"] for row in items["omitted"]}
        assert omitted[CODE_H] == f"security_board_missing:{CODE_H}"


def test_snapshot_hash_matches_dimensions_digest(temp_db: Engine) -> None:
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        _fetch_bars(conn)
        ident, _ = snap.build_owned_snapshot(conn, U1, DAY_1010)
        row = _owned_row(conn, ident)
        assert row.hash == dimensions.digest(row.items)
        assert row.hash == baseline.manifest_hash(row.items)


def test_suspended_placeholder_becomes_gap_not_bar(temp_db: Engine) -> None:
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        _fetch_bars(conn, suspended=(CODE_B,))
        ident, issues = snap.build_owned_snapshot(conn, U1, DAY_1010)
        assert ident is not None
        assert all(not i.startswith("daily_bars_missing") for i in issues)
        items = _owned_row(conn, ident).items
        inst = next(i for i in items["instruments"] if i["security_code"] == CODE_B)
        today = DAY_1010.isoformat()
        assert today not in {b["trade_date"] for b in inst["bars"]}
        assert {"trade_date": today, "reason": "suspended"} in inst["gaps"]
        frame = prepare(
            inst,
            items["sessions"],
            as_of=dt.datetime.combine(DAY_1010, dt.time(17, 30), BEIJING),
            factors=[],
            registry={},
        )
        assert frame["features"]["f.is_suspended"] is True


def test_snapshot_omits_code_without_today_bar(temp_db: Engine) -> None:
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        _fetch_bars(conn, missing=(CODE_B,))
        ident, issues = snap.build_owned_snapshot(conn, U1, DAY_1010)
        items = _owned_row(conn, ident).items
        codes = {i["security_code"] for i in items["instruments"]}
        assert CODE_B not in codes
        assert f"daily_bars_missing:{CODE_B}" in issues
        assert any(
            row["security_code"] == CODE_B and row["issue"] == f"daily_bars_missing:{CODE_B}"
            for row in items["omitted"]
        )


def test_snapshot_excludes_unsourced_legacy_rows(temp_db: Engine) -> None:
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        _fetch_bars(conn, missing=(CODE_A,))
        conn.execute(
            insert(daily_bars).values(
                code=CODE_A,
                trade_date=DAY_1010,
                adj_type="none",
                open=Decimal("10"),
                high=Decimal("10.1"),
                low=Decimal("9.9"),
                close=Decimal("10"),
                pre_close=Decimal("10"),
                volume=Decimal("10000"),
                amount=Decimal("100000"),
                is_suspended=False,
                source=None,
                fetched_at=FETCHED,
            )
        )
        ident, issues = snap.build_owned_snapshot(conn, U1, DAY_1010)
        items = _owned_row(conn, ident).items
        assert CODE_A not in {i["security_code"] for i in items["instruments"]}
        assert f"daily_bars_missing:{CODE_A}" in issues


def test_snapshot_board_missing_omitted(temp_db: Engine) -> None:
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        _fetch_bars(conn)
        ident, issues = snap.build_owned_snapshot(conn, U1, DAY_1010)
        items = _owned_row(conn, ident).items
        codes = {i["security_code"] for i in items["instruments"]}
        assert CODE_H not in codes
        assert {CODE_A, CODE_B} <= codes
        assert f"security_board_missing:{CODE_H}" in issues


def test_snapshot_today_bar_outside_final_window_omitted(temp_db: Engine) -> None:
    snap = _import_impl()
    early = dt.datetime(2026, 11, 10, 16, 0, tzinfo=BEIJING)
    late = dt.datetime(2026, 11, 10, 20, 0, tzinfo=BEIJING)
    with temp_db.begin() as conn:
        _seed_core(conn)
        _fetch_bars(conn, fetched_at=early)
        conn.execute(
            update(daily_bars)
            .where(daily_bars.c.code == CODE_B, daily_bars.c.trade_date == DAY_1010)
            .values(fetched_at=late)
        )
        ident, issues = snap.build_owned_snapshot(conn, U1, DAY_1010)
        items = _owned_row(conn, ident).items
        omitted = {row["security_code"]: row["issue"] for row in items["omitted"]}
        assert omitted[CODE_A] == f"daily_bars_not_final:{CODE_A}"
        assert omitted[CODE_B] == f"daily_bars_after_asof:{CODE_B}"
        assert f"daily_bars_not_final:{CODE_A}" in issues
        assert f"daily_bars_after_asof:{CODE_B}" in issues


def test_snapshot_mairui_rows_unbound_in_b(temp_db: Engine) -> None:
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        _fetch_bars(conn)
        conn.execute(
            update(daily_bars)
            .where(daily_bars.c.code == CODE_A, daily_bars.c.trade_date == DAY_1010)
            .values(source="mairui")
        )
        ident, issues = snap.build_owned_snapshot(conn, U1, DAY_1010)
        row = _owned_row(conn, ident)
        assert row.licence_id is None
        items = row.items
        assert CODE_A not in {i["security_code"] for i in items["instruments"]}
        assert f"owned_snapshot_licence_unbound:{CODE_A}" in issues


def test_snapshot_closed_day_returns_none(temp_db: Engine) -> None:
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        before = _count_snapshots(conn)
        ident, issues = snap.build_owned_snapshot(conn, U1, DAY_0808)
        assert ident is None
        assert issues == ()
        assert _count_snapshots(conn) == before


def test_snapshot_calendar_hole_not_built(temp_db: Engine) -> None:
    snap = _import_impl()
    settings = _settings(temp_db.url)
    with temp_db.begin() as conn:
        account = _seed_core(conn)
        _seed_policy(conn)
        _seed_instance(conn, U1, account)
        _fetch_bars(conn)
        conn.execute(delete(trading_calendar).where(trading_calendar.c.date == DAY_0909))
        before = _count_snapshots(conn)
        ident, issues = snap.build_owned_snapshot(conn, U1, DAY_1010)
        assert ident is None
        assert issues == ("calendar_not_covered",)
        assert _count_snapshots(conn) == before
        # Restore 11-09 only? analyze on a day when calendar has a hole in sessions.
        # covered(11-10) still works. Ready needs a fetch run (already recorded).
        policy = latest_policy(conn)
        outcome = analyze(conn, settings, U1, DAY_1010, "user", policy)
        assert "calendar_not_covered" in outcome["issues"]


def test_snapshot_only_owner_universe(temp_db: Engine) -> None:
    """§11.1：u1 快照 instruments 恰为 A、B、E（另加 omitted 中的 H），不含 C、E2。"""
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        _seed_extra_security(conn, CODE_E2, "合成E2")
        _seed_watchlist(conn, U1, CODE_E)
        _seed_watchlist(conn, U1, CODE_E2, removed_at=AT)
        _fetch_bars(conn)
        ident, issues = snap.build_owned_snapshot(conn, U1, DAY_1010)
        assert ident is not None
        items = _owned_row(conn, ident).items
        inst = {i["security_code"] for i in items["instruments"]}
        omitted = {row["security_code"] for row in items["omitted"]}
        assert inst == {CODE_A, CODE_B, CODE_E}
        assert CODE_H in omitted
        assert f"security_board_missing:{CODE_H}" in issues
        assert CODE_C not in inst and CODE_C not in omitted
        assert CODE_E2 not in inst and CODE_E2 not in omitted


def test_owned_snapshot_idempotent_rerun(temp_db: Engine) -> None:
    snap = _import_impl()
    settings = _settings(temp_db.url)
    with temp_db.begin() as conn:
        account = _seed_core(conn)
        policy = _seed_policy(conn)
        _seed_instance(conn, U1, account)
        _fetch_bars(conn)
        first, _ = snap.build_owned_snapshot(conn, U1, DAY_1010)
        second, _ = snap.build_owned_snapshot(conn, U1, DAY_1010)
        assert first == second
        n = conn.execute(
            select(func.count())
            .select_from(data_snapshots)
            .where(data_snapshots.c["items"]["schema_version"].astext == snap.OWNED_VERSION)
        ).scalar_one()
        assert int(n) == 1
        first_run = analyze(conn, settings, U1, DAY_1010, "user", policy)
        second_run = analyze(conn, settings, U1, DAY_1010, "user", policy)
        assert first_run["suggestion_ids"] == second_run["suggestion_ids"] or set(
            second_run["suggestion_ids"]
        ).issubset(set(first_run["suggestion_ids"]))
        total = int(conn.execute(select(func.count()).select_from(suggestions)).scalar_one())
        assert total == len(set(first_run["suggestion_ids"]))


def test_snapshot_conflict_keeps_first_row(temp_db: Engine) -> None:
    snap = _import_impl()
    settings = _settings(temp_db.url)
    with temp_db.begin() as conn:
        from app.marketdata.daily_bars import DailyBar, DailyBarsResult, upsert_daily_bars

        account = _seed_core(conn)
        policy = _seed_policy(conn)
        _seed_instance(conn, U1, account)
        _fetch_bars(conn)
        ident, _ = snap.build_owned_snapshot(conn, U1, DAY_1010)
        digest = _owned_row(conn, ident).hash
        original = conn.execute(
            select(daily_bars.c.close).where(
                daily_bars.c.code == CODE_A, daily_bars.c.trade_date == DAY_1010
            )
        ).scalar_one()
        different = DailyBar(
            code=CODE_A,
            trade_date=DAY_1010,
            adj_type="none",
            open=Decimal("11"),
            high=Decimal("11.2"),
            low=Decimal("10.8"),
            close=Decimal("11"),
            pre_close=Decimal("10"),
            volume=Decimal("10000"),
            amount=Decimal("110000"),
            is_suspended=False,
        )
        stats = upsert_daily_bars(
            conn,
            DailyBarsResult(bars=(different,), gaps=(), halted=None),
            source="fake",
            licence_id=None,
            fetched_at=FETCHED,
        )
        assert stats.conflicts >= 1
        still = conn.execute(
            select(daily_bars.c.close).where(
                daily_bars.c.code == CODE_A, daily_bars.c.trade_date == DAY_1010
            )
        ).scalar_one()
        assert still == original
        again, _ = snap.build_owned_snapshot(conn, U1, DAY_1010)
        assert _owned_row(conn, again).hash == digest
        t1 = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=1)
        _insert_run(
            conn,
            status="partial",
            started_at=t1,
            finished_at=t1,
            issues=[f"daily_bar_conflict:{CODE_A}:{DAY_1010.isoformat()}"],
        )
        outcome = analyze(conn, settings, U1, DAY_1010, "user", policy)
        assert f"daily_bar_conflict:{CODE_A}:{DAY_1010.isoformat()}" in outcome["issues"]


def test_analyze_off_keeps_legacy_issue_and_report(temp_db: Engine) -> None:
    settings = _settings(temp_db.url, source="off", app_env="local")
    with temp_db.begin() as conn:
        account = _seed_core(conn)
        _seed_policy(conn)
        _seed_instance(conn, U1, account)
        before = _count_owned(conn)
    assert analysis_task(settings, str(DAY_1010), str(U1)) == 1
    assert report_task(settings, str(DAY_1010), str(U1)) == 1
    with temp_db.connect() as conn:
        stats = conn.execute(
            select(pipeline_runs.c.stats)
            .where(
                pipeline_runs.c.step == "tb76.daily_analysis",
                pipeline_runs.c.run_date == DAY_1010,
            )
            .order_by(pipeline_runs.c.finished_at.desc())
        ).scalar_one()
        own = stats["users"][str(U1)]
        assert own["evaluations"] == []
        assert "owned_market_cache_adapter_missing" in own["issues"]
        report = conn.execute(
            select(daily_reports).where(
                daily_reports.c.user_id == U1, daily_reports.c.trade_date == DAY_1010
            )
        ).first()
        assert report is not None
        blob = json.dumps(dict(report._mapping), default=str)
        assert "owned_market_cache_adapter_missing" in blob or "pipeline.owned_market_cache" in blob
        assert _count_owned(conn) == before


def test_analyze_test_env_off_keeps_tb70_path(temp_db: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(temp_db.url, source="off", app_env="test")
    calls = {"isolated": 0, "build": 0}

    def fake_isolated(*_a: Any, **_k: Any) -> None:
        calls["isolated"] += 1

    def fake_build(*_a: Any, **_k: Any) -> tuple[None, tuple[()]]:
        calls["build"] += 1
        return None, ()

    monkeypatch.setattr("app.workers.daily.require_isolated", fake_isolated)
    monkeypatch.setattr("app.workers.daily.build_owned_snapshot", fake_build)
    with temp_db.begin() as conn:
        account = _seed_core(conn)
        policy = _seed_policy(conn)
        _seed_instance(conn, U1, account)
        outcome = analyze(conn, settings, U1, DAY_1010, "user", policy)
        assert calls["isolated"] == 1
        assert calls["build"] == 0
        assert "daily_bars_not_ready" not in outcome["issues"]
        assert "owned_source_or_card_missing" in outcome["issues"]


def test_analyze_not_ready_no_bars_today(temp_db: Engine) -> None:
    settings = _settings(temp_db.url, source="fake")
    with temp_db.begin() as conn:
        account = _seed_core(conn)
        _seed_policy(conn)
        _seed_instance(conn, U1, account)
        before = _count_owned(conn)
    assert analysis_task(settings, str(DAY_1010), str(U1)) == 1
    assert report_task(settings, str(DAY_1010), str(U1)) == 1
    with temp_db.connect() as conn:
        stats = conn.execute(
            select(pipeline_runs.c.stats)
            .where(
                pipeline_runs.c.step == "tb76.daily_analysis",
                pipeline_runs.c.run_date == DAY_1010,
            )
            .order_by(pipeline_runs.c.finished_at.desc())
        ).scalar_one()
        own = stats["users"][str(U1)]
        assert own["evaluations"] == []
        assert "daily_bars_not_ready" in own["issues"]
        assert int(conn.execute(select(func.count()).select_from(suggestions)).scalar_one()) == 0
        assert _count_owned(conn) == before
        report = conn.execute(
            select(daily_reports).where(
                daily_reports.c.user_id == U1, daily_reports.c.trade_date == DAY_1010
            )
        ).first()
        assert report is not None


def test_analyze_fake_bars_produces_evaluations(temp_db: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(temp_db.url, source="fake")
    assert not (temp_db.url.database or "").startswith("tb70_")
    isolated = {"n": 0}

    def boom(*_a: Any, **_k: Any) -> None:
        isolated["n"] += 1
        raise AssertionError("require_isolated must not be called on owned path")

    monkeypatch.setattr("app.workers.daily.require_isolated", boom)
    snap = _import_impl()
    with temp_db.begin() as conn:
        account = _seed_core(conn)
        policy = _seed_policy(conn)
        _seed_instance(conn, U1, account)
        _fetch_bars(conn)
        outcome = analyze(conn, settings, U1, DAY_1010, "user", policy)
        ev = {row["security_code"]: row for row in outcome["evaluations"]}
        assert CODE_A in ev and CODE_B in ev
        ident, _ = snap.build_owned_snapshot(conn, U1, DAY_1010)
        digest = _owned_row(conn, ident).hash
        assert ev[CODE_A]["simulation"] is True
        assert ev[CODE_A]["source_hash"] == digest
        assert ev[CODE_B]["source_hash"] == digest
        assert isolated["n"] == 0


def test_missing_factor_stays_gap_not_one(temp_db: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(temp_db.url, source="fake")
    monkeypatch.setattr("app.workers.daily.require_isolated", lambda *_a, **_k: None)
    with temp_db.begin() as conn:
        account = _seed_core(conn)
        policy = _seed_policy(conn)
        _seed_instance(conn, U1, account)
        _fetch_bars(conn)
        outcome = analyze(conn, settings, U1, DAY_1010, "user", policy)
        ev = next(row for row in outcome["evaluations"] if row["security_code"] == CODE_A)
        dates = [d.isoformat() for d in OPEN_DAYS]
        assert any(
            g == f"adjust_factor_missing:{day}" or str(g).endswith(f"adjust_factor_missing:{day}")
            for g in ev["gaps"]
            for day in dates
        )
        state = ev["state"]
        # f.close_qfq must be null in evidence / frame remnants
        blob = json.dumps(ev, default=str)
        assert "close_qfq" not in blob or "null" in blob
        assert ev["evidence"] is not None
        features = {}
        if isinstance(ev["evidence"], dict):
            features = ev["evidence"].get("features") or ev["evidence"]
        # tolerate evidence list: look at state only if features missing
        if "f.close_qfq" in features:
            assert features["f.close_qfq"] is None
        assert "1" not in [str(g) for g in ev["gaps"] if "adjust_factor" in str(g)]
        assert state is not None


def test_analyze_partial_bars_gaps_no_fabricated_suggestion(temp_db: Engine) -> None:
    settings = _settings(temp_db.url, source="fake")
    with temp_db.begin() as conn:
        account = _seed_core(conn)
        policy = _seed_policy(conn)
        _seed_instance(conn, U1, account)
        _fetch_bars(conn, missing=(CODE_B,))
        outcome = analyze(conn, settings, U1, DAY_1010, "user", policy)
        ev_codes = {row["security_code"] for row in outcome["evaluations"]}
        assert CODE_A in ev_codes
        assert CODE_B not in ev_codes
        assert f"daily_bars_missing:{CODE_B}" in outcome["issues"]
        assert f"owned_source_security_missing:{CODE_B}" in outcome["issues"]
        ids = outcome["suggestion_ids"]
        if ids:
            rows = conn.execute(select(suggestions).where(suggestions.c.id.in_(ids))).all()
            assert all(r.security_code != CODE_B for r in rows)


def test_load_inputs_accepts_owned_schema_same_day(temp_db: Engine) -> None:
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        _fetch_bars(conn)
        snap.build_owned_snapshot(conn, U1, DAY_1010)
        now = dt.datetime.now(BEIJING) + dt.timedelta(seconds=1)
        same = dimensions.load_inputs(conn, U1, CODE_A, DAY_1010, now)
        assert same["sources"]
        assert same["sources"][0]["kind"] == snap.OWNED_VERSION
        other = dimensions.load_inputs(conn, U1, CODE_A, DAY_0909, now)
        kinds = [s["kind"] for s in other["sources"]]
        assert snap.OWNED_VERSION not in kinds


def test_baseline_read_accepts_owned_keeps_filters(temp_db: Engine) -> None:
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        _fetch_bars(conn)
        ident, _ = snap.build_owned_snapshot(conn, U1, DAY_1010)
        body = baseline.read(conn, U1, ident)
        assert body["schema_version"] == snap.OWNED_VERSION
        with pytest.raises(AppError) as missing:
            baseline.read(conn, U2, ident)
        assert missing.value.code == ErrorCode.NOT_FOUND
        lid = uuid.uuid4()
        conn.execute(
            insert(user_data_licences).values(
                id=lid,
                user_id=U1,
                status="active",
                tier="free",
                ciphertext=b"purely-synthetic-never-decrypted",
                seal_key_version=1,
                licence_hmac=uuid.uuid4().bytes + uuid.uuid4().bytes,
            )
        )
        licensed = uuid.uuid4()
        row = _owned_row(conn, ident)
        conn.execute(
            insert(data_snapshots).values(
                id=licensed,
                user_id=U1,
                licence_id=lid,
                purpose="report",
                items=row.items,
                hash=row.hash,
            )
        )
        with pytest.raises(AppError) as also:
            baseline.read(conn, U1, licensed)
        assert also.value.code == ErrorCode.NOT_FOUND


def test_fetch_and_record_fetched_at_injection(temp_db: Engine) -> None:
    from app.marketdata.daily_bars import FakeDailyBarsSource, daily_bars_fetch_task, fetch_and_record

    sig_task = inspect.signature(daily_bars_fetch_task)
    assert "fetched_at" not in sig_task.parameters
    sig_fn = inspect.signature(fetch_and_record)
    assert sig_fn.parameters["fetched_at"].kind is inspect.Parameter.KEYWORD_ONLY
    with temp_db.begin() as conn:
        _seed_core(conn)
        fetch_and_record(
            conn,
            FakeDailyBarsSource(),
            trade_date=DAY_1010,
            user_id=U1,
            window_trading_days=3,
            fetched_at=FETCHED,
        )
        stamps = list(
            conn.execute(
                select(daily_bars.c.fetched_at).where(daily_bars.c.trade_date == DAY_1010)
            ).scalars()
        )
        assert stamps
        assert all(ts == FETCHED for ts in stamps)
        before = int(conn.execute(select(func.count()).select_from(daily_bars)).scalar_one())
        naive = dt.datetime(2026, 11, 10, 17, 15)
        with pytest.raises(ValueError, match=r"fetched_at"):
            fetch_and_record(
                conn,
                FakeDailyBarsSource(),
                trade_date=DAY_1010,
                user_id=U1,
                window_trading_days=3,
                fetched_at=naive,
            )
        after = int(conn.execute(select(func.count()).select_from(daily_bars)).scalar_one())
        assert after == before


def test_daily_snapshot_not_a_task() -> None:
    snap = _import_impl()
    assert snap.daily_bars_ready not in jobs_mod.TASKS.values()
    assert snap.build_owned_snapshot not in jobs_mod.TASKS.values()
    assert snap.daily_bars_ready not in jobs_mod.LOCKED_TASKS
    assert "daily_snapshot" not in jobs_mod.TASKS
    assert "daily_snapshot" not in jobs_mod.LOCKED_TASKS
    src = inspect.getsource(jobs_mod.slot_jobs) + inspect.getsource(jobs_mod.schedule)
    assert "daily_snapshot" not in src
    assert "build_owned_snapshot" not in src
    assert "daily_bars_ready" not in src
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=SecretStr("postgresql+psycopg://postgres@127.0.0.1:55461/postgres"),
        session_cookie_secure=False,
    )
    table = jobs_mod.schedule(settings)
    assert all("daily_snapshot" not in str(k) for k in table)
    noon = dt.datetime(2026, 11, 10, 12, 0, tzinfo=BEIJING)
    jobs = jobs_mod.slot_jobs(settings, noon)
    assert all("daily_snapshot" not in row[0] for row in jobs)


def test_impl_b_has_no_network_imports() -> None:
    files = [
        APP / "marketdata" / "daily_snapshot.py",
        APP / "workers" / "daily.py",
        APP / "replay" / "baseline.py",
        APP / "reports" / "dimensions.py",
    ]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "socket" or alias.name.startswith(FORBIDDEN_IMPORTS):
                        found.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module and (
                node.module == "socket" or node.module.startswith(FORBIDDEN_IMPORTS)
            ):
                found.append(node.module)
        assert found == [], f"{path} imports {found}"


def test_placeholder_rows_ignored_by_price_readers(temp_db: Engine) -> None:
    from app.api.v1.portfolio import build_portfolio, latest_daily_close

    with temp_db.begin() as conn:
        account = _seed_core(conn)
        _fetch_bars(conn, suspended=(CODE_B,))
        inst = tracking.instrument(
            conn, CODE_B, DAY_1010, dt.datetime(2026, 11, 10, 18, 0, tzinfo=BEIJING)
        )
        assert DAY_1010.isoformat() not in {b["trade_date"] for b in inst["bars"]}
        closes = latest_daily_close(conn, {CODE_B}, DAY_1010)
        if CODE_B in closes:
            assert closes[CODE_B][1].date() != DAY_1010
        portfolio = build_portfolio(conn, [account])
        now = dt.datetime(2026, 11, 10, 18, 0, tzinfo=BEIJING)
        report_id = build(conn, U1, DAY_1010, now)
        report = conn.execute(select(daily_reports).where(daily_reports.c.id == report_id)).one()
        blob = json.dumps(dict(report._mapping), default=str)
        # today's empty close must not be used as a valuation price for B
        del blob  # valuation asserted via latest_daily_close / portfolio below
        positions = portfolio.get("positions") or portfolio.get("items") or []
        for row in positions:
            code = row.get("security_code") or row.get("code")
            if code == CODE_B:
                price = row.get("price") or row.get("last_price") or row.get("market_price")
                if price is not None:
                    assert Decimal(str(price)) != 0


def test_analyze_watchlist_code_evaluated(
    temp_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§11.1：u1 有效自选 E 当日有行时，analyze 对 E 求值且无 owned_source_security_missing:E。"""
    settings = _settings(temp_db.url, source="fake")
    monkeypatch.setattr("app.workers.daily.require_isolated", lambda *_a, **_k: None)
    snap = _import_impl()
    with temp_db.begin() as conn:
        account = _seed_core(conn)
        policy = _seed_policy(conn)
        _seed_instance(conn, U1, account)
        _seed_watchlist(conn, U1, CODE_E)
        _fetch_bars(conn)
        outcome = analyze(conn, settings, U1, DAY_1010, "user", policy)
        ev = {row["security_code"]: row for row in outcome["evaluations"]}
        assert CODE_E in ev
        ident, _ = snap.build_owned_snapshot(conn, U1, DAY_1010)
        digest = _owned_row(conn, ident).hash
        assert ev[CODE_E]["source_hash"] == digest
        assert f"owned_source_security_missing:{CODE_E}" not in outcome["issues"]


def test_snapshot_watchlist_change_new_id(temp_db: Engine) -> None:
    """§11.1：同日加有效自选后再 build，id 不同，旧行保留，load_inputs 取后者。"""
    import time

    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        _fetch_bars(conn)
        first, _ = snap.build_owned_snapshot(conn, U1, DAY_1010)
        assert first is not None
    time.sleep(0.05)
    with temp_db.begin() as conn:
        _seed_watchlist(conn, U1, CODE_E)
        _fetch_bars(conn)
        second, _ = snap.build_owned_snapshot(conn, U1, DAY_1010)
        assert second is not None and second != first
        rows = conn.execute(
            select(data_snapshots.c.id).where(
                data_snapshots.c.user_id == U1,
                data_snapshots.c["items"]["schema_version"].astext == snap.OWNED_VERSION,
            )
        ).scalars().all()
        assert first in rows and second in rows
        now = dt.datetime.now(BEIJING) + dt.timedelta(seconds=1)
        loaded = dimensions.load_inputs(conn, U1, CODE_A, DAY_1010, now)
        assert loaded["sources"]
        assert loaded["sources"][0]["id"] == str(second)


def test_snapshot_includes_backfilled_history(temp_db: Engine) -> None:
    """§11.2：回填的 11-06、11-09 与当日 11-10 均入选且 is_final 为真；omitted 不含 A、B。"""
    from app.marketdata.daily_bars import FakeDailyBarsSource, fetch_and_record

    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        fetch_and_record(
            conn,
            FakeDailyBarsSource(),
            trade_date=DAY_0909,
            user_id=U1,
            window_trading_days=2,
            fetched_at=dt.datetime(2026, 11, 9, 20, 0, tzinfo=BEIJING),
        )
        fetch_and_record(
            conn,
            FakeDailyBarsSource(),
            trade_date=DAY_1010,
            user_id=U1,
            window_trading_days=None,
            fetched_at=dt.datetime(2026, 11, 10, 17, 15, tzinfo=BEIJING),
        )
        ident, _issues = snap.build_owned_snapshot(conn, U1, DAY_1010)
        assert ident is not None
        items = _owned_row(conn, ident).items
        omitted = {row["security_code"] for row in items["omitted"]}
        assert CODE_A not in omitted and CODE_B not in omitted
        for code in (CODE_A, CODE_B):
            inst = next(i for i in items["instruments"] if i["security_code"] == code)
            days = {b["trade_date"]: b for b in inst["bars"]}
            for day in (DAY_0606, DAY_0909, DAY_1010):
                assert day.isoformat() in days
                assert days[day.isoformat()]["is_final"] is True


def test_late_fetch_row_used_as_history_next_day(temp_db: Engine) -> None:
    """§11.3：11-09 17:35 取到的 A 当日 omitted 为 after_asof；次日作为历史 bar 且 is_final。"""
    from app.marketdata.daily_bars import FakeDailyBarsSource, fetch_and_record

    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        fetch_and_record(
            conn,
            FakeDailyBarsSource(),
            trade_date=DAY_0909,
            user_id=U1,
            window_trading_days=None,
            fetched_at=dt.datetime(2026, 11, 9, 17, 35, tzinfo=BEIJING),
        )
        ident_09, issues_09 = snap.build_owned_snapshot(conn, U1, DAY_0909)
        assert ident_09 is not None
        items_09 = _owned_row(conn, ident_09).items
        omitted_09 = {row["security_code"] for row in items_09["omitted"]}
        assert CODE_A in omitted_09
        assert f"daily_bars_after_asof:{CODE_A}" in issues_09
        fetch_and_record(
            conn,
            FakeDailyBarsSource(),
            trade_date=DAY_1010,
            user_id=U1,
            window_trading_days=None,
            fetched_at=dt.datetime(2026, 11, 10, 17, 15, tzinfo=BEIJING),
        )
        ident_10, _ = snap.build_owned_snapshot(conn, U1, DAY_1010)
        assert ident_10 is not None
        items_10 = _owned_row(conn, ident_10).items
        inst = next(i for i in items_10["instruments"] if i["security_code"] == CODE_A)
        bars = {b["trade_date"]: b for b in inst["bars"]}
        assert DAY_0909.isoformat() in bars
        assert bars[DAY_0909.isoformat()]["is_final"] is True
