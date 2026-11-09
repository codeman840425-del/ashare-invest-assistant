# ruff: noqa: S101
"""T-B112 L-8: tick attempts pending flush once per user."""

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
from app.ingest.core import IngestCore
from app.ingest.state import Priority
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
def test_tb112_l8_tick_flushes_pending() -> None:
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
    assert mem.pending_escalation is None, "L-8: tick did not flush pending"
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
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=1)) is False


@pytest.mark.skipif(not os.environ.get("TB112_DATABASE_URL"), reason="TB112_DATABASE_URL not set")
def test_tb112_l8_tick_flush_failure_keeps_pending() -> None:
    """Flush error on tick keeps pending and stays fail-closed."""

    class _BoomBegin:
        def __enter__(self) -> object:
            raise RuntimeError("tb112 tick flush boom")

        def __exit__(self, *a: object) -> None:
            return None

    class _BoomEngine:
        def connect(self) -> object:
            raise RuntimeError("unused")

        def begin(self) -> _BoomBegin:
            return _BoomBegin()

    # Real seed not needed — memory pending + boom engine
    core = IngestCore(CFG)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    core.upsert(
        lid,
        user_id=uid,
        tier=DataLicenceTier.ANNUAL,
        status=DataLicenceStatus.ACTIVE,
        now=NOW0,
    )
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
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=1)) is False
