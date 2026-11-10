# ruff: noqa: S101
"""T-T70：按 docs/contracts/daily-bars-source.md 实现单 A 的 10 个验收用例先写测试。

基线 docs/T-A128=1d6bb8a。实现尚不存在。本文件按契约接口名导入（app.marketdata.daily_bars
等），导入失败即红；不用 xfail。理由：左移后一旦实现落地，断言立刻执行，不必再摘 xfail，
也不会把半成品实现继续藏在 xfailed 里。导入放在各例内部，收集本文件与其他测试互不影响。

假源按契约应从 app.marketdata.daily_bars.FakeDailyBarsSource 导入（实现由后端写在该模块）。
本测试不提供生产复刻，也不出网（env -u MAIRUI_LICENCE；出网=否用 netguard 计数）。
需要库时走 tests/backend/pg_o61.py，且仅在契约符号导入成功之后建库，用完 DROP。

歧义与 TODO 见各例注释及 reports/T-T70.md。
"""

from __future__ import annotations

import ast
import datetime as dt
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = ROOT / "src/backend/app"
CONTRACT_MOD = "app.marketdata.daily_bars"
_A_SYMBOLS = (
    "DailyBarsSource",
    "DailyBarsResult",
    "DailyBar",
    "BarGap",
    "UpsertStats",
    "FakeDailyBarsSource",
    "daily_universe",
    "upsert_daily_bars",
)


def _impl() -> Any:
    """导入实现单 A 在契约中点名的模块与符号，缺一即失败。"""
    module = __import__(CONTRACT_MOD, fromlist=list(_A_SYMBOLS))
    missing = [name for name in _A_SYMBOLS if not hasattr(module, name)]
    if missing:
        raise ImportError(f"{CONTRACT_MOD} 缺少契约符号：{', '.join(missing)}")
    return module


def _daily_bars_fetch_entry() -> Any:
    """契约只要求在 workers/jobs 注册任务名 daily_bars_fetch，未给出可调用签名。

    这里不发明新名字：只在已点名的模块与 jobs 上查找同名可调用物；找不到即红。
    """
    module = _impl()
    for candidate in (
        getattr(module, "daily_bars_fetch", None),
        getattr(__import__("app.workers.jobs", fromlist=["daily_bars_fetch"]), "daily_bars_fetch", None),
    ):
        if callable(candidate):
            return candidate
    raise ImportError(
        "找不到可调用的 daily_bars_fetch（契约 §5.A 只给出任务注册名，未立函数签名）"
    )


def _assert_no_egress(before: int) -> None:
    from app.ingest.netguard import netguard_blocks

    # TODO(T-T70 歧义): netguard_blocks 在现网是占位、恒返回 0（netguard.py:200-202）。
    assert netguard_blocks() == before == 0


def _count_daily_bars(engine: Engine) -> int:
    from app.db.tables.market import daily_bars

    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(daily_bars)).scalar_one())


def _pipeline_mentions_issue(engine: Engine, issue: str) -> bool:
    """契约未规定 issue 写在 pipeline_runs 哪一列/JSON 键；只断言该字符串出现在运行记录中。"""
    from app.db.tables.realtime import pipeline_runs

    with engine.connect() as conn:
        rows = conn.execute(
            select(pipeline_runs.c.stats, pipeline_runs.c.error, pipeline_runs.c.status)
        ).all()
    for stats, error, status in rows:
        blob = f"{stats!s} {error!s} {status!s}"
        if issue in blob:
            return True
    return False


def _temp_engine() -> Iterator[Engine]:
    """o61 临时库；调用方必须先完成契约导入。不打印 DSN/口令。"""
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
    admin = create_engine(
        libpq_sqlalchemy_url("postgres"),
        isolation_level="AUTOCOMMIT",
        hide_parameters=True,
    )
    try:
        with admin.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {name} TEMPLATE {tpl}"))
    except Exception as exc:  # noqa: BLE001
        admin.dispose()
        pytest.skip(f"无法在目标实例上创建临时库：{type(exc).__name__}")
    engine = create_engine(libpq_sqlalchemy_url(name), hide_parameters=True)
    try:
        yield engine
    finally:
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


# ---------------------------------------------------------------------------
# A-1 … A-10  与契约 §5.A 验收用例一一对应
# ---------------------------------------------------------------------------


def test_daily_bars_default_off_no_writes() -> None:
    """A-1 / 契约 :129。

    依赖：Settings.daily_bars_source（默认 off，环境变量 DAILY_BARS_SOURCE）；
    任务 daily_bars_fetch（workers/jobs 注册）；表 market.daily_bars、app.pipeline_runs；
    缺口名 daily_bars_source_off。
    """
    from app.config import Settings
    from app.ingest.netguard import netguard_blocks

    # 配置键已立约（:52）；字段不存在即红
    assert "daily_bars_source" in Settings.model_fields
    assert Settings.model_fields["daily_bars_source"].default == "off"

    _impl()
    fetch_job = _daily_bars_fetch_entry()
    before = netguard_blocks()
    engines = _temp_engine()
    engine = next(engines)
    try:
        # TODO(T-T70 歧义): daily_bars_fetch 的参数表未立约（是否要 conn/date/owner？）；
        # 「返回 0」未说明是 inserted、整份 UpsertStats 还是退出码。
        result = fetch_job()
        assert result == 0 or getattr(result, "inserted", None) == 0
        assert _count_daily_bars(engine) == 0
        assert _pipeline_mentions_issue(engine, "daily_bars_source_off")
        _assert_no_egress(before)
    finally:
        engines.close()


def test_fake_source_refused_outside_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A-2 / 契约 :130。

    依赖：Settings 启动校验；DAILY_BARS_SOURCE；app_env；表 market.daily_bars。
    """
    from pydantic import ValidationError

    from app.config import Settings

    assert "daily_bars_source" in Settings.model_fields
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DAILY_BARS_SOURCE", "fake")
    with pytest.raises(ValidationError):
        Settings()
    # 校验失败不得写库；本例在实现落地前于字段缺失处已红，不先建模库。
    _assert_no_egress(0)


def test_fake_no_bars_for_day() -> None:
    """A-3 / 契约 :131（无数据）。

    依赖：FakeDailyBarsSource.fetch；可能经 daily_bars_fetch / upsert_daily_bars；
    表 market.daily_bars、app.pipeline_runs；缺口 daily_bars_missing:<code>；
    GapReason.no_source；运行状态 partial。
    """
    from app.ingest.netguard import netguard_blocks
    from app.schemas.enums import BarAdjust, GapReason

    m = _impl()
    before = netguard_blocks()
    source = m.FakeDailyBarsSource()
    # TODO(T-T70 歧义): 「全部标的都不出 bar」如何注入 FakeDailyBarsSource 未立约；
    # 「无数据」与停牌占位、休市、日历未覆盖的边界只在 §1 :43-47 部分描述。
    codes = ["600001.SH", "600002.SH"]
    day = dt.date(2026, 11, 9)
    result = source.fetch(codes, day, day, BarAdjust.NONE)
    engines = _temp_engine()
    engine = next(engines)
    try:
        with engine.begin() as conn:
            stats = m.upsert_daily_bars(
                conn, result, source="fake", licence_id="", fetched_at=dt.datetime.now(dt.UTC)
            )
        assert _count_daily_bars(engine) == 0
        for code in codes:
            issue = f"daily_bars_missing:{code}"
            # TODO: issue 落在 DailyBarsResult.gaps、pipeline_runs.stats 还是二者都有，未统一。
            in_result = any(issue in f"{g.reason} {g.issue} {g!s}" for g in getattr(result, "gaps", []) or [])
            assert in_result or _pipeline_mentions_issue(engine, issue)
        assert GapReason.NO_SOURCE.value == "no_source"
        # TODO: 「运行状态 partial」写在 pipeline_runs.status 还是 UpsertStats，未立约。
        assert _pipeline_mentions_issue(engine, "partial") or getattr(stats, "status", None) == "partial"
        _assert_no_egress(before)
    finally:
        engines.close()


def test_fake_partial_codes_missing() -> None:
    """A-4 / 契约 :132。

    依赖：FakeDailyBarsSource.fetch、upsert_daily_bars；表 market.daily_bars；
    缺口 daily_bars_missing:<code>；状态 partial。
    """
    from app.ingest.netguard import netguard_blocks
    from app.schemas.enums import BarAdjust

    m = _impl()
    before = netguard_blocks()
    source = m.FakeDailyBarsSource()
    # TODO(T-T70 歧义): 3 个标的中指定 1 个无 bar 的注入方式未立约。
    codes = ["600001.SH", "600002.SH", "600003.SH"]
    day = dt.date(2026, 11, 9)
    result = source.fetch(codes, day, day, BarAdjust.NONE)
    engines = _temp_engine()
    engine = next(engines)
    try:
        with engine.begin() as conn:
            m.upsert_daily_bars(
                conn, result, source="fake", licence_id="", fetched_at=dt.datetime.now(dt.UTC)
            )
        # 写 2 个标的的行（行数是否按 adj_type 再拆，未另述）
        assert _count_daily_bars(engine) >= 2
        found_missing = False
        for code in codes:
            if _pipeline_mentions_issue(engine, f"daily_bars_missing:{code}"):
                found_missing = True
        if not found_missing:
            gaps = getattr(result, "gaps", []) or []
            found_missing = any("daily_bars_missing:" in f"{g.issue}" for g in gaps)
        assert found_missing
        _assert_no_egress(before)
    finally:
        engines.close()


def test_fake_source_deterministic_and_idempotent() -> None:
    """A-5 / 契约 :133。

    依赖：FakeDailyBarsSource、upsert_daily_bars（幂等键 code, trade_date, adj_type）；
    表 market.daily_bars；UpsertStats（inserted / unchanged 仅在验收原文出现）。
    """
    from app.schemas.enums import BarAdjust

    m = _impl()
    source = m.FakeDailyBarsSource()
    codes = ["600001.SH"]
    day = dt.date(2026, 11, 9)
    first = source.fetch(codes, day, day, BarAdjust.NONE)
    second = source.fetch(codes, day, day, BarAdjust.NONE)
    # 确定性：同一 (code, trade_date) 种子应得到相同结果
    assert first == second or (first.bars == second.bars and first.gaps == second.gaps)

    engines = _temp_engine()
    engine = next(engines)
    try:
        fetched_at = dt.datetime(2026, 11, 9, 8, 0, tzinfo=dt.UTC)
        with engine.begin() as conn:
            m.upsert_daily_bars(conn, first, source="fake", licence_id="", fetched_at=fetched_at)
        with engine.connect() as conn:
            from app.db.tables.market import daily_bars

            row1 = conn.execute(select(daily_bars)).all()
            seen = {r.fetched_at for r in row1}
        with engine.begin() as conn:
            stats = m.upsert_daily_bars(
                conn, second, source="fake", licence_id="", fetched_at=dt.datetime(2026, 11, 9, 9, 0, tzinfo=dt.UTC)
            )
        # TODO(T-T70 歧义): UpsertStats 字段未在 §1 定义；验收原文要求 inserted=0、unchanged=全部。
        assert getattr(stats, "inserted", None) == 0
        with engine.connect() as conn:
            from app.db.tables.market import daily_bars

            row2 = conn.execute(select(daily_bars)).all()
        assert len(row2) == len(row1)
        assert {r.fetched_at for r in row2} == seen
    finally:
        engines.close()


def test_upsert_conflict_never_overwrites() -> None:
    """A-6 / 契约 :134。

    依赖：upsert_daily_bars；表 market.daily_bars（主键 code, trade_date, adj_type；
    列 close、fetched_at）；缺口 daily_bar_conflict:<code>:<date>。无独立冲突表。
    """
    m = _impl()
    day = dt.date(2026, 11, 9)
    code = "600001.SH"
    t0 = dt.datetime(2026, 11, 9, 8, 0, tzinfo=dt.UTC)
    bar_kw = dict(
        code=code,
        trade_date=day,
        open=10,
        high=11,
        low=9,
        close=10,
        pre_close=10,
        volume=1,
        amount=10,
        adj_type="none",
        is_suspended=False,
    )
    first = m.DailyBarsResult(bars=[m.DailyBar(**bar_kw)], gaps=[], halted=None)
    second_kw = dict(bar_kw)
    second_kw["close"] = 12
    second = m.DailyBarsResult(bars=[m.DailyBar(**second_kw)], gaps=[], halted=None)
    engines = _temp_engine()
    engine = next(engines)
    try:
        with engine.begin() as conn:
            m.upsert_daily_bars(conn, first, source="fake", licence_id="", fetched_at=t0)
        with engine.begin() as conn:
            stats = m.upsert_daily_bars(
                conn, second, source="fake", licence_id="", fetched_at=dt.datetime(2026, 11, 9, 9, 0, tzinfo=dt.UTC)
            )
        with engine.connect() as conn:
            from app.db.tables.market import daily_bars

            row = conn.execute(
                select(daily_bars).where(
                    daily_bars.c.code == code,
                    daily_bars.c.trade_date == day,
                    daily_bars.c.adj_type == "none",
                )
            ).one()
        assert row.close is not None and str(row.close).startswith("10")
        assert row.fetched_at == t0 or row.fetched_at == t0.replace(tzinfo=None)
        issue = f"daily_bar_conflict:{code}:{day}"
        # TODO(T-T70 歧义): 契约未定义独立冲突表或字段，只要求记 issue 字符串（:31/:134/:187）。
        # 持久化位置未立约，故 pipeline_runs 或 upsert 返回值任一出现该字符串即视为已记。
        assert _pipeline_mentions_issue(engine, issue) or issue in f"{stats}"
    finally:
        engines.close()


def test_only_writer_inserts_daily_bars() -> None:
    """A-7 / 契约 :135。

    依赖：upsert_daily_bars；扫描范围 src/backend/app；表 market.daily_bars。
    """
    m = _impl()
    assert callable(m.upsert_daily_bars)
    writers: list[str] = []
    write_pat = (
        "insert(daily_bars",
        "update(daily_bars",
        "delete(daily_bars",
        "daily_bars.insert",
        "daily_bars.update",
        "daily_bars.delete",
        "INSERT INTO market.daily_bars",
        "insert into market.daily_bars",
    )
    for path in APP_ROOT.rglob("*.py"):
        text_src = path.read_text(encoding="utf-8")
        rel = path.relative_to(APP_ROOT).as_posix()
        hits = [p for p in write_pat if p.lower() in text_src.lower() or p in text_src]
        if not hits:
            continue
        writers.append(rel)
    # 只允许 app/marketdata/daily_bars.py 中的 upsert_daily_bars 写该表
    assert writers == ["marketdata/daily_bars.py"] or (
        writers and all(w == "marketdata/daily_bars.py" for w in writers)
    )
    # 函数体本身须含写语句，避免「目录里完全没有写者」被误判为通过
    src = ast.parse((APP_ROOT / "marketdata/daily_bars.py").read_text(encoding="utf-8"))
    fn = next(
        n for n in src.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "upsert_daily_bars"
    )
    body = ast.get_source_segment((APP_ROOT / "marketdata/daily_bars.py").read_text(encoding="utf-8"), fn) or ""
    assert any(p.lower() in body.lower() or p in body for p in write_pat)


def test_non_trading_day_noop_and_calendar_not_covered() -> None:
    """A-8 / 契约 :136。

    依赖：daily_bars_fetch 或经 reports/service.covered；表 market.trading_calendar、
    market.daily_bars、app.pipeline_runs；缺口 calendar_not_covered。
    """
    from app.ingest.netguard import netguard_blocks

    _impl()
    fetch_job = _daily_bars_fetch_entry()
    before = netguard_blocks()
    engines = _temp_engine()
    engine = next(engines)
    try:
        # TODO(T-T70 歧义): 任务入参未立约；休市日 vs 未覆盖日如何传给 fetch 未立约。
        # covered() 现网在缺行时抛 AppError(MAINTENANCE, issue=CALENDAR_NOT_COVERED)
        # （service.py:37-38），与契约「抛出 CALENDAR_NOT_COVERED」（:42）的字面不完全一致。
        closed = dt.date(2026, 11, 8)  # 需测试夹具保证其为 is_open=false 的已覆盖日
        missing = dt.date(2099, 1, 1)
        fetch_job()  # TODO: 传入 closed / missing
        _ = closed, missing
        assert _count_daily_bars(engine) == 0
        # 休市日无 issue、未覆盖日记 calendar_not_covered——两组应分开跑；此处先列契约原文断言。
        # TODO: 如何在同一例中隔离两组 pipeline_runs 未说明。
        assert _pipeline_mentions_issue(engine, "calendar_not_covered")
        _assert_no_egress(before)
    finally:
        engines.close()


def test_suspended_placeholder_becomes_gap_not_bar() -> None:
    """A-9 / 契约 :137。

    依赖：FakeDailyBarsSource、upsert_daily_bars；表 market.daily_bars（列 is_suspended、
    open/high/low/close）；构建快照后 gaps.reason=suspended，不进 bars。
    """
    from app.schemas.enums import BarAdjust

    m = _impl()
    source = m.FakeDailyBarsSource()
    # TODO(T-T70 歧义): 假源如何「报告当日停牌」未立约；
    # 「构建快照」的函数是 §2 / 实现单 B 的 build_owned_snapshot
    # （app/marketdata/daily_snapshot.py），但本例写在实现单 A 验收里。
    # GapReason 现网枚举无 suspended（enums.py:293-300）。
    day = dt.date(2026, 11, 9)
    result = source.fetch(["600001.SH"], day, day, BarAdjust.NONE)
    engines = _temp_engine()
    engine = next(engines)
    try:
        with engine.begin() as conn:
            m.upsert_daily_bars(
                conn, result, source="fake", licence_id="", fetched_at=dt.datetime.now(dt.UTC)
            )
        with engine.connect() as conn:
            from app.db.tables.market import daily_bars

            row = conn.execute(
                select(daily_bars).where(daily_bars.c.code == "600001.SH", daily_bars.c.trade_date == day)
            ).one()
        assert row.is_suspended is True
        assert row.open is None and row.high is None and row.low is None and row.close is None
        # 快照入口未在 A 立约，导入失败或缺失即红并列入歧义。
        from app.marketdata.daily_snapshot import build_owned_snapshot

        # TODO: build_owned_snapshot(conn, owner, date) 的 owner 如何取得未在本例给出。
        _ = build_owned_snapshot
    finally:
        engines.close()


def test_universe_holdings_only_until_clarified() -> None:
    """A-10 / 契约 :138。

    依赖：daily_universe(conn, owner, trade_date)；持仓口径沿用
    api/v1/portfolio._account(...).positions；表（种子未立约）可能涉及
    app.holdings / opening_positions / trades、app.watchlist_items、
    app.strategy_instances。
    """
    m = _impl()
    engines = _temp_engine()
    engine = next(engines)
    try:
        # TODO(T-T70 歧义): 如何写入「持仓 2 / 自选 1 / scope=security 实例 1」使
        # portfolio._account.positions 得到两只，契约未给出建行步骤。
        owner = uuid.uuid4()
        day = dt.date(2026, 11, 9)
        with engine.begin() as conn:
            got = m.daily_universe(conn, owner, day)
        assert isinstance(got, list)
        # 澄清前只返回持仓 2 只（Q4）。在种子未立约前，仅锁定「不得悄悄纳入自选/实例」的长度断言
        # 会误伤空库；因此要求实现后的结果恰好为那两只持仓代码——种子步骤待补。
        assert len(got) == 2
    finally:
        engines.close()
