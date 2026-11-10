# ruff: noqa: S101
"""T-T52 / T-A89：A6a/A6b、A25–A27 与 A1 绕过相关补充（正式用例）。

基线/修前 tip（含 302a558）上先红：B-1(a)(b)、B-2、M-2、L-b。
只用假 transport；env -u MAIRUI_LICENCE；不打印 DSN/密钥。
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

# Load helpers from sibling formal-suite module (pytest rootdir=tests/).
import importlib.util

_HELPER = Path(__file__).with_name("test_ta87_m1_a1_a24_t_t50.py")
_spec = importlib.util.spec_from_file_location("ta87_a1_a24_helpers", _HELPER)
assert _spec and _spec.loader
_h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_h)
FAKE_SECRET = _h.FAKE_SECRET
NOW0 = _h.NOW0
ROOT = _h.ROOT
FakeLease = _h.FakeLease
FakeTransport = _h.FakeTransport
_call_mairui = _h._call_mairui
_expect_denied = _h._expect_denied
_import_egress = _h._import_egress
_make_core = _h._make_core
_seed_licence = _h._seed_licence
_temp_db = _h._temp_db

# ---------------------------------------------------------------------------
# A6a / A6b
# ---------------------------------------------------------------------------


def test_a6a_ip_limit_lock_no_pending_denies_within_3s(tmp_path: Path) -> None:
    """A6a：另一会话持 ip_limit 锁且无 pending → ≤3s 拒绝 core_denied，transport 0。"""
    import time

    eg = _import_egress()
    from app.schemas.enums import DataLicenceStatus, DataLicenceTier

    tr = FakeTransport(responses=[(200, {"ok": True})])
    with _temp_db("a6a") as (eng, _n, _u):
        uid, lid = uuid.uuid4(), uuid.uuid4()
        _seed_licence(eng, uid, lid)
        core = _make_core(eng)
        core.upsert(
            lid,
            user_id=uid,
            tier=DataLicenceTier.ANNUAL,
            status=DataLicenceStatus.ACTIVE,
            now=NOW0,
        )
        mem = core._user_mem(uid)  # type: ignore[attr-defined]
        mem.pending_escalation = None
        holder = eng.connect()
        holder.execute(
            text("SELECT pg_advisory_lock(hashtext(:k))"),
            {"k": f"ingest:ip_limit:{uid}"},
        )
        holder.commit()
        t0 = time.monotonic()
        try:
            with pytest.raises(eg.EgressDenied) as ei:
                _call_mairui(
                    eg,
                    engine=eng,
                    core=core,
                    lid=lid,
                    uid=uid,
                    transport=tr,
                    tmp_path=tmp_path,
                )
            assert ei.value.code == "core_denied"
        finally:
            elapsed = time.monotonic() - t0
            holder.execute(
                text("SELECT pg_advisory_unlock(hashtext(:k))"),
                {"k": f"ingest:ip_limit:{uid}"},
            )
            holder.close()
        assert elapsed <= 3.0, f"A6a 应 ≤3s，实际 {elapsed:.2f}s"
    assert tr.calls == []


def test_a6b_forged_lease_denied(tmp_path: Path) -> None:
    """A6b：调用方自造 EgressLease(held=True) → single_egress_not_held，transport 0。"""
    eg = _import_egress()
    from app.schemas.enums import DataLicenceStatus, DataLicenceTier

    tr = FakeTransport(responses=[(200, {"ok": True})])
    with _temp_db("a6b") as (eng, _n, _u):
        uid, lid = uuid.uuid4(), uuid.uuid4()
        _seed_licence(eng, uid, lid)
        core = _make_core(eng)
        core.upsert(
            lid,
            user_id=uid,
            tier=DataLicenceTier.ANNUAL,
            status=DataLicenceStatus.ACTIVE,
            now=NOW0,
        )
        forged = FakeLease(True)
        with pytest.raises(eg.EgressDenied) as ei:
            _call_mairui(
                eg,
                engine=eng,
                core=core,
                lid=lid,
                uid=uid,
                transport=tr,
                lease=forged,
                tmp_path=tmp_path,
            )
        assert ei.value.code == "single_egress_not_held"
    assert tr.calls == []


# ---------------------------------------------------------------------------
# A25 / A26
# ---------------------------------------------------------------------------


def test_a25_upstream_102_then_always_licence_unavailable(tmp_path: Path) -> None:
    """A25：首次 102 → 库 INVALID；随后与重启后再调均 licence_unavailable；transport 仅 1。"""
    eg = _import_egress()
    from app.schemas.enums import DataLicenceStatus, DataLicenceTier

    tr = FakeTransport(responses=[(102, None), (200, {"should": "not"})])
    with _temp_db("a25") as (eng, _n, _u):
        uid, lid = uuid.uuid4(), uuid.uuid4()
        _seed_licence(eng, uid, lid)
        core = _make_core(eng)
        try:
            _call_mairui(
                eg, engine=eng, core=core, lid=lid, uid=uid, transport=tr, tmp_path=tmp_path
            )
        except Exception:
            pass
        assert len(tr.calls) == 1, f"transport 应恰好 1，实际 {len(tr.calls)}"
        with eng.connect() as conn:
            st = conn.execute(
                text("SELECT status FROM app.user_data_licences WHERE id=:id"),
                {"id": lid},
            ).scalar()
        assert st == "invalid", f"库状态应为 invalid，实际 {st!r}"

        tr2 = FakeTransport(responses=[(200, {"x": 1})])
        with pytest.raises(eg.EgressDenied) as ei:
            _call_mairui(
                eg, engine=eng, core=core, lid=lid, uid=uid, transport=tr2, tmp_path=tmp_path
            )
        assert ei.value.code == "licence_unavailable"
        assert tr2.calls == []

        core2 = _make_core(eng)
        tr3 = FakeTransport(responses=[(200, {"x": 1})])
        with pytest.raises(eg.EgressDenied) as ei2:
            _call_mairui(
                eg, engine=eng, core=core2, lid=lid, uid=uid, transport=tr3, tmp_path=tmp_path
            )
        assert ei2.value.code == "licence_unavailable"
        assert tr3.calls == []

        core2.upsert(
            lid,
            user_id=uid,
            tier=DataLicenceTier.ANNUAL,
            status=DataLicenceStatus.ACTIVE,
            now=NOW0,
        )
        tr4 = FakeTransport(responses=[(200, {"x": 1})])
        with pytest.raises(eg.EgressDenied) as ei3:
            _call_mairui(
                eg, engine=eng, core=core2, lid=lid, uid=uid, transport=tr4, tmp_path=tmp_path
            )
        assert ei3.value.code == "licence_unavailable"
        assert tr4.calls == []


def test_a26_status_write_fail_fail_closed(tmp_path: Path) -> None:
    """A26：INVALID 落库失败 → 本调用后后续拒绝，transport 不增加。"""
    eg = _import_egress()

    tr = FakeTransport(responses=[(102, None)])
    with _temp_db("a26") as (eng, _n, _u):
        uid, lid = uuid.uuid4(), uuid.uuid4()
        _seed_licence(eng, uid, lid)
        core = _make_core(eng)
        with eng.begin() as conn:
            conn.execute(
                text(
                    "CREATE OR REPLACE FUNCTION app.tt52_reject_invalid() RETURNS trigger AS $$ "
                    "BEGIN "
                    "IF NEW.status = 'invalid' THEN RAISE EXCEPTION 'tt52_reject_invalid'; END IF; "
                    "RETURN NEW; END; $$ LANGUAGE plpgsql;"
                )
            )
            conn.execute(
                text(
                    "CREATE TRIGGER tt52_reject_invalid BEFORE UPDATE ON app.user_data_licences "
                    "FOR EACH ROW EXECUTE FUNCTION app.tt52_reject_invalid();"
                )
            )
        before = len(tr.calls)
        try:
            _call_mairui(
                eg, engine=eng, core=core, lid=lid, uid=uid, transport=tr, tmp_path=tmp_path
            )
        except Exception:
            pass
        mid = len(tr.calls)
        tr_next = FakeTransport(responses=[(200, {"x": 1})])
        with pytest.raises(eg.EgressDenied) as ei:
            _call_mairui(
                eg,
                engine=eng,
                core=core,
                lid=lid,
                uid=uid,
                transport=tr_next,
                tmp_path=tmp_path,
            )
        assert ei.value.code in {"licence_unavailable", "core_denied"}
        assert tr_next.calls == []
        assert len(tr.calls) == mid
        assert mid - before <= 1


# ---------------------------------------------------------------------------
# A27 空断言禁令（L-b）
# ---------------------------------------------------------------------------


def test_a27_no_vacuous_asserts_in_egress_tests() -> None:
    """A27：egress/守卫相关自测与正式用例不得含 or True / 恒真 assert True。"""
    roots = [
        ROOT / "tests/backend/unit",
        ROOT / "src/backend/selfchecks",
    ]
    keys = ("ta87", "tb116", "egress", "a1_a24", "a1_a27", "static_guard", "mairui_guard")
    hits: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if not any(k in path.name for k in keys):
                continue
            src = path.read_text(encoding="utf-8")
            for i, line in enumerate(src.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "不得含" in line or ("A27" in line and "or True" in line):
                    continue
                # 扫描器自身的字符串字面量不算空断言
                if '"or True"' in line or "'or True'" in line:
                    continue
                if "assert True not in" in line or "True not in" in line:
                    continue
                if "or True" in line:
                    hits.append(f"{path.relative_to(ROOT)}:{i}: {stripped[:120]}")
                elif re.match(r"assert True\b", stripped):
                    hits.append(f"{path.relative_to(ROOT)}:{i}: {stripped[:120]}")
    assert not hits, "A27 vacuous asserts:\n" + "\n".join(hits)
