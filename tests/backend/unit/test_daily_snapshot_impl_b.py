# ruff: noqa: S101
"""T-T71：docs/contracts/daily-snapshot-from-bars.md（docs/T-A128=9065767）§8 实现单 B 验收，共 28 例。

基线 be/T-B127=50835e3（实现单 B 尚未落地）。用例名与契约 §8 :153–:180 一一对应。
契约新符号（app.marketdata.daily_snapshot 及 fetch_and_record 的 fetched_at 参数）
一律在用例内部探测：缺失时以 ``assert ..., "缺实现：…"`` 报红，保证本文件可被收集。

临时库与探针复用 tests/backend/daily_bars_t70_support.py（自 T-T70 复制，T-T70 文件不改）：
guard_temp_pg → TEMPLATE o61_tmp_0030 → upgrade head（动态单头）→ §7 种子 + H + tb76 链 → DROP。
麦蕊 0：拦 socket connect（只放 AF_UNIX/回环）+ egress.mairui_get 计数桩=0。
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib
import importlib.util
import inspect
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import insert, select, text, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from daily_bars_t70_support import (  # noqa: E402
    APP_ROOT,
    BEIJING,
    CLOSED_08,
    CODE_A,
    CODE_B,
    CODE_C,
    CODE_E,
    CODE_H,
    OPEN_06,
    OPEN_09,
    OPEN_10,
    ROOT,
    _impl,
    _open_temp_db,
    _settings,
    no_egress,  # noqa: F401
)

B_MOD = "app.marketdata.daily_snapshot"
B_SYMBOLS = ("daily_bars_ready", "build_owned_snapshot", "OWNED_VERSION", "ANALYZE_AS_OF", "FINAL_AFTER")
TOP_KEYS = {"schema_version", "trade_date", "calendar_basis", "sessions", "instruments", "omitted"}
BAR_KEYS = {
    "trade_date", "open", "high", "low", "close", "pre_close", "volume", "amount",
    "first_seen_at", "is_final",
}
NET_BANNED = ("app.ingest", "socket", "httpx", "requests", "urllib.request")


# ---------------------------------------------------------------------------
# 缺实现探测（不在模块顶层导入）
# ---------------------------------------------------------------------------


def _snapshot_mod() -> Any:
    spec = importlib.util.find_spec(B_MOD)
    assert spec is not None, f"缺实现：模块 {B_MOD} 不存在（契约 §1 :18）"
    mod = importlib.import_module(B_MOD)
    for name in B_SYMBOLS:
        assert hasattr(mod, name), f"缺实现：{B_MOD}.{name}（契约 §1 :19–:26）"
    return mod


def _require_fetched_at() -> Any:
    m = _impl()
    params = inspect.signature(m.fetch_and_record).parameters
    assert "fetched_at" in params, "缺实现：fetch_and_record 无 fetched_at 关键字参数（契约 §1 :40）"
    assert params["fetched_at"].kind is inspect.Parameter.KEYWORD_ONLY
    return m


def _at(day: dt.date, hh: int, mm: int = 0) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hh, mm), BEIJING)


def _fetch(conn: Any, day: dt.date, *, at: dt.datetime | None = None,
           missing: tuple[str, ...] = (), suspended: tuple[str, ...] = ()) -> int:
    m = _require_fetched_at()
    return m.fetch_and_record(
        conn,
        m.FakeDailyBarsSource(missing=missing, suspended=suspended),
        trade_date=day,
        user_id=None,
        window_trading_days=None,
        fetched_at=at or _at(day, 17, 15),
    )


def _fetch_three(conn: Any, **kw: Any) -> None:
    for day in (OPEN_06, OPEN_09, OPEN_10):
        _fetch(conn, day, **kw)


def _owned_rows(conn: Any, owner: uuid.UUID, version: str) -> list[Any]:
    from app.db.tables.reviews import data_snapshots

    return list(
        conn.execute(
            select(data_snapshots).where(
                data_snapshots.c.user_id == owner,
                data_snapshots.c["items"]["schema_version"].astext == version,
            )
        ).all()
    )


def _snap_count(conn: Any) -> int:
    return int(conn.execute(text("SELECT count(*) FROM app.data_snapshots")).scalar_one())


def _suggestion_count(conn: Any) -> int:
    return int(conn.execute(text("SELECT count(*) FROM app.suggestions")).scalar_one())


def _run_row(conn: Any, day: dt.date, status: str, *, user_id: Any = None,
             issues: list[str] | None = None, started: dt.datetime | None = None) -> None:
    from app.db.tables.realtime import pipeline_runs

    conn.execute(
        insert(pipeline_runs).values(
            kind="daily_batch",
            run_date=day,
            step="daily_bars.fetch",
            status=status,
            started_at=started or dt.datetime.now(dt.UTC),
            finished_at=started or dt.datetime.now(dt.UTC),
            stats={"user_id": str(user_id) if user_id else None, "issues": issues or []},
        )
    )


def _analyze(conn: Any, ctx: SimpleNamespace, *, app_env: str = "test", source: str = "fake",
             day: dt.date = OPEN_10) -> dict[str, Any]:
    from app.engine_policies import latest
    from app.workers.daily import analyze

    settings = _settings(app_env=app_env, daily_bars_source=source, database_url=ctx.url)
    return analyze(conn, settings, ctx.u1, day, "user", latest(conn))


# ---------------------------------------------------------------------------
# 种子：§7 + 板块 + H + tb76 形状实例链（契约 §8 :144–:148）
# ---------------------------------------------------------------------------


def _seed_b(conn: Any, ctx: SimpleNamespace) -> None:
    from app.db.tables.accounts import broker_position_snapshot_items
    from app.db.tables.market import securities
    from app.db.tables.research import watchlist_items
    from app.db.tables.strategy import (
        feature_catalog,
        strategies,
        strategy_card_versions,
        strategy_cards,
        strategy_instances,
        strategy_versions,
    )
    from app.engine_policies import load as load_policy
    from app.engine_policies import seed as seed_policy
    from app.schemas.enums import Board

    for code, board in ((CODE_A, Board.MAIN), (CODE_B, Board.CHINEXT), (CODE_C, Board.MAIN)):
        conn.execute(update(securities).where(securities.c.code == code).values(board=board.value))
    conn.execute(insert(securities).values(
        code=CODE_H, type="stock", name="合成H", exchange="BJ", listing_status="listed", board=None))
    conn.execute(insert(securities).values(
        code=CODE_E, type="stock", name="合成E", exchange="SH", listing_status="listed",
        board=Board.MAIN.value))
    conn.execute(insert(watchlist_items).values(id=uuid.uuid4(), user_id=ctx.u1, security_code=CODE_E))
    conn.execute(insert(broker_position_snapshot_items).values(
        id=uuid.uuid4(), snapshot_id=ctx.snap1, security_code=CODE_H, quantity=100,
        sellable_quantity=100))
    seed_policy(conn, load_policy(ROOT / "config"))
    conn.execute(insert(feature_catalog).values(
        feature_key="f.close_qfq", unit="CNY/share", status="declared", source={"synthetic": True}))
    card, cardversion, strategy, version, instance = (uuid.uuid4() for _ in range(5))
    spec = {
        "params_schema": {},
        "rules": [{"id": "fictional_only", "dimension": "technical", "role": "entry",
                   "expr": "ma(f.close_qfq,60) > 0", "eval_time": "daily"}],
        "action_map": {"entry_all_core_pass": "buy", "else": "wait"},
    }
    conn.execute(insert(strategy_cards).values(
        id=card, key="tt71_fiction_" + card.hex, title="明确虚构非正式卡", source_kind="user",
        owner_user_id=ctx.u1))
    conn.execute(insert(strategy_card_versions).values(
        id=cardversion, card_id=card, version_no=1, fields={"mount_policy": "user"}))
    conn.execute(insert(strategies).values(
        id=strategy, key="tt71_fiction_" + strategy.hex, name="明确虚构非正式卡",
        owner_user_id=ctx.u1, horizons=["swing"]))
    conn.execute(insert(strategy_versions).values(
        id=version, strategy_id=strategy, card_version_id=cardversion, version_no=1, config=spec,
        config_hash=version.hex, param_hash=version.hex, lifecycle="published"))
    conn.execute(insert(strategy_instances).values(
        id=instance, user_id=ctx.u1, strategy_version_id=version, scope="account",
        account_id=ctx.acc1, status="active", origin="user", horizon="swing"))
    ctx.instance = instance


@pytest.fixture
def b_db(no_egress: None) -> Iterator[SimpleNamespace]:  # noqa: F811
    gen = _open_temp_db()
    ctx = next(gen)
    try:
        with ctx.engine.begin() as conn:
            _seed_b(conn, ctx)
        yield ctx
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def _instr(items: dict[str, Any], code: str) -> dict[str, Any] | None:
    return next((i for i in items["instruments"] if i["security_code"] == code), None)


def _omitted_issues(items: dict[str, Any]) -> set[str]:
    return {o["issue"] for o in items["omitted"]}


def _build(conn: Any, ctx: SimpleNamespace, day: dt.date = OPEN_10) -> tuple[Any, Any, dict[str, Any]]:
    from app.db.tables.reviews import data_snapshots

    mod = _snapshot_mod()
    sid, issues = mod.build_owned_snapshot(conn, ctx.u1, day)
    assert sid is not None
    row = conn.execute(select(data_snapshots).where(data_snapshots.c.id == sid)).one()
    return sid, issues, row


# ---------------------------------------------------------------------------
# 1–3 daily_bars_ready（§1 :22–:25）
# ---------------------------------------------------------------------------


def test_ready_requires_ok_or_partial_run(b_db: SimpleNamespace) -> None:
    """§8 :153。"""
    mod = _snapshot_mod()
    with b_db.engine.begin() as conn:
        assert mod.daily_bars_ready(conn, b_db.u1, OPEN_10) == (False, ())
        for status, expected in (("skipped", False), ("failed", False), ("ok", True), ("partial", True)):  # Then :153 只写 ok；按用例名与 §1 :24 将 partial 视为 True，见报告 J13
            conn.execute(text("DELETE FROM app.pipeline_runs"))
            _run_row(conn, OPEN_10, status)
            assert mod.daily_bars_ready(conn, b_db.u1, OPEN_10)[0] is expected, status
        conn.rollback()


def test_ready_uses_latest_run_in_owner_scope(b_db: SimpleNamespace) -> None:
    """§8 :154。"""
    mod = _snapshot_mod()
    t0 = dt.datetime(2026, 11, 10, 9, 15, tzinfo=dt.UTC)
    with b_db.engine.begin() as conn:
        _run_row(conn, OPEN_10, "ok", started=t0)
        _run_row(conn, OPEN_10, "skipped", started=t0 + dt.timedelta(minutes=5))
        assert mod.daily_bars_ready(conn, b_db.u1, OPEN_10)[0] is False
        conn.execute(text("DELETE FROM app.pipeline_runs"))
        _run_row(conn, OPEN_10, "ok", user_id=b_db.u2, started=t0)
        assert mod.daily_bars_ready(conn, b_db.u1, OPEN_10)[0] is False
        conn.rollback()


def test_ready_carries_only_owner_issues(b_db: SimpleNamespace) -> None:
    """§8 :155；§1 :24。"""
    mod = _snapshot_mod()
    with b_db.engine.begin() as conn:
        _run_row(conn, OPEN_10, "partial",
                 issues=[f"daily_bars_missing:{CODE_A}", f"daily_bars_missing:{CODE_C}"])
        assert mod.daily_bars_ready(conn, b_db.u1, OPEN_10) == (True, (f"daily_bars_missing:{CODE_A}",))
        conn.rollback()


# ---------------------------------------------------------------------------
# 4–16 build_owned_snapshot（§2、§3、§5）
# ---------------------------------------------------------------------------


def test_snapshot_shape_fields_from_daily_bars(b_db: SimpleNamespace) -> None:
    """§8 :156；§2 :46–:72。"""
    _snapshot_mod()
    with b_db.engine.begin() as conn:
        _fetch_three(conn)
        _sid, _issues, row = _build(conn, b_db)
        items = row.items
        assert set(items) == TOP_KEYS
        assert not ({"factors", "scalars", "lots", "entry"} & set(items))
        assert items["sessions"] == [d.isoformat() for d in (OPEN_06, OPEN_09, OPEN_10)]
        for code in (CODE_A, CODE_B):
            inst = _instr(items, code)
            assert inst is not None and len(inst["bars"]) == 3
            for bar in inst["bars"]:
                assert set(bar) == BAR_KEYS
                assert bar["is_final"] is True
                day = dt.date.fromisoformat(bar["trade_date"])
                assert dt.datetime.fromisoformat(bar["first_seen_at"]) == _at(day, 17, 15)


def test_snapshot_hash_matches_dimensions_digest(b_db: SimpleNamespace) -> None:
    """§8 :157；§5 :120。"""
    _snapshot_mod()
    from app.replay.baseline import manifest_hash
    from app.reports.dimensions import digest

    with b_db.engine.begin() as conn:
        _fetch_three(conn)
        _sid, _issues, row = _build(conn, b_db)
        assert row.hash == digest(row.items) == manifest_hash(row.items)


def test_suspended_placeholder_becomes_gap_not_bar(b_db: SimpleNamespace) -> None:
    """§8 :158；§2 :71、:79；§0 :11。"""
    mod = _snapshot_mod()
    from app.features.pipeline import prepare

    with b_db.engine.begin() as conn:
        _fetch(conn, OPEN_06)
        _fetch(conn, OPEN_09)
        _fetch(conn, OPEN_10, suspended=(CODE_B,))
        _sid, _issues, row = _build(conn, b_db)
        inst = _instr(row.items, CODE_B)
        assert inst is not None
        assert OPEN_10.isoformat() not in {b["trade_date"] for b in inst["bars"]}
        assert {"trade_date": OPEN_10.isoformat(), "reason": "suspended"} in inst["gaps"]
        as_of = dt.datetime.combine(OPEN_10, mod.ANALYZE_AS_OF) if isinstance(mod.ANALYZE_AS_OF, dt.time) \
            else mod.ANALYZE_AS_OF
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=BEIJING)
        out = prepare(inst, row.items["sessions"], as_of=as_of, factors=[], registry={})
        # TODO(歧义 J3)：prepare 输出里 f.is_suspended 的确切路径契约未写明，按字符串查找。
        assert "is_suspended" in repr(out)


def test_snapshot_omits_code_without_today_bar(b_db: SimpleNamespace) -> None:
    """§8 :159；§2 :76。"""
    _snapshot_mod()
    with b_db.engine.begin() as conn:
        _fetch_three(conn, missing=(CODE_B,))
        _sid, _issues, row = _build(conn, b_db)
        assert _instr(row.items, CODE_B) is None
        assert f"daily_bars_missing:{CODE_B}" in _omitted_issues(row.items)


def test_snapshot_excludes_unsourced_legacy_rows(b_db: SimpleNamespace) -> None:
    """§8 :160；§2 :76；§3 :100。"""
    _snapshot_mod()
    with b_db.engine.begin() as conn:
        _fetch(conn, OPEN_06)
        _fetch(conn, OPEN_09)
        _fetch(conn, OPEN_10, missing=(CODE_A,))
        conn.execute(text(
            "INSERT INTO market.daily_bars (code, trade_date, adj_type, open, high, low, close, "
            "is_suspended, source, fetched_at) VALUES (:c, :d, 'none', 10, 10, 10, 10, false, NULL, :f)"
        ), {"c": CODE_A, "d": OPEN_10, "f": _at(OPEN_10, 17, 15)})
        _sid, _issues, row = _build(conn, b_db)
        assert _instr(row.items, CODE_A) is None
        assert f"daily_bars_missing:{CODE_A}" in _omitted_issues(row.items)


def test_snapshot_board_missing_omitted(b_db: SimpleNamespace) -> None:
    """§8 :161；§2 :64。"""
    _snapshot_mod()
    with b_db.engine.begin() as conn:
        _fetch_three(conn)
        _sid, _issues, row = _build(conn, b_db)
        assert _instr(row.items, CODE_H) is None
        assert f"security_board_missing:{CODE_H}" in _omitted_issues(row.items)
        assert _instr(row.items, CODE_A) is not None and _instr(row.items, CODE_B) is not None


def test_snapshot_today_bar_outside_final_window_omitted(b_db: SimpleNamespace) -> None:
    """§8 :162；§2 :77–:78；§9 QB1 :188。"""
    _snapshot_mod()
    with b_db.engine.begin() as conn:
        _fetch_three(conn)
        for code, at in ((CODE_A, _at(OPEN_10, 16)), (CODE_B, _at(OPEN_10, 20))):
            conn.execute(text(
                "UPDATE market.daily_bars SET fetched_at=:f WHERE code=:c AND trade_date=:d"
            ), {"f": at, "c": code, "d": OPEN_10})
        _sid, _issues, row = _build(conn, b_db)
        omitted = _omitted_issues(row.items)
        assert f"daily_bars_not_final:{CODE_A}" in omitted
        assert f"daily_bars_after_asof:{CODE_B}" in omitted


def test_snapshot_mairui_rows_unbound_in_b(b_db: SimpleNamespace) -> None:
    """§8 :163；§3 :99。"""
    _snapshot_mod()
    with b_db.engine.begin() as conn:
        _fetch_three(conn)
        conn.execute(text(
            "UPDATE market.daily_bars SET source='mairui' WHERE code=:c AND trade_date=:d"
        ), {"c": CODE_A, "d": OPEN_10})
        _sid, _issues, row = _build(conn, b_db)
        assert _instr(row.items, CODE_A) is None
        assert f"owned_snapshot_licence_unbound:{CODE_A}" in _omitted_issues(row.items)
        assert row.licence_id is None


def test_snapshot_closed_day_returns_none(b_db: SimpleNamespace) -> None:
    """§8 :164；§1 :29。"""
    mod = _snapshot_mod()
    with b_db.engine.begin() as conn:
        before = _snap_count(conn)
        assert mod.build_owned_snapshot(conn, b_db.u1, CLOSED_08) == (None, ())
        assert _snap_count(conn) == before


def test_snapshot_calendar_hole_not_built(b_db: SimpleNamespace) -> None:
    """§8 :165；§1 :27；§3 :95。"""
    mod = _snapshot_mod()
    with b_db.engine.begin() as conn:
        _fetch_three(conn)
        conn.execute(text("DELETE FROM market.trading_calendar WHERE date=:d"), {"d": OPEN_09})
        before = _snap_count(conn)
        assert mod.build_owned_snapshot(conn, b_db.u1, OPEN_10) == (None, ("calendar_not_covered",))
        assert _snap_count(conn) == before
        out = _analyze(conn, b_db)
        assert "calendar_not_covered" in out["issues"]


def test_snapshot_only_owner_universe(b_db: SimpleNamespace) -> None:
    """§8 :166；§1 :30（Q4）。"""
    _snapshot_mod()
    with b_db.engine.begin() as conn:
        _fetch_three(conn)
        _sid, _issues, row = _build(conn, b_db)
        codes = {i["security_code"] for i in row.items["instruments"]} | {
            o["security_code"] for o in row.items["omitted"]}
        assert CODE_C not in codes
        assert CODE_E not in codes


def test_owned_snapshot_idempotent_rerun(b_db: SimpleNamespace) -> None:
    """§8 :167；§5 :121–:122。"""
    mod = _snapshot_mod()
    with b_db.engine.begin() as conn:
        _fetch_three(conn)
        sid1, _ = mod.build_owned_snapshot(conn, b_db.u1, OPEN_10)
        sid2, _ = mod.build_owned_snapshot(conn, b_db.u1, OPEN_10)
        assert sid1 is not None and sid1 == sid2
        _analyze(conn, b_db)
        n1 = _suggestion_count(conn)
        _analyze(conn, b_db)
        assert _suggestion_count(conn) == n1
        assert len(_owned_rows(conn, b_db.u1, mod.OWNED_VERSION)) == 1


def test_snapshot_conflict_keeps_first_row(b_db: SimpleNamespace) -> None:
    """§8 :168；§3 :101；§5 :123。"""
    _snapshot_mod()
    m = _impl()
    with b_db.engine.begin() as conn:
        _fetch_three(conn)
        _sid, _i, row1 = _build(conn, b_db)
        old = conn.execute(text(
            "SELECT * FROM market.daily_bars WHERE code=:c AND trade_date=:d"
        ), {"c": CODE_A, "d": OPEN_10}).mappings().one()
        bar = m.DailyBar(
            code=CODE_A, trade_date=OPEN_10, adj_type="none", open=old["open"], high=old["high"],
            low=old["low"], close=old["close"] + 1, pre_close=old["pre_close"],
            volume=old["volume"], amount=old["amount"], is_suspended=False)
        m.upsert_daily_bars(conn, m.DailyBarsResult(bars=(bar,), gaps=(), halted=()),
                            source="fake", licence_id=None, fetched_at=_at(OPEN_10, 17, 20))
        # TODO(歧义 J5)：冲突 issue 须经运行记录带出（§3 :101）；此处补一条 partial 运行承载。
        _run_row(conn, OPEN_10, "partial", issues=[f"daily_bar_conflict:{CODE_A}:{OPEN_10}"])
        _sid2, _i2, row2 = _build(conn, b_db)
        assert row2.hash == row1.hash
        out = _analyze(conn, b_db)
        assert f"daily_bar_conflict:{CODE_A}:{OPEN_10}" in out["issues"]


# ---------------------------------------------------------------------------
# 17–22 analyze 解闸（§1 :32–:37；§4）
# ---------------------------------------------------------------------------


def test_analyze_off_keeps_legacy_issue_and_report(b_db: SimpleNamespace) -> None:
    """§8 :169；§3 :86。经 phase 跑 daily_analysis、daily_report。"""
    from app.db.tables.realtime import daily_reports, pipeline_runs
    from app.workers.daily import ANALYZE, REPORT, phase

    settings = _settings(app_env="local", daily_bars_source="off", database_url=b_db.url)
    with b_db.engine.connect() as conn:
        before = _snap_count(conn)
    assert phase(settings, ANALYZE, OPEN_10.isoformat()) >= 1
    assert phase(settings, REPORT, OPEN_10.isoformat()) >= 1
    with b_db.engine.connect() as conn:
        run = conn.execute(select(pipeline_runs).where(pipeline_runs.c.step == "tb76." + ANALYZE)
                           .order_by(pipeline_runs.c.started_at.desc())).first()
        outcome = run.stats["users"][str(b_db.u1)]
        assert outcome["evaluations"] == []
        assert "owned_market_cache_adapter_missing" in outcome["issues"]
        report = conn.execute(select(daily_reports).where(
            daily_reports.c.user_id == b_db.u1, daily_reports.c.trade_date == OPEN_10)).first()
        assert report is not None
        assert any("owned_market_cache_adapter_missing" in g["key"] for g in report.gaps)
        # TODO(歧义 J6)：report 自身是否写 data_snapshots 契约未写；此处只断言 analyze 后零新增 owned 行。
        assert _snap_count(conn) >= before
        assert conn.execute(text(
            "SELECT count(*) FROM app.data_snapshots WHERE items->>'schema_version'='owned-daily-v1'"
        )).scalar_one() == 0


def test_analyze_test_env_off_keeps_tb70_path(b_db: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """§8 :170；§1 :33。模块尚未落地时不强制导入，按现状行为验收（可本就绿）。"""
    import app.workers.daily as daily

    calls = {"iso": 0, "build": 0}

    def iso(*_a: Any, **_k: Any) -> None:
        calls["iso"] += 1

    def build(*_a: Any, **_k: Any) -> Any:
        calls["build"] += 1
        return None, ()

    monkeypatch.setattr(daily, "require_isolated", iso)
    spec = importlib.util.find_spec(B_MOD)
    if spec is not None:
        mod = importlib.import_module(B_MOD)
        if hasattr(mod, "build_owned_snapshot"):
            monkeypatch.setattr(mod, "build_owned_snapshot", build)
        if hasattr(daily, "build_owned_snapshot"):
            monkeypatch.setattr(daily, "build_owned_snapshot", build)
    with b_db.engine.begin() as conn:
        out = _analyze(conn, b_db, source="off")
    assert calls == {"iso": 1, "build": 0}
    # 改动前：tt71_ 库无 VERSION 快照 → owned_source_or_card_missing（现状 daily.py tb70 分支）。
    assert "owned_source_or_card_missing" in out["issues"]
    assert "daily_bars_not_ready" not in out["issues"]


def test_analyze_not_ready_no_bars_today(b_db: SimpleNamespace) -> None:
    """§8 :171；§1 :34。"""
    _snapshot_mod()
    from app.reports.service import build

    with b_db.engine.begin() as conn:
        snaps, sugg = _snap_count(conn), _suggestion_count(conn)
        out = _analyze(conn, b_db)
        assert out["evaluations"] == []
        assert "daily_bars_not_ready" in out["issues"]
        assert _suggestion_count(conn) == sugg and _snap_count(conn) == snaps
        assert build(conn, b_db.u1, OPEN_10, dt.datetime.now(dt.UTC)) is not None


def _full_analyze(conn: Any, ctx: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
                  **fetch_kw: Any) -> tuple[dict[str, Any], dict[str, int]]:
    import app.workers.daily as daily

    calls = {"iso": 0}

    def iso(*_a: Any, **_k: Any) -> None:
        calls["iso"] += 1

    monkeypatch.setattr(daily, "require_isolated", iso)
    _fetch_three(conn, **fetch_kw)
    assert not ctx.name.startswith("tb70_")
    return _analyze(conn, ctx), calls


def test_analyze_fake_bars_produces_evaluations(b_db: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """§8 :172；§1 :36。"""
    mod = _snapshot_mod()
    with b_db.engine.begin() as conn:
        out, calls = _full_analyze(conn, b_db, monkeypatch)
        row = _owned_rows(conn, b_db.u1, mod.OWNED_VERSION)[0]
    codes = {e.get("security_code") for e in out["evaluations"]}
    assert {CODE_A, CODE_B} <= codes
    assert all(e["simulation"] is True for e in out["evaluations"])
    # TODO(歧义 J7)：evaluation 内 source_hash 的确切键名契约未写，按 source_hash 取。
    assert all(e.get("source_hash") == row.hash for e in out["evaluations"])
    assert calls["iso"] == 0


def test_missing_factor_stays_gap_not_one(b_db: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """§8 :173；§2 :72；§3 :96。"""
    _snapshot_mod()
    with b_db.engine.begin() as conn:
        out, _ = _full_analyze(conn, b_db, monkeypatch)
    ev = next(e for e in out["evaluations"] if e.get("security_code") == CODE_A)
    text_ev = repr(ev)
    assert "adjust_factor_missing:" in text_ev
    # TODO(歧义 J7)：f.close_qfq 在 evaluation 中的路径未写明；断言不出现 1 补值的因子痕迹。
    assert "'value': '1'" not in text_ev and "'factor': '1'" not in text_ev


def test_analyze_partial_bars_gaps_no_fabricated_suggestion(
    b_db: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8 :174；§2 :80；§3 :89。"""
    _snapshot_mod()
    with b_db.engine.begin() as conn:
        out, _ = _full_analyze(conn, b_db, monkeypatch, missing=(CODE_B,))
        n_b = conn.execute(text(
            "SELECT count(*) FROM app.suggestions WHERE security_code=:c"), {"c": CODE_B}).scalar_one()
    codes = {e.get("security_code") for e in out["evaluations"]}
    assert CODE_A in codes and CODE_B not in codes
    assert f"daily_bars_missing:{CODE_B}" in out["issues"]
    assert f"owned_source_security_missing:{CODE_B}" in out["issues"]
    assert n_b == 0


# ---------------------------------------------------------------------------
# 23–25 下游读方与 A 侧参数
# ---------------------------------------------------------------------------


def test_load_inputs_accepts_owned_schema_same_day(b_db: SimpleNamespace) -> None:
    """§8 :175；§1 :39。"""
    mod = _snapshot_mod()
    from app.reports.dimensions import load_inputs

    with b_db.engine.begin() as conn:
        _fetch_three(conn)
        _build(conn, b_db)
        now = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=1)
        got = load_inputs(conn, b_db.u1, CODE_A, OPEN_10, now)
        # TODO(歧义 J8)：sources 元素的 kind 键形状未写明，按 repr 查 OWNED_VERSION。
        assert mod.OWNED_VERSION in repr(got.get("sources"))
        got9 = load_inputs(conn, b_db.u1, CODE_A, OPEN_09, now)
        assert mod.OWNED_VERSION not in repr(got9.get("sources"))


def test_baseline_read_accepts_owned_keeps_filters(b_db: SimpleNamespace) -> None:
    """§8 :176；§1 :38。"""
    _snapshot_mod()
    from app.common.errors import AppError
    from app.db.tables.reviews import data_snapshots
    from app.replay.baseline import read

    with b_db.engine.begin() as conn:
        _fetch_three(conn)
        sid, _i, row = _build(conn, b_db)
        assert read(conn, b_db.u1, sid)
        with pytest.raises(AppError):
            read(conn, b_db.u2, sid)
        lic = conn.execute(text("SELECT id FROM app.user_data_licences LIMIT 1")).scalar()
        # TODO(歧义 J9)：licence_id 非空行需一条 user_data_licences；临时库无则此半句无法构造。
        if lic is not None:
            other = uuid.uuid4()
            conn.execute(insert(data_snapshots).values(
                id=other, user_id=b_db.u1, purpose="report", items=row.items, hash=row.hash,
                licence_id=lic))
            with pytest.raises(AppError):
                read(conn, b_db.u1, other)


def test_fetch_and_record_fetched_at_injection(b_db: SimpleNamespace) -> None:
    """§8 :177；§1 :40。"""
    m = _require_fetched_at()
    with b_db.engine.begin() as conn:
        at = _at(OPEN_10, 17, 15)
        _fetch(conn, OPEN_10, at=at)
        got = conn.execute(text(
            "SELECT fetched_at FROM market.daily_bars WHERE code=:c AND trade_date=:d"
        ), {"c": CODE_A, "d": OPEN_10}).scalar_one()
        assert got == at
    with b_db.engine.begin() as conn:
        before = conn.execute(text("SELECT count(*) FROM market.daily_bars")).scalar_one()
        with pytest.raises(ValueError):
            m.fetch_and_record(conn, m.FakeDailyBarsSource(), trade_date=OPEN_09, user_id=None,
                               window_trading_days=None, fetched_at=dt.datetime(2026, 11, 9, 17, 15))
        after = conn.execute(text("SELECT count(*) FROM market.daily_bars")).scalar_one()
        assert after == before
    params = list(inspect.signature(m.daily_bars_fetch_task).parameters)
    assert params == ["settings", "trade_date", "user_id", "window_trading_days"]


# ---------------------------------------------------------------------------
# 26–27 不连库
# ---------------------------------------------------------------------------


def test_daily_snapshot_not_a_task() -> None:
    """§8 :178；§1 :18。负向断言：实现前后都应为绿。"""
    from app.workers import jobs

    def from_b(fn: Any) -> bool:
        return getattr(fn, "__module__", "") == B_MOD

    assert not any(from_b(fn) for fn in jobs.TASKS.values())
    assert not any("daily_snapshot" in str(t) for t in jobs.LOCKED_TASKS)
    assert not any(from_b(fn) for fn in jobs.RETRY_TASKS.values())
    # TODO(歧义 J10)：slot_jobs/schedule 需 redis/时钟，按源码静态检查而非调用。
    for fn in (jobs.slot_jobs, jobs.schedule):
        src = inspect.getsource(fn)
        for name in ("daily_snapshot", "build_owned_snapshot", "daily_bars_ready"):
            assert name not in src


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names.add(mod)
            names.update(f"{mod}.{a.name}" for a in node.names)
    return names


def test_impl_b_has_no_network_imports() -> None:
    """§8 :179；§6 :129。"""
    files = [
        APP_ROOT / "marketdata/daily_snapshot.py",
        APP_ROOT / "workers/daily.py",
        APP_ROOT / "replay/baseline.py",
        APP_ROOT / "reports/dimensions.py",
    ]
    assert files[0].exists(), "缺实现：app/marketdata/daily_snapshot.py 不存在（契约 §6 :129）"
    for path in files:
        bad = sorted(n for n in _imports(path)
                     if any(n == b or n.startswith(b + ".") for b in NET_BANNED))
        assert bad == [], f"{path.name}: {bad}"


# ---------------------------------------------------------------------------
# 28 停牌占位行与价格读方（§7 :135）
# ---------------------------------------------------------------------------


def test_placeholder_rows_ignored_by_price_readers(b_db: SimpleNamespace) -> None:
    """§8 :180；§0 :14；§7 :135。不依赖 fetched_at 参数（A 现状即可）。"""
    m = _impl()
    from app.api.v1.portfolio import latest_daily_close
    from app.reports.service import build
    from app.tracking.service import instrument

    with b_db.engine.begin() as conn:
        for day, sus in ((OPEN_06, ()), (OPEN_09, ()), (OPEN_10, (CODE_B,))):
            m.fetch_and_record(conn, m.FakeDailyBarsSource(suspended=sus), trade_date=day,
                               user_id=None, window_trading_days=None)
        far = dt.datetime(2030, 1, 1, tzinfo=dt.UTC)
        bars = instrument(conn, CODE_B, OPEN_10, far)["bars"]
        assert OPEN_10.isoformat() not in {b["trade_date"] for b in bars}
        close = latest_daily_close(conn, {CODE_B}, OPEN_10)
        assert close[CODE_B][1].date() == OPEN_09
        # TODO(歧义 J11)：日报估值取价的观测面契约未写；断言 build 不因占位行出错。
        assert build(conn, b_db.u1, OPEN_10, far) is not None
