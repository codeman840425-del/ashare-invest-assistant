# ruff: noqa: S101
"""T-B114: two simulated ingest starts — IP-limit escalation counts survive restart.

Requires TB114_DATABASE_URL (isolated PG with app/ops schema). Creates no containers;
caller owns CREATE/DROP of the temp DB.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config_files import IngestConfig
from app.ingest.core import IngestCore
from app.schemas.enums import DataLicenceStatus, DataLicenceTier

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
NOW0 = dt.datetime(2026, 11, 9, 18, 0, tzinfo=dt.UTC)
TIER = DataLicenceTier.ANNUAL
ACTIVE = DataLicenceStatus.ACTIVE


def _require_url() -> str:
    url = os.environ.get("TB114_DATABASE_URL")
    if not url:
        pytest.skip("TB114_DATABASE_URL not set (isolated temp DB required)")
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


def _hit(core: IngestCore, lid: uuid.UUID, when: dt.datetime) -> list[str]:
    core.tick(when)
    tr = core.apply_ip_limited(lid, when)
    return [t.event for t in tr]


def test_tb114_two_starts_escalation_count_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate start→2 hits→stop→start→3rd hit escalates from DB counts."""
    url = _require_url()
    monkeypatch.setenv("SERVICE_NAME", "ingest")
    monkeypatch.setenv("APP_ENV", "local")

    from app.db import engine as engine_mod
    from app.ingest import runtime
    from app.workers import ingest as ingest_worker

    # Fresh cache so bootstrap uses this URL's engine.
    engine_mod.engine_for.cache_clear()
    runtime.set_ingest_core(None)

    uid, lid = uuid.uuid4(), uuid.uuid4()
    admin = create_engine(url, hide_parameters=True)
    _seed(admin, uid, lid)

    class _HB:
        interval_s = 15
        ttl_s = 30

    class _BizIngest:
        heartbeat = _HB()
        licences = CFG

    class _Settings:
        database_url = SecretStr(url)
        business = SimpleNamespace(ingest=_BizIngest())

    # ---- start 1 ----
    eng1 = ingest_worker.bootstrap_ingest_core(_Settings())  # type: ignore[arg-type]
    core1 = runtime.get_ingest_core()
    assert core1 is not None
    assert core1.engine is eng1
    core1.upsert(lid, user_id=uid, tier=TIER, status=ACTIVE, now=NOW0)
    assert "ip_limited" in _hit(core1, lid, NOW0)
    assert "ip_limited" in _hit(core1, lid, NOW0 + dt.timedelta(minutes=5))

    with eng1.connect() as conn:
        n_hit = conn.execute(
            text(
                "SELECT count(*) FROM ops.data_licence_events "
                "WHERE user_id=:u AND actor='ingest' AND event='ip_limited'"
            ),
            {"u": uid},
        ).scalar_one()
    assert n_hit >= 2, f"start1 did not persist hits, n={n_hit}"

    # ---- stop (process memory cleared; DB remains) ----
    runtime.set_ingest_core(None)
    assert runtime.get_ingest_core() is None

    # ---- start 2 ----
    eng2 = ingest_worker.bootstrap_ingest_core(_Settings())  # type: ignore[arg-type]
    core2 = runtime.get_ingest_core()
    assert core2 is not None
    assert core2 is not core1
    assert core2.engine is not None
    # Same URL → engine_for cache may return same Engine object; that is fine.
    t3 = NOW0 + dt.timedelta(minutes=10)
    core2.upsert(lid, user_id=uid, tier=TIER, status=ACTIVE, now=t3)
    events = _hit(core2, lid, t3)
    assert "ip_limited_escalated" in events, f"restart lost counts; events={events}"

    # DB marks escalation as event=paused / to_status=ip_limited (not the in-memory name).
    with eng2.connect() as conn:
        n_esc = conn.execute(
            text(
                "SELECT count(*) FROM ops.data_licence_events "
                "WHERE user_id=:u AND actor='ingest' AND event='paused' "
                "AND to_status='ip_limited'"
            ),
            {"u": uid},
        ).scalar_one()
    assert n_esc >= 1
    assert core2.user_escalated_until(lid) is not None

    runtime.set_ingest_core(None)
    engine_mod.engine_for.cache_clear()
