# ruff: noqa: S101
"""T-T46 / T-B113：L-1′、L-10、runner tick、H12/S12 正式用例 + H17 锁定。

对照：c4e0e74 红 / 52d3bee 绿（H17 基线已有行为，两侧绿，作 G7 H17 证据）。
"""

from __future__ import annotations

import datetime as dt
import os
import threading
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config_files import IngestConfig, RiskControlsConfig
from app.ingest import ip_limit as ipl
from app.ingest.core import IngestCore
from app.schemas.enums import DataLicenceStatus, DataLicenceTier

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
TIER = DataLicenceTier.ANNUAL
ACTIVE = DataLicenceStatus.ACTIVE
NOW0 = dt.datetime(2026, 11, 9, 17, 0, tzinfo=dt.UTC)

HOLDINGS_WATCH = {"pool": "持仓 ∪ 自选", "boards": {"main": True}, "security_types": ["stock"]}
HOLDINGS_ONLY = {"pool": "持仓", "boards": {"main": True}, "security_types": ["stock"]}


def _require_tt41_db() -> str:
    url = os.environ.get("TT41_DATABASE_URL")
    if not url:
        pytest.skip(
            "TT41_DATABASE_URL 未设置：T-T46 L-10 需要隔离 PG；"
            "请 export TT41_DATABASE_URL=postgresql+psycopg://… 后重跑"
        )
    return url


def _seed(engine: Engine, uid: uuid.UUID, lid: uuid.UUID) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app.users(id, username, password_hash, role, status) "
                "VALUES (:id, :u, 'x', 'user', 'approved')"
            ),
            {"id": uid, "u": f"u{uid.hex[:12]}"},
        )
        conn.execute(
            text(
                "INSERT INTO app.user_data_licences("
                "id, user_id, ciphertext, seal_key_version, licence_hmac, tier, status"
                ") VALUES ("
                ":id, :uid, decode('00','hex'), 1, decode(:hm,'hex'), 'annual', 'active')"
            ),
            {"id": lid, "uid": uid, "hm": uuid.uuid4().hex},
        )


# ---- L-1′：SERVICE_NAME=ingest 或 APP_ENV∉{local,test} 时 engine 必填 ----


def test_tb113_l1prime_service_ingest_requires_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "ingest")
    monkeypatch.setenv("APP_ENV", "local")
    with pytest.raises(RuntimeError, match="engine is required"):
        IngestCore(CFG)


def test_tb113_l1prime_staging_requires_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "staging")
    with pytest.raises(RuntimeError, match="engine is required"):
        IngestCore(CFG)


def test_tb113_l1prime_local_api_allows_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    assert IngestCore(CFG).engine is None


# ---- L-10：等锁/语句超时后 fail-closed，pending 保留 ----


def test_tb113_l10_tick_lock_timeout_keeps_pending() -> None:
    url = _require_tt41_db()
    engine = create_engine(url, hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(engine, uid, lid)
    core = IngestCore(CFG, engine=engine)
    core.upsert(lid, user_id=uid, tier=TIER, status=ACTIVE, now=NOW0)
    mem = core.user_ip[uid]
    mem.escalated_until = NOW0 + dt.timedelta(hours=1)
    ipl.queue_pending_escalation(
        mem,
        licence_id=lid,
        user_id=uid,
        from_status="active",
        upstream_code="103",
        at=NOW0,
    )
    key = (
        ipl.ip_limit_lock_key(uid)
        if hasattr(ipl, "ip_limit_lock_key")
        else f"ingest:ip_limit:{uid}"
    )
    holder = engine.connect()
    holder.execute(text("SELECT pg_advisory_lock(hashtext(:k))"), {"k": key})
    result: dict[str, float | bool | None] = {"elapsed": None, "pending": None}
    done = threading.Event()

    def _run() -> None:
        t0 = time.monotonic()
        try:
            core.tick(NOW0 + dt.timedelta(seconds=1))
        finally:
            result["elapsed"] = time.monotonic() - t0
            result["pending"] = mem.pending_escalation is not None
            done.set()

    th = threading.Thread(target=_run)
    th.start()
    finished = done.wait(timeout=4.0)
    if not finished:
        holder.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": key})
        holder.close()
        th.join(timeout=5)
        pytest.fail("L-10 红：tick 在 4s 后仍阻塞（无 lock_timeout，c4e0e74 预期）")
    holder.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": key})
    holder.close()
    th.join(timeout=5)
    assert result["elapsed"] is not None
    assert float(result["elapsed"]) < 3.5, f"elapsed={result['elapsed']}"
    assert result["pending"] is True
    assert float(result["elapsed"]) >= 1.0, "应等待 lock_timeout 后再 fail-closed 返回"


# ---- runner：write_heartbeat 每轮调用 tick_ingest_core ----


def test_tb113_write_heartbeat_source_calls_tick_ingest_core() -> None:
    src = (ROOT / "src/backend/app/workers/ingest.py").read_text(encoding="utf-8")
    assert "tick_ingest_core" in src, "runner 缺少 IngestCore.tick 调用点（T-A84 / c4e0e74 红）"
    # 必须落在 write_heartbeat 体内，而非仅 import
    assert "def write_heartbeat" in src
    wh = src.split("def write_heartbeat", 1)[1].split("\ndef ", 1)[0]
    assert "tick_ingest_core" in wh


def test_tb113_tick_ingest_core_invokes_core_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    try:
        from app.ingest import runtime
    except ImportError:
        pytest.fail("app.ingest.runtime 缺失 — tick 接线未落地（c4e0e74 红）")
    core = IngestCore(CFG)
    called: list[dt.datetime] = []

    def _capture(now: dt.datetime) -> list[Any]:
        called.append(now)
        return []

    monkeypatch.setattr(core, "tick", _capture)
    runtime.set_ingest_core(core)
    try:
        when = dt.datetime(2026, 11, 9, 17, 0, tzinfo=dt.UTC)
        runtime.tick_ingest_core(when)
        assert called == [when]
    finally:
        runtime.set_ingest_core(None)


def test_tb113_write_heartbeat_invokes_tick_ingest_core(monkeypatch: pytest.MonkeyPatch) -> None:
    """每轮 write_heartbeat 实际调用 tick_ingest_core（不连真实 Redis/DB）。"""
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    from app.workers import ingest as ingest_worker

    calls: list[str] = []

    class _FakeRedis:
        def set(self, *a: object, **k: object) -> bool:
            return True

        def exists(self, *a: object, **k: object) -> int:
            return 0

        def close(self) -> None:
            return None

    class _HB:
        ttl_s = 30

    class _BizIngest:
        heartbeat = _HB()

    class _Business:
        ingest = _BizIngest()

    class _Settings:
        redis_url = "redis://127.0.0.1:9/0"
        health_check_timeout_s = 1.0
        ingest_heartbeat_key = "tt46:hb"
        ingest_paused_key = "tt46:pause"
        database_url = None
        business = _Business()

    monkeypatch.setattr(
        ingest_worker.redis.Redis,
        "from_url",
        staticmethod(lambda *a, **k: _FakeRedis()),
    )

    def _fake_tick(*a: object, **k: object) -> None:
        calls.append("tick")

    # 若 runtime 不存在则导入失败 → 红
    import app.ingest.runtime as runtime  # noqa: F401

    monkeypatch.setattr(runtime, "tick_ingest_core", _fake_tick)
    ingest_worker.write_heartbeat(_Settings())  # type: ignore[arg-type]
    assert calls == ["tick"], f"write_heartbeat 未调用 tick_ingest_core，calls={calls}"


# ---- H12 / S12 screen 执行链 ----


def test_tb113_h12_system_only_evaluates_holdings_exits_only() -> None:
    try:
        from app.signals.screen import screen_membership
    except ImportError:
        pytest.fail("screen_membership 缺失（H12/S12 未实现，c4e0e74 红）")
    assert (
        screen_membership(
            universe=HOLDINGS_ONLY,
            quantity=0,
            on_watchlist=True,
            mount_policy="system_only",
            proposed_action="buy",
        )
        == "outside_universe"
    )
    assert (
        screen_membership(
            universe=HOLDINGS_ONLY,
            quantity=100,
            on_watchlist=False,
            mount_policy="system_only",
            proposed_action="buy",
        )
        == "system_exit_only"
    )
    assert (
        screen_membership(
            universe=HOLDINGS_ONLY,
            quantity=100,
            on_watchlist=False,
            mount_policy="system_only",
            proposed_action="sell",
        )
        is None
    )


def test_tb113_s12_screen_null_pool_is_holdings_union_watchlist_not_full_market() -> None:
    try:
        from app.signals.screen import screen_membership
    except ImportError:
        pytest.fail("screen_membership 缺失（H12/S12 未实现，c4e0e74 红）")
    assert (
        screen_membership(
            universe={"pool": None, "boards": {"main": True}, "security_types": ["stock"]},
            quantity=0,
            on_watchlist=False,
            mount_policy="user",
            proposed_action="buy",
        )
        == "universe_pool_not_supported"
    )
    assert (
        screen_membership(
            universe={"pool": "全市场", "boards": {"main": True}, "security_types": ["stock"]},
            quantity=Decimal(0),
            on_watchlist=False,
            mount_policy="user",
            proposed_action="buy",
        )
        == "universe_pool_not_supported"
    )
    assert (
        screen_membership(
            universe=HOLDINGS_WATCH,
            quantity=0,
            on_watchlist=False,
            mount_policy="user",
            proposed_action="buy",
        )
        == "outside_universe"
    )
    assert (
        screen_membership(
            universe=HOLDINGS_WATCH,
            quantity=0,
            on_watchlist=True,
            mount_policy="user",
            proposed_action="buy",
        )
        is None
    )


# ---- H17：锁定 sim_fail_horizon_unknown（基线已有，作 G7 H17 证据）----


def test_tb113_h17_missing_horizon_is_gap_not_counted() -> None:
    """H-01 多周期、version_horizon=None 时缺 horizon → sim_fail_horizon_unknown，不进 n。

    基线 c4e0e74 / 52d3bee 两侧均绿；本用例锁定行为，可作为 G7 H17 证据。
    """
    from app.feedback.core import Observation, simulated_failures

    h01_horizons = ("intraday_t", "short", "swing", "long")
    assert set(h01_horizons) == {"intraday_t", "short", "swing", "long"}
    raw = yaml.safe_load((ROOT / "config/risk_controls.yaml").read_text(encoding="utf-8"))
    cfg = RiskControlsConfig.model_validate(raw).rc5_loss_streak_drawdown
    owner, version = uuid.uuid4(), uuid.uuid4()
    at = dt.datetime(2026, 11, 9, 15, 0, tzinfo=dt.UTC)

    def _obs(*, horizon: str | None, direction_correct: bool, sid: str) -> Observation:
        return Observation(
            owner,
            version,
            uuid.uuid5(uuid.NAMESPACE_URL, sid),
            uuid.uuid5(uuid.NAMESPACE_URL, sid + "-inst"),
            at - dt.timedelta(days=2),
            horizon,
            5,
            "complete",
            direction_correct,
            at - dt.timedelta(days=1),
            at - dt.timedelta(days=1),
            (sid,),
        )

    good = _obs(horizon="short", direction_correct=False, sid="h01-known")
    missing = _obs(horizon=None, direction_correct=False, sid="h01-missing")
    metric = simulated_failures(
        owner,
        version,
        [good, missing],
        cfg,
        version_horizon=None,
        at=at,
    )
    assert "sim_fail_horizon_unknown" in metric.gaps
    assert metric.value == 1
