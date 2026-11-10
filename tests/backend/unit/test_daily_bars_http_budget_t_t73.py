# ruff: noqa: S101
"""T-T73：单 C（T-B130）tests/ 侧用例。

依据 git show 7234aa7:docs/contracts/daily-bars-source.md §8.1（T-A135 单 C），
未合入 docs。禁用 skip / xfail / importorskip。
新符号在用例内探测，缺失时以「缺实现：…」报红，保证可被收集。

麦蕊绝对 0：env -u MAIRUI_LICENCE；假 transport / 假源；T-T70 换网探针拦
socket connect（只放 AF_UNIX/回环）+ egress.mairui_get 计数桩。
假 transport 只在进程内模拟 STOP/103/429，不读不打印真实 licence。
临时库复用 daily_bars_t70_support._open_temp_db（o61，finally DROP）。
"""

from __future__ import annotations

import ast
import contextlib
import datetime as dt
import importlib
import importlib.util
import inspect
import json
import os
import time
import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, insert, select

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from daily_bars_t70_support import (  # noqa: E402
    BEIJING,
    OPEN_10,
    ROOT,
    _open_temp_db,
    no_egress,  # noqa: F401
)

INGEST_MOD = "app.ingest.daily_bars"
CLOCK = dt.datetime(2026, 11, 10, 17, 20, tzinfo=BEIJING)
CODES = (
    "600010.SH",
    "600011.SH",
    "600012.SH",
    "600013.SH",
    "600014.SH",
)
OWNER = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1")
AT = dt.datetime(2026, 11, 10, 15, 0, tzinfo=BEIJING)


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


def _require_ingest(*names: str) -> Any:
    spec = importlib.util.find_spec(INGEST_MOD)
    assert spec is not None, f"缺实现：模块 {INGEST_MOD} 不存在（契约 §8.1）"
    mod = importlib.import_module(INGEST_MOD)
    for name in names:
        assert hasattr(mod, name), f"缺实现：{INGEST_MOD}.{name}（契约 §8.1）"
    return mod


def _seed_c_owner(conn: Any) -> None:
    from app.db.tables.accounts import (
        accounts,
        broker_position_snapshot_items,
        broker_position_snapshots,
        import_batches,
    )
    from app.db.tables.market import securities
    from app.db.tables.users import users

    conn.execute(
        insert(users).values(
            id=OWNER,
            username="tt73_owner",
            display_name="tt73_owner",
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
    conn.execute(insert(accounts).values(id=account, user_id=OWNER, name="tt73"))
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


def _bar(code: str, day: dt.date) -> Any:
    from app.marketdata.daily_bars import DailyBar

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
    def transport(code: str, start: dt.date, end: dt.date) -> tuple[int, Any]:
        calls.append((code, start, end))
        return 200, _bar(code, start)

    return transport


def _status_on(
    nth: int, status: int, calls: list[tuple[str, dt.date, dt.date]]
) -> Callable[..., Any]:
    def transport(code: str, start: dt.date, end: dt.date) -> tuple[int, Any]:
        calls.append((code, start, end))
        if len(calls) == nth:
            return status, None
        return 200, _bar(code, start)

    return transport


def _issues(conn: Any) -> list[str]:
    from app.db.tables.realtime import pipeline_runs

    row = conn.execute(
        select(pipeline_runs.c.stats, pipeline_runs.c.status).order_by(
            pipeline_runs.c.finished_at.desc()
        )
    ).first()
    assert row is not None
    stats = row.stats if isinstance(row.stats, dict) else json.loads(row.stats)
    return list(stats.get("issues") or [])


def _bar_count(conn: Any) -> int:
    from app.db.tables.market import daily_bars

    return int(conn.execute(select(func.count()).select_from(daily_bars)).scalar_one())


def _clock() -> dt.datetime:
    return CLOCK


def _fetch(
    conn: Any,
    *,
    transport: Callable[..., Any],
    tmp_path: Path,
    grant: object | None = object(),
    stop: bool = False,
    halt: bool = False,
    stop_path: Path | None = None,
    halt_path: Path | None = None,
) -> int:
    ibars = _require_ingest("fetch_mairui_daily_bars")
    stop_p = stop_path if stop_path is not None else (tmp_path / "STOP")
    halt_p = halt_path if halt_path is not None else (tmp_path / "HALT")
    if stop:
        stop_p.write_text("stop", encoding="utf-8")
    if halt:
        halt_p.write_text("halt", encoding="utf-8")
    return ibars.fetch_mairui_daily_bars(
        conn,
        trade_date=OPEN_10,
        user_id=OWNER,
        transport=transport,
        stop_path=stop_p,
        halt_path=halt_p,
        grant_reader=lambda: grant,
        clock=_clock,
    )


def _assert_fetch_not_retried() -> None:
    from app.workers import jobs as jobs_mod

    assert "daily_bars_fetch" not in jobs_mod.RETRY_TASKS


# ---------------------------------------------------------------------------
# 1) 哨兵能解析，但没有任何开启入口
# ---------------------------------------------------------------------------


def test_http_budget_resolution_table() -> None:
    """§8.1 :429–:433、:444：0→unset，哨兵→unlimited，3→capped(3)，其余非法值全部 unset。"""
    ibars = _require_ingest("daily_bars_http_budget", "DAILY_BARS_HTTP_UNLIMITED", "DailyBarsBudget")
    cases: list[tuple[object, Any]] = [
        (0, ibars.DailyBarsBudget(kind="unset")),
        (ibars.DAILY_BARS_HTTP_UNLIMITED, ibars.DailyBarsBudget(kind="unlimited")),
        (3, ibars.DailyBarsBudget(kind="capped", cap=3)),
        (-1, ibars.DailyBarsBudget(kind="unset")),
        (True, ibars.DailyBarsBudget(kind="unset")),
        (None, ibars.DailyBarsBudget(kind="unset")),
        ("0", ibars.DailyBarsBudget(kind="unset")),
        (2.0, ibars.DailyBarsBudget(kind="unset")),
    ]
    for value, expected in cases:
        assert ibars.daily_bars_http_budget(value) == expected, value


def test_no_switch_entry_and_not_settings() -> None:
    """§8.1 :425–:428、:434–:439：哨兵可解析为 unlimited，但无任何开启入口。

    限额不进 Settings、生产赋值仍为 0、CLI 无开关；改成哨兵属于开放单 D。
    """
    from app.config import Settings as SettingsType

    ibars = _require_ingest("DAILY_BARS_HTTP_LIMIT", "DAILY_BARS_HTTP_UNLIMITED", "daily_bars_http_budget")
    assert ibars.DAILY_BARS_HTTP_UNLIMITED == "unlimited"
    assert ibars.daily_bars_http_budget(ibars.DAILY_BARS_HTTP_UNLIMITED).kind == "unlimited"
    assert ibars.DAILY_BARS_HTTP_LIMIT == 0
    assert type(ibars.DAILY_BARS_HTTP_LIMIT) is int
    assert ibars.daily_bars_http_budget(ibars.DAILY_BARS_HTTP_LIMIT).kind == "unset"
    fields = getattr(SettingsType, "model_fields", {})
    assert "daily_bars_http_limit" not in fields
    assert "daily_bars_http_unlimited" not in fields
    src = Path(inspect.getsourcefile(ibars) or "")
    assert src.is_file(), "缺实现：无法定位 ingest/daily_bars.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "DAILY_BARS_HTTP_LIMIT":
                found = True
                assert isinstance(node.value, ast.Constant) and node.value.value == 0
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "DAILY_BARS_HTTP_LIMIT" in names:
                found = True
                assert isinstance(node.value, ast.Constant) and node.value.value == 0
    assert found
    cli = ROOT / "src/backend/app/cli/daily_bars_backfill.py"
    cli_text = cli.read_text(encoding="utf-8")
    assert "HTTP_UNLIMITED" not in cli_text
    assert "DAILY_BARS_HTTP_LIMIT" not in cli_text


# ---------------------------------------------------------------------------
# 2) LIMIT 默认 0 时不出网
# ---------------------------------------------------------------------------


def test_limit_default_zero_no_network(temp_db: SimpleNamespace, tmp_path: Path) -> None:
    """§8.1 :428、:430：默认限额 0 为 unset；假 transport 0 次，不写库，记 budget_unset。"""
    ibars = _require_ingest("fetch_mairui_daily_bars", "DAILY_BARS_HTTP_LIMIT")
    assert ibars.DAILY_BARS_HTTP_LIMIT == 0
    with temp_db.engine.begin() as conn:
        _seed_c_owner(conn)
        calls: list[tuple[str, dt.date, dt.date]] = []
        written = _fetch(conn, transport=_ok_transport(calls), tmp_path=tmp_path)
        assert written == 0
        assert calls == []
        assert "daily_bars_http_budget_unset" in _issues(conn)
        assert _bar_count(conn) == 0


def test_limit_not_widened_by_env_or_receipt(
    temp_db: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.1 :434、:447：限额常量为 0 时，环境变量或回执里的 limit 都不能放宽，transport 0 次。"""
    ibars = _require_ingest("DAILY_BARS_HTTP_LIMIT", "fetch_mairui_daily_bars")
    monkeypatch.setenv("DAILY_BARS_HTTP_LIMIT", "9999")
    receipt = tmp_path / "mairui-daily-bars.json"
    receipt.write_text(json.dumps({"limit": 9999, "kind": "mairui_daily_bars"}), encoding="utf-8")
    with temp_db.engine.begin() as conn:
        _seed_c_owner(conn)
        calls: list[tuple[str, dt.date, dt.date]] = []
        written = ibars.fetch_mairui_daily_bars(
            conn,
            trade_date=OPEN_10,
            user_id=OWNER,
            transport=_ok_transport(calls),
            stop_path=tmp_path / "STOP",
            halt_path=tmp_path / "HALT",
            grant_reader=lambda: {"limit": 9999},
            clock=_clock,
        )
        assert ibars.DAILY_BARS_HTTP_LIMIT == 0
        assert os.environ["DAILY_BARS_HTTP_LIMIT"] == "9999"
        assert written == 0
        assert calls == []
        assert "daily_bars_http_budget_unset" in _issues(conn)
        assert _bar_count(conn) == 0


def test_mairui_requires_receipt_and_budget(
    temp_db: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.1 :435–:439、:448：默认 0 即使缺回执也只记 unset；monkeypatch 哨兵后缺回执记 licence unavailable，仍 0 次。"""
    ibars = _require_ingest("DAILY_BARS_HTTP_LIMIT", "DAILY_BARS_HTTP_UNLIMITED", "fetch_mairui_daily_bars")
    with temp_db.engine.begin() as conn:
        _seed_c_owner(conn)
        calls: list[tuple[str, dt.date, dt.date]] = []
        written = _fetch(conn, transport=_ok_transport(calls), tmp_path=tmp_path, grant=None)
        assert written == 0 and calls == []
        assert "daily_bars_http_budget_unset" in _issues(conn)
        assert _bar_count(conn) == 0

        monkeypatch.setattr(ibars, "DAILY_BARS_HTTP_LIMIT", ibars.DAILY_BARS_HTTP_UNLIMITED)
        calls2: list[tuple[str, dt.date, dt.date]] = []
        written2 = _fetch(conn, transport=_ok_transport(calls2), tmp_path=tmp_path, grant=None)
        assert written2 == 0 and calls2 == []
        assert "data_licence_unavailable" in _issues(conn)
        assert _bar_count(conn) == 0


# ---------------------------------------------------------------------------
# 3) STOP / 103 / 429 分别覆盖：整批停、不重试
# ---------------------------------------------------------------------------


def test_unlimited_halts_on_103(
    temp_db: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.1 :420、:446；§3 :85：假 transport 第 2 次返回 103，恰 2 次、写 HALT，剩余 4 只记 halted，已成功 1 行；再 tick 0 次。不进 RETRY_TASKS。"""
    _assert_fetch_not_retried()
    ibars = _require_ingest("DAILY_BARS_HTTP_LIMIT", "DAILY_BARS_HTTP_UNLIMITED", "fetch_mairui_daily_bars")
    monkeypatch.setattr(ibars, "DAILY_BARS_HTTP_LIMIT", ibars.DAILY_BARS_HTTP_UNLIMITED)
    halt_path = tmp_path / "halt-103"
    stop_path = tmp_path / "stop-103"
    with temp_db.engine.begin() as conn:
        _seed_c_owner(conn)
        calls: list[tuple[str, dt.date, dt.date]] = []
        written = ibars.fetch_mairui_daily_bars(
            conn,
            trade_date=OPEN_10,
            user_id=OWNER,
            transport=_status_on(2, 103, calls),
            stop_path=stop_path,
            halt_path=halt_path,
            grant_reader=lambda: object(),
            clock=_clock,
        )
        assert len(calls) == 2
        assert halt_path.is_file()
        issues = _issues(conn)
        assert issues.count("daily_bars_upstream_halted") == 4
        assert written == 1
        assert _bar_count(conn) == 1
        calls2: list[tuple[str, dt.date, dt.date]] = []
        again = ibars.fetch_mairui_daily_bars(
            conn,
            trade_date=OPEN_10,
            user_id=OWNER,
            transport=_ok_transport(calls2),
            stop_path=stop_path,
            halt_path=halt_path,
            grant_reader=lambda: object(),
            clock=_clock,
        )
        assert calls2 == [] and again == 0
        assert "daily_bars_upstream_halted" in _issues(conn)
    _assert_fetch_not_retried()


def test_unlimited_halts_on_429(
    temp_db: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.1 :420、:446；§3 :85：假 transport 第 2 次返回 429，恰 2 次、写 HALT，剩余 4 只记 halted，已成功 1 行；再 tick 0 次。不进 RETRY_TASKS。"""
    _assert_fetch_not_retried()
    ibars = _require_ingest("DAILY_BARS_HTTP_LIMIT", "DAILY_BARS_HTTP_UNLIMITED", "fetch_mairui_daily_bars")
    monkeypatch.setattr(ibars, "DAILY_BARS_HTTP_LIMIT", ibars.DAILY_BARS_HTTP_UNLIMITED)
    halt_path = tmp_path / "halt-429"
    stop_path = tmp_path / "stop-429"
    with temp_db.engine.begin() as conn:
        _seed_c_owner(conn)
        calls: list[tuple[str, dt.date, dt.date]] = []
        written = ibars.fetch_mairui_daily_bars(
            conn,
            trade_date=OPEN_10,
            user_id=OWNER,
            transport=_status_on(2, 429, calls),
            stop_path=stop_path,
            halt_path=halt_path,
            grant_reader=lambda: object(),
            clock=_clock,
        )
        assert len(calls) == 2
        assert halt_path.is_file()
        issues = _issues(conn)
        assert issues.count("daily_bars_upstream_halted") == 4
        assert written == 1
        assert _bar_count(conn) == 1
        calls2: list[tuple[str, dt.date, dt.date]] = []
        again = ibars.fetch_mairui_daily_bars(
            conn,
            trade_date=OPEN_10,
            user_id=OWNER,
            transport=_ok_transport(calls2),
            stop_path=stop_path,
            halt_path=halt_path,
            grant_reader=lambda: object(),
            clock=_clock,
        )
        assert calls2 == [] and again == 0
        assert "daily_bars_upstream_halted" in _issues(conn)
    _assert_fetch_not_retried()


def test_unlimited_halts_on_stop(
    temp_db: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.1 :420、:446；§3 :85：运行前已有 STOP 文件，transport 0 次，5 只都记 halted，不写行；不进 RETRY_TASKS。"""
    _assert_fetch_not_retried()
    ibars = _require_ingest("DAILY_BARS_HTTP_LIMIT", "DAILY_BARS_HTTP_UNLIMITED", "fetch_mairui_daily_bars")
    monkeypatch.setattr(ibars, "DAILY_BARS_HTTP_LIMIT", ibars.DAILY_BARS_HTTP_UNLIMITED)
    with temp_db.engine.begin() as conn:
        _seed_c_owner(conn)
        calls: list[tuple[str, dt.date, dt.date]] = []
        written = _fetch(conn, transport=_ok_transport(calls), tmp_path=tmp_path, stop=True)
        assert calls == [] and written == 0
        assert _issues(conn).count("daily_bars_upstream_halted") == 5
        assert _bar_count(conn) == 0
        calls2: list[tuple[str, dt.date, dt.date]] = []
        again = _fetch(conn, transport=_ok_transport(calls2), tmp_path=tmp_path, stop=True)
        assert calls2 == [] and again == 0
    _assert_fetch_not_retried()


# ---------------------------------------------------------------------------
# 4) 不放宽 DAILY_HTTP_LIMIT / live_budget；达到上限拒绝
# ---------------------------------------------------------------------------


def test_daily_http_limit_unchanged() -> None:
    """§8.1 :440、:443：DAILY_HTTP_LIMIT 仍为 1，live_budget_issue 仍为 daily_http_budget_unresolved；达上限拒绝出队。"""
    from app.master import daily_delivery as daily

    assert daily.DAILY_HTTP_LIMIT == 1
    assert type(daily.DAILY_HTTP_LIMIT) is int
    assert len(daily.LISTS) > daily.DAILY_HTTP_LIMIT
    assert daily.live_budget_issue() == "daily_http_budget_unresolved"
    # 达到上限时 request / publish_pending 直接拒绝，不写出队。
    assert daily.request(None, object(), CLOCK) is None  # type: ignore[arg-type]
    assert daily.publish_pending(None, None) == 0  # type: ignore[arg-type]
    ibars = _require_ingest("DAILY_BARS_HTTP_LIMIT", "DAILY_BARS_HTTP_UNLIMITED")
    assert ibars.DAILY_BARS_HTTP_LIMIT == 0
    assert ibars.DAILY_BARS_HTTP_UNLIMITED == "unlimited"


def test_budget_cap_reached_defers_rest(
    temp_db: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.1 :432：仅测试 monkeypatch 为正整数 2 时，第 2 次之后的标的记 quota_deferred，当日不重试。"""
    ibars = _require_ingest("DAILY_BARS_HTTP_LIMIT", "fetch_mairui_daily_bars")
    monkeypatch.setattr(ibars, "DAILY_BARS_HTTP_LIMIT", 2)
    with temp_db.engine.begin() as conn:
        _seed_c_owner(conn)
        calls: list[tuple[str, dt.date, dt.date]] = []
        written = _fetch(conn, transport=_ok_transport(calls), tmp_path=tmp_path)
        assert len(calls) == 2
        assert written == 2
        assert _issues(conn).count("daily_bars_quota_deferred") == 3
        assert _bar_count(conn) == 2


def test_unlimited_no_cap_calls_equal_planned(
    temp_db: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.1 :441、:445：monkeypatch 为哨兵、回执与假 transport 齐备、5 个标的单日，transport 恰 5 次，无 quota_deferred。"""
    ibars = _require_ingest("DAILY_BARS_HTTP_LIMIT", "DAILY_BARS_HTTP_UNLIMITED", "fetch_mairui_daily_bars")
    monkeypatch.setattr(ibars, "DAILY_BARS_HTTP_LIMIT", ibars.DAILY_BARS_HTTP_UNLIMITED)
    with temp_db.engine.begin() as conn:
        _seed_c_owner(conn)
        calls: list[tuple[str, dt.date, dt.date]] = []
        written = _fetch(conn, transport=_ok_transport(calls), tmp_path=tmp_path)
        assert len(calls) == 5
        assert written == 5
        assert _bar_count(conn) == 5
        assert "daily_bars_quota_deferred" not in _issues(conn)
