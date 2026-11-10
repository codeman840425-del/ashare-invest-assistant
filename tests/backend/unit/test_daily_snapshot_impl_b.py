# ruff: noqa: S101
"""T-T71 / T-T71c / T-T71d 第 1 步：daily-snapshot-from-bars.md 实现单 B 验收。

T-T71 28 例名与契约 §8 一一对应；T-T71c 按 7234aa7 §12 新增 6 例。
T-T71d 第 1 步按 §11.1 补自选纳入范围的新例（af77bb5 上应为功能缺失红，消息「缺实现：…」）。
自选只在专用 helper 播种，不进 _seed_b。用例 14 的 Then 与 drafts 本步不动。
契约新符号一律在用例内部探测：缺失时以 ``assert ..., "缺实现：…"`` 报红，保证本文件可被收集。

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
from decimal import ROUND_HALF_UP, Decimal
from sqlalchemy import insert, select, text, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from daily_bars_t70_support import (  # noqa: E402
    APP_ROOT,
    BEIJING,
    CLOSED_08,
    CODE_A,
    CODE_B,
    CODE_C,
    CODE_D,
    CODE_E,
    CODE_G,
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
    conn.execute(insert(broker_position_snapshot_items).values(
        id=uuid.uuid4(), snapshot_id=ctx.snap1, security_code=CODE_H, quantity=100,
        sellable_quantity=100))
    seed_policy(conn, load_policy(ROOT / "config"))
    conn.execute(insert(feature_catalog).values(
        feature_key="f.close_qfq", unit="CNY/share", status="declared", source={"synthetic": True}))
    card, cardversion, strategy, version, instance = (uuid.uuid4() for _ in range(5))
    # 10.2：形状同 test_tb76_assembly 虚构接线卡（E/X/C/I），不是 tb76_daily 的单条 entry。
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
            for key, role, expr in (
                ("E", "entry", "f.close_qfq > 0"),
                ("X", "exit", "f.close_qfq > 0"),
                ("C", "counter", "f.close_qfq < 0"),
                ("I", "invalidation", "f.close_qfq < 0"),
            )
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



def _seed_u1_watchlist_e(conn: Any, ctx: SimpleNamespace) -> None:
    """§11.1：自选行只加在专用用例，不进公共种子。"""
    from app.db.tables.market import securities
    from app.db.tables.research import watchlist_items
    from app.schemas.enums import Board

    conn.execute(insert(securities).values(
        code=CODE_E, type="stock", name="合成E", exchange="SH", listing_status="listed",
        board=Board.MAIN.value))
    conn.execute(insert(watchlist_items).values(
        id=uuid.uuid4(), user_id=ctx.u1, security_code=CODE_E))



def _seed_u1_watchlist(conn: Any, ctx: SimpleNamespace, code: str) -> None:
    """§11.1：只写 u1 有效自选行（证券已在公共或专用种子中）。"""
    from app.db.tables.research import watchlist_items

    conn.execute(insert(watchlist_items).values(
        id=uuid.uuid4(), user_id=ctx.u1, security_code=code, removed_at=None))


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


def _owned_id(version: str, owner: uuid.UUID, day: dt.date, digest: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{version}:{owner}:{day.isoformat()}:{digest}")


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
        for status, expected in (
            ("skipped", False),
            ("failed", False),
            ("running", False),
            ("ok", True),
            ("partial", True),
        ):
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
        sid, _issues, row = _build(conn, b_db)
        assert row.hash == digest(row.items) == manifest_hash(row.items)
        assert sid == row.id == _owned_id(row.items["schema_version"], b_db.u1, OPEN_10, row.hash)


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
        out = prepare(inst, row.items["sessions"], as_of=as_of, factors=inst.get("factors") or [], registry={})
        assert out["features"]["f.is_suspended"] is True
        assert out["raw_close"] is None


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
    """§8 :166；§1 :30（Q4）；§11.1：自选 E 只在本例播种。

    af77bb5 的 daily_universe 尚未纳入自选，Then 仍排除 E（与播种前相同，断言不弱化）。
    T-B129 落地后 Then 才改为含 E；不在本单改期望。
    """
    _snapshot_mod()
    with b_db.engine.begin() as conn:
        _seed_u1_watchlist_e(conn, b_db)
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


class _CloseOverrideSource:
    """包装 FakeDailyBarsSource：只改 A 在 11-10 的 close，仍落在该行 [low, high] 内。"""

    def __init__(self, inner: Any, *, code: str, day: dt.date, close: Any) -> None:
        self._inner = inner
        self._code = code
        self._day = day
        self._close = close

    def fetch(self, codes: Any, start: Any, end: Any, adjust: Any) -> Any:
        import dataclasses

        raw = self._inner.fetch(codes, start, end, adjust)
        bars = []
        for bar in raw.bars:
            if bar.code == self._code and bar.trade_date == self._day:
                bar = dataclasses.replace(bar, close=self._close)
            bars.append(bar)
        return dataclasses.replace(raw, bars=tuple(bars))


def test_snapshot_conflict_keeps_first_row(b_db: SimpleNamespace) -> None:
    """§8 :168；§3 :101；§5 :123；§10.1 J5。"""
    mod = _snapshot_mod()
    m = _require_fetched_at()
    with b_db.engine.begin() as conn:
        _fetch_three(conn)
        sid1, _i, row1 = _build(conn, b_db)
        old = conn.execute(text(
            "SELECT close, low, high FROM market.daily_bars WHERE code=:c AND trade_date=:d"
        ), {"c": CODE_A, "d": OPEN_10}).mappings().one()
        close, low, high = old["close"], old["low"], old["high"]
        if high is not None and high != close:
            new_close = high
        elif low is not None and low != close:
            new_close = low
        else:
            raise AssertionError("无法在 [low, high] 内构造不同于原 close 的值")
        source = _CloseOverrideSource(
            m.FakeDailyBarsSource(), code=CODE_A, day=OPEN_10, close=new_close)
        m.fetch_and_record(
            conn, source, trade_date=OPEN_10, user_id=None, window_trading_days=None,
            fetched_at=_at(OPEN_10, 17, 20),
        )
        latest = conn.execute(text(
            "SELECT status, stats FROM app.pipeline_runs "
            "WHERE kind='daily_batch' AND step='daily_bars.fetch' AND run_date=:d "
            "ORDER BY finished_at DESC, started_at DESC LIMIT 1"
        ), {"d": OPEN_10}).mappings().one()
        issue = f"daily_bar_conflict:{CODE_A}:{OPEN_10.isoformat()}"
        assert latest["status"] == "partial"
        assert issue in (latest["stats"] or {}).get("issues", [])
        kept = conn.execute(text(
            "SELECT close FROM market.daily_bars WHERE code=:c AND trade_date=:d"
        ), {"c": CODE_A, "d": OPEN_10}).scalar_one()
        assert kept == close
        sid2, _i2, row2 = _build(conn, b_db)
        assert sid2 == sid1 and row2.hash == row1.hash
        out = _analyze(conn, b_db)
        assert issue in out["issues"]


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
    with b_db.engine.connect() as conn:
        assert _snap_count(conn) == before
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
        assert conn.execute(text(
            "SELECT count(*) FROM app.data_snapshots WHERE items->>'schema_version'='owned-daily-v1'"
        )).scalar_one() == 0


def test_analyze_test_env_off_keeps_tb70_path(b_db: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """§8 :170；§1 :33。模块尚未落地时不强制导入，按现状行为验收（可本就绿）。"""
    import app.workers.daily as daily

    calls = {"iso": 0, "build": 0, "ready": 0}

    def iso(*_a: Any, **_k: Any) -> None:
        calls["iso"] += 1

    def build(*_a: Any, **_k: Any) -> Any:
        calls["build"] += 1
        return None, ()

    def ready(*_a: Any, **_k: Any) -> Any:
        calls["ready"] += 1
        return False, ()

    monkeypatch.setattr(daily, "require_isolated", iso)
    spec = importlib.util.find_spec(B_MOD)
    if spec is not None:
        mod = importlib.import_module(B_MOD)
        if hasattr(mod, "build_owned_snapshot"):
            monkeypatch.setattr(mod, "build_owned_snapshot", build)
        if hasattr(daily, "build_owned_snapshot"):
            monkeypatch.setattr(daily, "build_owned_snapshot", build)
        if hasattr(mod, "daily_bars_ready"):
            monkeypatch.setattr(mod, "daily_bars_ready", ready)
        if hasattr(daily, "daily_bars_ready"):
            monkeypatch.setattr(daily, "daily_bars_ready", ready)
    with b_db.engine.begin() as conn:
        out = _analyze(conn, b_db, source="off")
    assert calls == {"iso": 1, "build": 0, "ready": 0}
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
    codes = {e["security_code"] for e in out["evaluations"]}
    assert {CODE_A, CODE_B} <= codes
    assert all(e["simulation"] is True for e in out["evaluations"])
    assert all(e["source_hash"] == row.hash for e in out["evaluations"])
    assert calls["iso"] == 0


def test_missing_factor_stays_gap_not_one(b_db: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """§8 :173；§2 :72；§3 :96；§10.1 J7。"""
    from app.features.pipeline import prepare

    mod = _snapshot_mod()
    with b_db.engine.begin() as conn:
        out, _ = _full_analyze(conn, b_db, monkeypatch)
        row = _owned_rows(conn, b_db.u1, mod.OWNED_VERSION)[0]
    ev = next(e for e in out["evaluations"] if e["security_code"] == CODE_A)
    sessions = row.items["sessions"]
    for d in sessions:
        assert f"adjust_factor_missing:{d}" in ev["gaps"]
    inst = _instr(row.items, CODE_A)
    assert inst is not None
    as_of = dt.datetime.combine(OPEN_10, mod.ANALYZE_AS_OF) if isinstance(mod.ANALYZE_AS_OF, dt.time) else mod.ANALYZE_AS_OF
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=BEIJING)
    prepared = prepare(inst, sessions, as_of=as_of, factors=inst.get("factors") or [], registry={})
    assert prepared["features"]["f.close_qfq"] is None
    assert all(v is None for v in prepared["series"]["f.close_qfq"])
    for item in ev["evidence"]:
        if item["key"] == "f.close_qfq":
            val = item["value"]
            if isinstance(val, (list, tuple)):
                assert all(v is None for v in val)
            else:
                assert val is None


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
        sid, _i, row = _build(conn, b_db)
        now = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=1)
        got = load_inputs(conn, b_db.u1, CODE_A, OPEN_10, now)
        assert got["sources"] == [
            {"kind": mod.OWNED_VERSION, "id": str(sid), "hash": row.hash}
        ]
        got9 = load_inputs(conn, b_db.u1, CODE_A, OPEN_09, now)
        assert got9["sources"] == []


def test_baseline_read_accepts_owned_keeps_filters(b_db: SimpleNamespace) -> None:
    """§8 :176；§1 :38。"""
    _snapshot_mod()
    from app.common.errors import AppError, ErrorCode
    from app.db.tables.licences import ROW_STATUSES, user_data_licences
    from app.db.tables.reviews import data_snapshots
    from app.replay.baseline import read

    with b_db.engine.begin() as conn:
        _fetch_three(conn)
        sid, _i, row = _build(conn, b_db)
        assert read(conn, b_db.u1, sid)
        with pytest.raises(AppError) as ei_other:
            read(conn, b_db.u2, sid)
        assert ei_other.value.code == ErrorCode.NOT_FOUND
        lic_id = uuid.uuid4()
        conn.execute(insert(user_data_licences).values(
            id=lic_id,
            user_id=b_db.u1,
            provider="mairui",
            seal_key_version=1,
            tier="free",
            status=ROW_STATUSES[0],
            deleted_at=dt.datetime.now(dt.UTC),
            ciphertext=None,
            licence_hmac=None,
        ))
        other = uuid.uuid4()
        conn.execute(insert(data_snapshots).values(
            id=other, user_id=b_db.u1, purpose="report", items=row.items, hash=row.hash,
            licence_id=lic_id))
        with pytest.raises(AppError) as ei_lic:
            read(conn, b_db.u1, other)
        assert ei_lic.value.code == ErrorCode.NOT_FOUND


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
    scheduled = jobs.schedule(_settings())
    assert not any(from_b(jobs.TASKS[name]) for name in scheduled if name in jobs.TASKS)
    assert not any(
        name in {"build_owned_snapshot", "daily_bars_ready"} or "daily_snapshot" in name
        for name in scheduled
    )
    slot_src = inspect.getsource(jobs.slot_jobs)
    for name in ("daily_snapshot", "build_owned_snapshot", "daily_bars_ready"):
        assert name not in slot_src
    jobs_text = (APP_ROOT / "workers/jobs.py").read_text(encoding="utf-8")
    for name in ("build_owned_snapshot", "daily_bars_ready", "daily_snapshot"):
        assert name not in jobs_text


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
    """§8 :180；§0 :14；§7 :135；§10.1 J11。不依赖 fetched_at 参数（A 现状即可）。"""
    m = _impl()
    from app.aggregates.service import select_account
    from app.api.v1.portfolio import _account, latest_daily_close
    from app.db.tables.accounts import (
        broker_position_snapshot_items,
        broker_position_snapshots,
        import_batches,
    )
    from app.db.tables.realtime import daily_reports
    from app.reports.service import build
    from app.tracking.service import instrument

    with b_db.engine.begin() as conn:
        # 持仓行只追加、禁止 DELETE。本例另写 version_no=2 快照（不含 H），使估值可计算。
        batch_id, snap2 = uuid.uuid4(), uuid.uuid4()
        conn.execute(insert(import_batches).values(
            id=batch_id, user_id=b_db.u1, account_id=b_db.acc1, status="committed", kind="positions"))
        conn.execute(insert(broker_position_snapshots).values(
            id=snap2, account_id=b_db.acc1, import_batch_id=batch_id,
            as_of=dt.datetime(2026, 11, 10, 15, 0, tzinfo=BEIJING), version_no=2))
        conn.execute(insert(broker_position_snapshot_items), [
            {"id": uuid.uuid4(), "snapshot_id": snap2, "security_code": code,
             "quantity": 100, "sellable_quantity": 100}
            for code in (CODE_A, CODE_B)
        ])
        for day, sus in ((OPEN_06, ()), (OPEN_09, ()), (OPEN_10, (CODE_B,))):
            m.fetch_and_record(conn, m.FakeDailyBarsSource(suspended=sus), trade_date=day,
                               user_id=None, window_trading_days=None)
        far = dt.datetime(2030, 1, 1, tzinfo=dt.UTC)
        bars = instrument(conn, CODE_B, OPEN_10, far)["bars"]
        assert OPEN_10.isoformat() not in {b["trade_date"] for b in bars}
        close = latest_daily_close(conn, {CODE_B}, OPEN_10)
        assert close[CODE_B][1].date() == OPEN_09
        rid = build(conn, b_db.u1, OPEN_10, far)
        report = conn.execute(select(daily_reports).where(daily_reports.c.id == rid)).one()
        assert report.body["account"] is not None
        prices = {
            (r.code, r.trade_date): r.close
            for r in conn.execute(text(
                "SELECT code, trade_date, close FROM market.daily_bars "
                "WHERE adj_type='none' AND close IS NOT NULL AND close > 0"
            ))
        }
        acc = _account(conn, select_account(conn, b_db.u1, None), OPEN_10)
        cash = acc.cash if acc.cash is not None else Decimal("0.00")
        # 本例最新快照只保留 A、B：H 按 J11 去掉；ETF D 不在 daily_universe、无日 K，
        # 留下会使估值不可计算。与 :245 的 A+B+现金口径一致。
        qty = Decimal("100")
        total = (
            Decimal(str(prices[(CODE_A, OPEN_10)])) * qty
            + Decimal(str(prices[(CODE_B, OPEN_09)])) * qty
            + cash
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert report.body["account"]["total_assets"] == format(total, "f")
        assert all(g.get("key") != "account." + CODE_B + ".price" for g in (report.gaps or []))


# ---------------------------------------------------------------------------
# T-T71c / §12（T-A137）6 例，名与 7234aa7 :432–:457 一一对应
# ---------------------------------------------------------------------------


def _seed_ineligible_g(conn: Any, ctx: SimpleNamespace) -> None:
    from app.db.tables.accounts import broker_position_snapshot_items
    from app.db.tables.market import securities

    conn.execute(insert(securities).values(
        code=CODE_G, type="stock", name="合成G", exchange="SH", listing_status=None))
    conn.execute(insert(broker_position_snapshot_items).values(
        id=uuid.uuid4(), snapshot_id=ctx.snap1, security_code=CODE_G,
        quantity=100, sellable_quantity=100))


def _insert_fake_bars(conn: Any, codes: tuple[str, ...], day: dt.date = OPEN_10) -> None:
    from app.marketdata.daily_bars import FakeDailyBarsSource, upsert_daily_bars
    from app.schemas.enums import BarAdjust

    result = FakeDailyBarsSource().fetch(list(codes), day, day, BarAdjust.NONE)
    upsert_daily_bars(
        conn, result, source="fake", licence_id=None, fetched_at=_at(day, 17, 15),
    )


def test_snapshot_excludes_ineligible_codes_silently(b_db: SimpleNamespace) -> None:
    """§12.1 :432。"""
    _snapshot_mod()
    with b_db.engine.begin() as conn:
        _seed_ineligible_g(conn, b_db)
        _fetch_three(conn)
        _insert_fake_bars(conn, (CODE_D, CODE_G))
        _sid, issues, row = _build(conn, b_db)
        inst_codes = {i["security_code"] for i in row.items["instruments"]}
        omitted_codes = {o["security_code"] for o in row.items["omitted"]}
        assert CODE_D not in inst_codes and CODE_G not in inst_codes
        assert CODE_D not in omitted_codes and CODE_G not in omitted_codes
        blob = " ".join(str(x) for x in issues)
        assert CODE_D not in blob and CODE_G not in blob


def test_analyze_ineligible_holding_not_evaluated(
    b_db: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§12.1 :433。"""
    _snapshot_mod()
    with b_db.engine.begin() as conn:
        _seed_ineligible_g(conn, b_db)
        _insert_fake_bars(conn, (CODE_D, CODE_G))
        out, _ = _full_analyze(conn, b_db, monkeypatch)
    ev_codes = {e.get("security_code") for e in out["evaluations"]}
    assert f"security_not_eligible:{CODE_D}" in out["issues"]
    assert f"security_not_eligible:{CODE_G}" in out["issues"]
    assert f"owned_source_security_missing:{CODE_D}" not in out["issues"]
    assert CODE_D not in ev_codes and CODE_G not in ev_codes


def test_report_account_null_when_holding_unpriced_uncosted(b_db: SimpleNamespace) -> None:
    """§12.1 :434。守护现状：持仓含无价无成本的 D 时 account 为 null。"""
    from app.db.tables.realtime import daily_reports
    from app.reports.service import build

    with b_db.engine.begin() as conn:
        far = dt.datetime(2030, 1, 1, tzinfo=dt.UTC)
        rid = build(conn, b_db.u1, OPEN_10, far)
        report = conn.execute(select(daily_reports).where(daily_reports.c.id == rid)).one()
    assert report.body["account"] is None
    assert any(g.get("key") == "account" for g in (report.body.get("gaps") or report.gaps or []))


def test_analyze_empty_catalog_rejects_run(b_db: SimpleNamespace) -> None:
    """§12.2 :446。虚构卡无 source_hash；空目录整次 ANALYZE 被拒。"""
    from app.workers.daily import analysis_task

    mod = _snapshot_mod()
    with b_db.engine.begin() as conn:
        conn.execute(text("DELETE FROM app.feature_catalog"))
        _fetch_three(conn)
        before_sugg = _suggestion_count(conn)
    settings = _settings(app_env="test", daily_bars_source="fake", database_url=b_db.url)
    with pytest.raises(ValueError, match="dsl_unknown_symbol"):
        analysis_task(settings, OPEN_10.isoformat(), user_id=str(b_db.u1))
    with b_db.engine.connect() as conn:
        run = conn.execute(text(
            "SELECT status, error FROM app.pipeline_runs "
            "WHERE step='tb76.daily_analysis' ORDER BY started_at DESC LIMIT 1"
        )).one()
        assert run.status == "failed"
        assert run.error == "ValueError"
        assert len(_owned_rows(conn, b_db.u1, mod.OWNED_VERSION)) == 0
        assert _suggestion_count(conn) == before_sugg == 0


def test_analyze_missing_catalog_with_source_hash_is_gate_issue(b_db: SimpleNamespace) -> None:
    """§12.2 :447。"""
    import copy

    from app.db.tables.strategy import strategy_instances, strategy_versions

    _snapshot_mod()
    with b_db.engine.begin() as conn:
        conn.execute(text("DELETE FROM app.feature_catalog"))
        version_id = conn.execute(
            select(strategy_instances.c.strategy_version_id).where(
                strategy_instances.c.id == b_db.instance
            )
        ).scalar_one()
        config = copy.deepcopy(conn.execute(
            select(strategy_versions.c.config).where(strategy_versions.c.id == version_id)
        ).scalar_one())
        config["source_hash"] = "tt71c-synthetic-source-hash"
        for rule in config["rules"]:
            rule["required_features"] = ["f.close_qfq"]
        conn.execute(
            update(strategy_versions)
            .where(strategy_versions.c.id == version_id)
            .values(config=config)
        )
        _fetch_three(conn)
        out = _analyze(conn, b_db)
    ev_codes = {e.get("security_code") for e in out["evaluations"]}
    assert "runtime_source_gate:f.close_qfq:feature_not_verified_doc_or_live" in out["issues"]
    assert ev_codes == set()


def test_report_build_now_before_ledger_nulls_account(b_db: SimpleNamespace) -> None:
    """§12.3 :457。now 早于 ledger_at 时不抛错，account 置空，持仓标的不出现。"""
    from app.db.tables.accounts import broker_position_snapshots
    from app.db.tables.realtime import daily_reports
    from app.reports.service import build

    with b_db.engine.begin() as conn:
        t = conn.execute(
            select(broker_position_snapshots.c.created_at).where(
                broker_position_snapshots.c.id == b_db.snap1
            )
        ).scalar_one()
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.UTC)
        rid = build(conn, b_db.u1, OPEN_10, t - dt.timedelta(hours=1))
        report = conn.execute(select(daily_reports).where(daily_reports.c.id == rid)).one()
    assert report.body["account"] is None
    gaps = report.body.get("gaps") or report.gaps or []
    assert any(g.get("key") == "account" for g in gaps)
    stocks = report.body.get("stocks") or []
    codes = {s.get("security_code") for s in stocks}
    assert CODE_A not in codes and CODE_B not in codes
    assert stocks == []


# ---------------------------------------------------------------------------
# T-T71d 第 1 步 / §11.1 自选纳入范围（新例；用例 14 Then 本步不动）
# af77bb5 上应为功能缺失红；T-B129 落地后转绿。
# ---------------------------------------------------------------------------


def test_analyze_watchlist_code_evaluated(
    b_db: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§11.1 :386；:379–:380。"""
    mod = _snapshot_mod()
    with b_db.engine.begin() as conn:
        _seed_u1_watchlist_e(conn, b_db)
        _insert_fake_bars(conn, (CODE_E,))
        out, _ = _full_analyze(conn, b_db, monkeypatch)
        rows = _owned_rows(conn, b_db.u1, mod.OWNED_VERSION)
    ev = next((e for e in out["evaluations"] if e.get("security_code") == CODE_E), None)
    assert ev is not None, (
        f"缺实现：自选 {CODE_E} 未进入 analyze 求值（契约 §11.1 :380、:386）"
    )
    assert rows, "缺实现：analyze 未写入 owned 快照（契约 §11.1 :386）"
    assert ev["source_hash"] == rows[0].hash, (
        "缺实现：自选 E 的 evaluation.source_hash 应等于快照 hash（契约 §11.1 :386）"
    )
    assert f"owned_source_security_missing:{CODE_E}" not in out["issues"], (
        f"缺实现：自选 {CODE_E} 仍记 owned_source_security_missing（契约 §11.1 :380、:386）"
    )


def test_ready_carries_watchlist_owner_issues(b_db: SimpleNamespace) -> None:
    """§11.1 :387（既有 test_ready_carries_only_owner_issues 的加一组）。

    不能把这组断言写进既有用例 4：本步须保持既有 34 例在 af77bb5 上全绿。
    """
    mod = _snapshot_mod()
    with b_db.engine.begin() as conn:
        _seed_u1_watchlist(conn, b_db, CODE_C)
        _run_row(conn, OPEN_10, "partial",
                 issues=[f"daily_bars_missing:{CODE_A}", f"daily_bars_missing:{CODE_C}"])
        got = mod.daily_bars_ready(conn, b_db.u1, OPEN_10)
        assert f"daily_bars_missing:{CODE_C}" in got[1], (
            f"缺实现：daily_bars_ready 的 owner 当日 universe 未包含自选 {CODE_C}"
            "（契约 §11.1 :381、:387）"
        )
        assert got[0] is True
        assert f"daily_bars_missing:{CODE_C}" in got[1]
        conn.rollback()


def test_snapshot_watchlist_change_new_id(b_db: SimpleNamespace) -> None:
    """§11.1 :388；:382。"""
    mod = _snapshot_mod()
    from app.reports.dimensions import load_inputs

    with b_db.engine.begin() as conn:
        _fetch_three(conn)
        _insert_fake_bars(conn, (CODE_E,))
        sid1, _i1, _row1 = _build(conn, b_db)
        _seed_u1_watchlist_e(conn, b_db)
        sid2, _i2, _row2 = _build(conn, b_db)
        assert sid1 is not None and sid2 is not None
        assert sid1 != sid2, (
            "缺实现：同日自选变化未得到新的 hash 与 id（契约 §11.1 :382、:388）"
        )
        rows = _owned_rows(conn, b_db.u1, mod.OWNED_VERSION)
        assert any(r.id == sid1 for r in rows), (
            "缺实现：自选变化后旧快照未被保留（契约 §11.1 :382、:388）"
        )
        now = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=1)
        got = load_inputs(conn, b_db.u1, CODE_A, OPEN_10, now)
        src_ids = [s.get("id") for s in got.get("sources") or []]
        assert src_ids and src_ids[0] == str(sid2), (
            "缺实现：load_inputs(u1, A, 当日) 未取自选变化后的快照（契约 §11.1 :388）"
        )
