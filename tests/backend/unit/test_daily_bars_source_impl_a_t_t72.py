# ruff: noqa: S101
"""T-T72：按 7234aa7 §8.3 / §8.4 与 T-B129-review 非阻断第 3 条，在 tests/ 侧补日 K 主线用例。

契约只通过 git show 阅读，未合入 docs。禁用 skip / xfail / importorskip。
新符号在用例内探测，缺失时以「缺实现：…」报红，保证可被收集。
临时库复用 daily_bars_t70_support._open_temp_db（o61 模板 0030 → upgrade head → finally DROP）。
麦蕊 0：拦 socket connect（只放 AF_UNIX/回环）+ egress.mairui_get 计数桩=0。
CLI --apply 用内存 Redis 桩拦投递，不连真实 broker。
"""

from __future__ import annotations

import contextlib
import datetime as dt
import time
import importlib
import importlib.util
import io
import json
import sys
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event, func, insert, select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from daily_bars_t70_support import (  # noqa: E402
    BEIJING,
    CLOSED_07,
    CODE_A,
    CODE_B,
    CODE_E,
    OPEN_10,
    _impl,
    _open_temp_db,
    _settings,
    no_egress,  # noqa: F401
)

CONTRACT_MOD = "app.marketdata.daily_bars"
CLI_MOD = "app.cli.daily_bars_backfill"
FETCHED = dt.datetime(2026, 11, 10, 17, 15, tzinfo=BEIJING)


@pytest.fixture
def temp_db(no_egress: None) -> Iterator[SimpleNamespace]:  # noqa: F811
    # o61 模板库偶发被 Timescale 后台会话占用；只重试建库失败，不 skip、不改断言。
    from _pytest.outcomes import Failed

    gen: Any = None
    ctx: SimpleNamespace | None = None
    last: BaseException | None = None
    for attempt in range(8):
        gen = _open_temp_db()
        try:
            ctx = next(gen)
            break
        except Failed as exc:
            last = exc
            with contextlib.suppress(Exception):
                next(gen, None)
            if "无法在目标实例上创建临时库" not in str(exc) or attempt == 7:
                raise
            time.sleep(0.5)
    else:
        assert last is not None
        raise last
    assert ctx is not None and gen is not None
    try:
        yield ctx
    finally:
        with contextlib.suppress(StopIteration, Failed):
            next(gen)


def _require_impl(*names: str) -> Any:
    spec = importlib.util.find_spec(CONTRACT_MOD)
    assert spec is not None, f"缺实现：模块 {CONTRACT_MOD} 不存在（契约 §8）"
    mod = _impl()
    for name in names:
        assert hasattr(mod, name), f"缺实现：{CONTRACT_MOD}.{name}（契约 §8）"
    return mod


def _forget_jobs_engine(url: Any) -> None:
    from app.workers import jobs as jobs_mod

    raw = url if isinstance(url, str) else url.render_as_string(hide_password=False)
    cached = jobs_mod._engines.pop(raw, None)
    if cached is not None:
        cached.dispose()


def _cli_settings(url: Any) -> Any:
    from app.config import Settings
    from pydantic import SecretStr

    raw = url if isinstance(url, str) else url.render_as_string(hide_password=False)
    return Settings(
        _env_file=None,
        app_env="test",
        daily_bars_source="fake",
        database_url=SecretStr(raw),
        redis_url="redis://127.0.0.1:9/0",
        session_cookie_secure=False,
    )


def _bar_count(conn: Any) -> int:
    from app.db.tables.market import daily_bars

    return int(conn.execute(select(func.count()).select_from(daily_bars)).scalar_one())


def _make_bars(
    n_codes: int,
    n_days: int,
    *,
    close: Decimal = Decimal("10.0000"),
    start: dt.date = dt.date(2020, 1, 1),
    prefix: int = 600100,
) -> list[Any]:
    mod = _require_impl("DailyBar")
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


def _listen_daily_bar_inserts(engine: Any) -> tuple[list[int], Any]:
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

    event.listen(engine, "before_cursor_execute", _before)
    return inserts, _before


def _seed_calendar_span(
    conn: Any, start: dt.date, end: dt.date, *, hole: dt.date | None = None
) -> None:
    from app.db.tables.market import trading_calendar

    cur = start
    rows = []
    while cur <= end:
        if hole is None or cur != hole:
            rows.append({"date": cur, "is_open": cur.weekday() < 5})
        cur += dt.timedelta(days=1)
    if rows:
        conn.execute(insert(trading_calendar), rows)


class _MemRedis:
    """拦投递用的内存 Redis 桩：不连真实 broker / Redis。"""

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


def _stub_jobs_engine(monkeypatch: pytest.MonkeyPatch, engine: Any | None = None) -> None:
    from app.workers import jobs as jobs_mod

    if engine is not None:
        monkeypatch.setattr(jobs_mod, "_engine", lambda _settings: engine)
        return

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


# ---------------------------------------------------------------------------
# §8.3 分批 upsert
# ---------------------------------------------------------------------------


def test_upsert_batch_constant_bound() -> None:
    """§8.3 :511：UPSERT_BATCH_ROWS 为 1000，乘以每行参数数后不超过 65535。"""
    mod = _require_impl("UPSERT_BATCH_ROWS")
    assert mod.UPSERT_BATCH_ROWS == 1000
    per_row = getattr(mod, "UPSERT_PARAMS_PER_ROW", 14)
    assert mod.UPSERT_BATCH_ROWS * int(per_row) <= 65535


def test_upsert_batches_under_param_limit(temp_db: SimpleNamespace) -> None:
    """§8.3 :471–:473、:510：每批 1000 行；2500 行分 3 批，5000 行分 5 批；参数不超过 65535。"""
    mod = _require_impl("UPSERT_BATCH_ROWS", "upsert_daily_bars", "DailyBarsResult")
    assert mod.UPSERT_BATCH_ROWS == 1000
    inserts, listener = _listen_daily_bar_inserts(temp_db.engine)
    try:
        with temp_db.engine.begin() as conn:
            stats = mod.upsert_daily_bars(
                conn,
                mod.DailyBarsResult(bars=tuple(_make_bars(5, 500))),
                source="fake",
                licence_id=None,
                fetched_at=FETCHED,
            )
            assert stats.inserted == 2500
            assert _bar_count(conn) == 2500
        assert len(inserts) == 3
        inserts.clear()
        with temp_db.engine.begin() as conn:
            stats = mod.upsert_daily_bars(
                conn,
                mod.DailyBarsResult(bars=tuple(_make_bars(10, 500, prefix=600300))),
                source="fake",
                licence_id=None,
                fetched_at=FETCHED,
            )
            assert stats.inserted == 5000
            assert _bar_count(conn) == 7500
        assert len(inserts) == 5
    finally:
        event.remove(temp_db.engine, "before_cursor_execute", listener)


def test_upsert_batched_stats_aggregate(temp_db: SimpleNamespace) -> None:
    """§8.3 :475、:512：2500 行（含已有 1500 键，1 行 close 不同）跨批累加统计。"""
    mod = _require_impl("upsert_daily_bars", "DailyBarsResult", "DailyBar")
    first = _make_bars(3, 500)
    with temp_db.engine.begin() as conn:
        stats1 = mod.upsert_daily_bars(
            conn,
            mod.DailyBarsResult(bars=tuple(first)),
            source="fake",
            licence_id=None,
            fetched_at=FETCHED,
        )
        assert stats1.inserted == 1500
    changed = mod.DailyBar(
        code=first[0].code,
        trade_date=first[0].trade_date,
        adj_type=first[0].adj_type,
        open=first[0].open,
        high=first[0].high,
        low=first[0].low,
        close=Decimal("11.0000"),
        pre_close=first[0].pre_close,
        volume=first[0].volume,
        amount=first[0].amount,
        is_suspended=first[0].is_suspended,
    )
    second = [changed, *first[1:], *_make_bars(2, 500, prefix=600200)]
    assert len(second) == 2500
    with temp_db.engine.begin() as conn:
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


def test_upsert_batched_atomic_on_error(temp_db: SimpleNamespace) -> None:
    """§8.3 :476、:513：全部块在调用方同一事务；第 2 块失败则整体回滚，不留半批。"""
    mod = _require_impl("upsert_daily_bars", "DailyBarsResult")
    # 2500 行 → 3 块；第 2 块注入异常，第 1 块已写入的 1000 行也须回滚。
    result = mod.DailyBarsResult(bars=tuple(_make_bars(5, 500)))
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

    event.listen(temp_db.engine, "before_cursor_execute", _before)
    try:
        with pytest.raises(RuntimeError, match="injected batch failure"), temp_db.engine.begin() as conn:
            mod.upsert_daily_bars(
                conn, result, source="fake", licence_id=None, fetched_at=FETCHED
            )
    finally:
        event.remove(temp_db.engine, "before_cursor_execute", _before)
    with temp_db.engine.connect() as conn:
        assert _bar_count(conn) == 0
        assert seen["n"] >= 2


# ---------------------------------------------------------------------------
# §8.3 回填窗口与 CLI
# ---------------------------------------------------------------------------


def _run_cli(
    argv: list[str],
    *,
    settings: Any,
    now: dt.datetime,
    redis_client: _MemRedis,
) -> tuple[int, str]:
    spec = importlib.util.find_spec(CLI_MOD)
    assert spec is not None, f"缺实现：模块 {CLI_MOD} 不存在（契约 §8.3 :492）"
    from app.cli.daily_bars_backfill import main

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = main(argv, now=now, redis_client=redis_client, settings=settings)
    return code, buf.getvalue()


def _prep_backfill_calendar(conn: Any) -> None:
    conn.execute(text("TRUNCATE market.trading_calendar"))
    _seed_calendar_span(conn, dt.date(2023, 11, 1), dt.date(2026, 11, 11))


def test_backfill_window_days_three_years(temp_db: SimpleNamespace) -> None:
    """§8.3 :482–:486、:514：三年窗口按实际开市日计；闰日 2-29 回落到 2-28。"""
    from app.db.tables.market import trading_calendar

    mod = _require_impl("backfill_window_days")
    end = dt.date(2026, 11, 10)
    start = dt.date(2023, 11, 10)
    with temp_db.engine.begin() as conn:
        conn.execute(text("TRUNCATE market.trading_calendar"))
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


def test_backfill_window_days_calendar_short(temp_db: SimpleNamespace) -> None:
    """§8.3 :487、:515：覆盖不足或中间缺日返回 None，不缩短窗口；years 非正则 ValueError。"""
    mod = _require_impl("backfill_window_days")
    with temp_db.engine.begin() as conn:
        conn.execute(text("TRUNCATE market.trading_calendar"))
        _seed_calendar_span(conn, dt.date(2025, 1, 1), dt.date(2026, 11, 10))
        assert mod.backfill_window_days(conn, dt.date(2026, 11, 10), 3) is None
    with temp_db.engine.begin() as conn:
        conn.execute(text("TRUNCATE market.trading_calendar"))
        _seed_calendar_span(
            conn, dt.date(2023, 11, 10), dt.date(2026, 11, 10), hole=dt.date(2025, 6, 1)
        )
        assert mod.backfill_window_days(conn, dt.date(2026, 11, 10), 3) is None
    with pytest.raises(ValueError), temp_db.engine.begin() as conn:
        mod.backfill_window_days(conn, dt.date(2026, 11, 10), 0)


def test_backfill_cli_dry_run_default_no_enqueue(temp_db: SimpleNamespace) -> None:
    """§8.3 :494、:516：默认 dry-run，不入队、不写库、输出不含证券代码。"""
    from app.db.tables.realtime import pipeline_runs
    from app.workers import jobs as jobs_mod

    settings = _cli_settings(temp_db.url)
    client = _MemRedis()
    client.lpush(jobs_mod.QUEUE_KEY, json.dumps({"task": "keep"}))
    before = client.llen(jobs_mod.QUEUE_KEY)
    with temp_db.engine.begin() as conn:
        _prep_backfill_calendar(conn)
    now = dt.datetime(2026, 11, 10, 20, 0, tzinfo=BEIJING)
    try:
        code, out = _run_cli(
            ["--years", "3", "--trade-date", "2026-11-10"],
            settings=settings,
            now=now,
            redis_client=client,
        )
        assert code == 0
        assert client.llen(jobs_mod.QUEUE_KEY) == before
        assert CODE_A not in out and CODE_B not in out and CODE_E not in out
        assert "window_trading_days=" in out
        assert "securities=" in out or "N=" in out
        with temp_db.engine.connect() as conn:
            assert _bar_count(conn) == 0
            assert int(conn.execute(select(func.count()).select_from(pipeline_runs)).scalar_one()) == 0
    finally:
        _forget_jobs_engine(temp_db.url)


def test_backfill_cli_apply_enqueues_once(temp_db: SimpleNamespace) -> None:
    """§8.3 :495、:517：--apply 只推 1 条 daily_bars_fetch；日历不足不入队、退出码非零。"""
    from app.workers import jobs as jobs_mod

    settings = _cli_settings(temp_db.url)
    client = _MemRedis()
    with temp_db.engine.begin() as conn:
        _prep_backfill_calendar(conn)
        window = _require_impl("backfill_window_days").backfill_window_days(conn, OPEN_10, 3)
        assert window is not None
    now = dt.datetime(2026, 11, 10, 18, 0, tzinfo=BEIJING)
    try:
        code, _out = _run_cli(
            ["--years", "3", "--trade-date", "2026-11-10", "--apply"],
            settings=settings,
            now=now,
            redis_client=client,
        )
        assert code == 0
        assert client.llen(jobs_mod.QUEUE_KEY) == 1
        body = json.loads(client.lrange(jobs_mod.QUEUE_KEY, 0, 0)[0])
        assert body["task"] == "daily_bars_fetch"
        assert body["args"] == {"trade_date": "2026-11-10", "window_trading_days": window}
        with temp_db.engine.begin() as conn:
            conn.execute(text("TRUNCATE market.trading_calendar"))
            _seed_calendar_span(conn, dt.date(2025, 1, 1), OPEN_10)
        client2 = _MemRedis()
        code2, out2 = _run_cli(
            ["--years", "3", "--trade-date", "2026-11-10", "--apply"],
            settings=settings,
            now=now,
            redis_client=client2,
        )
        assert code2 != 0
        assert client2.llen(jobs_mod.QUEUE_KEY) == 0
        assert "calendar_not_covered" in out2
    finally:
        _forget_jobs_engine(temp_db.url)


def test_backfill_cli_refuses_today_before_1745(temp_db: SimpleNamespace) -> None:
    """§8.3 :493、:518：显式今天且早于 17:45 拒绝；缺省 trade-date 取上一开市日。"""
    from app.db.tables.market import trading_calendar
    from app.workers import jobs as jobs_mod

    settings = _cli_settings(temp_db.url)
    client = _MemRedis()
    with temp_db.engine.begin() as conn:
        _prep_backfill_calendar(conn)
        prev = conn.execute(
            select(trading_calendar.c.date)
            .where(
                trading_calendar.c.date < OPEN_10,
                trading_calendar.c.is_open.is_(True),
            )
            .order_by(trading_calendar.c.date.desc())
            .limit(1)
        ).scalar_one()
    now = dt.datetime(2026, 11, 10, 16, 0, tzinfo=BEIJING)
    try:
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
        assert client.llen(jobs_mod.QUEUE_KEY) == 0
    finally:
        _forget_jobs_engine(temp_db.url)


# ---------------------------------------------------------------------------
# §8.4 17:15 槽与 beat（补充已有 test_daily_bars_fetch_slot_1715_open_day_only，不弱化）
# ---------------------------------------------------------------------------


def test_daily_bars_fetch_slot_1715_open_and_closed_days(
    temp_db: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.4 :523、:526–:527：真实开市日 11-10 触发，休市日 11-07 不触发；仍在 LOCKED、不在 RETRY。

    与已有 test_daily_bars_fetch_slot_1715_open_day_only（covered 打桩）互补，不改动也不弱化该例。
    本例把 _engine 接到临时库，走真实 covered（日历已播 OPEN_10 / CLOSED_07）。
    """
    from app.workers import jobs as jobs_mod

    name = "daily_bars_fetch"
    assert name in jobs_mod.LOCKED_TASKS
    assert name not in jobs_mod.RETRY_TASKS
    settings = _settings(app_env="test", daily_bars_source="fake", database_url=temp_db.url)
    _stub_jobs_engine(monkeypatch, temp_db.engine)
    hits: list[tuple[int, int, str, dict[str, Any]]] = []
    for minute in range(0, 24 * 60, 5):
        now = dt.datetime(OPEN_10.year, OPEN_10.month, OPEN_10.day, minute // 60, minute % 60, tzinfo=BEIJING)
        for task_name, slot, args in jobs_mod.slot_jobs(settings, now):
            if task_name == name:
                hits.append((now.hour, now.minute, slot, args))
    assert [(h, m) for h, m, _s, _a in hits] == [(17, 15), (17, 20), (17, 25)]
    assert all(
        slot == f"{OPEN_10:%Y%m%d}:1715" and args == {"trade_date": OPEN_10.isoformat()}
        for _h, _m, slot, args in hits
    )
    for minute in range(0, 24 * 60, 5):
        now = dt.datetime(
            CLOSED_07.year, CLOSED_07.month, CLOSED_07.day, minute // 60, minute % 60, tzinfo=BEIJING
        )
        for task_name, _slot, _args in jobs_mod.slot_jobs(settings, now):
            assert task_name != name


def test_beat_slots_fetch_once_no_intent_no_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    """§8.4 :528、:542：开市日 17:16 连续两次 beat 只推一次；record_intent / read_grant 计数为 0。"""
    from app.workers import jobs as jobs_mod

    _stub_jobs_engine(monkeypatch)
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
    settings = _settings(app_env="test", daily_bars_source="off")
    client = _MemRedis()
    now = dt.datetime(2026, 11, 10, 17, 16, tzinfo=BEIJING)
    first = jobs_mod.beat_slots(settings, client=client, now=now)
    second = jobs_mod.beat_slots(settings, client=client, now=now)
    name = _require_impl("DAILY_BARS_FETCH").DAILY_BARS_FETCH
    assert first.count(name) == 1
    assert second == []
    assert client.llen(jobs_mod.QUEUE_KEY) == 1
    assert intent["n"] == 0
    assert grant["n"] == 0
    # 休市（covered=False）不推。
    monkeypatch.setattr("app.reports.service.covered", lambda _conn, _day: False)
    client_closed = _MemRedis()
    closed_now = dt.datetime(2026, 11, 7, 17, 16, tzinfo=BEIJING)
    assert name not in jobs_mod.beat_slots(settings, client=client_closed, now=closed_now)
    assert client_closed.llen(jobs_mod.QUEUE_KEY) == 0


def test_fetch_locked_skip_not_retried() -> None:
    """§8.4 :535、:543：锁已被占时 worker_tick 为 locked，jobs:delayed 为空。"""
    from app.workers import jobs as jobs_mod

    settings = _settings(app_env="test", daily_bars_source="fake")
    client = _MemRedis()
    name = _require_impl("DAILY_BARS_FETCH").DAILY_BARS_FETCH
    client.set(f"{jobs_mod.LOCK_PREFIX}{name}", "held", nx=True)
    client.lpush(
        jobs_mod.QUEUE_KEY,
        json.dumps({"task": name, "enqueued_at": 1, "args": {"trade_date": "2026-11-10"}}),
    )
    done = jobs_mod.worker_tick(settings, client=client)
    assert done == [(name, "locked")]
    assert client.zrangebyscore(jobs_mod.DELAYED_KEY, 0, 10**18) == []
    assert client.llen(jobs_mod.QUEUE_KEY) == 0
