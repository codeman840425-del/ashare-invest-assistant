# ruff: noqa: S101
"""Shared helpers copied from T-T70 / T-T70b for T-T71 impl-B tests.

T-T70 的 A 套件文件保持不动，断言一字不改。本模块文件名不以 test_ 开头，不会被收集。
"""

from __future__ import annotations

import ipaddress
import socket
import datetime as dt
import uuid
from argparse import Namespace
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = ROOT / "src/backend/app"
MIGRATIONS = ROOT / "src/backend/migrations"
BACKEND_TESTS = Path(__file__).resolve().parent
BEIJING = dt.timezone(dt.timedelta(hours=8))

CODE_A = "600001.SH"
CODE_B = "301002.SZ"
CODE_C = "002001.SZ"
CODE_D = "510981.SH"  # etf
CODE_E = "600981.SH"  # 仅自选
CODE_F = "600991.SH"
CODE_G = "600000.SH"
CODE_H = "830991.BJ"  # 仓库合成夹具（T-T66），board 为空
OPEN_06 = dt.date(2026, 11, 6)
CLOSED_07 = dt.date(2026, 11, 7)
CLOSED_08 = dt.date(2026, 11, 8)
OPEN_09 = dt.date(2026, 11, 9)
OPEN_10 = dt.date(2026, 11, 10)
UNCOVERED_11 = dt.date(2026, 11, 11)

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
    module = __import__("app.marketdata.daily_bars", fromlist=list(_A_SYMBOLS))
    missing = [name for name in _A_SYMBOLS if not hasattr(module, name)]
    if missing:
        raise ImportError(f"app.marketdata.daily_bars 缺少契约符号：{', '.join(missing)}")
    return module


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


def _count(engine: Engine, table: Any) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar_one())


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


def _open_temp_db() -> Iterator[SimpleNamespace]:
    """o61 临时库：模板 0030 → upgrade head → 播种；建库失败则 fail；finally DROP。不打印 DSN。"""
    import sys

    sys.path.insert(0, str(BACKEND_TESTS))
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
    name = validate_temp_db_name("tt71_" + uuid.uuid4().hex[:8])
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
            pytest.fail(f"无法在目标实例上创建临时库：{type(exc).__name__}")
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
    payload: dict[str, Any] = {"app_env": app_env, "_env_file": None}
    if daily_bars_source is not None:
        payload["daily_bars_source"] = daily_bars_source
    if database_url is _MISSING:
        pass
    elif database_url is None:
        payload["database_url"] = None
    else:
        payload["database_url"] = _database_url_text(database_url)
    return Settings(**payload)
