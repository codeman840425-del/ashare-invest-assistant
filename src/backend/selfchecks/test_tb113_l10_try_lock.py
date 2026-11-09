# ruff: noqa: S101
"""T-B113 L-10: tick flush bounds lock wait; timeout keeps pending (fail-closed)."""

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
from app.schemas.enums import DataLicenceStatus, DataLicenceTier

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
NOW0 = dt.datetime(2026, 11, 9, 17, 0, tzinfo=dt.UTC)


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


@pytest.mark.skipif(not os.environ.get("TB113_DATABASE_URL"), reason="TB113_DATABASE_URL not set")
def test_tb113_l10_tick_lock_timeout_keeps_pending() -> None:
    """While another session holds the lock, tick must not hang forever."""
    engine = create_engine(os.environ["TB113_DATABASE_URL"])
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(engine, uid, lid)
    core = IngestCore(CFG, engine=engine)
    core.upsert(
        lid,
        user_id=uid,
        tier=DataLicenceTier.ANNUAL,
        status=DataLicenceStatus.ACTIVE,
        now=NOW0,
    )
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
    # Fixed path: lock_timeout ~2s then return. Baseline: blocks until we unlock.
    finished = done.wait(timeout=4.0)
    if not finished:
        holder.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": key})
        holder.close()
        th.join(timeout=5)
        pytest.fail("L-10: tick still blocked after 4s (no lock_timeout)")
    holder.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": key})
    holder.close()
    th.join(timeout=5)
    assert result["elapsed"] is not None
    assert result["elapsed"] < 3.5, f"elapsed={result['elapsed']}"
    assert result["pending"] is True
    # Must have waited for the timeout rather than returning instantly without trying.
    assert result["elapsed"] >= 1.0, "expected lock_timeout wait before fail-closed return"
