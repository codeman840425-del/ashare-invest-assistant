# ruff: noqa: S101, ANN401, S603, S607, S106, PT018, E501, I001
"""T-B129：日 K 后端 A 补丁（upsert 分批、17:15 槽、回填 CLI、宇宙加自选）。

契约只读参照 ``git show 0e44f77:docs/contracts/daily-bars-source.md`` §8。
隔离 PG：仅在 o61-pg 127.0.0.1:55461 自建临时库，用后删除。
不连接、不删除 o53/o55/o57/o60、tt51_tpl、o61_tmp_0030。
本单不做 DAILY_BARS_HTTP_UNLIMITED / 单 C，不加 U3 参数名。
"""

from __future__ import annotations

import datetime as dt
import io
import ipaddress
import json
import re
import socket
import subprocess
import uuid
from argparse import Namespace
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy import create_engine, event, func, insert, select, text
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
from app.db.tables.research import watchlist_items
from app.db.tables.users import users
from app.workers import jobs as jobs_mod

HOST = "127.0.0.1"
PORT = 55461
USER = "postgres"
FORBIDDEN_DBS = frozenset({"tt51_tpl", "o61_tmp_0030"})
_SAFE_TMP = re.compile(r"^o61_tmp_b129_[a-z0-9]+$")
_O61 = "o61-pg"

CODE_A = "688018.SH"
CODE_B = "688073.SH"
CODE_C = "300364.SZ"
CODE_E = "600000.SH"

DAY_1010 = dt.date(2026, 11, 10)
BEIJING = dt.timezone(dt.timedelta(hours=8))
AT = dt.datetime(2026, 11, 10, 15, 0, tzinfo=BEIJING)
FETCHED = dt.datetime(2026, 11, 10, 17, 15, tzinfo=BEIJING)


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
    name = "o61_tmp_b129_" + uuid.uuid4().hex[:10]
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


def _settings(url: URL, *, source: str = "fake") -> Settings:
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
        raise OSError("blocked non-loopback / non-unix connect_ex")

    def fake_mairui_get(*_a: Any, **_k: Any) -> Any:
        counts["mairui_get"] += 1
        raise RuntimeError("mairui_get must not be called")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_ex)
    monkeypatch.setattr("app.ingest.egress.mairui_get", fake_mairui_get)
    yield counts
    assert blocked == []
    assert counts["mairui_get"] == 0


@pytest.fixture
def temp_db(no_egress: Any) -> Iterator[Engine]:
    name = _create_temp_db()
    url = _url(name)
    engine: Engine | None = None
    try:
        _upgrade(url, "head")
        engine = create_engine(url, future=True)
        yield engine
    finally:
        raw = url.render_as_string(hide_password=False)
        cached = jobs_mod._engines.pop(raw, None)
        if cached is not None:
            cached.dispose()
        if engine is not None:
            engine.dispose()
        _drop_temp_db(name)


def _import_impl() -> Any:
    import app.marketdata.daily_bars as mod

    return mod


def _seed_calendar_span(conn: Any, start: dt.date, end: dt.date, *, hole: dt.date | None = None) -> None:
    cur = start
    while cur <= end:
        if hole is None or cur != hole:
            conn.execute(
                insert(trading_calendar).values(date=cur, is_open=(cur.weekday() < 5))
            )
        cur += dt.timedelta(days=1)


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


def _seed_security(conn: Any, code: str) -> None:
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


def _seed_holding(conn: Any, user_id: uuid.UUID, codes: tuple[str, ...], *, tag: str) -> None:
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


def _make_bars(
    n_codes: int,
    n_days: int,
    *,
    close: Decimal = Decimal("10.0000"),
    start: dt.date = dt.date(2020, 1, 1),
    prefix: int = 600100,
) -> list[Any]:
    mod = _import_impl()
    bars = []
    for i in range(n_codes):
        code = f"{prefix + i:06d}.SH"
        for j in range(n_days):
            day = start + dt.timedelta(days=j)
            bars.append(
                mod.DailyBar(
                    code=code,
                    trade_date=day,
                    adj_type="none",
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    pre_close=close,
                    volume=Decimal("10000"),
                    amount=Decimal("100000.0000"),
                    is_suspended=False,
                )
            )
    return bars


def _bar_count(conn: Any) -> int:
    return int(conn.execute(select(func.count()).select_from(daily_bars)).scalar_one())


class _MemRedis:
    def __init__(self) -> None:
        self._kv: dict[str, bytes] = {}
        self._lists: dict[str, list[bytes]] = {}
        self._z: dict[str, dict[bytes, float]] = {}

    def set(self, key: str, value: Any, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self._kv:
            return False
        raw = value if isinstance(value, bytes) else str(value).encode()
        self._kv[key] = raw
        return True

    def get(self, key: str) -> bytes | None:
        return self._kv.get(key)

    def delete(self, *keys: str) -> int:
        n = 0
        for key in keys:
            if key in self._kv or key in self._lists or key in self._z:
                n += 1
            self._kv.pop(key, None)
            self._lists.pop(key, None)
            self._z.pop(key, None)
        return n

    def lpush(self, key: str, value: Any) -> int:
        raw = value if isinstance(value, bytes) else str(value).encode()
        buf = self._lists.setdefault(key, [])
        buf.insert(0, raw)
        return len(buf)

    def llen(self, key: str) -> int:
        return len(self._lists.get(key, []))

    def lrange(self, key: str, start: int, end: int) -> list[bytes]:
        buf = self._lists.get(key, [])
        if end == -1:
            end = len(buf) - 1
        return buf[start : end + 1]

    def rpop(self, key: str) -> bytes | None:
        buf = self._lists.get(key, [])
        if not buf:
            return None
        return buf.pop()

    def zrangebyscore(self, key: str, min_s: float, max_s: float) -> list[bytes]:
        z = self._z.get(key, {})
        return [m for m, score in z.items() if min_s <= score <= max_s]

    def zrem(self, key: str, member: Any) -> int:
        raw = member if isinstance(member, bytes) else str(member).encode()
        z = self._z.get(key, {})
        if raw in z:
            del z[raw]
            return 1
        return 0

    def close(self) -> None:
        return None


def _stub_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Conn:
        def __enter__(self) -> _Conn:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

    class _Eng:
        def connect(self) -> _Conn:
            return _Conn()

        def dispose(self) -> None:
            return None

    monkeypatch.setattr(jobs_mod, "_engine", lambda _settings: _Eng())


# --- 不连库 -----------------------------------------------------------------


def test_upsert_batch_constant_bound() -> None:
    mod = _import_impl()
    assert mod.UPSERT_BATCH_ROWS == 1000
    per_row = getattr(mod, "UPSERT_PARAMS_PER_ROW", 14)
    assert mod.UPSERT_BATCH_ROWS * int(per_row) <= 65535


def test_no_settings_field_for_window() -> None:
    names = list(Settings.model_fields)
    for name in names:
        lowered = name.lower()
        assert "window" not in lowered
        assert "backfill" not in lowered
        assert "lookback" not in lowered
    assert {n for n in names if n.lower().startswith("daily_bars_")} == {"daily_bars_source"}


def test_daily_bars_fetch_slot_1715_open_day_only(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_impl()
    name = mod.DAILY_BARS_FETCH
    settings = Settings(_env_file=None, app_env="test", session_cookie_secure=False)
    assert name not in jobs_mod.schedule(settings)
    assert name in jobs_mod.LOCKED_TASKS
    assert name not in jobs_mod.RETRY_TASKS
    assert jobs_mod.DAILY_BARS_FETCH_TIME == "17:15"
    _stub_engine(monkeypatch)
    monkeypatch.setattr("app.reports.service.covered", lambda _conn, _day: True)
    hits: list[tuple[int, int, str, dict[str, Any]]] = []
    for minute in range(0, 24 * 60, 5):
        now = dt.datetime(2026, 11, 10, minute // 60, minute % 60, tzinfo=BEIJING)
        for task_name, slot, args in jobs_mod.slot_jobs(settings, now):
            if task_name == name:
                hits.append((now.hour, now.minute, slot, args))
    assert [(h, m) for h, m, _s, _a in hits] == [(17, 15), (17, 20), (17, 25)]
    assert all(slot == "20261110:1715" and args == {"trade_date": "2026-11-10"} for _h, _m, slot, args in hits)
    # REPORT 仍在 18:30；17:15 窗口不含 17:30
    report_slots = []
    for hhmm in ("17:15", "17:30", "18:30"):
        h, m = (int(p) for p in hhmm.split(":"))
        now = dt.datetime(2026, 11, 10, h, m, tzinfo=BEIJING)
        report_slots.append(
            [task for task, slot, _a in jobs_mod.slot_jobs(settings, now)]
        )
    assert name in report_slots[0] and jobs_mod.REPORT not in report_slots[0]
    assert name not in report_slots[1] and jobs_mod.ANALYZE in report_slots[1]
    assert jobs_mod.REPORT in report_slots[2]
    monkeypatch.setattr("app.reports.service.covered", lambda _conn, _day: False)
    for minute in range(0, 24 * 60, 5):
        now = dt.datetime(2026, 11, 10, minute // 60, minute % 60, tzinfo=BEIJING)
        for task_name, _slot, _args in jobs_mod.slot_jobs(settings, now):
            assert task_name != name


def test_beat_slots_fetch_once_no_intent_no_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_engine(monkeypatch)
    monkeypatch.setattr("app.reports.service.covered", lambda _conn, _day: True)
    intent = {"n": 0}
    grant = {"n": 0}
    monkeypatch.setattr(
        "app.workers.daily.record_intent",
        lambda *_a, **_k: intent.__setitem__("n", intent["n"] + 1),
    )
    monkeypatch.setattr(
        "app.master.daily_delivery.read_grant",
        lambda *_a, **_k: grant.__setitem__("n", grant["n"] + 1) or None,
    )
    settings = Settings(_env_file=None, app_env="test", session_cookie_secure=False)
    client = _MemRedis()
    now = dt.datetime(2026, 11, 10, 17, 16, tzinfo=BEIJING)
    first = jobs_mod.beat_slots(settings, client=client, now=now)
    second = jobs_mod.beat_slots(settings, client=client, now=now)
    assert first.count(_import_impl().DAILY_BARS_FETCH) == 1
    assert second == []
    assert client.llen(jobs_mod.QUEUE_KEY) == 1
    assert intent["n"] == 0
    assert grant["n"] == 0


def test_fetch_locked_skip_not_retried() -> None:
    settings = Settings(_env_file=None, app_env="test", session_cookie_secure=False)
    client = _MemRedis()
    name = _import_impl().DAILY_BARS_FETCH
    client.set(f"{jobs_mod.LOCK_PREFIX}{name}", "held", nx=True)
    client.lpush(
        jobs_mod.QUEUE_KEY,
        json.dumps({"task": name, "enqueued_at": 1, "args": {"trade_date": "2026-11-10"}}),
    )
    done = jobs_mod.worker_tick(settings, client=client)
    assert done == [(name, "locked")]
    assert client.zrangebyscore(jobs_mod.DELAYED_KEY, 0, 10**18) == []
    assert client.llen(jobs_mod.QUEUE_KEY) == 0


def test_universe_watchlist_only_owner(temp_db: Engine) -> None:
    mod = _import_impl()
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    with temp_db.begin() as conn:
        _seed_user(conn, u1, "tb129_u1")
        _seed_user(conn, u2, "tb129_u2")
        _seed_security(conn, CODE_E)
        conn.execute(insert(watchlist_items).values(user_id=u1, security_code=CODE_E))
        assert mod.daily_universe(conn, u1, DAY_1010) == [CODE_E]
        assert CODE_E not in mod.daily_universe(conn, u2, DAY_1010)


def test_fetch_and_record_uses_source_name(temp_db: Engine) -> None:
    """T-A132 ⑴：source 取自源对象 name，不再写死 fake。"""
    mod = _import_impl()
    u1 = uuid.uuid4()
    with temp_db.begin() as conn:
        _seed_calendar_span(conn, dt.date(2026, 11, 9), DAY_1010)
        _seed_user(conn, u1, "tb129_src")
        _seed_security(conn, CODE_A)
        _seed_holding(conn, u1, (CODE_A,), tag="u1")

        class _Named:
            name = "mairui"

            def fetch(self, codes: Any, start: dt.date, end: dt.date, adjust: str) -> Any:
                return mod.FakeDailyBarsSource().fetch(codes, start, end, adjust)

        mod.fetch_and_record(
            conn,
            _Named(),
            trade_date=DAY_1010,
            user_id=u1,
            window_trading_days=None,
            fetched_at=FETCHED,
        )
        sources = set(conn.execute(select(daily_bars.c.source)).scalars().all())
    assert sources == {"mairui"}


def test_upsert_batches_under_param_limit(temp_db: Engine) -> None:
    mod = _import_impl()
    bars = _make_bars(10, 500)
    result = mod.DailyBarsResult(bars=tuple(bars))
    inserts: list[int] = []

    def _before(
        _conn: Any,
        _cursor: Any,
        statement: str,
        parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if "INSERT" in statement.upper() and "daily_bars" in statement.lower():
            nparams = len(parameters) if isinstance(parameters, (dict, list, tuple)) else 0
            inserts.append(nparams)
            assert nparams <= 65535

    event.listen(temp_db, "before_cursor_execute", _before)
    try:
        with temp_db.begin() as conn:
            stats = mod.upsert_daily_bars(
                conn, result, source="fake", licence_id=None, fetched_at=FETCHED
            )
            assert stats.inserted == 5000
            assert _bar_count(conn) == 5000
    finally:
        event.remove(temp_db, "before_cursor_execute", _before)
    assert len(inserts) == 5


def test_upsert_batched_stats_aggregate(temp_db: Engine) -> None:
    mod = _import_impl()
    first = _make_bars(3, 500)  # 1500
    with temp_db.begin() as conn:
        stats1 = mod.upsert_daily_bars(
            conn,
            mod.DailyBarsResult(bars=tuple(first)),
            source="fake",
            licence_id=None,
            fetched_at=FETCHED,
        )
        assert stats1.inserted == 1500
    changed = dataclasses_replace_close(mod, first[0], Decimal("11.0000"))
    second = [changed, *first[1:], *_make_bars(2, 500, prefix=600200)]  # 1500 + 1000
    assert len(second) == 2500
    with temp_db.begin() as conn:
        stats = mod.upsert_daily_bars(
            conn,
            mod.DailyBarsResult(bars=tuple(second)),
            source="fake",
            licence_id=None,
            fetched_at=FETCHED,
        )
    assert stats.inserted == 1000
    assert stats.unchanged == 1499
    assert stats.conflicts == 1
    issue = f"daily_bar_conflict:{first[0].code}:{first[0].trade_date.isoformat()}"
    assert stats.issues == (issue,)


def dataclasses_replace_close(mod: Any, bar: Any, close: Decimal) -> Any:
    return mod.DailyBar(
        code=bar.code,
        trade_date=bar.trade_date,
        adj_type=bar.adj_type,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=close,
        pre_close=bar.pre_close,
        volume=bar.volume,
        amount=bar.amount,
        is_suspended=bar.is_suspended,
    )


def test_upsert_batched_atomic_on_error(temp_db: Engine) -> None:
    mod = _import_impl()
    bars = _make_bars(4, 500)  # 2000 → two chunks
    result = mod.DailyBarsResult(bars=tuple(bars))
    seen = {"n": 0}

    def _before(
        _conn: Any,
        _cursor: Any,
        statement: str,
        parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if "INSERT" in statement.upper() and "daily_bars" in statement.lower():
            seen["n"] += 1
            if seen["n"] >= 2:
                raise RuntimeError("injected batch failure")

    event.listen(temp_db, "before_cursor_execute", _before)
    try:
        with pytest.raises(RuntimeError, match="injected batch failure"), temp_db.begin() as conn:
            mod.upsert_daily_bars(
                conn, result, source="fake", licence_id=None, fetched_at=FETCHED
            )
    finally:
        event.remove(temp_db, "before_cursor_execute", _before)
    with temp_db.connect() as conn:
        assert _bar_count(conn) == 0


def test_backfill_window_days_three_years(temp_db: Engine) -> None:
    mod = _import_impl()
    end = dt.date(2026, 11, 10)
    start = dt.date(2023, 11, 10)
    with temp_db.begin() as conn:
        _seed_calendar_span(conn, start, end)
        got = mod.backfill_window_days(conn, end, 3)
        expected = int(
            conn.execute(
                select(func.count())
                .select_from(trading_calendar)
                .where(
                    trading_calendar.c.date > start,
                    trading_calendar.c.date <= end,
                    trading_calendar.c.is_open.is_(True),
                )
            ).scalar_one()
        )
        assert got == expected
        leap = dt.date(2024, 2, 29)
        _seed_calendar_span(conn, dt.date(2021, 2, 28), dt.date(2023, 11, 9))
        got_leap = mod.backfill_window_days(conn, leap, 3)
        expected_leap = int(
            conn.execute(
                select(func.count())
                .select_from(trading_calendar)
                .where(
                    trading_calendar.c.date > dt.date(2021, 2, 28),
                    trading_calendar.c.date <= leap,
                    trading_calendar.c.is_open.is_(True),
                )
            ).scalar_one()
        )
        assert got_leap == expected_leap


def test_backfill_window_days_calendar_short(temp_db: Engine) -> None:
    mod = _import_impl()
    with temp_db.begin() as conn:
        _seed_calendar_span(conn, dt.date(2025, 1, 1), dt.date(2026, 11, 10))
        assert mod.backfill_window_days(conn, dt.date(2026, 11, 10), 3) is None
    with temp_db.begin() as conn:
        conn.execute(text("TRUNCATE market.trading_calendar"))
        _seed_calendar_span(
            conn, dt.date(2023, 11, 10), dt.date(2026, 11, 10), hole=dt.date(2025, 6, 1)
        )
        assert mod.backfill_window_days(conn, dt.date(2026, 11, 10), 3) is None
    with pytest.raises(ValueError, match="positive integer"), temp_db.begin() as conn:
        mod.backfill_window_days(conn, dt.date(2026, 11, 10), 0)


def _run_cli(
    argv: list[str],
    *,
    settings: Settings,
    now: dt.datetime,
    redis_client: _MemRedis,
) -> tuple[int, str]:
    from app.cli.daily_bars_backfill import main

    buf = io.StringIO()
    import contextlib

    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = main(argv, now=now, redis_client=redis_client, settings=settings)
    return code, buf.getvalue()


def _seed_cli_world(conn: Any) -> None:
    _seed_calendar_span(conn, dt.date(2023, 11, 1), dt.date(2026, 11, 11))
    u1 = uuid.uuid4()
    _seed_user(conn, u1, "tb129_cli")
    _seed_security(conn, CODE_A)
    _seed_security(conn, CODE_B)
    _seed_holding(conn, u1, (CODE_A, CODE_B), tag="cli")


def test_backfill_cli_dry_run_default_no_enqueue(temp_db: Engine) -> None:
    from app.db.tables.realtime import pipeline_runs

    settings = _settings(temp_db.url)
    client = _MemRedis()
    client.lpush(jobs_mod.QUEUE_KEY, json.dumps({"task": "keep"}))
    before = client.llen(jobs_mod.QUEUE_KEY)
    with temp_db.begin() as conn:
        _seed_cli_world(conn)
    now = dt.datetime(2026, 11, 10, 20, 0, tzinfo=BEIJING)
    code, out = _run_cli(
        ["--years", "3", "--trade-date", "2026-11-09"],
        settings=settings,
        now=now,
        redis_client=client,
    )
    assert code == 0
    assert client.llen(jobs_mod.QUEUE_KEY) == before
    assert CODE_A not in out and CODE_B not in out
    assert "window_trading_days=" in out
    assert "securities=" in out or "N=" in out
    with temp_db.connect() as conn:
        assert _bar_count(conn) == 0
        assert int(conn.execute(select(func.count()).select_from(pipeline_runs)).scalar_one()) == 0


def test_backfill_cli_apply_enqueues_once(temp_db: Engine) -> None:
    settings = _settings(temp_db.url)
    client = _MemRedis()
    past = dt.date(2026, 11, 9)
    with temp_db.begin() as conn:
        _seed_cli_world(conn)
        window = _import_impl().backfill_window_days(conn, past, 3)
        assert window is not None
    now = dt.datetime(2026, 11, 10, 18, 0, tzinfo=BEIJING)
    code, _out = _run_cli(
        ["--years", "3", "--trade-date", "2026-11-09", "--apply"],
        settings=settings,
        now=now,
        redis_client=client,
    )
    assert code == 0
    assert client.llen(jobs_mod.QUEUE_KEY) == 1
    body = json.loads(client.lrange(jobs_mod.QUEUE_KEY, 0, 0)[0])
    assert body["task"] == "daily_bars_fetch"
    assert body["args"] == {"trade_date": "2026-11-09", "window_trading_days": window}
    # 日历不足
    with temp_db.begin() as conn:
        conn.execute(text("TRUNCATE market.trading_calendar"))
        _seed_calendar_span(conn, dt.date(2025, 1, 1), DAY_1010)
    client2 = _MemRedis()
    code2, out2 = _run_cli(
        ["--years", "3", "--trade-date", "2026-11-09", "--apply"],
        settings=settings,
        now=now,
        redis_client=client2,
    )
    assert code2 != 0
    assert client2.llen(jobs_mod.QUEUE_KEY) == 0
    assert "calendar_not_covered" in out2


def test_backfill_cli_refuses_today_before_1745(temp_db: Engine) -> None:
    settings = _settings(temp_db.url)
    client = _MemRedis()
    with temp_db.begin() as conn:
        _seed_cli_world(conn)
        prev = conn.execute(
            select(trading_calendar.c.date)
            .where(
                trading_calendar.c.date < DAY_1010,
                trading_calendar.c.is_open.is_(True),
            )
            .order_by(trading_calendar.c.date.desc())
            .limit(1)
        ).scalar_one()
    now = dt.datetime(2026, 11, 10, 16, 0, tzinfo=BEIJING)
    code, _out = _run_cli(
        ["--years", "3", "--trade-date", "2026-11-10", "--apply"],
        settings=settings,
        now=now,
        redis_client=client,
    )
    assert code != 0
    assert client.llen(jobs_mod.QUEUE_KEY) == 0
    code2, out2 = _run_cli(
        ["--years", "3"],
        settings=settings,
        now=now,
        redis_client=client,
    )
    assert code2 == 0
    assert str(prev) in out2 or f"trade_date={prev.isoformat()}" in out2



def test_backfill_cli_trade_date_must_be_past_open_day(temp_db: Engine) -> None:
    """--trade-date 必须是过去的开市日：今天、未来、休市日一律拒绝。"""
    settings = _settings(temp_db.url)
    client = _MemRedis()
    with temp_db.begin() as conn:
        _seed_cli_world(conn)
    now = dt.datetime(2026, 11, 10, 20, 0, tzinfo=BEIJING)
    for value in ("2026-11-10", "2026-11-11", "2026-11-08"):
        code, out = _run_cli(
            ["--years", "3", "--trade-date", value],
            settings=settings,
            now=now,
            redis_client=client,
        )
        assert code != 0, value
        assert "past open" in out or "过去" in out or "refused" in out
        assert client.llen(jobs_mod.QUEUE_KEY) == 0
    code_ok, out_ok = _run_cli(
        ["--years", "3", "--trade-date", "2026-11-09"],
        settings=settings,
        now=now,
        redis_client=client,
    )
    assert code_ok == 0
    assert "trade_date=2026-11-09" in out_ok
