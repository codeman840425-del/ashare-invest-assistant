# ruff: noqa: S101, ANN401, ANN202, S603, S607, S106, PT018, PT022, E501, I001
"""T-B127：日 K 写入入口、假源、迁移 0032、配置与任务注册。

契约只读参照 ``git show 4a81876:docs/contracts/daily-bars-source.md`` §7（与 §5.A 冲突时以 §7 为准）。
隔离 PG：仅在 o61-pg 127.0.0.1:55461 自建临时库，用后删除。
不连接、不删除 o53/o55/o57/o60、tt51_tpl、o61_tmp_0030。
"""

from __future__ import annotations

import ast
import datetime as dt
import dataclasses
import inspect
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
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.engine import Engine, URL

from app.config import Settings
from app.db.migration_check import BACKEND, require_single_head, script_directory
from app.db.tables.accounts import (
    accounts,
    broker_position_snapshot_items,
    broker_position_snapshots,
    import_batches,
)
from app.db.tables.market import daily_bars, securities, trading_calendar
from app.db.tables.realtime import pipeline_runs
from app.db.tables.research import watchlist_items
from app.db.tables.strategy import strategies, strategy_instances, strategy_versions
from app.db.tables.users import users
from app.workers import jobs as jobs_mod

HOST = "127.0.0.1"
PORT = 55461
USER = "postgres"
FORBIDDEN_DBS = frozenset({"tt51_tpl", "o61_tmp_0030"})
_SAFE_TMP = re.compile(r"^o61_tmp_b127_[a-z0-9]+$")
_O61 = "o61-pg"

CODE_A = "688018.SH"
CODE_B = "688073.SH"
CODE_C = "300364.SZ"
CODE_D = "510300.SH"
CODE_E = "600000.SH"
CODE_F = "600001.SH"

DAY_0606 = dt.date(2026, 11, 6)
DAY_0707 = dt.date(2026, 11, 7)
DAY_0808 = dt.date(2026, 11, 8)
DAY_0909 = dt.date(2026, 11, 9)
DAY_1010 = dt.date(2026, 11, 10)
DAY_1111 = dt.date(2026, 11, 11)
OPEN_DAYS = (DAY_0606, DAY_0909, DAY_1010)
AT = dt.datetime(2026, 11, 10, 15, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))
FETCHED = dt.datetime(2026, 11, 10, 10, 0, tzinfo=dt.UTC)

APP_DIR = Path(__file__).resolve().parents[1] / "app"


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
    return psycopg.connect(
        host=HOST, port=PORT, user=USER, dbname="postgres", autocommit=True
    )


def _url(dbname: str) -> URL:
    return URL.create(
        "postgresql+psycopg", username=USER, password=None, host=HOST, port=PORT, database=dbname
    )


def _create_temp_db() -> str:
    _require_o61()
    name = "o61_tmp_b127_" + uuid.uuid4().hex[:10]
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


def _downgrade(url: URL, revision: str) -> None:
    command.downgrade(_alembic(url), revision)


def _settings(url: URL, *, source: str = "fake") -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        daily_bars_source=source,  # type: ignore[arg-type]
        database_url=SecretStr(url.render_as_string(hide_password=False)),
        session_cookie_secure=False,
    )


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
        (CODE_D, "etf", "合成D", "SH", None, "listed"),
        (CODE_E, "stock", "合成E", "SH", "main", "listed"),
        (CODE_F, "stock", "合成F", "SH", "main", "listed"),
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


def _seed_user(conn: Any, ident: uuid.UUID, username: str, *, status: str = "approved") -> None:
    conn.execute(
        insert(users).values(
            id=ident,
            username=username,
            display_name=username,
            role="user",
            status=status,
            password_hash="x",
        )
    )


def _seed_holdings(
    conn: Any, user_id: uuid.UUID, codes: tuple[str, ...], *, tag: str
) -> uuid.UUID:
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


def _seed_watch_and_instance(conn: Any, user_id: uuid.UUID, account_id: uuid.UUID) -> None:
    conn.execute(insert(watchlist_items).values(user_id=user_id, security_code=CODE_E))
    template, version, instance = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn.execute(
        insert(strategies).values(
            id=template,
            key="tb127_" + template.hex,
            name="合成实例模板",
            owner_user_id=user_id,
            horizons=["swing"],
        )
    )
    conn.execute(
        insert(strategy_versions).values(
            id=version,
            strategy_id=template,
            version_no=1,
            config={"spec": {}},
            config_hash=template.hex,
            lifecycle="published",
            param_hash=template.hex,
        )
    )
    conn.execute(
        insert(strategy_instances).values(
            id=instance,
            user_id=user_id,
            strategy_version_id=version,
            scope="security",
            security_code=CODE_F,
            account_id=account_id,
            status="active",
            origin="user",
            horizon="swing",
        )
    )


def _import_impl() -> Any:
    import app.marketdata.daily_bars as mod

    return mod


def _bar_count(conn: Any) -> int:
    return int(conn.execute(select(func.count()).select_from(daily_bars)).scalar_one())


def _run_count(conn: Any) -> int:
    return int(conn.execute(select(func.count()).select_from(pipeline_runs)).scalar_one())


def _runs(conn: Any) -> list[Any]:
    return list(
        conn.execute(select(pipeline_runs).order_by(pipeline_runs.c.started_at)).mappings().all()
    )


def _codes_on(conn: Any, day: dt.date) -> list[str]:
    return list(
        conn.execute(
            select(daily_bars.c.code)
            .where(daily_bars.c.trade_date == day)
            .order_by(daily_bars.c.code)
        )
        .scalars()
        .all()
    )


def _dates_for(conn: Any, code: str) -> list[dt.date]:
    return list(
        conn.execute(
            select(daily_bars.c.trade_date)
            .where(daily_bars.c.code == code)
            .order_by(daily_bars.c.trade_date)
        )
        .scalars()
        .all()
    )


@pytest.fixture(scope="module")
def world() -> Iterator[dict[str, Any]]:
    name = _create_temp_db()
    url = _url(name)
    engine: Engine | None = None
    try:
        _upgrade(url, "head")
        engine = create_engine(url)
        u1, u2 = uuid.uuid4(), uuid.uuid4()
        with engine.begin() as conn:
            _seed_calendar(conn)
            _seed_securities(conn)
            _seed_user(conn, u1, "tb127_u1")
            _seed_user(conn, u2, "tb127_u2")
            acc1 = _seed_holdings(conn, u1, (CODE_A, CODE_B, CODE_D), tag="u1")
            _seed_holdings(conn, u2, (CODE_C,), tag="u2")
            _seed_watch_and_instance(conn, u1, acc1)
        yield {"engine": engine, "url": url, "name": name, "u1": u1, "u2": u2}
    finally:
        raw = url.render_as_string(hide_password=False)
        cached = jobs_mod._engines.pop(raw, None)
        if cached is not None:
            cached.dispose()
        if engine is not None:
            engine.dispose()
        _drop_temp_db(name)


@pytest.fixture
def db(world: dict[str, Any]) -> Iterator[dict[str, Any]]:
    engine: Engine = world["engine"]
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE market.daily_bars, app.pipeline_runs"))
    yield world


# --- §7 任务与窗口 -----------------------------------------------------------


def test_task_registered_locked_not_retried() -> None:
    mod = _import_impl()
    name = mod.DAILY_BARS_FETCH
    assert name == "daily_bars_fetch"
    assert jobs_mod.TASKS[name] is mod.daily_bars_fetch_task
    assert name in jobs_mod.LOCKED_TASKS
    assert name not in jobs_mod.RETRY_TASKS
    sig = inspect.signature(mod.daily_bars_fetch_task)
    params = list(sig.parameters)
    assert params == ["settings", "trade_date", "user_id", "window_trading_days"]
    assert sig.parameters["user_id"].default is None
    assert sig.parameters["window_trading_days"].default is None


def test_task_user_scope_union_and_single(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine, url, u1, u2 = db["engine"], db["url"], db["u1"], db["u2"]
    trade = DAY_1010.isoformat()
    with engine.begin() as conn:
        inserted = mod.fetch_and_record(
            conn,
            mod.FakeDailyBarsSource(),
            trade_date=DAY_1010,
            user_id=None,
            window_trading_days=None,
        )
        assert inserted == 3
        assert _codes_on(conn, DAY_1010) == [CODE_C, CODE_A, CODE_B]
        assert _run_count(conn) == 1
        assert _runs(conn)[0]["stats"]["codes"] == 3

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE market.daily_bars, app.pipeline_runs"))
        inserted = mod.fetch_and_record(
            conn,
            mod.FakeDailyBarsSource(),
            trade_date=DAY_1010,
            user_id=u1,
            window_trading_days=None,
        )
        assert inserted == 2
        assert _codes_on(conn, DAY_1010) == [CODE_A, CODE_B]

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE market.daily_bars, app.pipeline_runs"))
        inserted = mod.fetch_and_record(
            conn,
            mod.FakeDailyBarsSource(),
            trade_date=DAY_1010,
            user_id=u2,
            window_trading_days=None,
        )
        assert inserted == 1
        assert _codes_on(conn, DAY_1010) == [CODE_C]

    settings = _settings(url, source="fake")
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE market.daily_bars, app.pipeline_runs"))
    assert jobs_mod.TASKS[mod.DAILY_BARS_FETCH](settings, trade) == 3
    with engine.begin() as conn:
        assert _codes_on(conn, DAY_1010) == [CODE_C, CODE_A, CODE_B]


def test_mairui_before_c_is_inert(db: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_impl()
    url, engine = db["url"], db["engine"]
    opened: list[int] = []

    def _blocked(*args: Any, **kwargs: Any) -> Any:
        opened.append(1)
        raise AssertionError("mairui-before-C must not open a socket")

    monkeypatch.setattr(socket, "socket", _blocked)
    settings = _settings(url, source="mairui")
    assert jobs_mod.TASKS[mod.DAILY_BARS_FETCH](settings, DAY_1010.isoformat()) == 0
    assert opened == []
    with engine.begin() as conn:
        assert _bar_count(conn) == 0
        rows = _runs(conn)
        assert len(rows) == 1
        assert rows[0]["status"] == "skipped"
        assert rows[0]["kind"] == "daily_batch"
        assert rows[0]["step"] == "daily_bars.fetch"
        assert rows[0]["run_date"] == DAY_1010
        assert "daily_bars_http_budget_unset" in (rows[0]["stats"] or {}).get("issues", [])


def test_single_day_when_no_window(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    with engine.begin() as conn:
        mod.fetch_and_record(
            conn,
            mod.FakeDailyBarsSource(),
            trade_date=DAY_1010,
            user_id=None,
            window_trading_days=None,
        )
        dates = set(
            conn.execute(select(daily_bars.c.trade_date).distinct()).scalars().all()
        )
        assert dates == {DAY_1010}
        assert _bar_count(conn) == 3


def test_window_backfills_open_days_only(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    with engine.begin() as conn:
        inserted = mod.fetch_and_record(
            conn,
            mod.FakeDailyBarsSource(),
            trade_date=DAY_1010,
            user_id=None,
            window_trading_days=3,
        )
        assert inserted == 9  # 3 codes × 3 open days
        dates = set(conn.execute(select(daily_bars.c.trade_date).distinct()).scalars().all())
        assert dates == set(OPEN_DAYS)
        for code in (CODE_A, CODE_B, CODE_C):
            assert _dates_for(conn, code) == list(OPEN_DAYS)


def test_window_exceeds_calendar_records_not_covered(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    with engine.begin() as conn:
        inserted = mod.fetch_and_record(
            conn,
            mod.FakeDailyBarsSource(),
            trade_date=DAY_1010,
            user_id=None,
            window_trading_days=4,
        )
        assert inserted == 0
        assert _bar_count(conn) == 0
        rows = _runs(conn)
        assert len(rows) == 1
        assert rows[0]["status"] == "skipped"
        assert "calendar_not_covered" in (rows[0]["stats"] or {}).get("issues", [])


def test_window_non_positive_rejected(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    for bad in (0, -1):
        with engine.begin() as conn:
            with pytest.raises(ValueError, match="window_trading_days"):
                mod.fetch_and_record(
                    conn,
                    mod.FakeDailyBarsSource(),
                    trade_date=DAY_1010,
                    user_id=None,
                    window_trading_days=bad,
                )
            assert _bar_count(conn) == 0
            assert _run_count(conn) == 0


def test_no_settings_field_for_window() -> None:
    assert "window_trading_days" not in Settings.model_fields
    assert not hasattr(Settings(), "window_trading_days")


def test_daily_bars_fetch_never_scheduled(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_impl()
    name = mod.DAILY_BARS_FETCH
    assert name not in jobs_mod.schedule(Settings(_env_file=None, app_env="test", session_cookie_secure=False))

    class _Conn:
        def __enter__(self) -> _Conn:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

    class _Eng:
        def connect(self) -> _Conn:
            return _Conn()

    monkeypatch.setattr(jobs_mod, "_engine", lambda settings: _Eng())
    monkeypatch.setattr("app.reports.service.covered", lambda conn, day: True)
    settings = Settings(_env_file=None, app_env="test", session_cookie_secure=False)
    beijing = dt.timezone(dt.timedelta(hours=8))
    day = DAY_1010
    seen: set[str] = set()
    for minute in range(0, 24 * 60, 5):
        now = dt.datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=beijing)
        for task_name, _hhmm, _args in jobs_mod.slot_jobs(settings, now):
            seen.add(task_name)
            assert task_name != name
    # 显式撞上已知钟点，避免网格漏窗
    for hhmm in ("03:30", "17:30", "18:00", "18:30"):
        h, m = (int(p) for p in hhmm.split(":"))
        now = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=beijing)
        for task_name, _hhmm, _args in jobs_mod.slot_jobs(settings, now):
            assert task_name != name


# --- §7 迁移 -----------------------------------------------------------------


def test_migration_adds_nullable_columns_single_head() -> None:
    name = _create_temp_db()
    url = _url(name)
    engine: Engine | None = None
    try:
        _upgrade(url, "0030")
        _upgrade(url, "head")
        head = require_single_head(script_directory())
        assert head == "0032"
        engine = create_engine(url)
        with engine.begin() as conn:
            cols = {
                r[0]: (r[1], r[2])
                for r in conn.execute(
                    text(
                        """
                        SELECT column_name, is_nullable, column_default
                        FROM information_schema.columns
                        WHERE table_schema = 'market' AND table_name = 'daily_bars'
                          AND column_name IN ('pre_close', 'is_suspended', 'source', 'source_licence_id')
                        """
                    )
                )
            }
            assert set(cols) == {"pre_close", "is_suspended", "source", "source_licence_id"}
            for col, (nullable, default) in cols.items():
                assert nullable == "YES", col
                assert default is None, col
            conn.execute(
                insert(daily_bars).values(
                    code=CODE_A,
                    trade_date=DAY_1010,
                    adj_type="none",
                    close=Decimal("10"),
                    fetched_at=FETCHED,
                )
            )
            with pytest.raises(Exception, match=r"source_allowed|ck_daily_bars"):
                conn.execute(
                    insert(daily_bars).values(
                        code=CODE_B,
                        trade_date=DAY_1010,
                        adj_type="none",
                        close=Decimal("10"),
                        fetched_at=FETCHED,
                        source="legacy",
                    )
                )
    finally:
        if engine is not None:
            engine.dispose()
        _drop_temp_db(name)


def test_upsert_requires_source(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    bar = mod.DailyBar(
        code=CODE_A,
        trade_date=DAY_1010,
        adj_type="none",
        open=Decimal("10"),
        high=Decimal("10"),
        low=Decimal("10"),
        close=Decimal("10"),
        pre_close=Decimal("10"),
        volume=Decimal("10000"),
        amount=Decimal("100000"),
        is_suspended=False,
    )
    with engine.begin() as conn:
        with pytest.raises(ValueError, match="source"):
            mod.upsert_daily_bars(conn, mod.FetchResult(bars=(bar,)), source="", licence_id=None, fetched_at=FETCHED)
        with pytest.raises(ValueError, match="source"):
            mod.upsert_daily_bars(conn, mod.FetchResult(bars=(bar,)), source=None, licence_id=None, fetched_at=FETCHED)
        assert _bar_count(conn) == 0


def test_downgrade_refuses_when_sourced_rows_exist() -> None:
    mod = _import_impl()
    name = _create_temp_db()
    url = _url(name)
    engine: Engine | None = None
    try:
        _upgrade(url, "head")
        engine = create_engine(url)
        bar = mod.DailyBar(
            code=CODE_A,
            trade_date=DAY_1010,
            adj_type="none",
            open=Decimal("10"),
            high=Decimal("10"),
            low=Decimal("10"),
            close=Decimal("10"),
            pre_close=Decimal("10"),
            volume=Decimal("10000"),
            amount=Decimal("100000"),
            is_suspended=False,
        )
        with engine.begin() as conn:
            mod.upsert_daily_bars(
                conn,
                mod.FetchResult(bars=(bar,)),
                source="fake",
                licence_id=None,
                fetched_at=FETCHED,
            )
        with pytest.raises(Exception, match=r"refusing downgrade"):
            _downgrade(url, "0031")
        with engine.begin() as conn:
            assert _bar_count(conn) == 1
            conn.execute(daily_bars.delete())
        _downgrade(url, "0031")
        with engine.connect() as conn:
            cols = {
                r[0]
                for r in conn.execute(
                    text(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = 'market' AND table_name = 'daily_bars'
                        """
                    )
                )
            }
            assert "source" not in cols
            assert "pre_close" not in cols
            assert "is_suspended" not in cols
            assert "source_licence_id" not in cols
    finally:
        if engine is not None:
            engine.dispose()
        _drop_temp_db(name)


def test_normal_row_is_suspended_false(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    with engine.begin() as conn:
        mod.fetch_and_record(
            conn,
            mod.FakeDailyBarsSource(),
            trade_date=DAY_1010,
            user_id=None,
            window_trading_days=None,
        )
        flags = list(conn.execute(select(daily_bars.c.is_suspended)).scalars().all())
        assert flags and all(flag is False for flag in flags)


# --- §7 写入语义 / 假源 / 边界 -----------------------------------------------


def test_upsert_stats_fields_and_equal_after_quantize(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    first = mod.DailyBar(
        code=CODE_A,
        trade_date=DAY_1010,
        adj_type="none",
        open=Decimal("10.00004"),
        high=Decimal("10.00004"),
        low=Decimal("10.00004"),
        close=Decimal("10.00004"),
        pre_close=Decimal("10.00004"),
        volume=Decimal("10000"),
        amount=Decimal("100000.00004"),
        is_suspended=False,
    )
    second = mod.DailyBar(
        code=CODE_A,
        trade_date=DAY_1010,
        adj_type="none",
        open=Decimal("10.00001"),
        high=Decimal("10.00001"),
        low=Decimal("10.00001"),
        close=Decimal("10.00001"),
        pre_close=Decimal("10.00001"),
        volume=Decimal("10000"),
        amount=Decimal("100000.00001"),
        is_suspended=False,
    )
    with engine.begin() as conn:
        stats1 = mod.upsert_daily_bars(
            conn, mod.FetchResult(bars=(first,)), source="fake", licence_id=None, fetched_at=FETCHED
        )
        stats2 = mod.upsert_daily_bars(
            conn, mod.FetchResult(bars=(second,)), source="fake", licence_id=None, fetched_at=FETCHED
        )
    assert stats1.inserted == 1 and stats1.unchanged == 0 and stats1.conflicts == 0
    assert stats2.inserted == 0 and stats2.unchanged == 1 and stats2.conflicts == 0
    for stats in (stats1, stats2):
        assert set(stats.__dataclass_fields__) == {"inserted", "unchanged", "conflicts", "issues"}
        assert stats.issues == []
    assert dataclasses.is_dataclass(mod.UpsertStats)
    assert mod.UpsertStats.__dataclass_params__.frozen is True  # type: ignore[attr-defined]


def test_same_values_different_source_is_unchanged(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    bar = mod.DailyBar(
        code=CODE_A,
        trade_date=DAY_1010,
        adj_type="none",
        open=Decimal("10"),
        high=Decimal("10"),
        low=Decimal("10"),
        close=Decimal("10"),
        pre_close=Decimal("10"),
        volume=Decimal("10000"),
        amount=Decimal("100000"),
        is_suspended=False,
    )
    with engine.begin() as conn:
        mod.upsert_daily_bars(
            conn, mod.FetchResult(bars=(bar,)), source="fake", licence_id=None, fetched_at=FETCHED
        )
        stats = mod.upsert_daily_bars(
            conn, mod.FetchResult(bars=(bar,)), source="mairui", licence_id=None, fetched_at=FETCHED
        )
        row = conn.execute(select(daily_bars).where(daily_bars.c.code == CODE_A)).mappings().one()
        assert stats.unchanged == 1 and stats.conflicts == 0 and stats.inserted == 0
        assert row["source"] == "fake"
        assert row["close"] == Decimal("10.0000")


def test_run_row_stats_shape(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    expected = {
        "user_id",
        "window_trading_days",
        "codes",
        "inserted",
        "unchanged",
        "conflicts",
        "missing",
        "suspended",
        "issues",
    }
    with engine.begin() as conn:
        mod.fetch_and_record(
            conn,
            mod.FakeDailyBarsSource(),
            trade_date=DAY_1010,
            user_id=None,
            window_trading_days=None,
        )
        ok = _runs(conn)[0]
        assert ok["status"] == "ok"
        assert set(ok["stats"]) == expected
        assert ok["stats"]["issues"] == []

        conn.execute(text("TRUNCATE market.daily_bars, app.pipeline_runs"))
        # 先写一根不同收盘价，再让假源写入同日同码 → 冲突
        conn.execute(
            insert(daily_bars).values(
                code=CODE_A,
                trade_date=DAY_1010,
                adj_type="none",
                open=Decimal("1"),
                high=Decimal("1"),
                low=Decimal("1"),
                close=Decimal("1"),
                volume=Decimal("1"),
                amount=Decimal("1"),
                fetched_at=FETCHED,
                is_suspended=False,
                source="fake",
            )
        )
        mod.fetch_and_record(
            conn,
            mod.FakeDailyBarsSource(),
            trade_date=DAY_1010,
            user_id=None,
            window_trading_days=None,
        )
        partial = _runs(conn)[0]
        assert partial["status"] == "partial"
        assert set(partial["stats"]) == expected
        assert partial["stats"]["conflicts"] >= 1
        assert any(s.startswith("daily_bar_conflict:") for s in partial["stats"]["issues"])


def test_fake_default_one_bar_per_code_day() -> None:
    mod = _import_impl()
    source = mod.FakeDailyBarsSource()
    result = source.fetch([CODE_A, CODE_B], DAY_0909, DAY_1010, "none")
    keys = {(b.code, b.trade_date) for b in result.bars}
    assert keys == {
        (CODE_A, DAY_0909),
        (CODE_A, DAY_1010),
        (CODE_B, DAY_0909),
        (CODE_B, DAY_1010),
    }
    assert result.gaps == ()
    assert all(b.adj_type == "none" and b.is_suspended is False for b in result.bars)


def test_fake_missing_and_suspended_injection(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    source = mod.FakeDailyBarsSource(missing=(CODE_A,), suspended=(CODE_A, CODE_B))
    result = source.fetch([CODE_A, CODE_B], DAY_1010, DAY_1010, "none")
    assert all(b.code != CODE_A for b in result.bars)
    assert any(g.code == CODE_A for g in result.gaps)
    with engine.begin() as conn:
        inserted = mod.fetch_and_record(
            conn, source, trade_date=DAY_1010, user_id=db["u1"], window_trading_days=None
        )
        assert inserted == 1
        row = conn.execute(select(daily_bars).where(daily_bars.c.code == CODE_B)).mappings().one()
        assert row["is_suspended"] is True
        assert row["open"] is None and row["high"] is None and row["low"] is None
        assert row["close"] is None and row["pre_close"] is None
        assert row["volume"] is None and row["amount"] is None
        assert conn.execute(select(func.count()).select_from(daily_bars).where(daily_bars.c.code == CODE_A)).scalar_one() == 0
        stats = _runs(conn)[0]["stats"]
        assert "daily_bars_missing:" + CODE_A in stats["issues"]
        assert stats["missing"] >= 1
        assert stats["suspended"] == 1


def test_fake_deterministic_and_bounded() -> None:
    mod = _import_impl()
    source = mod.FakeDailyBarsSource()
    a = source.fetch([CODE_A], DAY_1010, DAY_1010, "none")
    b = source.fetch([CODE_A], DAY_1010, DAY_1010, "none")
    assert a.bars == b.bars
    bar = a.bars[0]
    assert Decimal("5") <= bar.pre_close <= Decimal("50")
    lo, hi = bar.pre_close * Decimal("0.8"), bar.pre_close * Decimal("1.2")
    assert lo <= bar.open <= hi
    assert lo <= bar.close <= hi
    assert lo <= bar.low <= bar.high <= hi
    assert bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
    for price in (bar.open, bar.high, bar.low, bar.close, bar.pre_close):
        assert price == price.quantize(Decimal("0.01"))
    assert bar.volume == Decimal("10000")
    assert bar.amount == bar.close * bar.volume
    other_day = source.fetch([CODE_A], DAY_0909, DAY_0909, "none").bars[0]
    assert other_day.pre_close != bar.pre_close or other_day.close != bar.close


def test_suspended_placeholder_row_written(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    with engine.begin() as conn:
        inserted = mod.fetch_and_record(
            conn,
            mod.FakeDailyBarsSource(suspended=(CODE_A,)),
            trade_date=DAY_1010,
            user_id=db["u1"],
            window_trading_days=None,
        )
        assert inserted == 2  # A placeholder + B normal
        row = conn.execute(select(daily_bars).where(daily_bars.c.code == CODE_A)).mappings().one()
        assert row["is_suspended"] is True
        assert row["adj_type"] == "none"
        for col in ("open", "high", "low", "close", "pre_close", "volume", "amount"):
            assert row[col] is None
        run = _runs(conn)[0]
        assert run["status"] == "ok"
        assert run["stats"]["suspended"] == 1
        assert run["stats"]["missing"] == 0


def test_impl_a_imports_no_b_module() -> None:
    targets = {"app.marketdata.daily_snapshot", "app.workers.daily"}
    files = [
        APP_DIR / "marketdata" / "daily_bars.py",
        Path(__file__),
    ]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module in targets or any(
                    node.module.startswith(t + ".") for t in targets
                ):
                    found.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in targets or any(alias.name.startswith(t + ".") for t in targets):
                        found.add(alias.name)
        assert not found, f"{path} imports {found}"


def test_non_trading_day_noop_and_calendar_not_covered(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    with engine.begin() as conn:
        assert (
            mod.fetch_and_record(
                conn,
                mod.FakeDailyBarsSource(),
                trade_date=DAY_0707,
                user_id=None,
                window_trading_days=None,
            )
            == 0
        )
        assert _bar_count(conn) == 0
        assert _run_count(conn) == 0

        inserted = mod.fetch_and_record(
            conn,
            mod.FakeDailyBarsSource(),
            trade_date=DAY_1111,
            user_id=None,
            window_trading_days=None,
        )
        assert inserted == 0
        assert _bar_count(conn) == 0
        rows = _runs(conn)
        assert len(rows) == 1
        assert rows[0]["status"] == "skipped"
        assert rows[0]["run_date"] == DAY_1111
        assert "calendar_not_covered" in (rows[0]["stats"] or {}).get("issues", [])


def test_off_recorded_even_on_closed_day(db: dict[str, Any]) -> None:
    mod = _import_impl()
    url, engine = db["url"], db["engine"]
    settings = _settings(url, source="off")
    assert jobs_mod.TASKS[mod.DAILY_BARS_FETCH](settings, DAY_0707.isoformat()) == 0
    with engine.begin() as conn:
        assert _bar_count(conn) == 0
        rows = _runs(conn)
        assert len(rows) == 1
        assert rows[0]["status"] == "skipped"
        assert rows[0]["run_date"] == DAY_0707
        assert "daily_bars_source_off" in (rows[0]["stats"] or {}).get("issues", [])


def test_licence_id_none_written_as_null(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    with engine.begin() as conn:
        mod.fetch_and_record(
            conn,
            mod.FakeDailyBarsSource(),
            trade_date=DAY_1010,
            user_id=None,
            window_trading_days=None,
        )
        ids = list(conn.execute(select(daily_bars.c.source_licence_id)).scalars().all())
        assert ids and all(v is None for v in ids)


def test_licence_id_empty_string_rejected(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    bar = mod.DailyBar(
        code=CODE_A,
        trade_date=DAY_1010,
        adj_type="none",
        open=Decimal("10"),
        high=Decimal("10"),
        low=Decimal("10"),
        close=Decimal("10"),
        pre_close=Decimal("10"),
        volume=Decimal("10000"),
        amount=Decimal("100000"),
        is_suspended=False,
    )
    with engine.begin() as conn:
        with pytest.raises(TypeError):
            mod.upsert_daily_bars(
                conn,
                mod.FetchResult(bars=(bar,)),
                source="fake",
                licence_id="",  # type: ignore[arg-type]
                fetched_at=FETCHED,
            )
        assert _bar_count(conn) == 0


# --- 仍有效的 §5.A 用例 -------------------------------------------------------


def test_daily_bars_default_off_no_writes(db: dict[str, Any]) -> None:
    mod = _import_impl()
    url, engine = db["url"], db["engine"]
    blank = Settings(
        _env_file=None,
        app_env="test",
        database_url=SecretStr(url.render_as_string(hide_password=False)),
        session_cookie_secure=False,
    )
    assert blank.daily_bars_source == "off"
    assert jobs_mod.TASKS[mod.DAILY_BARS_FETCH](blank, DAY_1010.isoformat()) == 0
    with engine.begin() as conn:
        assert _bar_count(conn) == 0
        rows = _runs(conn)
        assert len(rows) == 1
        assert rows[0]["status"] == "skipped"
        assert "daily_bars_source_off" in (rows[0]["stats"] or {}).get("issues", [])


def test_fake_source_refused_outside_test_env() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="local", daily_bars_source="fake")


def test_fake_no_bars_for_day(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    with engine.begin() as conn:
        inserted = mod.fetch_and_record(
            conn,
            mod.FakeDailyBarsSource(missing=(CODE_A, CODE_B, CODE_C)),
            trade_date=DAY_1010,
            user_id=None,
            window_trading_days=None,
        )
        assert inserted == 0
        assert _bar_count(conn) == 0
        run = _runs(conn)[0]
        assert run["status"] == "partial"
        issues = run["stats"]["issues"]
        assert issues == sorted(
            [
                "daily_bars_missing:" + CODE_A,
                "daily_bars_missing:" + CODE_B,
                "daily_bars_missing:" + CODE_C,
            ]
        )
        assert run["stats"]["missing"] == 3


def test_fake_partial_codes_missing(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    with engine.begin() as conn:
        inserted = mod.fetch_and_record(
            conn,
            mod.FakeDailyBarsSource(missing=(CODE_A,)),
            trade_date=DAY_1010,
            user_id=None,
            window_trading_days=None,
        )
        assert inserted == 2
        assert _codes_on(conn, DAY_1010) == [CODE_C, CODE_B]
        run = _runs(conn)[0]
        assert run["status"] == "partial"
        assert "daily_bars_missing:" + CODE_A in run["stats"]["issues"]
        assert run["stats"]["missing"] == 1


def test_fake_source_deterministic_and_idempotent(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    source = mod.FakeDailyBarsSource()
    with engine.begin() as conn:
        first = mod.fetch_and_record(
            conn, source, trade_date=DAY_1010, user_id=None, window_trading_days=None
        )
        assert first == 3
    with engine.begin() as conn:
        second = mod.fetch_and_record(
            conn, source, trade_date=DAY_1010, user_id=None, window_trading_days=None
        )
        assert second == 0
        run = _runs(conn)[-1]
        assert run["stats"]["inserted"] == 0
        assert run["stats"]["unchanged"] == 3
        assert run["status"] == "ok"
        assert _bar_count(conn) == 3


def test_upsert_conflict_never_overwrites(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    first = mod.DailyBar(
        code=CODE_A,
        trade_date=DAY_1010,
        adj_type="none",
        open=Decimal("10"),
        high=Decimal("10"),
        low=Decimal("10"),
        close=Decimal("10"),
        pre_close=Decimal("10"),
        volume=Decimal("10000"),
        amount=Decimal("100000"),
        is_suspended=False,
    )
    changed = mod.DailyBar(
        code=CODE_A,
        trade_date=DAY_1010,
        adj_type="none",
        open=Decimal("11"),
        high=Decimal("11"),
        low=Decimal("11"),
        close=Decimal("11"),
        pre_close=Decimal("11"),
        volume=Decimal("10000"),
        amount=Decimal("110000"),
        is_suspended=False,
    )
    with engine.begin() as conn:
        mod.upsert_daily_bars(
            conn, mod.FetchResult(bars=(first,)), source="fake", licence_id=None, fetched_at=FETCHED
        )
        stats = mod.upsert_daily_bars(
            conn, mod.FetchResult(bars=(changed,)), source="fake", licence_id=None, fetched_at=FETCHED
        )
        row = conn.execute(select(daily_bars).where(daily_bars.c.code == CODE_A)).mappings().one()
        assert stats.conflicts == 1 and stats.inserted == 0 and stats.unchanged == 0
        assert stats.issues == [f"daily_bar_conflict:{CODE_A}:{DAY_1010.isoformat()}"]
        assert row["close"] == Decimal("10.0000")


def test_only_writer_inserts_daily_bars() -> None:
    writers: list[str] = []
    needles = (
        "insert(daily_bars)",
        "pg_insert(daily_bars)",
        "daily_bars.insert(",
        'insert(market.daily_bars)',
    )
    for path in APP_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(n in text for n in needles) or (
            "daily_bars" in text and re.search(r"\binsert\b.*daily_bars|daily_bars.*\binsert\b", text)
        ):
            # 仅将明确写入点记为 writer；本票允许 upsert_daily_bars
            if path.name == "daily_bars.py" and "def upsert_daily_bars" in text:
                continue
            if any(n in text for n in needles):
                writers.append(str(path.relative_to(APP_DIR.parent)))
    assert writers == [], writers


def test_universe_holdings_only_until_clarified(db: dict[str, Any]) -> None:
    mod = _import_impl()
    engine = db["engine"]
    with engine.begin() as conn:
        mod.fetch_and_record(
            conn,
            mod.FakeDailyBarsSource(),
            trade_date=DAY_1010,
            user_id=db["u1"],
            window_trading_days=None,
        )
        assert _codes_on(conn, DAY_1010) == [CODE_A, CODE_B]
        for excluded in (CODE_C, CODE_D, CODE_E, CODE_F):
            n = conn.execute(
                select(func.count()).select_from(daily_bars).where(daily_bars.c.code == excluded)
            ).scalar_one()
            assert n == 0, excluded
