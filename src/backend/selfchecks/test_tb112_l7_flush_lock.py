# ruff: noqa: S101
"""T-B112 L-7: rehydrate/tick flush takes the same §4.1 advisory lock."""

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
NOW0 = dt.datetime(2026, 11, 9, 16, 0, tzinfo=dt.UTC)


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


@pytest.mark.skipif(not os.environ.get("TB112_DATABASE_URL"), reason="TB112_DATABASE_URL not set")
def test_tb112_l7_flush_blocks_on_same_advisory_lock() -> None:
    engine = create_engine(os.environ["TB112_DATABASE_URL"])
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
    ipl.queue_pending_escalation(
        mem,
        licence_id=lid,
        user_id=uid,
        from_status="active",
        upstream_code="103",
        at=NOW0,
    )
    # Prefer lock helper if present (post-fix); else raw key.
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
            core._try_flush_pending(uid) if hasattr(core, "_try_flush_pending") else None
            if not hasattr(core, "_try_flush_pending"):
                # baseline: rehydrate flush path without lock — returns fast
                with engine.begin() as conn:
                    ipl.flush_pending_escalation(conn, mem)
                    if mem.pending_escalation is None:
                        pass
        finally:
            elapsed.append(time.monotonic() - t0)
            done.set()

    th = threading.Thread(target=_flush)
    th.start()
    time.sleep(0.4)
    # Still blocked if lock taken (fixed); baseline returns ~0s
    blocked = not done.is_set()
    holder.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": key})
    holder.close()
    th.join(timeout=5)
    assert blocked, f"L-7: flush did not wait on advisory lock (elapsed={elapsed})"
    assert elapsed
    assert elapsed[0] >= 0.3
