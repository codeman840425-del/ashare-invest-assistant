# ruff: noqa: S101, ANN401, S603, S607, S106, PT018, E501, I001
"""T-B130：单 C，HTTP_UNLIMITED 哨兵与日 K HTTP 预算。

契约只读参照 ``git show 7234aa7:docs/contracts/daily-bars-source.md`` §8.1 / §8.5。
隔离 PG：仅在 o61-pg 127.0.0.1:55461 自建临时库，用后删除。
不连接、不删除 o53/o55/o57/o60、tt51_tpl、o61_tmp_0030。
本单不切换哨兵、不提供切换入口、不加 U3、不读证书、不真调麦蕊。
"""

from __future__ import annotations

import ast
import datetime as dt
import inspect
import ipaddress
import json
import os
import re
import socket
import subprocess
import uuid
from argparse import Namespace
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy import create_engine, func, insert, select
from sqlalchemy.engine import Engine, URL

from app.config import Settings
from app.db.migration_check import BACKEND
from app.db.tables.accounts import (
    accounts,
    broker_position_snapshot_items,
    broker_position_snapshots,
    import_batches,
)
from app.db.tables.market import daily_bars, securities, trading_calendar
from app.db.tables.realtime import pipeline_runs
from app.db.tables.users import users
from app.marketdata.daily_bars import DailyBar
from app.master.daily_delivery import DAILY_HTTP_LIMIT, live_budget_issue

HOST = "127.0.0.1"
PORT = 55461
USER = "postgres"
FORBIDDEN_DBS = frozenset({"tt51_tpl", "o61_tmp_0030"})
_SAFE_TMP = re.compile(r"^o61_tmp_b130_[a-z0-9]+$")
_O61 = "o61-pg"

CODES = (
    "600000.SH",
    "600001.SH",
    "600002.SH",
    "600003.SH",
    "600004.SH",
)
DAY = dt.date(2026, 11, 10)
BEIJING = dt.timezone(dt.timedelta(hours=8))
AT = dt.datetime(2026, 11, 10, 15, 0, tzinfo=BEIJING)
OWNER = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")


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


def _admin() -> Any:
    return psycopg.connect(
        host=HOST, port=PORT, user=USER, dbname="postgres", autocommit=True
    )


def _url(dbname: str) -> URL:
    return URL.create(
        "postgresql+psycopg", username=USER, password=None, host=HOST, port=PORT, database=dbname
    )


def _create_temp_db() -> str:
    _require_o61()
    name = "o61_tmp_b130_" + uuid.uuid4().hex[:10]
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


def _settings(url: URL, *, source: str = "mairui") -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        daily_bars_source=source,  # type: ignore[arg-type]
        database_url=SecretStr(url.render_as_string(hide_password=False)),
        redis_url="redis://127.0.0.1:9/0",
        session_cookie_secure=False,
    )


def _is_loopback_host(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in {"localhost", ""}


def _host_of(address: Any) -> str:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return ""


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
        return 111

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_ex)

    def blocked_mairui_get(*args: Any, **kwargs: Any) -> Any:
        counts["mairui_get"] += 1
        raise AssertionError("mairui_get must not be called in T-B130")

    try:
        import app.ingest.egress as egress

        monkeypatch.setattr(egress, "mairui_get", blocked_mairui_get)
    except Exception:
        pass
    counts["blocked"] = blocked
    return counts


def _seed_world(conn: Any) -> None:
    conn.execute(insert(trading_calendar).values(date=DAY, is_open=True))
    conn.execute(
        insert(users).values(
            id=OWNER,
            username="owner_b130",
            display_name="owner_b130",
            role="user",
            status="approved",
            password_hash="x",
        )
    )
    for code in CODES:
        conn.execute(
            insert(securities).values(
                code=code,
                type="stock",
                name="合成" + code[:6],
                exchange="SH",
                board="main",
                listing_status="listed",
            )
        )
    account, batch, snapshot = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn.execute(insert(accounts).values(id=account, user_id=OWNER, name="b130"))
    conn.execute(
        insert(import_batches).values(
            id=batch, user_id=OWNER, account_id=account, status="committed", kind="positions"
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
    for code in CODES:
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


@pytest.fixture(scope="module")
def world() -> Iterator[Any]:
    name = _create_temp_db()
    url = _url(name)
    try:
        _upgrade(url, "head")
        engine = create_engine(url)
        with engine.begin() as conn:
            _seed_world(conn)
        box = Namespace(engine=engine, url=url, name=name, settings=_settings(url))
        yield box
        engine.dispose()
    finally:
        _drop_temp_db(name)


@pytest.fixture
def db(world: Any) -> Iterator[Any]:
    with world.engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()


def _bar(code: str, day: dt.date) -> DailyBar:
    px = Decimal("10.0000")
    return DailyBar(
        code=code,
        trade_date=day,
        adj_type="none",
        open=px,
        high=px,
        low=px,
        close=px,
        pre_close=px,
        volume=Decimal("10000"),
        amount=Decimal("100000.0000"),
        is_suspended=False,
    )


def _ok_transport(calls: list[tuple[str, dt.date, dt.date]]) -> Callable[..., Any]:
    def transport(code: str, start: dt.date, end: dt.date) -> tuple[int, DailyBar]:
        calls.append((code, start, end))
        return 200, _bar(code, start)

    return transport


def _status_on(
    nth: int, status: int, calls: list[tuple[str, dt.date, dt.date]]
) -> Callable[..., Any]:
    def transport(code: str, start: dt.date, end: dt.date) -> tuple[int, DailyBar | None]:
        calls.append((code, start, end))
        if len(calls) == nth:
            return status, None
        return 200, _bar(code, start)

    return transport


def _issues(conn: Any) -> list[str]:
    row = conn.execute(
        select(pipeline_runs.c.stats, pipeline_runs.c.status).order_by(pipeline_runs.c.finished_at.desc())
    ).first()
    assert row is not None
    stats = row.stats if isinstance(row.stats, dict) else json.loads(row.stats)
    return list(stats.get("issues") or [])


def _bar_count(conn: Any) -> int:
    return int(conn.execute(select(func.count()).select_from(daily_bars)).scalar_one())


def _run(
    conn: Any,
    *,
    transport: Callable[..., Any],
    tmp_path: Path,
    grant: object | None = object(),
    stop: bool = False,
    halt: bool = False,
    clock: Callable[[], dt.datetime] | None = None,
) -> int:
    from app.ingest.daily_bars import fetch_mairui_daily_bars

    stop_path = tmp_path / "STOP"
    halt_path = tmp_path / "mairui-daily-bars.HALTED"
    if stop:
        stop_path.write_text("stop", encoding="utf-8")
    if halt:
        halt_path.write_text("halt", encoding="utf-8")

    def grant_reader() -> object | None:
        return grant

    return fetch_mairui_daily_bars(
        conn,
        trade_date=DAY,
        user_id=OWNER,
        transport=transport,
        stop_path=stop_path,
        halt_path=halt_path,
        grant_reader=grant_reader,
        clock=clock or (lambda: dt.datetime(2026, 11, 10, 17, 20, tzinfo=BEIJING)),
    )


def test_daily_http_limit_unchanged() -> None:
    from app.ingest.daily_bars import DAILY_BARS_HTTP_LIMIT, DAILY_BARS_HTTP_UNLIMITED

    assert DAILY_HTTP_LIMIT == 1
    assert live_budget_issue() == "daily_http_budget_unresolved"
    assert DAILY_BARS_HTTP_LIMIT == 0
    assert type(DAILY_BARS_HTTP_LIMIT) is int
    assert DAILY_BARS_HTTP_UNLIMITED == "unlimited"


def test_http_budget_resolution_table() -> None:
    from app.ingest.daily_bars import (
        DAILY_BARS_HTTP_UNLIMITED,
        DailyBarsBudget,
        daily_bars_http_budget,
    )

    cases: list[tuple[object, DailyBarsBudget]] = [
        (0, DailyBarsBudget(kind="unset")),
        (DAILY_BARS_HTTP_UNLIMITED, DailyBarsBudget(kind="unlimited")),
        (3, DailyBarsBudget(kind="capped", cap=3)),
        (-1, DailyBarsBudget(kind="unset")),
        (True, DailyBarsBudget(kind="unset")),
        (None, DailyBarsBudget(kind="unset")),
        ("0", DailyBarsBudget(kind="unset")),
        (2.0, DailyBarsBudget(kind="unset")),
    ]
    for value, expected in cases:
        assert daily_bars_http_budget(value) == expected, value


def test_no_switch_entry_and_not_settings() -> None:
    from app.config import Settings as SettingsType
    from app.ingest import daily_bars as ibars

    fields = getattr(SettingsType, "model_fields", {})
    assert "daily_bars_http_limit" not in fields
    assert "daily_bars_http_unlimited" not in fields
    assert ibars.DAILY_BARS_HTTP_LIMIT == 0
    src = Path(inspect.getsourcefile(ibars) or "")
    text = src.read_text(encoding="utf-8")
    assert "DAILY_BARS_HTTP_LIMIT" in text
    # 生产源码不得把限额写成正整数或哨兵；切换属于开放单 D。
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "DAILY_BARS_HTTP_LIMIT" in names:
                assert isinstance(node.value, ast.Constant) and node.value.value == 0
    cli = Path(__file__).resolve().parents[1] / "app/cli/daily_bars_backfill.py"
    cli_text = cli.read_text(encoding="utf-8")
    assert "HTTP_UNLIMITED" not in cli_text
    assert "DAILY_BARS_HTTP_LIMIT" not in cli_text


def test_marketdata_daily_bars_no_top_level_egress() -> None:
    path = Path(__file__).resolve().parents[1] / "app/marketdata/daily_bars.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    banned = {
        "socket",
        "httpx",
        "requests",
        "urllib.request",
        "app.ingest.egress",
        "app.ingest.netguard",
    }
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in banned
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod not in banned
            if mod.startswith("urllib"):
                raise AssertionError(mod)


def test_load_inputs_uses_final_after() -> None:
    from app.marketdata.daily_snapshot import FINAL_AFTER
    from app.reports import dimensions

    src = inspect.getsource(dimensions.load_inputs)
    assert "FINAL_AFTER" in src
    assert "dt.time(17, 10)" not in src
    assert FINAL_AFTER == dt.time(17, 10)


def test_dead_try_removed_from_build_owned_snapshot() -> None:
    from app.marketdata import daily_snapshot

    src = inspect.getsource(daily_snapshot.build_owned_snapshot)
    assert "except AppError" not in src
    assert "is_open = covered(" in src


def test_limit_not_widened_by_env_or_receipt(
    world: Any, db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_egress: Any
) -> None:
    from app.ingest.daily_bars import DAILY_BARS_HTTP_LIMIT, fetch_mairui_daily_bars

    monkeypatch.setenv("DAILY_BARS_HTTP_LIMIT", "9999")
    receipt = tmp_path / "mairui-daily-bars.json"
    receipt.write_text(json.dumps({"limit": 9999, "kind": "mairui_daily_bars"}), encoding="utf-8")
    calls: list[Any] = []
    written = fetch_mairui_daily_bars(
        db,
        trade_date=DAY,
        user_id=OWNER,
        transport=_ok_transport(calls),
        stop_path=tmp_path / "STOP",
        halt_path=tmp_path / "HALT",
        grant_reader=lambda: {"limit": 9999},
        clock=lambda: dt.datetime(2026, 11, 10, 17, 20, tzinfo=BEIJING),
    )
    assert DAILY_BARS_HTTP_LIMIT == 0
    assert os.environ["DAILY_BARS_HTTP_LIMIT"] == "9999"
    assert written == 0
    assert calls == []
    assert "daily_bars_http_budget_unset" in _issues(db)
    assert _bar_count(db) == 0
    assert no_egress["mairui_get"] == 0


def test_mairui_requires_receipt_and_budget(
    world: Any, db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_egress: Any
) -> None:
    from app.ingest import daily_bars as ibars

    calls: list[Any] = []
    written = _run(db, transport=_ok_transport(calls), tmp_path=tmp_path, grant=None)
    # 默认限额 0：即使缺回执，也记 unset，零写入。
    assert written == 0 and calls == []
    assert "daily_bars_http_budget_unset" in _issues(db)
    assert _bar_count(db) == 0

    monkeypatch.setattr(ibars, "DAILY_BARS_HTTP_LIMIT", ibars.DAILY_BARS_HTTP_UNLIMITED)
    calls = []
    written = _run(db, transport=_ok_transport(calls), tmp_path=tmp_path, grant=None)
    assert written == 0 and calls == []
    assert "data_licence_unavailable" in _issues(db)
    assert _bar_count(db) == 0
    assert no_egress["mairui_get"] == 0


def test_unlimited_no_cap_calls_equal_planned(
    world: Any, db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_egress: Any
) -> None:
    from app.ingest import daily_bars as ibars

    monkeypatch.setattr(ibars, "DAILY_BARS_HTTP_LIMIT", ibars.DAILY_BARS_HTTP_UNLIMITED)
    calls: list[Any] = []
    written = _run(db, transport=_ok_transport(calls), tmp_path=tmp_path)
    assert len(calls) == 5
    assert written == 5
    assert _bar_count(db) == 5
    assert "daily_bars_quota_deferred" not in _issues(db)
    assert no_egress["mairui_get"] == 0


def test_budget_cap_reached_defers_rest(
    world: Any, db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_egress: Any
) -> None:
    from app.ingest import daily_bars as ibars

    monkeypatch.setattr(ibars, "DAILY_BARS_HTTP_LIMIT", 2)
    calls: list[Any] = []
    written = _run(db, transport=_ok_transport(calls), tmp_path=tmp_path)
    assert len(calls) == 2
    assert written == 2
    issues = _issues(db)
    assert issues.count("daily_bars_quota_deferred") == 3
    assert no_egress["mairui_get"] == 0


def test_unlimited_still_halts_on_stop_103_429(
    world: Any, db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_egress: Any
) -> None:
    from app.ingest import daily_bars as ibars

    monkeypatch.setattr(ibars, "DAILY_BARS_HTTP_LIMIT", ibars.DAILY_BARS_HTTP_UNLIMITED)

    for status in (103, 429):
        calls: list[Any] = []
        halt_path = tmp_path / f"halt-{status}"
        stop_path = tmp_path / f"stop-{status}"
        written = ibars.fetch_mairui_daily_bars(
            db,
            trade_date=DAY,
            user_id=OWNER,
            transport=_status_on(2, status, calls),
            stop_path=stop_path,
            halt_path=halt_path,
            grant_reader=lambda: object(),
            clock=lambda: dt.datetime(2026, 11, 10, 17, 20, tzinfo=BEIJING),
        )
        assert len(calls) == 2, status
        assert halt_path.is_file(), status
        issues = _issues(db)
        assert "daily_bars_upstream_halted" in issues
        # 第 2 次失败，剩余 4 只（含失败那只）记 halted；已成功 1 行。
        assert issues.count("daily_bars_upstream_halted") == 4
        assert written == 1
        # 下一次 tick：HALT 仍在，0 次，不重试。
        calls2: list[Any] = []
        again = ibars.fetch_mairui_daily_bars(
            db,
            trade_date=DAY,
            user_id=OWNER,
            transport=_ok_transport(calls2),
            stop_path=stop_path,
            halt_path=halt_path,
            grant_reader=lambda: object(),
            clock=lambda: dt.datetime(2026, 11, 10, 17, 20, tzinfo=BEIJING),
        )
        assert calls2 == [] and again == 0
        assert "daily_bars_upstream_halted" in _issues(db)

    calls_stop: list[Any] = []
    written_stop = _run(
        db, transport=_ok_transport(calls_stop), tmp_path=tmp_path, stop=True
    )
    assert calls_stop == [] and written_stop == 0
    assert _issues(db).count("daily_bars_upstream_halted") == 5
    assert no_egress["mairui_get"] == 0


def test_mairui_fetched_at_not_before_last_response(
    world: Any, db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_egress: Any
) -> None:
    from app.ingest import daily_bars as ibars

    monkeypatch.setattr(ibars, "DAILY_BARS_HTTP_LIMIT", ibars.DAILY_BARS_HTTP_UNLIMITED)
    last = dt.datetime(2026, 11, 10, 17, 21, 30, tzinfo=BEIJING)
    seen: list[dt.datetime] = []

    def transport(code: str, start: dt.date, end: dt.date) -> tuple[int, DailyBar]:
        seen.append(last if len(seen) == 4 else last - dt.timedelta(seconds=5 - len(seen)))
        return 200, _bar(code, start)

    def clock() -> dt.datetime:
        return seen[-1]

    written = _run(db, transport=transport, tmp_path=tmp_path, clock=clock)
    assert written == 5
    stamps = list(db.execute(select(daily_bars.c.fetched_at)).scalars().all())
    assert stamps and all(ts >= last for ts in stamps)
    assert no_egress["mairui_get"] == 0


GRANT_CLOCK = dt.datetime(2026, 11, 10, 17, 20, tzinfo=BEIJING)


def _receipt_payload(*, kind: str, user_id: uuid.UUID, start: dt.datetime, end: dt.datetime) -> dict[str, str]:
    return {
        "kind": kind,
        "user_id": str(user_id),
        "licence_id": str(uuid.uuid4()),
        "receipt_id": str(uuid.uuid4()),
        "not_before": start.isoformat(),
        "expires_at": end.isoformat(),
    }


def _write_receipt(path: Path, payload: object) -> Path:
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload),
        encoding="utf-8",
    )
    return path


def _fetch_with_receipt(
    conn: Any,
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
    user_id: uuid.UUID = OWNER,
    clock: dt.datetime = GRANT_CLOCK,
) -> tuple[int, list[Any]]:
    from app.ingest import daily_bars as ibars

    monkeypatch.setattr(ibars, "DAILY_BARS_HTTP_LIMIT", ibars.DAILY_BARS_HTTP_UNLIMITED)
    monkeypatch.setattr(ibars, "_receipt_permission_ok", lambda _path: True)
    receipt = _write_receipt(tmp_path / "mairui-daily-bars.json", payload)
    calls: list[Any] = []
    written = ibars.fetch_mairui_daily_bars(
        conn,
        trade_date=DAY,
        user_id=user_id,
        transport=_ok_transport(calls),
        stop_path=tmp_path / "STOP",
        halt_path=tmp_path / "HALT",
        receipt_path=receipt,
        clock=lambda: clock,
    )
    return written, calls


def _valid_receipt(*, user_id: uuid.UUID = OWNER) -> dict[str, str]:
    from app.ingest.daily_bars import KIND

    return _receipt_payload(
        kind=KIND,
        user_id=user_id,
        start=dt.datetime(2026, 11, 10, 17, 0, tzinfo=BEIJING),
        end=dt.datetime(2026, 11, 10, 18, 0, tzinfo=BEIJING),
    )


def test_receipt_expired_is_rejected(
    world: Any, db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_egress: Any
) -> None:
    from app.ingest.daily_bars import KIND

    payload = _receipt_payload(
        kind=KIND,
        user_id=OWNER,
        start=dt.datetime(2026, 11, 10, 16, 0, tzinfo=BEIJING),
        end=dt.datetime(2026, 11, 10, 17, 20, tzinfo=BEIJING),
    )
    written, calls = _fetch_with_receipt(db, tmp_path=tmp_path, monkeypatch=monkeypatch, payload=payload)
    assert written == 0 and calls == []
    assert "data_licence_unavailable" in _issues(db)
    assert _bar_count(db) == 0
    assert no_egress["mairui_get"] == 0


def test_receipt_wrong_kind_is_rejected(
    world: Any, db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_egress: Any
) -> None:
    payload = _receipt_payload(
        kind="mairui_daily_snapshot",
        user_id=OWNER,
        start=dt.datetime(2026, 11, 10, 17, 0, tzinfo=BEIJING),
        end=dt.datetime(2026, 11, 10, 18, 0, tzinfo=BEIJING),
    )
    written, calls = _fetch_with_receipt(db, tmp_path=tmp_path, monkeypatch=monkeypatch, payload=payload)
    assert written == 0 and calls == []
    assert "data_licence_unavailable" in _issues(db)
    assert _bar_count(db) == 0
    assert no_egress["mairui_get"] == 0


def test_receipt_non_json_is_rejected(
    world: Any, db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_egress: Any
) -> None:
    written, calls = _fetch_with_receipt(
        db, tmp_path=tmp_path, monkeypatch=monkeypatch, payload="this is not json{"
    )
    assert written == 0 and calls == []
    assert "data_licence_unavailable" in _issues(db)
    assert _bar_count(db) == 0
    assert no_egress["mairui_get"] == 0


def test_receipt_user_mismatch_is_rejected(
    world: Any, db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_egress: Any
) -> None:
    from app.ingest.daily_bars import KIND

    payload = _receipt_payload(
        kind=KIND,
        user_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2"),
        start=dt.datetime(2026, 11, 10, 17, 0, tzinfo=BEIJING),
        end=dt.datetime(2026, 11, 10, 18, 0, tzinfo=BEIJING),
    )
    written, calls = _fetch_with_receipt(db, tmp_path=tmp_path, monkeypatch=monkeypatch, payload=payload)
    assert written == 0 and calls == []
    assert "data_licence_unavailable" in _issues(db)
    assert _bar_count(db) == 0
    assert no_egress["mairui_get"] == 0


def test_valid_receipt_still_allows_unlimited_fetch(
    world: Any, db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_egress: Any
) -> None:
    """对照：字段齐全、kind 正确、在有效期内且绑定本人时，unlimited 仍可按计划取数。"""
    written, calls = _fetch_with_receipt(
        db, tmp_path=tmp_path, monkeypatch=monkeypatch, payload=_valid_receipt()
    )
    assert len(calls) == 5
    assert written == 5
    assert no_egress["mairui_get"] == 0
