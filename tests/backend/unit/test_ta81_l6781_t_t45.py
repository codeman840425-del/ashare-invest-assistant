# ruff: noqa: S101
"""T-T45 / T-A81 L-6·L-7·L-8 + T-A79 L-1 正式用例（对照 be/T-B112=810f89a）。

L-3（at 用调用方时钟）按派单不动，等架构师裁定。
"""

from __future__ import annotations

import datetime as dt
import os
import threading
import time
import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config_files import IngestConfig
from app.ingest import ip_limit as ipl
from app.ingest.core import IngestCore
from app.ingest.state import Priority
from app.schemas.enums import DataLicenceStatus, DataLicenceTier

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
TIER = DataLicenceTier.ANNUAL
ACTIVE = DataLicenceStatus.ACTIVE
NOW0 = dt.datetime(2026, 11, 9, 16, 0, tzinfo=dt.UTC)


def _require_tt41_db() -> str:
    url = os.environ.get("TT41_DATABASE_URL")
    if not url:
        pytest.skip(
            "TT41_DATABASE_URL 未设置：T-T45 L-6/L-7/L-8 需要隔离 PG；"
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


# ---- L-6：提交失败后 pending 保留 ----


def test_ta81_l6_flush_does_not_clear_pending_before_commit() -> None:
    """flush_pending_escalation 不得在事务提交前清 pending（T-A81 L-6）。"""
    url = _require_tt41_db()
    engine = create_engine(url, hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(engine, uid, lid)
    mem = ipl.UserIpLimitMemory()
    ipl.queue_pending_escalation(
        mem,
        licence_id=lid,
        user_id=uid,
        from_status="active",
        upstream_code="103",
        at=NOW0,
    )
    with engine.begin() as conn:
        ipl.flush_pending_escalation(conn, mem)
        assert mem.pending_escalation is not None, (
            "L-6 红：pending 在提交前已被清掉（56709d5 预期）"
        )


def test_ta81_l6_commit_abort_retains_pending() -> None:
    """写事务中途失败回滚后，pending 必须仍在，可重试补写。"""
    url = _require_tt41_db()
    engine = create_engine(url, hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(engine, uid, lid)
    mem = ipl.UserIpLimitMemory()
    ipl.queue_pending_escalation(
        mem,
        licence_id=lid,
        user_id=uid,
        from_status="active",
        upstream_code="103",
        at=NOW0,
    )
    try:
        with engine.begin() as conn:
            ipl.flush_pending_escalation(conn, mem)
            raise RuntimeError("tt45 synthetic commit abort")
    except RuntimeError:
        pass
    assert mem.pending_escalation is not None, "L-6：提交失败后 pending 丢失"
    with engine.connect() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM ops.data_licence_events "
                "WHERE user_id=:u AND actor='ingest'"
            ),
            {"u": uid},
        ).scalar_one()
    assert n == 0, "回滚后库内不应留下补写行"


# ---- L-7：补写时取咨询锁 ----


def test_ta81_l7_flush_waits_on_advisory_lock() -> None:
    """_try_flush_pending / 补写路径须先取与 record_hit 同一把咨询锁。"""
    url = _require_tt41_db()
    engine = create_engine(url, hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(engine, uid, lid)
    core = IngestCore(CFG, engine=engine)
    core.upsert(lid, user_id=uid, tier=TIER, status=ACTIVE, now=NOW0)
    mem = core.user_ip[uid]
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
    done = threading.Event()
    elapsed: list[float] = []

    def _flush() -> None:
        t0 = time.monotonic()
        try:
            if hasattr(core, "_try_flush_pending"):
                core._try_flush_pending(uid)
            else:
                # 56709d5：回填补写不取锁 → 立即返回（预期红）
                with engine.begin() as conn:
                    ipl.flush_pending_escalation(conn, mem)
        finally:
            elapsed.append(time.monotonic() - t0)
            done.set()

    th = threading.Thread(target=_flush)
    th.start()
    time.sleep(0.4)
    blocked = not done.is_set()
    holder.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": key})
    holder.close()
    th.join(timeout=5)
    assert blocked, f"L-7 红：补写未等待咨询锁（elapsed={elapsed}）"
    assert elapsed and elapsed[0] >= 0.3


# ---- L-8：tick 会补写 ----


def test_ta81_l8_tick_flushes_pending() -> None:
    """tick 对有 pending 的用户各尝试一次补写。"""
    url = _require_tt41_db()
    engine = create_engine(url, hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(engine, uid, lid)
    core = IngestCore(CFG, engine=engine)
    core.upsert(lid, user_id=uid, tier=TIER, status=ACTIVE, now=NOW0)
    mem = core.user_ip[uid]
    mem.escalated_until = NOW0 + dt.timedelta(seconds=CFG.ip_limited_escalate.pause_s)
    ipl.queue_pending_escalation(
        mem,
        licence_id=lid,
        user_id=uid,
        from_status="active",
        upstream_code="103",
        at=NOW0,
    )
    core.tick(NOW0 + dt.timedelta(seconds=1))
    assert mem.pending_escalation is None, "L-8 红：tick 未补写 pending（56709d5 预期）"
    with engine.connect() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM ops.data_licence_events "
                "WHERE user_id=:u AND actor='ingest' AND event='paused' "
                "AND to_status='ip_limited'"
            ),
            {"u": uid},
        ).scalar_one()
    assert n == 1
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=1), verify=True) is False


def test_ta81_l8_tick_flush_failure_keeps_pending() -> None:
    """tick 补写失败时 pending 保留且仍拒绝。"""

    class _BoomBegin:
        def __enter__(self) -> object:
            raise RuntimeError("tt45 tick flush boom")

        def __exit__(self, *a: object) -> None:
            return None

    class _BoomEngine:
        def connect(self) -> object:
            raise RuntimeError("unused")

        def begin(self) -> _BoomBegin:
            return _BoomBegin()

    core = IngestCore(CFG)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    core.upsert(lid, user_id=uid, tier=TIER, status=ACTIVE, now=NOW0)
    mem = core.user_ip[uid]
    mem.escalated_until = NOW0 + dt.timedelta(seconds=3600)
    ipl.queue_pending_escalation(
        mem,
        licence_id=lid,
        user_id=uid,
        from_status="active",
        upstream_code="103",
        at=NOW0,
    )
    core.engine = _BoomEngine()  # type: ignore[assignment]
    core.tick(NOW0 + dt.timedelta(seconds=1))
    assert mem.pending_escalation is not None
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=1), verify=True) is False


# ---- L-1：production 必须挂 engine ----


def test_ta79_l1_production_requires_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="engine is required"):
        IngestCore(CFG)


def test_ta79_l1_non_production_allows_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    core = IngestCore(CFG)
    assert core.engine is None
