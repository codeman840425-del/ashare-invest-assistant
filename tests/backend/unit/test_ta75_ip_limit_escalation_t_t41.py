# ruff: noqa: S101
"""T-T41 / T-A75 方案 A：限流升级绕过正式用例（先红 8e847d5、后绿 be/T-B111）。

覆盖 T1 删后重加、T2 重启回填、T3 user_reset、T4 边界与隔离、T5 不泄露、T6 fail-closed。
同一文件可在 8e847d5 上以 upsert TypeError 回落跑出红（三条绕过断言失败）。
"""

from __future__ import annotations

import datetime as dt
import os
import re
import uuid
from pathlib import Path
from typing import Any, NoReturn

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
FAKE_LICENCE = "Tt41FakeLicence9x7Q2m"  # ≥4 chars; must never appear in events/logs


def _upsert(core: IngestCore, lid: uuid.UUID, *, user_id: uuid.UUID, now: dt.datetime) -> None:
    try:
        core.upsert(lid, user_id=user_id, tier=TIER, status=ACTIVE, now=now)
    except TypeError:
        core.upsert(lid, tier=TIER, status=ACTIVE)  # type: ignore[call-arg]


def _hit(core: IngestCore, lid: uuid.UUID, when: dt.datetime) -> list[str]:
    core.tick(when)
    if hasattr(core, "apply_ip_limited"):
        tr = core.apply_ip_limited(lid, when)
    else:
        from app.ingest.core import Call
        from app.ingest.upstream import Signal

        core.submit(lid, Priority.P0, Call(endpoint="tt41"))
        d = core.next_call(when)
        assert d is not None
        tr = core.complete(d, Signal.IP_LIMITED, when)
    return [t.event for t in tr]


def _allows(core: IngestCore, lid: uuid.UUID, when: dt.datetime, *, verify: bool) -> bool:
    if hasattr(core, "allows"):
        return core.allows(lid, Priority.P0, when, verify=verify)
    return core.state(lid).allows(Priority.P0, when, verify=verify)


def _user_reset(core: IngestCore, lid: uuid.UUID, when: dt.datetime) -> None:
    if hasattr(core, "user_reset"):
        try:
            core.user_reset(lid, when)
        except TypeError:
            core.user_reset(lid)  # type: ignore[call-arg]
    else:
        core.state(lid).user_reset()


# ---- T1 删掉后重加 ----


def test_ta75_t1_delete_readd_escalates_same_user() -> None:
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


# ---- T3 user_reset / 换证窗口 ----


def test_ta75_t3_user_reset_keeps_escalation() -> None:
    uid, lid = uuid.uuid4(), uuid.uuid4()
    core = IngestCore(CFG)
    _upsert(core, lid, user_id=uid, now=NOW0)
    for mins in (0, 5, 10):
        _hit(core, lid, NOW0 + dt.timedelta(minutes=mins))
    t_esc = NOW0 + dt.timedelta(minutes=10)
    _user_reset(core, lid, t_esc)
    assert _allows(core, lid, t_esc + dt.timedelta(seconds=1), verify=True) is False
    later = t_esc + dt.timedelta(seconds=CFG.ip_limited_escalate.pause_s + 1)
    core.tick(later)
    assert _allows(core, lid, later, verify=True) is True


def test_ta75_t3_other_licence_same_user_blocked_during_escalation() -> None:
    """升级期内同用户另一证书也不放行验证。"""
    uid, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    core = IngestCore(CFG)
    _upsert(core, a, user_id=uid, now=NOW0)
    for mins in (0, 5, 10):
        _hit(core, a, NOW0 + dt.timedelta(minutes=mins))
    t_esc = NOW0 + dt.timedelta(minutes=10)
    _upsert(core, b, user_id=uid, now=t_esc)
    assert _allows(core, b, t_esc + dt.timedelta(seconds=1), verify=True) is False


# ---- T2 重启 ----


@pytest.mark.skipif(not os.environ.get("TT41_DATABASE_URL"), reason="TT41_DATABASE_URL not set")
def test_ta75_t2_restart_rehydrates_and_escalates() -> None:
    url = os.environ["TT41_DATABASE_URL"]
    uid, a = uuid.uuid4(), uuid.uuid4()
    try:
        engine = create_engine(url, hide_parameters=True)
        core = IngestCore(CFG, engine=engine)
    except TypeError:
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


# ---- T4 边界与隔离 ----


def test_ta75_t4_isolation_and_post_mark_recount() -> None:
    """用户 A 的命中不影响用户 B；升级标记之后命中从 1 重新计。"""
    uid_a, uid_b = uuid.uuid4(), uuid.uuid4()
    a1, b1 = uuid.uuid4(), uuid.uuid4()
    core = IngestCore(CFG)
    _upsert(core, a1, user_id=uid_a, now=NOW0)
    for mins in (0, 5, 10):
        _hit(core, a1, NOW0 + dt.timedelta(minutes=mins))

    _upsert(core, b1, user_id=uid_b, now=NOW0)
    assert "ip_limited" in _hit(core, b1, NOW0)
    ev_b = _hit(core, b1, NOW0 + dt.timedelta(minutes=5))
    assert "ip_limited_escalated" not in ev_b
    assert "ip_limited" in ev_b

    t_after = NOW0 + dt.timedelta(minutes=10) + dt.timedelta(seconds=CFG.ip_limited_escalate.pause_s + 1)
    core.tick(t_after)
    assert "ip_limited" in _hit(core, a1, t_after)
    assert "ip_limited_escalated" not in _hit(core, a1, t_after + dt.timedelta(minutes=5))


# ---- T5 不泄露 ----


@pytest.mark.skipif(not os.environ.get("TT41_DATABASE_URL"), reason="TT41_DATABASE_URL not set")
def test_ta75_t5_events_have_no_licence_material() -> None:
    url = os.environ["TT41_DATABASE_URL"]
    try:
        engine = create_engine(url, hide_parameters=True)
        core = IngestCore(CFG, engine=engine)
    except TypeError:
        pytest.skip("baseline has no engine persistence")
    uid, lid = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app.users(id, username, password_hash, role, status) "
                "VALUES (:id, :u, 'x', 'user', 'approved')"
            ),
            {"id": uid, "u": f"v{uid.hex[:12]}"},
        )
        # ciphertext holds fictional material; events must not echo it
        conn.execute(
            text(
                "INSERT INTO app.user_data_licences("
                "id, user_id, ciphertext, seal_key_version, licence_hmac, tier, status"
                ") VALUES ("
                ":id, :uid, convert_to(:lic, 'UTF8'), 1, decode(:hm,'hex'), 'annual', 'active')"
            ),
            {"id": lid, "uid": uid, "lic": FAKE_LICENCE, "hm": uuid.uuid4().hex},
        )
    _upsert(core, lid, user_id=uid, now=NOW0)
    for mins in (0, 5, 10):
        _hit(core, lid, NOW0 + dt.timedelta(minutes=mins))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT event, actor, from_status, to_status, upstream_code, "
                "licence_id::text AS licence_id, user_id::text AS user_id "
                "FROM ops.data_licence_events WHERE user_id=:u"
            ),
            {"u": uid},
        ).mappings().all()
    blob = " | ".join(
        f"{r['event']}/{r['actor']}/{r['from_status']}/{r['to_status']}/"
        f"{r['upstream_code']}/{r['licence_id']}/{r['user_id']}"
        for r in rows
    )
    assert FAKE_LICENCE not in blob
    assert FAKE_LICENCE.lower() not in blob.lower()
    # ≥4 子串扫描（契约口径）；虚构证书任 4 连续字符不得出现
    for i in range(len(FAKE_LICENCE) - 3):
        frag = FAKE_LICENCE[i : i + 4]
        assert frag not in blob and frag.lower() not in blob.lower(), frag
    assert rows, "应有 ingest 事件行"
    colnames = list(rows[0].keys())
    for forbidden in ("licence_hmac", "fingerprint", "ciphertext"):
        assert forbidden not in colnames


# ---- T6 fail-closed ----


class _BoomEngine:
    def connect(self) -> NoReturn:
        raise RuntimeError("tt41 synthetic DB down")

    def begin(self) -> NoReturn:
        raise RuntimeError("tt41 synthetic DB down")


def test_ta75_t6_fail_closed_on_rehydrate_error() -> None:
    uid, lid = uuid.uuid4(), uuid.uuid4()
    try:
        core = IngestCore(CFG, engine=_BoomEngine())  # type: ignore[arg-type]
    except TypeError:
        pytest.fail("baseline IngestCore ignores engine → cannot fail-closed on rehydrate")
    core.upsert(lid, user_id=uid, tier=TIER, status=ACTIVE, now=NOW0)
    assert core.user_escalated_until(lid) is not None
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=1), verify=True) is False


def test_ta75_t6_fail_closed_on_record_hit_error() -> None:
    uid, lid = uuid.uuid4(), uuid.uuid4()
    try:
        core = IngestCore(CFG)
        core.upsert(lid, user_id=uid, tier=TIER, status=ACTIVE, now=NOW0)
        core.engine = _BoomEngine()  # type: ignore[assignment]
        tr = core.apply_ip_limited(lid, NOW0)
    except (TypeError, AttributeError, RuntimeError) as exc:
        # 8e847d5: no apply_ip_limited / no engine → treat as red for fail-closed
        pytest.fail(f"baseline cannot fail-closed on record: {type(exc).__name__}")
    assert any(t.event == "ip_limited_escalated" for t in tr)
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=1)) is False
