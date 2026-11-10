# ruff: noqa: S101
"""T-T55 / T-A91：A28–A32（M-a/M-b/M-c、L9 flush 注错、existing_temp 后半段独立例）。

假 transport；env -u MAIRUI_LICENCE；不打印 DSN/密钥。临时库用完删除。
"""

from __future__ import annotations

import datetime as dt
import os
import stat
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests" / "backend" / "unit"))

from test_ta87_m1_a1_a24_t_t50 import (  # noqa: E402
    FakeTransport,
    _blackhole_tcp,
    _call_mairui,
    _import_egress,
    _make_core,
    _seed_licence,
    _temp_db,
    NOW0,
)
from test_ta87_m1_a1_a24_t_t50 import _require_pg  # noqa: E402

PY = sys.executable


def _child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "MAIRUI_LICENCE"}
    env["MAIRUI_LICENCE"] = ""
    env["MAIRUI_MODE"] = "replay"
    env["PYTHONPATH"] = (
        str(ROOT)
        + os.pathsep
        + str(ROOT / "src/backend")
        + os.pathsep
        + env.get("PYTHONPATH", "")
    )
    return env


# ---------------------------------------------------------------------------
# A28 M-a
# ---------------------------------------------------------------------------


def _run_a28(case: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    child = ROOT / "tests/backend/unit/_a28_negative_child.py"
    env = _child_env()
    env["A28_TMP"] = str(tmp_path)
    return subprocess.run(
        [PY, str(child), case],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
        env=env,
    )


def _a28_ok(proc: subprocess.CompletedProcess[str], label: str) -> None:
    if proc.returncode != 0 or "DENIED single_egress_not_held" not in (proc.stdout or "") and "DENIED" not in (proc.stdout or ""):
        raise AssertionError(
            f"A28 {label} 应为 single_egress_not_held 且 transport 0。"
            f" rc={proc.returncode}\nstdout={proc.stdout[-800:]}\nstderr={proc.stderr[-800:]}"
        )
    out = proc.stdout or ""
    assert "single_egress_not_held" in out, out[-400:]
    assert "calls 0" in out, out[-400:]


def test_a28_inject_registry_forged_item_denied(tmp_path: Path) -> None:
    """A28①：往 _ISSUED_LEASES/_LEASE_LOCK_CONN 塞假项 → single_egress_not_held，transport 0。"""
    _a28_ok(_run_a28("inject_registry", tmp_path), "inject_registry")


def test_a28_replace_mac_or_thread_id_denied(tmp_path: Path) -> None:
    """A28②：dataclasses.replace 改 mac 或 thread_id 的副本 → single_egress_not_held，transport 0。"""
    _a28_ok(_run_a28("replace_mac_or_thread", tmp_path), "replace")


def test_a28_other_thread_uses_real_lease_denied(tmp_path: Path) -> None:
    """A28③：另一线程使用真 lease → single_egress_not_held，transport 0。"""
    _a28_ok(_run_a28("other_thread", tmp_path), "other_thread")


def test_a28_advisory_unlock_object_still_present_denied(tmp_path: Path) -> None:
    """A28④：锁会话已被 pg_advisory_unlock 但对象仍在 → single_egress_not_held，transport 0。"""
    _a28_ok(_run_a28("unlock_still_in_registry", tmp_path), "unlock")


# ---------------------------------------------------------------------------
# A29 M-b
# ---------------------------------------------------------------------------


def _plant_pending(core: Any, uid: uuid.UUID, lid: uuid.UUID) -> None:
    from app.ingest.ip_limit import queue_pending_escalation

    mem = core._user_mem(uid)  # type: ignore[attr-defined]
    mem.escalated_until = NOW0 + dt.timedelta(hours=1)
    queue_pending_escalation(
        mem,
        licence_id=lid,
        user_id=uid,
        from_status="active",
        upstream_code="103",
        at=NOW0,
    )


def test_a29_pending_lock_contention_le_3s_one_connection(tmp_path: Path) -> None:
    """A29：有 pending 且另一会话持锁 → 进入 mairui_get 到 core_denied 墙钟 ≤3.0s；1 连接、1 次 xact lock。

    普通与 -O 各 10 轮取最大值。
    """
    _a29_contention_rounds(tmp_path, optimized=False)
    _a29_contention_rounds_dash_o(tmp_path)


def _a29_contention_rounds(tmp_path: Path, *, optimized: bool) -> None:
    eg = _import_egress()
    from app.schemas.enums import DataLicenceStatus, DataLicenceTier

    times: list[float] = []
    with _temp_db("a29") as (eng, _n, _u):
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
        _plant_pending(core, uid, lid)
        holder = eng.connect()
        holder.execute(
            text("SELECT pg_advisory_lock(hashtext(:k))"),
            {"k": f"ingest:ip_limit:{uid}"},
        )
        holder.commit()
        try:
            for _i in range(10):
                connects = {"n": 0}
                xact_locks = {"n": 0}

                def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
                    if "pg_advisory_xact_lock" in (statement or "").lower():
                        if "ingest:ip_limit" in (statement or "") or (
                            parameters and "ip_limit" in str(parameters)
                        ):
                            xact_locks["n"] += 1
                        else:
                            # hashtext argument may be bound
                            xact_locks["n"] += 1

                ev = event.listen(eng, "before_cursor_execute", _before)
                orig = eng.connect

                def _counting_connect(*a: Any, **k: Any):  # noqa: ANN401
                    connects["n"] += 1
                    return orig(*a, **k)

                tr = FakeTransport()
                # T-A92：连接数从进入 mairui_get 起算 ==1；single_egress 锁会话不计。
                try:
                    with eg.single_egress(eng) as lease:
                        eng.connect = _counting_connect  # type: ignore[method-assign]
                        t0 = time.monotonic()
                        with pytest.raises(eg.EgressDenied) as ei:
                            _call_mairui(
                                eg,
                                engine=eng,
                                core=core,
                                lid=lid,
                                uid=uid,
                                transport=tr,
                                lease=lease,
                                tmp_path=tmp_path,
                            )
                        elapsed = time.monotonic() - t0
                        times.append(elapsed)
                        assert ei.value.code == "core_denied"
                        assert tr.calls == []
                        assert connects["n"] == 1, (
                            f"从进入 mairui_get 起须恰好 1 条连接（不计 single_egress），实际 {connects['n']}"
                        )
                        # xact_lock 不计 single_egress 的 session 锁（非 xact）。
                        assert xact_locks["n"] == 1, (
                            f"从进入 mairui_get 起应只发 1 次 pg_advisory_xact_lock，实际 {xact_locks['n']}"
                        )
                finally:
                    eng.connect = orig  # type: ignore[method-assign]
                    try:
                        event.remove(eng, "before_cursor_execute", _before)
                    except Exception:
                        pass
                    _ = ev
        finally:
            holder.execute(
                text("SELECT pg_advisory_unlock(hashtext(:k))"),
                {"k": f"ingest:ip_limit:{uid}"},
            )
            holder.close()
    assert times, "no rounds"
    mx = max(times)
    assert mx <= 3.0, f"A29 墙钟最大值应 ≤3.0s，实际 {mx:.2f}s（optimized={optimized}） rounds={times}"


def _a29_contention_rounds_dash_o(tmp_path: Path) -> None:
    env = _child_env()
    env["A29_TMP"] = str(tmp_path)
    code = r"""
import os, sys
from pathlib import Path
sys.path.insert(0, os.environ["PYTHONPATH"].split(os.pathsep)[0])
# import the helper by running 10 rounds in this -O interpreter
from tests.backend.unit.test_ta91_a28_a32_t_t55 import _a29_contention_rounds
_a29_contention_rounds(Path(os.environ["A29_TMP"]), optimized=True)
print("A29_O_OK")
"""
    proc = subprocess.run(
        [PY, "-O", "-c", code],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
        env=env,
    )
    if proc.returncode != 0 or "A29_O_OK" not in (proc.stdout or ""):
        raise AssertionError(
            f"A29 -O 10 轮未通过。rc={proc.returncode}\n"
            f"stdout={proc.stdout[-800:]}\nstderr={proc.stderr[-800:]}"
        )


def test_a29_pending_savepoint_clears_only_after_outer_commit(tmp_path: Path) -> None:
    """A29：锁空闲时 pending 在 SAVEPOINT 内写入，外层提交后才清除。"""
    eg = _import_egress()
    from app.schemas.enums import DataLicenceStatus, DataLicenceTier
    from app.ingest import ip_limit as ipl

    with _temp_db("a29s") as (eng, _n, _u):
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
        _plant_pending(core, uid, lid)
        seen = {"savepoint": 0, "pending_during": None}

        orig = ipl.flush_pending_escalation

        def _wrap(conn: Any, mem: Any) -> bool:
            seen["pending_during"] = mem.pending_escalation is not None
            # require an open SAVEPOINT / nested transaction around flush
            in_nested = bool(getattr(conn, "_nested_transaction", None) or getattr(conn, "in_nested_transaction", lambda: False)())
            if not in_nested:
                # also accept dialect: inspect open savepoints via SQL
                try:
                    conn.execute(text("SAVEPOINT a29_probe"))
                    conn.execute(text("RELEASE SAVEPOINT a29_probe"))
                    # If we can create one, it doesn't prove the product used one.
                except Exception:
                    pass
            seen["savepoint"] += int(in_nested)
            return orig(conn, mem)

        ipl.flush_pending_escalation = _wrap  # type: ignore[assignment]
        tr = FakeTransport(responses=[(200, {"ok": True})])
        try:
            try:
                _call_mairui(
                    eg,
                    engine=eng,
                    core=core,
                    lid=lid,
                    uid=uid,
                    transport=tr,
                    tmp_path=tmp_path,
                )
            except eg.EgressDenied:
                # may still deny for other reasons; we care about savepoint semantics
                pass
        finally:
            ipl.flush_pending_escalation = orig  # type: ignore[assignment]
        mem = core._user_mem(uid)  # type: ignore[attr-defined]
        # After successful outer commit, pending must be cleared
        # If flush never ran in a SAVEPOINT, this is red.
        assert seen["savepoint"] >= 1, (
            "A29：flush_pending_escalation 须在 SAVEPOINT/nested txn 内调用（基线分事务 → 红）"
        )
        # If flush succeeded, pending cleared only after outer commit; wrap saw pending still set
        assert seen["pending_during"] is True
        assert mem.pending_escalation is None


def test_a29_blackhole_admit_denied_within_3s(tmp_path: Path) -> None:
    """A29：黑洞库（只 accept 不应答）时准入 ≤3.0s 拒绝。"""
    eg = _import_egress()
    from pydantic import SecretStr  # noqa: F401
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    from app.schemas.enums import DataLicenceStatus, DataLicenceTier

    with _temp_db("a29b") as (good, _n, _u):
        uid, lid = uuid.uuid4(), uuid.uuid4()
        _seed_licence(good, uid, lid)
        core = _make_core(good)
        core.upsert(
            lid,
            user_id=uid,
            tier=DataLicenceTier.ANNUAL,
            status=DataLicenceStatus.ACTIVE,
            now=NOW0,
        )
        _plant_pending(core, uid, lid)
        tr = FakeTransport()
        with _blackhole_tcp() as port:
            bad = create_engine(
                f"postgresql+psycopg://u:x@127.0.0.1:{port}/db",
                poolclass=NullPool,
                connect_args={"connect_timeout": 2},
            )
            # Issue a real lease on the good engine, admit against blackhole.
            t0 = time.monotonic()
            try:
                with eg.single_egress(good) as lease:
                    with pytest.raises(eg.EgressDenied) as ei:
                        _call_mairui(
                            eg,
                            engine=bad,
                            core=core,
                            lid=lid,
                            uid=uid,
                            transport=tr,
                            lease=lease,
                            tmp_path=tmp_path,
                        )
                    elapsed = time.monotonic() - t0
                    assert ei.value.code in {"core_denied", "licence_unavailable", "single_egress_not_held"}
            finally:
                bad.dispose()
            assert elapsed <= 3.0, f"A29 黑洞准入应 ≤3.0s，实际 {elapsed:.2f}s"
            assert tr.calls == []


# ---------------------------------------------------------------------------
# A30 M-c
# ---------------------------------------------------------------------------


def _install_reject_invalid(eng: Engine) -> None:
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE OR REPLACE FUNCTION app.tt55_reject_invalid() RETURNS trigger AS $$ "
                "BEGIN "
                "IF NEW.status = 'invalid' THEN RAISE EXCEPTION 'tt55_reject_invalid'; END IF; "
                "RETURN NEW; END; $$ LANGUAGE plpgsql;"
            )
        )
        conn.execute(
            text(
                "DROP TRIGGER IF EXISTS tt55_reject_invalid ON app.user_data_licences;"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER tt55_reject_invalid BEFORE UPDATE ON app.user_data_licences "
                "FOR EACH ROW EXECUTE FUNCTION app.tt55_reject_invalid();"
            )
        )


def test_a30_persist_fail_writes_halt_and_restart_halt_present(tmp_path: Path) -> None:
    """A30①：102 写库失败 → core_denied、HALT=licence_status_persist_failed、transport 1；
    模拟重启（新 core、库仍 active）→ halt_present，transport 仍 1。"""
    eg = _import_egress()
    halt = tmp_path / "HALT"
    tr = FakeTransport(responses=[(102, None)])
    with _temp_db("a30a") as (eng, _n, _u):
        uid, lid = uuid.uuid4(), uuid.uuid4()
        _seed_licence(eng, uid, lid)
        core = _make_core(eng)
        _install_reject_invalid(eng)
        with pytest.raises(eg.EgressDenied) as ei:
            _call_mairui(
                eg, engine=eng, core=core, lid=lid, uid=uid, transport=tr, tmp_path=tmp_path, halt=halt
            )
        assert ei.value.code == "core_denied"
        assert halt.is_file(), "A30：写库失败须同时写 HALT"
        assert halt.read_text(encoding="utf-8") == "licence_status_persist_failed"
        assert len(tr.calls) == 1
        # DB still active
        with eng.connect() as conn:
            st = conn.execute(
                text("SELECT status FROM app.user_data_licences WHERE id=:i"),
                {"i": lid},
            ).scalar_one()
        assert st == "active"
        core2 = _make_core(eng)
        tr2 = FakeTransport(responses=[(200, {"ok": True})])
        with pytest.raises(eg.EgressDenied) as ei2:
            _call_mairui(
                eg,
                engine=eng,
                core=core2,
                lid=lid,
                uid=uid,
                transport=tr2,
                tmp_path=tmp_path,
                halt=halt,
            )
        assert ei2.value.code == "halt_present"
        assert tr2.calls == []
        assert len(tr.calls) == 1


def test_a30_halt_dir_unwritable_exit_74(tmp_path: Path) -> None:
    """A30②：HALT 目录同时不可写 → 子进程退出码 74，stderr 只有固定文案。"""
    env = _child_env()
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    env["A30_TMP"] = str(frozen)
    code = r"""
import os, sys, uuid
from pathlib import Path
from sqlalchemy import create_engine
from tests.backend.unit.test_ta87_m1_a1_a24_t_t50 import (
    FakeTransport, _call_mairui, _import_egress, _make_core, _seed_licence,
)
from tests.backend.unit.test_ta91_a28_a32_t_t55 import _install_reject_invalid
eg = _import_egress()
tmp = Path(os.environ["A30_TMP"])
halt_dir = tmp / "nohalt"
halt_dir.mkdir()
os.chmod(halt_dir, 0o500)
halt = halt_dir / "HALT"
tr = FakeTransport(responses=[(102, None)])
eng = create_engine(os.environ["TT56_DATABASE_URL"], pool_pre_ping=True)
try:
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed_licence(eng, uid, lid)
    core = _make_core(eng)
    _install_reject_invalid(eng)
    try:
        _call_mairui(eg, engine=eng, core=core, lid=lid, uid=uid, transport=tr, tmp_path=tmp, halt=halt)
    except SystemExit:
        raise
    except Exception:
        pass
finally:
    eng.dispose()
    os.chmod(halt_dir, 0o700)
print("NO_EXIT_74", file=sys.stderr)
raise SystemExit(0)
"""
    with _temp_db("a30b") as (_eng, _n, url):
        env["TT56_DATABASE_URL"] = url
        proc = subprocess.run(
            [PY, "-c", code],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
            env=env,
        )
    assert proc.returncode == 74, (
        f"A30② 应 os._exit(74)，实际 rc={proc.returncode}\n"
        f"stdout={proc.stdout[-400:]}\nstderr={proc.stderr[-400:]}"
    )
    err = (proc.stderr or "").strip()
    # 固定文案：不得含 traceback / 路径 / 证书
    assert "Traceback" not in err
    assert "licence" not in err.lower()
    assert err, "stderr 应有固定文案"


def test_a30_bootstrap_halt_dir_unwritable_rc78_keeps_existing_halt(tmp_path: Path) -> None:
    """A30③：patch daily_lists.HALT 到不可写目录，并提供一次性库使 engine 探测通过；
    bootstrap 退出码 78，文案指向停机目录不可写，已有 HALT 不变。不加 A30_HALT_DIR 产品钩。"""
    env = _child_env()
    halt_dir = tmp_path / "hd"
    halt_dir.mkdir()
    existing = halt_dir / "mairui-daily.HALTED"
    existing.write_bytes(b"limit_103_or_429")
    os.chmod(existing, 0o600)
    before = existing.read_bytes()
    mtime = existing.stat().st_mtime_ns
    env["A30_HALT_PATH"] = str(existing)
    env["SERVICE_NAME"] = "ingest"
    env["APP_ENV"] = "local"
    code = r"""
import os, sys
from pathlib import Path
from types import SimpleNamespace
from pydantic import SecretStr
os.environ.setdefault("SERVICE_NAME", "ingest")
os.environ.setdefault("APP_ENV", "local")
os.environ.pop("MAIRUI_LICENCE", None)
os.environ.pop("APP_MASTER_KEY", None)
import app.ingest.daily_lists as dl
dl.HALT = Path(os.environ["A30_HALT_PATH"])
url = os.environ["TT56_DATABASE_URL"]
class _Settings:
    database_url = SecretStr(url)
    business = SimpleNamespace(
        ingest=SimpleNamespace(heartbeat=SimpleNamespace(interval_s=15), licences=None)
    )
import app.config as config_mod
config_mod.get_settings = lambda: _Settings()  # type: ignore[assignment]
from app.workers import ingest as iw
iw.legacy_licence_present = lambda environ=None: False
iw.master_key_present = lambda environ=None: False
try:
    rc = iw.main()
except SystemExit as exc:
    rc = exc.code if isinstance(exc.code, int) else 1
print("RC", rc)
raise SystemExit(int(rc) if isinstance(rc, int) else 1)
"""
    os.chmod(halt_dir, 0o500)
    try:
        with _temp_db("a30c") as (_eng, _n, url):
            env["TT56_DATABASE_URL"] = url
            proc = subprocess.run(
                [PY, "-c", code],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                check=False,
                timeout=20,
                env=env,
            )
    finally:
        os.chmod(halt_dir, 0o700)
    err = (proc.stderr or "") + (proc.stdout or "")
    assert proc.returncode == 78, (
        f"A30③ bootstrap 应 rc=78，实际 {proc.returncode}\n"
        f"stdout={proc.stdout[-400:]}\nstderr={proc.stderr[-400:]}"
    )
    needle = err.lower()
    assert any(s in needle for s in ("halt", "停机", "unwritable", "不可写")), (
        f"A30③ 用例过弱风险：rc=78 但文案未指向停机目录不可写。stderr={err[-400:]}"
    )
    assert existing.read_bytes() == before
    assert existing.stat().st_mtime_ns == mtime


# ---------------------------------------------------------------------------
# A31 L9：在 flush 上注错
# ---------------------------------------------------------------------------


def test_a31_l9_flush_inject_keeps_pending(tmp_path: Path) -> None:
    """A31：在 flush_pending_escalation 处注入失败 → pending 保留、事件 0 行、allows=False。"""
    from app.ingest import ip_limit as ipl
    from app.ingest.core import IngestCore
    from app.schemas.enums import DataLicenceStatus, DataLicenceTier
    from test_ta87_m1_a1_a24_t_t50 import _cfg

    with _temp_db("a31") as (eng, _n, _u):
        uid, lid = uuid.uuid4(), uuid.uuid4()
        _seed_licence(eng, uid, lid)
        core = IngestCore(_cfg(), engine=eng)
        core.upsert(
            lid,
            user_id=uid,
            tier=DataLicenceTier.ANNUAL,
            status=DataLicenceStatus.ACTIVE,
            now=NOW0,
        )
        _plant_pending(core, uid, lid)
        mem = core._user_mem(uid)  # type: ignore[attr-defined]
        assert mem.pending_escalation is not None

        def _boom(conn: Any, mem_: Any) -> bool:
            raise RuntimeError("a31_flush_injected")

        orig = ipl.flush_pending_escalation
        ipl.flush_pending_escalation = _boom  # type: ignore[assignment]
        try:
            core.rehydrate(uid, NOW0 + dt.timedelta(seconds=5))
        finally:
            ipl.flush_pending_escalation = orig  # type: ignore[assignment]
        assert mem.pending_escalation is not None, "flush 注错后 pending 必须保留"
        from app.ingest.state import Priority

        assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=5), verify=True) is False
        with eng.connect() as conn:
            n = conn.execute(
                text(
                    "SELECT count(*) FROM ops.data_licence_events "
                    "WHERE user_id=:u AND actor='ingest' AND event IN ('paused','ip_limited')"
                ),
                {"u": uid},
            ).scalar_one()
        assert n == 0, f"补写失败时库内不应有升级行，实际 {n}"


def test_a31_l9_flush_success_clears_pending_after_outer_commit() -> None:
    """A31：flush 成功时外层提交后 pending 才清除。"""
    from app.ingest import ip_limit as ipl
    from app.ingest.core import IngestCore
    from app.ingest.state import Priority
    from app.schemas.enums import DataLicenceStatus, DataLicenceTier
    from test_ta87_m1_a1_a24_t_t50 import _cfg

    with _temp_db("a31ok") as (eng, _n, _u):
        uid, lid = uuid.uuid4(), uuid.uuid4()
        _seed_licence(eng, uid, lid)
        core = IngestCore(_cfg(), engine=eng)
        core.upsert(
            lid,
            user_id=uid,
            tier=DataLicenceTier.ANNUAL,
            status=DataLicenceStatus.ACTIVE,
            now=NOW0,
        )
        _plant_pending(core, uid, lid)
        mem = core._user_mem(uid)  # type: ignore[attr-defined]
        seen = {"pending_inside": None}
        orig = ipl.flush_pending_escalation

        def _wrap(conn: Any, mem_: Any) -> bool:
            seen["pending_inside"] = mem_.pending_escalation is not None
            return orig(conn, mem_)

        ipl.flush_pending_escalation = _wrap  # type: ignore[assignment]
        try:
            core.rehydrate(uid, NOW0 + dt.timedelta(seconds=5))
        finally:
            ipl.flush_pending_escalation = orig  # type: ignore[assignment]
        assert seen["pending_inside"] is True, "flush 进行时 pending 仍应在"
        assert mem.pending_escalation is None, "外层提交后才清除 pending"


def test_a31_flush_ok_outer_commit_fails_keeps_pending() -> None:
    """A31：flush 已成功但外层提交失败 → pending 必须保留（不得在提交前清 pending）。"""
    from app.ingest.core import IngestCore
    from app.schemas.enums import DataLicenceStatus, DataLicenceTier
    from test_ta87_m1_a1_a24_t_t50 import _cfg

    with _temp_db("a31cf") as (eng, _n, _u):
        uid, lid = uuid.uuid4(), uuid.uuid4()
        _seed_licence(eng, uid, lid)
        core = IngestCore(_cfg(), engine=eng)
        core.upsert(
            lid,
            user_id=uid,
            tier=DataLicenceTier.ANNUAL,
            status=DataLicenceStatus.ACTIVE,
            now=NOW0,
        )
        _plant_pending(core, uid, lid)
        mem = core._user_mem(uid)  # type: ignore[attr-defined]
        assert mem.pending_escalation is not None
        orig_locked = core.rehydrate_locked

        def _locked(conn: Any, user_id: uuid.UUID, now: Any) -> bool:
            ok = orig_locked(conn, user_id, now)
            if ok:
                root = conn.get_transaction()
                while root is not None and getattr(root, "parent", None) is not None:
                    root = root.parent
                if root is None:
                    raise AssertionError("A31：找不到外层事务，无法注入提交失败")

                def _fail(*_a: Any, **_k: Any) -> None:
                    raise RuntimeError("a31_outer_commit_injected")

                root.commit = _fail  # type: ignore[method-assign]
            return ok

        core.rehydrate_locked = _locked  # type: ignore[method-assign]
        try:
            core.rehydrate(uid, NOW0 + dt.timedelta(seconds=5))
        finally:
            core.rehydrate_locked = orig_locked  # type: ignore[method-assign]
        assert mem.pending_escalation is not None, (
            "A31：flush 成功但外层提交失败时不得清 pending（提交前清 pending 即红）"
        )
        with eng.connect() as conn:
            n = conn.execute(
                text(
                    "SELECT count(*) FROM ops.data_licence_events "
                    "WHERE user_id=:u AND actor='ingest' AND event IN ('paused','ip_limited')"
                ),
                {"u": uid},
            ).scalar_one()
        assert n == 0, f"外层回滚后库内不应有升级行，实际 {n}"


# ---------------------------------------------------------------------------
# A32 existing_temp 后半段（tests/ 独立例；不改 src selfchecks）
# ---------------------------------------------------------------------------

# 不用 /tmp/tb90-*：该路径可能已被既有容器占用，本单不得触碰已有容器。
# 每次运行使用唯一目录，避免残留 socket（uid 70）无法删除。
SOCKET = ""
REDIS = ""


def _alloc_socket_dirs() -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    sock = f"/tmp/tt55-{suffix}-pg-socket"
    rdir = f"/tmp/tt55-{suffix}-redis"
    Path(sock).mkdir(parents=True, exist_ok=True)
    Path(rdir).mkdir(parents=True, exist_ok=True)
    for d in (sock, rdir):
        try:
            os.chmod(d, 0o1777)
        except PermissionError:
            pass
    return sock, rdir


def _docker_start_tb90() -> tuple[str, str]:
    global SOCKET, REDIS
    sock, rdir = _alloc_socket_dirs()
    SOCKET = sock
    REDIS = f"unix://{rdir}/redis.sock?db=0"
    pg = subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--pull", "never", "--network", "none",
            "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
            "-v", f"{sock}:/var/run/postgresql",
            "timescale/timescaledb:2.31.0-pg16",
            "-c", "listen_addresses=",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert pg.returncode == 0, (pg.stderr or pg.stdout)[-400:]
    pg_id = pg.stdout.strip()
    rd = subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--pull", "never", "--network", "none",
            "-v", f"{rdir}:/tmp",
            "redis:7.4.12-alpine",
            "redis-server", "--unixsocket", "/tmp/redis.sock",
            "--unixsocketperm", "777", "--port", "0", "--save", "", "--appendonly", "no",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if rd.returncode != 0:
        subprocess.run(["docker", "stop", pg_id], check=False, capture_output=True)
        raise AssertionError((rd.stderr or rd.stdout)[-400:])
    rd_id = rd.stdout.strip()
    Path("/tmp/tt55-tb90-pg-cid.txt").write_text(pg_id)
    Path("/tmp/tt55-tb90-redis-cid.txt").write_text(rd_id)
    stable = 0
    for _ in range(90):
        if Path(SOCKET + "/.s.PGSQL.5432").exists() and Path(rdir + "/redis.sock").exists():
            try:
                import psycopg

                with psycopg.connect(dbname="postgres", user="postgres", host=SOCKET, port=5432, autocommit=True) as c:  # noqa: E501
                    if c.execute("SHOW listen_addresses").fetchone() == ("",):
                        stable += 1
                        if stable >= 4:
                            return pg_id, rd_id
                    else:
                        stable = 0
            except Exception:
                stable = 0
        time.sleep(0.5)
    subprocess.run(["docker", "stop", pg_id], check=False, capture_output=True)
    subprocess.run(["docker", "stop", rd_id], check=False, capture_output=True)
    raise AssertionError("tb90 temp containers failed to become ready")


def _docker_stop(pg_id: str, rd_id: str) -> None:
    subprocess.run(["docker", "stop", pg_id], check=False, capture_output=True)
    subprocess.run(["docker", "stop", rd_id], check=False, capture_output=True)


@contextmanager
def _tb90_containers() -> Iterator[tuple[str, str]]:
    os.environ["PGPORT"] = "5432"
    ids = _docker_start_tb90()
    try:
        yield ids
    finally:
        _docker_stop(*ids)


def test_a32_existing_temp_second_batch_new_trade_day(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A32：用新交易日触发第二次批次（不用 owner 把 failed 改回 requested）；
    残留普通文件被替换为 0600 并在成功后清掉；非普通文件 temp_path_not_regular。
    """
    from selfchecks.test_tb89_full_migrations import AT, DAY
    from selfchecks.test_tb90_daily_pipeline import run_synthetic
    from app.ingest.daily_lists import temporary, DailyHaltError
    from app.master import daily_delivery as daily
    from app.db.tables.market import trading_calendar
    from sqlalchemy import update

    # Unit path first: non-regular leftover
    fifo = tmp_path / "fifo.tmp"
    os.mkfifo(fifo)
    with pytest.raises(DailyHaltError) as ei:
        temporary(fifo, "x")
    assert ei.value.args[0] == "temp_path_not_regular" or getattr(ei.value, "args", [""])[0] == "temp_path_not_regular" or "temp_path_not_regular" in str(ei.value)

    # T-A92 补例：残留普通文件被替换后须为 0600
    leftover = tmp_path / "cred.tmp"
    leftover.write_text("stale-mode")
    leftover.chmod(0o644)
    temporary(leftover, "x")
    mode = leftover.stat().st_mode
    assert stat.S_ISREG(mode)
    assert (mode & 0o777) == 0o600, f"A32：temporary 替换后须 0600，实际 {oct(mode & 0o777)}"
    leftover.unlink()

    with _tb90_containers() as (pg_id, rd_id):
        # Build env via the selfcheck fixture guts by invoking request on a new day
        # Import env setup by running a compact clone:
        from selfchecks import test_tb90_daily_pipeline as tb90
        monkeypatch.setattr(tb90, "SOCKET", SOCKET)
        monkeypatch.setattr(tb90, "REDIS", REDIS)
        db_gen = tb90.database.__wrapped__()
        name_url = next(db_gen)
        try:
            env_gen = tb90.env.__wrapped__(name_url, tmp_path, monkeypatch)
            e = next(env_gen)
            try:
                temp = e.root / "daily.tmp"
                temp.write_text("stale-again")
                temp.chmod(0o600)
                day2 = DAY + dt.timedelta(days=1)
                at2 = AT + dt.timedelta(days=1)
                monkeypatch.setattr(tb90.jobs, "_now", lambda: at2)
                with e.worker.begin() as conn:
                    bid2 = daily.request(conn, e.grant, at2)
                assert bid2 is not None, "新交易日应产生新批次（不得依赖 failed→requested）"
                # First-day batch may not even exist; bid2 must be a new requested batch
                state, calls, _ = run_synthetic(e, bid2, monkeypatch, clock=lambda: at2)
                assert state == "fetched"
                assert len(calls) == 3
                assert not temp.exists(), "残留普通 TEMP 须在成功路径被替换并清掉"
            finally:
                try:
                    next(env_gen)
                except StopIteration:
                    pass
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass
