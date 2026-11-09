# ruff: noqa: S101
"""T-B111 / T-A75: three bypass paths must escalate (green on fix; red on 8e847d5).

Same file is runnable on 8e847d5 via upsert TypeError fallback (no user_id kw).
On the unfixed baseline, assertions expecting cross-licence / persisted escalation fail.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, text

from app.config_files import IngestConfig
from app.ingest.core import IngestCore
from app.ingest.state import Priority
from app.schemas.enums import DataLicenceStatus, DataLicenceTier

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
TIER = DataLicenceTier.ANNUAL
ACTIVE = DataLicenceStatus.ACTIVE
NOW0 = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)


def _upsert(core: IngestCore, lid: uuid.UUID, *, user_id: uuid.UUID, now: dt.datetime) -> None:
    try:
        core.upsert(lid, user_id=user_id, tier=TIER, status=ACTIVE, now=now)
    except TypeError:
        # 8e847d5 baseline: no user_id / now
        core.upsert(lid, tier=TIER, status=ACTIVE)  # type: ignore[call-arg]


def _hit(core: IngestCore, lid: uuid.UUID, when: dt.datetime) -> list[str]:
    core.tick(when)
    if hasattr(core, "apply_ip_limited"):
        tr = core.apply_ip_limited(lid, when)
    else:
        from app.ingest.core import Call
        from app.ingest.upstream import Signal

        core.submit(lid, Priority.P0, Call(endpoint="tb111"))
        d = core.next_call(when)
        assert d is not None
        tr = core.complete(d, Signal.IP_LIMITED, when)
    return [t.event for t in tr]


def test_tb111_delete_readd_escalates_same_user() -> None:
    """T1: A hit×2 → remove(A) → upsert(B same user) → 3rd hit escalates."""
    uid, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    core = IngestCore(CFG)
    _upsert(core, a, user_id=uid, now=NOW0)
    assert "ip_limited" in _hit(core, a, NOW0)
    assert "ip_limited" in _hit(core, a, NOW0 + dt.timedelta(minutes=5))
    core.remove(a)
    t3 = NOW0 + dt.timedelta(minutes=10)
    _upsert(core, b, user_id=uid, now=t3)
    events = _hit(core, b, t3)
    assert "ip_limited_escalated" in events, events


def test_tb111_user_reset_keeps_escalation() -> None:
    """T3: after escalate, user_reset must not allow verify before deadline."""
    uid, lid = uuid.uuid4(), uuid.uuid4()
    core = IngestCore(CFG)
    _upsert(core, lid, user_id=uid, now=NOW0)
    for mins in (0, 5, 10):
        _hit(core, lid, NOW0 + dt.timedelta(minutes=mins))
    t_esc = NOW0 + dt.timedelta(minutes=10)
    # escalate deadline = t_esc + 3600
    if hasattr(core, "user_reset"):
        try:
            core.user_reset(lid, t_esc)
        except TypeError:
            core.user_reset(lid)  # type: ignore[call-arg]
    else:
        core.state(lid).user_reset()

    def _allows(verify: bool, when: dt.datetime) -> bool:
        if hasattr(core, "allows"):
            return core.allows(lid, Priority.P0, when, verify=verify)
        return core.state(lid).allows(Priority.P0, when, verify=verify)

    # Must stay blocked through the escalate window even after reset/PUT/test.
    assert _allows(True, t_esc + dt.timedelta(seconds=1)) is False
    later = t_esc + dt.timedelta(seconds=CFG.ip_limited_escalate.pause_s + 1)
    core.tick(later)
    assert _allows(True, later) is True


@pytest.mark.skipif(
    not os.environ.get("TB111_DATABASE_URL"),
    reason="TB111_DATABASE_URL not set",
)
def test_tb111_restart_rehydrates_and_escalates() -> None:
    """T2: persist 2 hits → new IngestCore + rehydrate → 3rd escalates."""
    url = os.environ["TB111_DATABASE_URL"]
    uid, a = uuid.uuid4(), uuid.uuid4()
    try:
        engine = create_engine(url)
        core = IngestCore(CFG, engine=engine)
    except TypeError:
        # 8e847d5: no engine / persistence → memory restart loses counts (bypass).
        core = IngestCore(CFG)
        _upsert(core, a, user_id=uid, now=NOW0)
        assert "ip_limited" in _hit(core, a, NOW0)
        assert "ip_limited" in _hit(core, a, NOW0 + dt.timedelta(minutes=5))
        core2 = IngestCore(CFG)
        t3 = NOW0 + dt.timedelta(minutes=10)
        _upsert(core2, a, user_id=uid, now=t3)
        events = _hit(core2, a, t3)
        assert "ip_limited_escalated" in events, events
        return

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
            {"id": a, "uid": uid, "hm": uuid.uuid4().hex},
        )

    _upsert(core, a, user_id=uid, now=NOW0)
    assert "ip_limited" in _hit(core, a, NOW0)
    assert "ip_limited" in _hit(core, a, NOW0 + dt.timedelta(minutes=5))

    core2 = IngestCore(CFG, engine=engine)
    t3 = NOW0 + dt.timedelta(minutes=10)
    _upsert(core2, a, user_id=uid, now=t3)
    events = _hit(core2, a, t3)
    assert "ip_limited_escalated" in events, events
    esc = core2.user_escalated_until(a)
    assert esc is not None
    assert esc == t3 + dt.timedelta(seconds=CFG.ip_limited_escalate.pause_s)

    with engine.connect() as conn:
        n_hit = conn.execute(
            text(
                "SELECT count(*) FROM ops.data_licence_events "
                "WHERE user_id=:u AND actor='ingest' AND event='ip_limited'"
            ),
            {"u": uid},
        ).scalar_one()
        n_mark = conn.execute(
            text(
                "SELECT count(*) FROM ops.data_licence_events "
                "WHERE user_id=:u AND actor='ingest' AND event='paused' "
                "AND to_status='ip_limited'"
            ),
            {"u": uid},
        ).scalar_one()
    assert n_hit == 3
    assert n_mark == 1
