# ruff: noqa: S101
"""T-T70 / T-T70b：docs/contracts/daily-bars-source.md 实现单 A 验收（以 §7 及 T-A131 补充裁定为准）。

基线 be/T-B127=832faa2，合入 test/T-T70=efc8cb8 后按 04178d0 补充裁定调整。
按契约接口名导入。导入放在各例内部，收集本文件与其他测试互不影响。

假源用 FakeDailyBarsSource(missing=, suspended=)，经 fetch_and_record 注入。
任务经 jobs.TASKS 取 daily_bars_fetch_task(settings, trade_date, user_id=None,
window_trading_days=None)。licence_id 传 None；空串应 TypeError。
停牌用例为 test_suspended_placeholder_row_written，不导入实现单 B 的快照模块。

临时库：guard_temp_pg → TEMPLATE o61_tmp_0030 → 断言版本 0030 → 仅对该库
alembic upgrade head → 播种 → finally DROP。建库失败 skip。麦蕊 0。
出网=否：拦 socket connect（只放行 AF_UNIX/回环）+ egress.mairui_get 计数桩=0；
不调用 netguard.install()，也不再用 netguard_blocks。
"""

from __future__ import annotations

import ast
import ipaddress
import socket
import datetime as dt
import inspect
import uuid
from argparse import Namespace
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = ROOT / "src/backend/app"
MIGRATIONS = ROOT / "src/backend/migrations"
CONTRACT_MOD = "app.marketdata.daily_bars"
BEIJING = ZoneInfo("Asia/Shanghai")

# 代码取自仓库已有合成夹具（test_expected_json / test_contract_v028 / T-T66），
# 不得取自用户持仓或股东代码材料。
CODE_A = "600001.SH"
CODE_B = "301002.SZ"
CODE_C = "002001.SZ"
CODE_D = "510981.SH"  # etf
CODE_E = "600981.SH"  # 仅 universe 用例自选
CODE_F = "600991.SH"  # 仅 universe 用例实例
CODE_G = "600000.SH"  # 仅 universe 用例：listing_status 为空的持仓股（夹具曾用）
OPEN_06 = dt.date(2026, 11, 6)
CLOSED_07 = dt.date(2026, 11, 7)
CLOSED_08 = dt.date(2026, 11, 8)
OPEN_09 = dt.date(2026, 11, 9)
OPEN_10 = dt.date(2026, 11, 10)
UNCOVERED_11 = dt.date(2026, 11, 11)
STATS_KEYS = frozenset(
    {
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
)
_A_SYMBOLS = (
    "DailyBarsSource",
    "DailyBarsResult",
    "DailyBar",
    "BarGap",
    "UpsertStats",
    "FakeDailyBarsSource",
    "daily_universe",
    "upsert_daily_bars",
    "daily_bars_fetch_task",
    "fetch_and_record",
)


def _impl() -> Any:
    module = __import__(CONTRACT_MOD, fromlist=list(_A_SYMBOLS))
    missing = [name for name in _A_SYMBOLS if not hasattr(module, name)]
    if missing:
        raise ImportError(f"{CONTRACT_MOD} 缺少契约符号：{', '.join(missing)}")
    return module


def _task_from_jobs() -> Any:
    from app.workers import jobs

    fn = jobs.TASKS.get("daily_bars_fetch")
    if not callable(fn):
        raise ImportError("workers/jobs.TASKS 未注册 daily_bars_fetch")
    return fn


def _host_of(address: Any) -> str | None:
    if isinstance(address, tuple) and address:
        return str(address[0])
    if isinstance(address, str):
        return address
    return None


def _is_loopback_host(host: str) -> bool:
    h = host.split("%", 1)[0]
    if h in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
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
    """出网=否：只放行 AF_UNIX 与回环；mairui_get 计数须为 0。不调用 netguard.install()。"""
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


def _imported_modules(path: Path, *, top_level: bool = False) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes: list[ast.AST] = list(tree.body) if top_level else list(ast.walk(tree))
    names: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names.add(mod)
            for alias in node.names:
                names.add(f"{mod}.{alias.name}" if mod else alias.name)
    return names


def _count(engine: Engine, table: Any) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar_one())


def _daily_bar_count(engine: Engine) -> int:
    from app.db.tables.market import daily_bars

    return _count(engine, daily_bars)


def _pipeline_rows(engine: Engine) -> list[Any]:
    from app.db.tables.realtime import pipeline_runs

    with engine.connect() as conn:
        return list(conn.execute(select(pipeline_runs).order_by(pipeline_runs.c.started_at)).all())


def _latest_run(engine: Engine) -> Any:
    rows = _pipeline_rows(engine)
    assert rows, "expected a pipeline_runs row"
    return rows[-1]


def _alembic_config(url_str: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.cmd_opts = Namespace(x=["url=" + url_str])
    return cfg


def _current_head() -> str:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, "alembic heads 必须单头"
    return ScriptDirectory.from_config(cfg).get_current_head()


def _seed_core(conn: Any, ctx: SimpleNamespace) -> None:
    from app.db.tables.accounts import (
        accounts,
        broker_position_snapshot_items,
        broker_position_snapshots,
        import_batches,
    )
    from app.db.tables.market import securities, trading_calendar
    from app.db.tables.users import users

    conn.execute(text("DELETE FROM market.trading_calendar"))
    conn.execute(
        insert(trading_calendar),
        [
            {"date": OPEN_06, "is_open": True},
            {"date": CLOSED_07, "is_open": False},
            {"date": CLOSED_08, "is_open": False},
            {"date": OPEN_09, "is_open": True},
            {"date": OPEN_10, "is_open": True},
        ],
    )
    # listing_status=listed 按 §7 :345「type=stock、listing_status=listed」写入；
    # 同条又写「列只填非空列 code、type、name、exchange」，见报告剩余歧义。
    conn.execute(
        insert(securities),
        [
            {"code": CODE_A, "type": "stock", "name": "合成A", "exchange": "SH", "listing_status": "listed"},
            {"code": CODE_B, "type": "stock", "name": "合成B", "exchange": "SZ", "listing_status": "listed"},
            {"code": CODE_C, "type": "stock", "name": "合成C", "exchange": "SZ", "listing_status": "listed"},
            {"code": CODE_D, "type": "etf", "name": "合成D", "exchange": "SH", "listing_status": "listed"},
        ],
    )
    as_of = dt.datetime(2026, 11, 10, 15, 0, tzinfo=BEIJING)
    for uname, uid, acc_id, batch_id, snap_id, items in (
        ("tt70_u1", ctx.u1, ctx.acc1, ctx.batch1, ctx.snap1, [(CODE_A, 100), (CODE_B, 100), (CODE_D, 100)]),
        ("tt70_u2", ctx.u2, ctx.acc2, ctx.batch2, ctx.snap2, [(CODE_C, 100)]),
    ):
        conn.execute(
            insert(users).values(
                id=uid,
                username=uname,
                password_hash="tt70-unused-hash",
                role="user",
                status="approved",
            )
        )
        conn.execute(insert(accounts).values(id=acc_id, user_id=uid, name="合成账户"))
        conn.execute(
            insert(import_batches).values(
                id=batch_id,
                user_id=uid,
                account_id=acc_id,
                status="committed",
                kind="positions",
            )
        )
        conn.execute(
            insert(broker_position_snapshots).values(
                id=snap_id,
                account_id=acc_id,
                import_batch_id=batch_id,
                as_of=as_of,
                version_no=1,
            )
        )
        conn.execute(
            insert(broker_position_snapshot_items),
            [
                {
                    "id": uuid.uuid4(),
                    "snapshot_id": snap_id,
                    "security_code": code,
                    "quantity": qty,
                    "sellable_quantity": qty,
                }
                for code, qty in items
            ],
        )


def _seed_universe_extras(conn: Any, ctx: SimpleNamespace) -> None:
    from app.db.tables.market import securities
    from app.db.tables.research import watchlist_items
    from app.db.tables.strategy import strategies, strategy_instances, strategy_versions

    conn.execute(
        insert(securities).values(
            code=CODE_E, type="stock", name="合成E", exchange="SH", listing_status="listed"
        )
    )
    conn.execute(
        insert(securities).values(
            code=CODE_F, type="stock", name="合成F", exchange="SH", listing_status="listed"
        )
    )
    conn.execute(
        insert(securities).values(
            code=CODE_G, type="stock", name="合成G", exchange="SH", listing_status=None
        )
    )
    conn.execute(
        insert(watchlist_items).values(id=uuid.uuid4(), user_id=ctx.u1, security_code=CODE_E)
    )
    from app.db.tables.accounts import broker_position_snapshot_items

    conn.execute(
        insert(broker_position_snapshot_items).values(
            id=uuid.uuid4(),
            snapshot_id=ctx.snap1,
            security_code=CODE_G,
            quantity=100,
            sellable_quantity=100,
        )
    )
    # 链路形状同 test_tb74_candidates.setup（§7 :348）
    tmpl, ver, inst = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn.execute(
        insert(strategies).values(
            id=tmpl,
            key="tt70_synthetic_" + tmpl.hex,
            name="合成模板",
            owner_user_id=ctx.u1,
            horizons=["swing"],
        )
    )
    conn.execute(
        insert(strategy_versions).values(
            id=ver,
            strategy_id=tmpl,
            version_no=1,
            config={"spec": {}, "universe": {"pool": "持仓"}},
            config_hash=tmpl.hex,
            lifecycle="published",
            param_hash=tmpl.hex,
        )
    )
    conn.execute(
        insert(strategy_instances).values(
            id=inst,
            user_id=ctx.u1,
            strategy_version_id=ver,
            scope="security",
            security_code=CODE_F,
            account_id=ctx.acc1,
            status="active",
            origin="user",
            horizon="swing",
        )
    )


def _open_temp_db() -> Iterator[SimpleNamespace]:
    """o61 临时库：模板 0030 → upgrade head → 播种；失败 skip；finally DROP。不打印 DSN。"""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from pg_o61 import (  # noqa: E402
        PgOwnershipError,
        guard_temp_pg,
        libpq_sqlalchemy_url,
        resolve_libpq_params,
        template_db_name,
        validate_temp_db_name,
    )

    host, port, _user, _password = resolve_libpq_params()
    try:
        guard_temp_pg(host, port)
    except PgOwnershipError as exc:
        pytest.fail(str(exc))
    name = validate_temp_db_name("tt70_" + uuid.uuid4().hex[:8])
    tpl = template_db_name()
    admin_url = libpq_sqlalchemy_url("postgres")
    db_url = libpq_sqlalchemy_url(name)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    engine: Engine | None = None
    try:
        try:
            with admin.connect() as conn:
                conn.execute(text(f"CREATE DATABASE {name} TEMPLATE {tpl}"))
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"无法在目标实例上创建临时库：{type(exc).__name__}")
        engine = create_engine(db_url, hide_parameters=True)
        with engine.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert ver == "0030"
        url_str = db_url.render_as_string(hide_password=False)
        cfg = _alembic_config(url_str)
        command.upgrade(cfg, "head")
        head = _current_head()
        with engine.connect() as conn:
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert ver == head
        ctx = SimpleNamespace(
            engine=engine,
            name=name,
            url=db_url,
            u1=uuid.uuid4(),
            u2=uuid.uuid4(),
            acc1=uuid.uuid4(),
            acc2=uuid.uuid4(),
            batch1=uuid.uuid4(),
            batch2=uuid.uuid4(),
            snap1=uuid.uuid4(),
            snap2=uuid.uuid4(),
        )
        with engine.begin() as conn:
            _seed_core(conn, ctx)
        yield ctx
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=:n AND pid<>pg_backend_pid()"
                ),
                {"n": name},
            )
            conn.execute(text(f"DROP DATABASE IF EXISTS {name}"))
        admin.dispose()


@pytest.fixture
def temp_db() -> Iterator[SimpleNamespace]:
    yield from _open_temp_db()


_MISSING = object()


def _database_url_text(url: Any) -> str:
    """URL.render_as_string(hide_password=False)；不打印返回值。"""
    if hasattr(url, "render_as_string"):
        return url.render_as_string(hide_password=False)
    if isinstance(url, str):
        return url
    raise TypeError("database_url 须为 str 或 SQLAlchemy URL")


def _settings(
    *,
    app_env: str = "test",
    daily_bars_source: str | None = None,
    database_url: Any = _MISSING,
):
    from app.config import Settings

    assert "daily_bars_source" in Settings.model_fields
    payload: dict[str, Any] = {"app_env": app_env}
    if daily_bars_source is not None:
        payload["daily_bars_source"] = daily_bars_source
    if database_url is _MISSING:
        pass
    elif database_url is None:
        payload["database_url"] = None
    else:
        payload["database_url"] = _database_url_text(database_url)
    return Settings(**payload)


# ---------------------------------------------------------------------------
# 临时库 fixture 自证（非契约验收名；应绿）
# ---------------------------------------------------------------------------


def test_tt70_temp_db_fixture_lifecycle() -> None:
    """自证：建库、断言 0030、upgrade head、播种 5 行日历，退出后库已删。"""
    gen = _open_temp_db()
    ctx = next(gen)
    dropped_name = ctx.name
    try:
        from app.db.tables.market import securities, trading_calendar
        from app.db.tables.users import users

        assert _count(ctx.engine, trading_calendar) == 5
        with ctx.engine.connect() as conn:
            dates = {r.date for r in conn.execute(select(trading_calendar)).all()}
            assert dates == {OPEN_06, CLOSED_07, CLOSED_08, OPEN_09, OPEN_10}
            assert _count(ctx.engine, securities) == 4
            assert _count(ctx.engine, users) == 2
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert ver == _current_head() == "0030" or ver == _current_head()
    finally:
        try:
            next(gen)
        except StopIteration:
            pass
    # 确认已 DROP（只读 postgres 库，不打印 DSN）
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from pg_o61 import libpq_sqlalchemy_url

    admin = create_engine(libpq_sqlalchemy_url("postgres"), hide_parameters=True)
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname=:n"), {"n": dropped_name}
            ).scalar()
        assert exists is None
    finally:
        admin.dispose()


# ---------------------------------------------------------------------------
# 纯单元（不连库）
# ---------------------------------------------------------------------------


def test_fake_source_refused_outside_test_env(monkeypatch: pytest.MonkeyPatch, no_egress: None) -> None:
    """A-2 / §5.A :131；§7 ① 配置校验。"""
    from pydantic import ValidationError

    from app.config import Settings

    assert "daily_bars_source" in Settings.model_fields
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DAILY_BARS_SOURCE", "fake")
    with pytest.raises(ValidationError):
        Settings()


def test_only_writer_inserts_daily_bars() -> None:
    """A-7 / §5.A :136。须存在 upsert_daily_bars 且其函数体含写语句，避免实现前空过。"""
    m = _impl()
    assert callable(m.upsert_daily_bars)
    write_pat = (
        "insert(daily_bars",
        "update(daily_bars",
        "delete(daily_bars",
        "daily_bars.insert",
        "INSERT INTO market.daily_bars",
        "insert into market.daily_bars",
        "pg_insert(daily_bars",
    )
    writers: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        if any(p.lower() in src.lower() for p in write_pat):
            writers.append(path.relative_to(APP_ROOT).as_posix())
    assert writers == ["marketdata/daily_bars.py"]
    text_src = (APP_ROOT / "marketdata/daily_bars.py").read_text(encoding="utf-8")
    tree = ast.parse(text_src)
    fn = next(
        n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "upsert_daily_bars"
    )
    body = ast.get_source_segment(text_src, fn) or ""
    assert any(p.lower() in body.lower() for p in write_pat)


def test_task_registered_locked_not_retried() -> None:
    """§7 ① :205。"""
    from app.workers import jobs

    fn = jobs.TASKS.get("daily_bars_fetch")
    m = _impl()
    assert fn is m.daily_bars_fetch_task
    assert "daily_bars_fetch" in jobs.LOCKED_TASKS
    assert "daily_bars_fetch" not in jobs.RETRY_TASKS
    params = list(inspect.signature(fn).parameters)
    assert params[:4] == ["settings", "trade_date", "user_id", "window_trading_days"]
    sig = inspect.signature(fn)
    assert sig.parameters["user_id"].default is None
    assert sig.parameters["window_trading_days"].default is None


def test_no_settings_field_for_window() -> None:
    """§7 补1 / T-A131：字段名不得含 window/backfill/lookback；daily_bars_ 前缀只允许 daily_bars_source。"""
    from app.config import Settings

    names = list(Settings.model_fields)
    for name in names:
        lowered = name.lower()
        assert "window" not in lowered
        assert "backfill" not in lowered
        assert "lookback" not in lowered
    assert {n for n in names if n.lower().startswith("daily_bars_")} == {"daily_bars_source"}


def test_daily_bars_fetch_never_scheduled(monkeypatch: pytest.MonkeyPatch) -> None:
    """§7 ③ :230。先断言已注册，避免实现前因任务不存在而空过。"""
    from app.workers import jobs

    assert "daily_bars_fetch" in jobs.TASKS
    monkeypatch.setattr("app.reports.service.covered", lambda _conn, _d: True)

    class _DummyConn:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

    class _DummyEngine:
        def connect(self) -> _DummyConn:
            return _DummyConn()

        def dispose(self) -> None:
            return None

    monkeypatch.setattr("app.workers.jobs._engine", lambda _settings: _DummyEngine())
    settings = __import__("app.config", fromlist=["Settings"]).Settings()
    day = dt.datetime(2026, 11, 10, 0, 0, tzinfo=BEIJING)
    end = dt.datetime(2026, 11, 10, 23, 59, tzinfo=BEIJING)
    now = day
    while now <= end:
        slots = jobs.slot_jobs(settings, now)
        assert all(item[0] != "daily_bars_fetch" for item in slots)
        now += dt.timedelta(minutes=5)
    assert "daily_bars_fetch" not in jobs.schedule(settings)


def test_fake_default_one_bar_per_code_day() -> None:
    """§7 ⑥ :290。"""
    from app.schemas.enums import BarAdjust

    m = _impl()
    src = m.FakeDailyBarsSource()
    result = src.fetch([CODE_A, CODE_B], OPEN_10, OPEN_10, BarAdjust.NONE)
    assert len(result.bars) == 2
    assert all(b.is_suspended is False for b in result.bars)
    assert list(result.gaps) == []


def test_fake_missing_and_suspended_injection() -> None:
    """§7 ⑥ :291。"""
    from app.schemas.enums import BarAdjust, GapReason

    m = _impl()
    src = m.FakeDailyBarsSource(missing=frozenset({CODE_A}), suspended=frozenset({CODE_B}))
    result = src.fetch([CODE_A, CODE_B, CODE_C], OPEN_10, OPEN_10, BarAdjust.NONE)
    gaps_a = [g for g in result.gaps if g.code == CODE_A]
    assert len(gaps_a) == 1
    assert gaps_a[0].reason == GapReason.NO_SOURCE or gaps_a[0].reason == "no_source"
    assert gaps_a[0].issue == f"daily_bars_missing:{CODE_A}"
    assert not any(b.code == CODE_A for b in result.bars)
    bar_b = next(b for b in result.bars if b.code == CODE_B)
    assert bar_b.is_suspended is True
    assert bar_b.open is None and bar_b.high is None and bar_b.low is None and bar_b.close is None
    bar_c = next(b for b in result.bars if b.code == CODE_C)
    assert bar_c.is_suspended is False
    assert bar_c.close is not None


def test_fake_deterministic_and_bounded() -> None:
    """§7 ⑥ :292。只断言约束，不钉黄金价格。"""
    from app.schemas.enums import BarAdjust

    m = _impl()
    a = m.FakeDailyBarsSource()
    b = m.FakeDailyBarsSource()
    ra = a.fetch([CODE_A], OPEN_10, OPEN_10, BarAdjust.NONE)
    rb = b.fetch([CODE_A], OPEN_10, OPEN_10, BarAdjust.NONE)
    assert ra == rb or (ra.bars == rb.bars and ra.gaps == rb.gaps)
    bar = ra.bars[0]
    assert bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
    assert abs(bar.close / bar.pre_close - 1) <= 0.2
    assert bar.volume == 10000


def test_impl_a_imports_no_b_module() -> None:
    """§7 ⑦ :304。按 import 口径禁止实现单 B 的模块，不把文档字符串里的说明当成引用。"""
    banned = (
        "app.marketdata.daily_snapshot",
        "app.workers.daily",
    )
    path = APP_ROOT / "marketdata/daily_bars.py"
    assert path.is_file()
    imported = _imported_modules(path)
    imported |= _imported_modules(Path(__file__))
    for name in banned:
        assert name not in imported
        assert not any(item == name or item.startswith(name + ".") for item in imported)


def test_impl_a_has_no_network_imports() -> None:
    """T-A131 补4：顶层不得导入 egress、netguard、socket 或 HTTP 库。"""
    forbidden = {
        "app.ingest.egress",
        "app.ingest.netguard",
        "socket",
        "httpx",
        "requests",
        "urllib.request",
    }
    path = APP_ROOT / "marketdata/daily_bars.py"
    imported = _imported_modules(path, top_level=True)
    hits = set()
    for name in imported:
        for bad in forbidden:
            if name == bad or name.startswith(bad + "."):
                hits.add(name)
    assert not hits


# ---------------------------------------------------------------------------
# 需要临时库的验收
# ---------------------------------------------------------------------------


def test_daily_bars_default_off_no_writes(temp_db: SimpleNamespace, no_egress: None) -> None:
    """A-1 / §5.A :130；「返回 0」只断言 int 0（§7 :335）。"""
    settings = _settings(app_env="test", daily_bars_source="off", database_url=temp_db.url)
    fn = _task_from_jobs()
    before = len(_pipeline_rows(temp_db.engine))
    result = fn(settings, trade_date=OPEN_10.isoformat())
    assert result == 0
    assert isinstance(result, int)
    assert _daily_bar_count(temp_db.engine) == 0
    run = _latest_run(temp_db.engine)
    assert run.status == "skipped"
    issues = (run.stats or {}).get("issues") or []
    assert "daily_bars_source_off" in issues
    assert len(_pipeline_rows(temp_db.engine)) == before + 1


def test_fake_no_bars_for_day(temp_db: SimpleNamespace, no_egress: None) -> None:
    """A-3 / §5.A :132。missing 等于全部标的（§7 :277）。"""
    m = _impl()
    source = m.FakeDailyBarsSource(missing=frozenset({CODE_A, CODE_B, CODE_C, CODE_D}))
    with temp_db.engine.begin() as conn:
        inserted = m.fetch_and_record(
            conn, source, trade_date=OPEN_10, user_id=temp_db.u1, window_trading_days=None
        )
    assert inserted == 0
    assert _daily_bar_count(temp_db.engine) == 0
    run = _latest_run(temp_db.engine)
    assert run.status == "partial"
    issues = (run.stats or {}).get("issues") or []
    for code in (CODE_A, CODE_B):
        assert f"daily_bars_missing:{code}" in issues


def test_fake_partial_codes_missing(temp_db: SimpleNamespace, no_egress: None) -> None:
    """A-4 / §5.A :133。"""
    m = _impl()
    source = m.FakeDailyBarsSource(missing=frozenset({CODE_B}))
    with temp_db.engine.begin() as conn:
        m.fetch_and_record(
            conn, source, trade_date=OPEN_10, user_id=temp_db.u1, window_trading_days=None
        )
    # u1 持 A、B、D；D 为 etf 应被资格过滤，B missing，故只写 A
    with temp_db.engine.connect() as conn:
        from app.db.tables.market import daily_bars

        rows = conn.execute(select(daily_bars)).all()
    codes = {r.code for r in rows}
    assert CODE_A in codes
    assert CODE_B not in codes
    run = _latest_run(temp_db.engine)
    assert run.status == "partial"
    issues = (run.stats or {}).get("issues") or []
    assert f"daily_bars_missing:{CODE_B}" in issues


def test_fake_source_deterministic_and_idempotent(temp_db: SimpleNamespace) -> None:
    """A-5 / §5.A :134。"""
    m = _impl()
    source = m.FakeDailyBarsSource()
    with temp_db.engine.begin() as conn:
        first = m.fetch_and_record(
            conn, source, trade_date=OPEN_10, user_id=temp_db.u2, window_trading_days=None
        )
    assert first >= 1
    with temp_db.engine.connect() as conn:
        from app.db.tables.market import daily_bars

        rows1 = conn.execute(select(daily_bars)).all()
        seen = {(r.code, r.trade_date, r.adj_type, r.fetched_at) for r in rows1}
    issues_after_first = set(((_latest_run(temp_db.engine).stats or {}).get("issues") or []))
    with temp_db.engine.begin() as conn:
        second = m.fetch_and_record(
            conn, source, trade_date=OPEN_10, user_id=temp_db.u2, window_trading_days=None
        )
    assert second == 0
    with temp_db.engine.connect() as conn:
        from app.db.tables.market import daily_bars

        rows2 = conn.execute(select(daily_bars)).all()
    assert {(r.code, r.trade_date, r.adj_type, r.fetched_at) for r in rows2} == seen
    # TODO(T-T70 剩余): 「unchanged=全部」落在返回 int 还是须另调 upsert，§5.A 与 §7 返回 int 并立。
    run = _latest_run(temp_db.engine)
    assert int((run.stats or {}).get("unchanged") or 0) == len(rows1)
    assert int((run.stats or {}).get("inserted") or 0) == 0
    new_issues = set((run.stats or {}).get("issues") or []) - issues_after_first
    assert not new_issues


def test_upsert_conflict_never_overwrites(temp_db: SimpleNamespace) -> None:
    """A-6 / §5.A :135。"""
    m = _impl()
    t0 = dt.datetime(2026, 11, 10, 8, 0, tzinfo=dt.UTC)
    bar_kw = dict(
        code=CODE_A,
        trade_date=OPEN_10,
        open=10,
        high=11,
        low=9,
        close=10,
        pre_close=10,
        volume=10000,
        amount=100000,
        adj_type="none",
        is_suspended=False,
    )
    first = m.DailyBarsResult(bars=[m.DailyBar(**bar_kw)], gaps=[], halted=None)
    second_kw = dict(bar_kw, close=12)
    second = m.DailyBarsResult(bars=[m.DailyBar(**second_kw)], gaps=[], halted=None)
    with temp_db.engine.begin() as conn:
        m.upsert_daily_bars(conn, first, source="fake", licence_id=None, fetched_at=t0)
    with temp_db.engine.begin() as conn:
        stats = m.upsert_daily_bars(
            conn,
            second,
            source="fake",
            licence_id=None,
            fetched_at=dt.datetime(2026, 11, 10, 9, 0, tzinfo=dt.UTC),
        )
    with temp_db.engine.connect() as conn:
        from app.db.tables.market import daily_bars

        row = conn.execute(
            select(daily_bars).where(
                daily_bars.c.code == CODE_A,
                daily_bars.c.trade_date == OPEN_10,
                daily_bars.c.adj_type == "none",
            )
        ).one()
    assert str(row.close).startswith("10")
    assert row.fetched_at == t0 or row.fetched_at == t0.replace(tzinfo=None)
    issue = f"daily_bar_conflict:{CODE_A}:{OPEN_10}"
    assert issue in tuple(stats.issues)


def test_non_trading_day_noop_and_calendar_not_covered(temp_db: SimpleNamespace, no_egress: None) -> None:
    """A-8 / §5.A :137；§7 ⑧ :315。"""
    settings = _settings(app_env="test", daily_bars_source="fake", database_url=temp_db.url)
    fn = _task_from_jobs()
    before = len(_pipeline_rows(temp_db.engine))
    closed = fn(settings, trade_date=CLOSED_08.isoformat())
    assert closed == 0
    assert _daily_bar_count(temp_db.engine) == 0
    assert len(_pipeline_rows(temp_db.engine)) == before
    missing = fn(settings, trade_date=UNCOVERED_11.isoformat())
    assert missing == 0
    assert _daily_bar_count(temp_db.engine) == 0
    run = _latest_run(temp_db.engine)
    assert run.status == "skipped"
    assert (run.stats or {}).get("issues") == ["calendar_not_covered"]


def test_suspended_placeholder_row_written(temp_db: SimpleNamespace) -> None:
    """§7 ⑦ :303（取代 §5.A :138 的快照用例，不导入 B）。"""
    m = _impl()
    source = m.FakeDailyBarsSource(suspended=frozenset({CODE_B}))
    with temp_db.engine.begin() as conn:
        m.fetch_and_record(
            conn, source, trade_date=OPEN_10, user_id=temp_db.u1, window_trading_days=None
        )
    with temp_db.engine.connect() as conn:
        from app.db.tables.market import daily_bars

        row = conn.execute(
            select(daily_bars).where(daily_bars.c.code == CODE_B, daily_bars.c.trade_date == OPEN_10)
        ).one()
    assert row.is_suspended is True
    assert row.open is None and row.high is None and row.low is None and row.close is None
    assert row.pre_close is None and row.volume is None and row.amount is None
    assert row.source == "fake"
    run = _latest_run(temp_db.engine)
    assert int((run.stats or {}).get("suspended") or 0) == 1
    issues = (run.stats or {}).get("issues") or []
    assert f"daily_bars_missing:{CODE_B}" not in issues
    assert run.status == "ok"


def test_universe_holdings_only_until_clarified(temp_db: SimpleNamespace) -> None:
    """A-10 / §7 :348 与 T-A131 补2/补3：列表相等 sorted([A, B])；排除 D/E/F 与 listing_status 为空的 G。"""
    m = _impl()
    with temp_db.engine.begin() as conn:
        _seed_universe_extras(conn, temp_db)
        got = m.daily_universe(conn, temp_db.u1, OPEN_10)
    assert got == sorted([CODE_A, CODE_B])
    assert CODE_D not in got
    assert CODE_E not in got
    assert CODE_F not in got
    assert CODE_G not in got


def test_task_user_scope_union_and_single(temp_db: SimpleNamespace) -> None:
    """§7 ① :206。"""
    from app.db.tables.market import daily_bars

    settings = _settings(app_env="test", daily_bars_source="fake", database_url=temp_db.url)
    fn = _task_from_jobs()
    n = fn(settings, trade_date=OPEN_10.isoformat())
    assert n == 3
    with temp_db.engine.connect() as conn:
        codes = {r.code for r in conn.execute(select(daily_bars)).all()}
    assert codes == {CODE_A, CODE_B, CODE_C}
    with temp_db.engine.begin() as conn:
        conn.execute(text("DELETE FROM market.daily_bars"))
    n2 = fn(settings, trade_date=OPEN_10.isoformat(), user_id=str(temp_db.u1))
    assert n2 == 2
    with temp_db.engine.connect() as conn:
        codes = {r.code for r in conn.execute(select(daily_bars)).all()}
    assert codes == {CODE_A, CODE_B}


def test_mairui_before_c_is_inert(temp_db: SimpleNamespace, no_egress: None) -> None:
    """§7 ① :207。"""
    settings = _settings(app_env="test", daily_bars_source="mairui", database_url=temp_db.url)
    fn = _task_from_jobs()
    result = fn(settings, trade_date=OPEN_10.isoformat())
    assert result == 0
    assert _daily_bar_count(temp_db.engine) == 0
    run = _latest_run(temp_db.engine)
    assert run.status == "skipped"
    assert "daily_bars_http_budget_unset" in ((run.stats or {}).get("issues") or [])


def test_task_without_database_url_raises_no_write() -> None:
    """T-A131 补6：显式 database_url=None 时任务抛 RuntimeError；本例不连库。"""
    settings = _settings(app_env="test", daily_bars_source="fake", database_url=None)
    fn = _task_from_jobs()
    with pytest.raises(RuntimeError):
        fn(settings, trade_date=OPEN_10.isoformat())


def test_single_day_when_no_window(temp_db: SimpleNamespace) -> None:
    """§7 ② :219。持仓 1 只用 u2。"""
    from app.db.tables.market import daily_bars

    m = _impl()
    source = m.FakeDailyBarsSource()
    with temp_db.engine.begin() as conn:
        m.fetch_and_record(
            conn, source, trade_date=OPEN_10, user_id=temp_db.u2, window_trading_days=None
        )
    with temp_db.engine.connect() as conn:
        rows = conn.execute(select(daily_bars)).all()
    assert len(rows) == 1
    assert rows[0].trade_date == OPEN_10
    assert rows[0].code == CODE_C


def test_window_backfills_open_days_only(temp_db: SimpleNamespace) -> None:
    """§7 ② :220。"""
    from app.db.tables.market import daily_bars

    m = _impl()
    source = m.FakeDailyBarsSource()
    with temp_db.engine.begin() as conn:
        m.fetch_and_record(
            conn, source, trade_date=OPEN_10, user_id=temp_db.u2, window_trading_days=3
        )
    with temp_db.engine.connect() as conn:
        dates = {r.trade_date for r in conn.execute(select(daily_bars)).all()}
    assert dates == {OPEN_06, OPEN_09, OPEN_10}


def test_window_exceeds_calendar_records_not_covered(temp_db: SimpleNamespace) -> None:
    """§7 ② :221。"""
    m = _impl()
    source = m.FakeDailyBarsSource()
    with temp_db.engine.begin() as conn:
        n = m.fetch_and_record(
            conn, source, trade_date=OPEN_10, user_id=temp_db.u2, window_trading_days=10
        )
    assert n == 0
    assert _daily_bar_count(temp_db.engine) == 0
    issues = (_latest_run(temp_db.engine).stats or {}).get("issues") or []
    assert "calendar_not_covered" in issues


def test_window_non_positive_rejected(temp_db: SimpleNamespace) -> None:
    """§7 ② :222。"""
    m = _impl()
    source = m.FakeDailyBarsSource()
    before = len(_pipeline_rows(temp_db.engine))
    for n in (0, -1):
        with pytest.raises(ValueError):
            with temp_db.engine.begin() as conn:
                m.fetch_and_record(
                    conn, source, trade_date=OPEN_10, user_id=temp_db.u2, window_trading_days=n
                )
        assert _daily_bar_count(temp_db.engine) == 0
        assert len(_pipeline_rows(temp_db.engine)) == before


def test_migration_adds_nullable_columns_single_head(temp_db: SimpleNamespace) -> None:
    """§7 ④ :245。fixture 已 upgrade head；本例断言 4 列与 CHECK。"""
    with temp_db.engine.connect() as conn:
        cols = {
            r[0]: r
            for r in conn.execute(
                text(
                    "SELECT column_name, is_nullable, data_type "
                    "FROM information_schema.columns "
                    "WHERE table_schema='market' AND table_name='daily_bars'"
                )
            ).all()
        }
        for name in ("pre_close", "is_suspended", "source", "source_licence_id"):
            assert name in cols
            assert cols[name][1] == "YES"
        conn.execute(
            text(
                "INSERT INTO market.daily_bars(code, trade_date, adj_type) "
                "VALUES ('600001.SH', '2026-11-10', 'none')"
            )
        )
        conn.commit()
        with pytest.raises(Exception):  # noqa: BLE001  # CHECK 拒绝非法 source
            with temp_db.engine.begin() as c2:
                c2.execute(
                    text(
                        "INSERT INTO market.daily_bars(code, trade_date, adj_type, source) "
                        "VALUES ('301002.SZ', '2026-11-10', 'none', 'legacy')"
                    )
                )


def test_upsert_requires_source(temp_db: SimpleNamespace) -> None:
    """§7 ④ :246。"""
    m = _impl()
    bar = m.DailyBar(
        code=CODE_A,
        trade_date=OPEN_10,
        open=10,
        high=11,
        low=9,
        close=10,
        pre_close=10,
        volume=10000,
        amount=100000,
        adj_type="none",
        is_suspended=False,
    )
    result = m.DailyBarsResult(bars=[bar], gaps=[], halted=None)
    with pytest.raises(ValueError):
        with temp_db.engine.begin() as conn:
            m.upsert_daily_bars(
                conn, result, source=None, licence_id=None, fetched_at=dt.datetime.now(dt.UTC)
            )
    assert _daily_bar_count(temp_db.engine) == 0


def test_downgrade_refuses_when_sourced_rows_exist(temp_db: SimpleNamespace) -> None:
    """§7 ④ :247。"""
    m = _impl()
    source = m.FakeDailyBarsSource()
    with temp_db.engine.begin() as conn:
        m.fetch_and_record(
            conn, source, trade_date=OPEN_10, user_id=temp_db.u2, window_trading_days=None
        )
    assert _daily_bar_count(temp_db.engine) >= 1
    url_str = temp_db.url.render_as_string(hide_password=False)
    cfg = _alembic_config(url_str)
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    down = script.get_revision(head).down_revision
    with pytest.raises(Exception):  # noqa: BLE001
        command.downgrade(cfg, down)
    with temp_db.engine.connect() as conn:
        assert _daily_bar_count(temp_db.engine) >= 1
        cols = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='market' AND table_name='daily_bars' "
                "AND column_name IN ('pre_close','is_suspended','source','source_licence_id')"
            )
        ).scalars().all()
        assert set(cols) == {"pre_close", "is_suspended", "source", "source_licence_id"}
    # 无来源行时 downgrade 成功
    with temp_db.engine.begin() as conn:
        conn.execute(text("DELETE FROM market.daily_bars"))
    command.downgrade(cfg, down)
    with temp_db.engine.connect() as conn:
        cols = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='market' AND table_name='daily_bars' "
                "AND column_name IN ('pre_close','is_suspended','source','source_licence_id')"
            )
        ).scalars().all()
        assert cols == []


def test_normal_row_is_suspended_false(temp_db: SimpleNamespace) -> None:
    """§7 ④ :248。"""
    m = _impl()
    source = m.FakeDailyBarsSource()
    with temp_db.engine.begin() as conn:
        m.fetch_and_record(
            conn, source, trade_date=OPEN_10, user_id=temp_db.u2, window_trading_days=None
        )
    with temp_db.engine.connect() as conn:
        from app.db.tables.market import daily_bars

        row = conn.execute(select(daily_bars).where(daily_bars.c.code == CODE_C)).one()
    assert row.is_suspended is False


def test_upsert_stats_fields_and_equal_after_quantize(temp_db: SimpleNamespace) -> None:
    """§7 ⑤ :267。"""
    m = _impl()
    t0 = dt.datetime(2026, 11, 10, 8, 0, tzinfo=dt.UTC)
    kw = dict(
        code=CODE_A,
        trade_date=OPEN_10,
        open=10,
        high=11,
        low=9,
        close=10.1234,
        pre_close=10,
        volume=10000,
        amount=101234,
        adj_type="none",
        is_suspended=False,
    )
    first = m.DailyBarsResult(bars=[m.DailyBar(**kw)], gaps=[], halted=None)
    second = m.DailyBarsResult(bars=[m.DailyBar(**dict(kw, close=10.12340))], gaps=[], halted=None)
    with temp_db.engine.begin() as conn:
        m.upsert_daily_bars(conn, first, source="fake", licence_id=None, fetched_at=t0)
    with temp_db.engine.begin() as conn:
        stats = m.upsert_daily_bars(conn, second, source="fake", licence_id=None, fetched_at=t0)
    assert stats.inserted == 0 and stats.unchanged == 1 and stats.conflicts == 0


def test_same_values_different_source_is_unchanged(temp_db: SimpleNamespace) -> None:
    """§7 ⑤ :268。"""
    m = _impl()
    t0 = dt.datetime(2026, 11, 10, 8, 0, tzinfo=dt.UTC)
    kw = dict(
        code=CODE_A,
        trade_date=OPEN_10,
        open=10,
        high=11,
        low=9,
        close=10,
        pre_close=10,
        volume=10000,
        amount=100000,
        adj_type="none",
        is_suspended=False,
    )
    first = m.DailyBarsResult(bars=[m.DailyBar(**kw)], gaps=[], halted=None)
    with temp_db.engine.begin() as conn:
        m.upsert_daily_bars(conn, first, source="fake", licence_id=None, fetched_at=t0)
    with temp_db.engine.begin() as conn:
        stats = m.upsert_daily_bars(
            conn, first, source="mairui", licence_id=uuid.uuid4(), fetched_at=t0
        )
    assert stats.unchanged == 1
    with temp_db.engine.connect() as conn:
        from app.db.tables.market import daily_bars

        row = conn.execute(select(daily_bars).where(daily_bars.c.code == CODE_A)).one()
    assert row.source == "fake"


def test_run_row_stats_shape(temp_db: SimpleNamespace) -> None:
    """§7 ⑤ :269。"""
    m = _impl()
    source = m.FakeDailyBarsSource(missing=frozenset({CODE_B}))
    before = len(_pipeline_rows(temp_db.engine))
    with temp_db.engine.begin() as conn:
        m.fetch_and_record(
            conn, source, trade_date=OPEN_10, user_id=temp_db.u1, window_trading_days=None
        )
    assert len(_pipeline_rows(temp_db.engine)) == before + 1
    run = _latest_run(temp_db.engine)
    assert run.step == "daily_bars.fetch"
    assert run.status == "partial"
    assert set((run.stats or {}).keys()) == STATS_KEYS
    assert f"daily_bars_missing:{CODE_B}" in ((run.stats or {}).get("issues") or [])


def test_off_recorded_even_on_closed_day(temp_db: SimpleNamespace) -> None:
    """§7 ⑧ :316。"""
    settings = _settings(app_env="test", daily_bars_source="off", database_url=temp_db.url)
    fn = _task_from_jobs()
    n = fn(settings, trade_date=CLOSED_08.isoformat())
    assert n == 0
    run = _latest_run(temp_db.engine)
    assert run.status == "skipped"
    assert "daily_bars_source_off" in ((run.stats or {}).get("issues") or [])


def test_licence_id_none_written_as_null(temp_db: SimpleNamespace) -> None:
    """§7 ⑨ :323。"""
    m = _impl()
    source = m.FakeDailyBarsSource()
    with temp_db.engine.begin() as conn:
        m.fetch_and_record(
            conn, source, trade_date=OPEN_10, user_id=temp_db.u2, window_trading_days=None
        )
    with temp_db.engine.connect() as conn:
        from app.db.tables.market import daily_bars

        row = conn.execute(select(daily_bars).where(daily_bars.c.code == CODE_C)).one()
    assert row.source_licence_id is None


def test_licence_id_empty_string_rejected(temp_db: SimpleNamespace) -> None:
    """§7 ⑨ :324。空串 TypeError，不规范化。"""
    m = _impl()
    bar = m.DailyBar(
        code=CODE_A,
        trade_date=OPEN_10,
        open=10,
        high=11,
        low=9,
        close=10,
        pre_close=10,
        volume=10000,
        amount=100000,
        adj_type="none",
        is_suspended=False,
    )
    result = m.DailyBarsResult(bars=[bar], gaps=[], halted=None)
    with pytest.raises(TypeError):
        with temp_db.engine.begin() as conn:
            m.upsert_daily_bars(
                conn, result, source="fake", licence_id="", fetched_at=dt.datetime.now(dt.UTC)
            )
    assert _daily_bar_count(temp_db.engine) == 0
