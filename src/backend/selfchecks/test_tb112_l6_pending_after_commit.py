# ruff: noqa: S101
"""T-B112 L-6: clear pending only after transaction commit succeeds."""

from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config_files import IngestConfig
from app.ingest import ip_limit as ipl

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
def test_tb112_l6_flush_keeps_pending_until_caller_clears() -> None:
    """flush_pending_escalation must not clear pending (commit may still fail)."""
    engine = create_engine(os.environ["TB112_DATABASE_URL"])
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
        wrote = ipl.flush_pending_escalation(conn, mem)
        # Mid-transaction: pending must still be set on fixed code.
        assert wrote is True or wrote is None  # old API returned None
        assert mem.pending_escalation is not None, (
            "L-6: pending cleared before commit (pre-fix)"
        )
    # Caller clears only after commit:
    mem.pending_escalation = None
    assert mem.pending_escalation is None


@pytest.mark.skipif(not os.environ.get("TB112_DATABASE_URL"), reason="TB112_DATABASE_URL not set")
def test_tb112_l6_commit_failure_retains_pending() -> None:
    """If the write txn aborts after flush, pending stays for retry."""
    engine = create_engine(os.environ["TB112_DATABASE_URL"])
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
            raise RuntimeError("tb112 synthetic commit abort")
    except RuntimeError:
        pass
    assert mem.pending_escalation is not None, "pending lost on aborted txn"
