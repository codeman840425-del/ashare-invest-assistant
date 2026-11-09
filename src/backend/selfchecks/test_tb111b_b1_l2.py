# ruff: noqa: S101
"""T-B111b / T-A79: B-1 memory escalate survives rehydrate; L-2 next-call rewrite.

Red on 79ffe61 (overwrite escalated_until); green after later()-merge + pending flush.
"""

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


class _ToggleEngine:
    """Routes to boom until ``recover()``; then delegates to a real Engine."""

    def __init__(self, real: Engine) -> None:
        self._real = real
        self._down = True
        self.begin_calls = 0
        self.connect_calls = 0

    def recover(self) -> None:
        self._down = False

    def connect(self) -> object:
        self.connect_calls += 1
        if self._down:
            raise RuntimeError("tb111b synthetic DB down")
        return self._real.connect()

    def begin(self) -> object:
        self.begin_calls += 1
        if self._down:
            raise RuntimeError("tb111b synthetic DB down")
        return self._real.begin()


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


@pytest.mark.skipif(not os.environ.get("TB111B_DATABASE_URL"), reason="TB111B_DATABASE_URL not set")
def test_tb111b_b1_write_fail_then_recover_user_reset_keeps_pause() -> None:
    """record fail → DB up → user_reset → still allows=False before deadline."""
    url = os.environ["TB111B_DATABASE_URL"]
    real = create_engine(url)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(real, uid, lid)
    tog = _ToggleEngine(real)
    core = IngestCore(CFG, engine=tog)  # type: ignore[arg-type]
    # upsert while down → fail-closed escalate in memory
    core.upsert(lid, user_id=uid, tier=TIER, status=ACTIVE, now=NOW0)
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=1), verify=True) is False
    until = core.user_escalated_until(lid)
    assert until is not None

    # record path also fails while down
    core.apply_ip_limited(lid, NOW0 + dt.timedelta(seconds=2))
    tog.recover()
    # user_reset rehydrates from empty DB; must NOT clear in-memory escalate (B-1)
    core.user_reset(lid, NOW0 + dt.timedelta(seconds=20))
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=20), verify=True) is False
    assert core.user_escalated_until(lid) is not None
    assert core.user_escalated_until(lid) >= until  # type: ignore[operator]


@pytest.mark.skipif(not os.environ.get("TB111B_DATABASE_URL"), reason="TB111B_DATABASE_URL not set")
def test_tb111b_b1_write_fail_then_recover_readd_keeps_pause() -> None:
    """record fail → DB up → remove+upsert new id same user → allows=False."""
    url = os.environ["TB111B_DATABASE_URL"]
    real = create_engine(url)
    uid, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _seed(real, uid, a)
    tog = _ToggleEngine(real)
    core = IngestCore(CFG, engine=tog)  # type: ignore[arg-type]
    core.upsert(a, user_id=uid, tier=TIER, status=ACTIVE, now=NOW0)
    core.apply_ip_limited(a, NOW0 + dt.timedelta(seconds=2))
    assert core.allows(a, Priority.P0, NOW0 + dt.timedelta(seconds=3)) is False
    tog.recover()
    core.remove(a)
    t_re = NOW0 + dt.timedelta(seconds=20)
    # new licence id, same user — rehydrate must keep in-memory escalate (B-1)
    core.upsert(b, user_id=uid, tier=TIER, status=ACTIVE, now=t_re)
    assert core.allows(b, Priority.P0, t_re, verify=True) is False


@pytest.mark.skipif(not os.environ.get("TB111B_DATABASE_URL"), reason="TB111B_DATABASE_URL not set")
def test_tb111b_l2_pending_flush_on_next_call() -> None:
    """L-2: after write fail, next successful call persists paused mark; still refuse until then."""
    url = os.environ["TB111B_DATABASE_URL"]
    real = create_engine(url)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(real, uid, lid)
    tog = _ToggleEngine(real)
    core = IngestCore(CFG)
    core.upsert(lid, user_id=uid, tier=TIER, status=ACTIVE, now=NOW0)
    core.engine = tog  # type: ignore[assignment]
    tr = core.apply_ip_limited(lid, NOW0)
    assert any(t.event == "ip_limited_escalated" for t in tr)
    mem = core.user_ip[uid]
    # pending queued only if attribute exists (post-fix); on 79ffe61 this may be absent → red
    pending = getattr(mem, "pending_escalation", None)
    assert pending is not None, "L-2 pending_escalation missing (pre-fix)"
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=1)) is False

    tog.recover()
    # next call: rehydrate/user_reset triggers one-shot flush
    core.user_reset(lid, NOW0 + dt.timedelta(seconds=5))
    assert mem.pending_escalation is None
    with real.connect() as conn:
        n_mark = conn.execute(
            text(
                "SELECT count(*) FROM ops.data_licence_events "
                "WHERE user_id=:u AND actor='ingest' AND event='paused' "
                "AND to_status='ip_limited'"
            ),
            {"u": uid},
        ).scalar_one()
    assert n_mark >= 1
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=5), verify=True) is False
