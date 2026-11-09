# ruff: noqa: S101
"""T-T41/T-T43 / T-A75+A79：限流升级正式用例。

T-T43 增补：B-1（写失败后 user_reset/重加仍拒绝）、L-2（恢复后补写计数）、
L-4（T4 窗口边界、T5 扫日志、缺 TT41_DATABASE_URL 时带原因 skip）。
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import uuid
from pathlib import Path
from typing import NoReturn

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
FAKE_LICENCE = "Tt41FakeLicence9x7Q2m"  # ≥4 chars; must never appear in events/logs
FAKE_SECRET_FRAG = "APP_MASTER_KEY=never-log-this-tt43"


def _require_tt41_db() -> str:
    """T-A79 L-4：缺 URL 时带原因 skip（非静默）；正式验收须 export TT41_DATABASE_URL。"""
    url = os.environ.get("TT41_DATABASE_URL")
    if not url:
        pytest.skip(
            "TT41_DATABASE_URL 未设置：T2/T5/B-1/L-2 需要隔离 PG；"
            "请 export TT41_DATABASE_URL=postgresql+psycopg://… 后重跑（T-A79 L-4）"
        )
    return url


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


def _seed(engine: Engine, uid: uuid.UUID, lid: uuid.UUID, *, lic_text: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app.users(id, username, password_hash, role, status) "
                "VALUES (:id, :u, 'x', 'user', 'approved')"
            ),
            {"id": uid, "u": f"u{uid.hex[:12]}"},
        )
        if lic_text is None:
            conn.execute(
                text(
                    "INSERT INTO app.user_data_licences("
                    "id, user_id, ciphertext, seal_key_version, licence_hmac, tier, status"
                    ") VALUES ("
                    ":id, :uid, decode('00','hex'), 1, decode(:hm,'hex'), 'annual', 'active')"
                ),
                {"id": lid, "uid": uid, "hm": uuid.uuid4().hex},
            )
        else:
            conn.execute(
                text(
                    "INSERT INTO app.user_data_licences("
                    "id, user_id, ciphertext, seal_key_version, licence_hmac, tier, status"
                    ") VALUES ("
                    ":id, :uid, convert_to(:lic, 'UTF8'), 1, decode(:hm,'hex'), 'annual', 'active')"
                ),
                {"id": lid, "uid": uid, "lic": lic_text, "hm": uuid.uuid4().hex},
            )


class _ToggleEngine:
    """Routes to boom until ``recover()``; then delegates to a real Engine."""

    def __init__(self, real: Engine) -> None:
        self._real = real
        self._down = True

    def recover(self) -> None:
        self._down = False

    def connect(self) -> object:
        if self._down:
            raise RuntimeError("tt43 synthetic DB down")
        return self._real.connect()

    def begin(self) -> object:
        if self._down:
            raise RuntimeError("tt43 synthetic DB down")
        return self._real.begin()


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


def test_ta75_t2_restart_rehydrates_and_escalates() -> None:
    url = _require_tt41_db()
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

    _seed(engine, uid, a)
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


# ---- T4 边界与隔离（含 at==now−window 边界）----


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


def test_ta75_t4_window_boundary_at_equals_now_minus_window_counts() -> None:
    """T-A79 L-4 / 方案 T4：at == now−window_s 的命中仍计入（与 state 用 < 丢弃一致）。"""
    window = CFG.ip_limited_escalate.window_s
    uid, lid = uuid.uuid4(), uuid.uuid4()
    core = IngestCore(CFG)
    _upsert(core, lid, user_id=uid, now=NOW0)
    t0 = NOW0
    assert "ip_limited" in _hit(core, lid, t0)
    assert "ip_limited" in _hit(core, lid, t0 + dt.timedelta(seconds=window // 2))
    # 第三次恰好在 first+window：first 的 at == now-window，应仍保留 → 升级
    events = _hit(core, lid, t0 + dt.timedelta(seconds=window))
    assert "ip_limited_escalated" in events, events


# ---- T5 不泄露（事件行 + 日志）----


def test_ta75_t5_events_and_logs_have_no_licence_material(caplog: pytest.LogCaptureFixture) -> None:
    url = _require_tt41_db()
    try:
        engine = create_engine(url, hide_parameters=True)
        core = IngestCore(CFG, engine=engine)
    except TypeError:
        pytest.fail("受测树 IngestCore 不接受 engine，无法做持久化不泄露验收（非静默 skip）")
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(engine, uid, lid, lic_text=FAKE_LICENCE)
    with caplog.at_level(logging.DEBUG):
        # inject a decoy secret into logger namespace; production path must not echo licence
        logging.getLogger("app.ingest").debug("tt43 decoy %s", FAKE_SECRET_FRAG)
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
    log_blob = "\n".join(r.message for r in caplog.records if "tt43 decoy" not in r.message)
    for material in (FAKE_LICENCE, FAKE_LICENCE.lower()):
        assert material not in blob
        assert material not in log_blob
    for i in range(len(FAKE_LICENCE) - 3):
        frag = FAKE_LICENCE[i : i + 4]
        assert frag not in blob and frag.lower() not in blob.lower(), frag
        assert frag not in log_blob and frag.lower() not in log_blob.lower(), frag
    assert rows, "应有 ingest 事件行"
    colnames = list(rows[0].keys())
    for forbidden in ("licence_hmac", "fingerprint", "ciphertext"):
        assert forbidden not in colnames
    # APP_MASTER_KEY 字面量不得因业务路径进入 ingest 日志（decoy 行已剔除）
    assert "APP_MASTER_KEY" not in log_blob
    assert "never-log-this-tt43" not in log_blob


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
        pytest.fail(f"baseline cannot fail-closed on record: {type(exc).__name__}")
    assert any(t.event == "ip_limited_escalated" for t in tr)
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=1)) is False


# ---- T-A79 B-1：写库失败 → 恢复 → user_reset / 重加 仍拒绝 ----


def test_ta79_b1_write_fail_then_recover_user_reset_keeps_pause() -> None:
    """record/rehydrate 失败后库恢复，user_reset 截止前 allows=False（79ffe61 红 / 6d45b06 绿）。"""
    url = _require_tt41_db()
    real = create_engine(url, hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(real, uid, lid)
    tog = _ToggleEngine(real)
    try:
        core = IngestCore(CFG, engine=tog)  # type: ignore[arg-type]
    except TypeError:
        pytest.fail("受测树无 engine 形参，无法验收 B-1")
    core.upsert(lid, user_id=uid, tier=TIER, status=ACTIVE, now=NOW0)
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=1), verify=True) is False
    until = core.user_escalated_until(lid)
    assert until is not None
    core.apply_ip_limited(lid, NOW0 + dt.timedelta(seconds=2))
    tog.recover()
    core.user_reset(lid, NOW0 + dt.timedelta(seconds=20))
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=20), verify=True) is False
    assert core.user_escalated_until(lid) is not None
    assert core.user_escalated_until(lid) >= until  # type: ignore[operator]


def test_ta79_b1_write_fail_then_recover_readd_keeps_pause() -> None:
    """写失败 → 库恢复 → remove+upsert 同用户新 id → allows=False。"""
    url = _require_tt41_db()
    real = create_engine(url, hide_parameters=True)
    uid, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _seed(real, uid, a)
    tog = _ToggleEngine(real)
    try:
        core = IngestCore(CFG, engine=tog)  # type: ignore[arg-type]
    except TypeError:
        pytest.fail("受测树无 engine 形参，无法验收 B-1")
    core.upsert(a, user_id=uid, tier=TIER, status=ACTIVE, now=NOW0)
    core.apply_ip_limited(a, NOW0 + dt.timedelta(seconds=2))
    assert core.allows(a, Priority.P0, NOW0 + dt.timedelta(seconds=3)) is False
    tog.recover()
    core.remove(a)
    t_re = NOW0 + dt.timedelta(seconds=20)
    core.upsert(b, user_id=uid, tier=TIER, status=ACTIVE, now=t_re)
    assert core.allows(b, Priority.P0, t_re, verify=True) is False


# ---- T-A79 L-2：失败期间拒绝；恢复后下次调用补写 ----


def test_ta79_l2_refuse_while_down_then_flush_count_on_recover() -> None:
    """写库失败期间一直拒绝；恢复后下一次调用把升级标记补写进库。"""
    url = _require_tt41_db()
    real = create_engine(url, hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(real, uid, lid)
    tog = _ToggleEngine(real)
    core = IngestCore(CFG)
    core.upsert(lid, user_id=uid, tier=TIER, status=ACTIVE, now=NOW0)
    core.engine = tog  # type: ignore[assignment]
    tr = core.apply_ip_limited(lid, NOW0)
    assert any(t.event == "ip_limited_escalated" for t in tr)
    # 失败期间持续拒绝
    for sec in (1, 5, 15):
        assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=sec)) is False
    mem = core.user_ip[uid]
    pending = getattr(mem, "pending_escalation", None)
    assert pending is not None, "L-2 pending_escalation missing（79ffe61 预期红）"

    tog.recover()
    core.user_reset(lid, NOW0 + dt.timedelta(seconds=5))
    assert getattr(mem, "pending_escalation", None) is None
    with real.connect() as conn:
        n_mark = conn.execute(
            text(
                "SELECT count(*) FROM ops.data_licence_events "
                "WHERE user_id=:u AND actor='ingest' AND event='paused' "
                "AND to_status='ip_limited'"
            ),
            {"u": uid},
        ).scalar_one()
        n_hit = conn.execute(
            text(
                "SELECT count(*) FROM ops.data_licence_events "
                "WHERE user_id=:u AND actor='ingest' AND event='ip_limited'"
            ),
            {"u": uid},
        ).scalar_one()
    assert n_mark >= 1, f"补写后应有 paused 标记，实际 {n_mark}"
    assert n_hit >= 1, f"补写路径应留下命中行或标记，ip_limited={n_hit}"
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=5), verify=True) is False
