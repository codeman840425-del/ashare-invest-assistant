# ruff: noqa: S101, S110, S603, ANN001, ANN002, ANN003, ANN202, E501, PT017, PT018, SIM105
"""T-B116d A28–A31 selfchecks (A32 lives with the tb90 pipeline fixture)."""

from __future__ import annotations

import datetime as dt
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config_files import IngestConfig
from app.db.engine import engine_for
from app.ingest import egress as eg
from app.ingest import ip_limit as ipl
from app.ingest.core import IngestCore
from app.ingest.state import Priority
from app.schemas.enums import DataLicenceStatus, DataLicenceTier
from app.workers import ingest as iw

ROOT = Path(__file__).resolve().parents[3]
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
NOW0 = dt.datetime(2026, 11, 9, 19, 30, tzinfo=dt.UTC)
FAKE_LIC = "FAKE-" + "tb116d" + "-a28a32"
A28_SCRIPT = Path(__file__).resolve().parent / "test_tb116d_a28_negative.py"


def _url() -> str:
    u = os.environ.get("TB116D_DATABASE_URL") or os.environ.get("TB116B_DATABASE_URL")
    if not u:
        pytest.skip("TB116D_DATABASE_URL not set")
    return u


def _seed(eng: Engine, uid: uuid.UUID, lid: uuid.UUID, *, status: str = "active") -> None:
    with eng.begin() as conn:
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
                ") VALUES (:id, :uid, decode('00','hex'), 1, decode(:hm,'hex'), 'annual', :st)"
            ),
            {"id": lid, "uid": uid, "hm": uuid.uuid4().hex, "st": status},
        )


def _transport(calls: list[str]):
    def transport(path: str, secret: str) -> tuple[int, object]:
        calls.append(path)
        return 200, {"ok": True}

    return transport


def test_tb116d_a28_hmac_thread_pg_locks_subprocess() -> None:
    url = _url()
    env = os.environ.copy()
    env["TB116D_DATABASE_URL"] = url
    env["PYTHONPATH"] = str(ROOT / "src/backend") + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, str(A28_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        cwd=str(ROOT / "src/backend"),
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "OK" in result.stdout


def _mairui(lease, core, eng, lid, uid, halt: Path, transport, **kw):
    return eg.mairui_get(
        lease=lease,
        core=core,
        engine=eng,
        licence_id=lid,
        user_id=uid,
        path="/hslt/list/",
        secret=FAKE_LIC,
        priority=Priority.P1,
        clock=lambda: NOW0,
        stop=halt.parent / "S",
        halt=halt,
        transport=transport,
        **kw,
    )


def test_tb116d_a29_one_connect_one_lock_and_savepoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    url = _url()
    eng = create_engine(url, hide_parameters=True)
    halt = tmp_path / "H"

    def one_round() -> float:
        uid, lid = uuid.uuid4(), uuid.uuid4()
        _seed(eng, uid, lid)
        core = IngestCore(CFG, engine=eng)
        mem = core._user_mem(uid)
        ipl.queue_pending_escalation(
            mem,
            licence_id=lid,
            user_id=uid,
            from_status=DataLicenceStatus.ACTIVE.value,
            upstream_code="429",
            at=NOW0,
        )
        holder = eng.connect()
        holder.execute(text("BEGIN"))
        ipl.acquire_ip_limit_lock(holder, uid)
        connects = {"n": 0}
        locks = {"n": 0}
        orig_connect = eng.connect

        def counting_connect(*a, **k):
            connects["n"] += 1
            return orig_connect(*a, **k)

        orig_lock = ipl.acquire_ip_limit_lock

        def counting_lock(conn, user_id):
            locks["n"] += 1
            return orig_lock(conn, user_id)

        monkeypatch.setattr(eng, "connect", counting_connect)
        monkeypatch.setattr(ipl, "acquire_ip_limit_lock", counting_lock)
        monkeypatch.setattr(eg.ipl, "acquire_ip_limit_lock", counting_lock)
        calls: list[str] = []
        t0 = time.monotonic()
        try:
            with eg.single_egress(eng) as lease:
                # Count only from entering mairui_get (lease conn already open).
                connects["n"] = 0
                locks["n"] = 0
                assert lease is not None
                with pytest.raises(eg.EgressDenied) as ei:
                    _mairui(lease, core, eng, lid, uid, halt, _transport(calls))
                assert ei.value.code == "core_denied"
        finally:
            elapsed = time.monotonic() - t0
            monkeypatch.setattr(eng, "connect", orig_connect)
            monkeypatch.setattr(ipl, "acquire_ip_limit_lock", orig_lock)
            monkeypatch.setattr(eg.ipl, "acquire_ip_limit_lock", orig_lock)
            holder.rollback()
            holder.close()
        assert calls == []
        assert connects["n"] == 1, connects
        assert locks["n"] == 1, locks
        return elapsed

    times = [one_round() for _ in range(10)]
    assert max(times) <= 3.0, times

    # SAVEPOINT success: lock free, pending written then cleared after outer commit
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(eng, uid, lid)
    core = IngestCore(CFG, engine=eng)
    mem = core._user_mem(uid)
    ipl.queue_pending_escalation(
        mem,
        licence_id=lid,
        user_id=uid,
        from_status=DataLicenceStatus.ACTIVE.value,
        upstream_code="429",
        at=NOW0,
    )
    calls: list[str] = []
    with eg.single_egress(eng) as lease:
        assert lease is not None
        try:
            _mairui(lease, core, eng, lid, uid, halt, _transport(calls))
        except eg.EgressDenied as exc:
            # flush success may still deny later if memory is escalated
            assert exc.code in {"core_denied", "licence_unavailable"}
    assert mem.pending_escalation is None
    with eng.connect() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM ops.data_licence_events "
                "WHERE user_id = :u AND event IN ('ip_limited','paused')"
            ),
            {"u": uid},
        ).scalar_one()
    assert n >= 2

    # blackhole library: admit engine accepts and never answers
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def accept_forever() -> None:
        try:
            conn, _ = srv.accept()
            time.sleep(30)
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    import threading

    threading.Thread(target=accept_forever, daemon=True).start()
    engine_for.cache_clear()
    black = engine_for(
        f"postgresql+psycopg://postgres@127.0.0.1:{port}/postgres",
        profile="ingest",
    )
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(eng, uid, lid)
    core = IngestCore(CFG, engine=black)
    calls = []
    t0 = time.monotonic()
    with eg.single_egress(eng) as lease:
        assert lease is not None
        with pytest.raises(eg.EgressDenied) as ei:
            _mairui(lease, core, black, lid, uid, halt, _transport(calls))
        assert ei.value.code == "core_denied"
    elapsed = time.monotonic() - t0
    engine_for.cache_clear()
    srv.close()
    assert elapsed <= 3.0, elapsed
    assert calls == []


def test_tb116d_a30_persist_fail_writes_halt_and_exit_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    url = _url()
    eng = create_engine(url, hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(eng, uid, lid)
    trig = f"tb116d_a30_{lid.hex[:12]}"
    with eng.begin() as conn:
        conn.execute(
            text(
                f"CREATE OR REPLACE FUNCTION {trig}() RETURNS trigger AS $$ "
                "BEGIN RAISE EXCEPTION 'tb116d_a30_reject'; END; $$ LANGUAGE plpgsql"
            )
        )
        conn.execute(
            text(
                f"CREATE TRIGGER {trig} BEFORE UPDATE ON app.user_data_licences "
                "FOR EACH ROW WHEN (NEW.status = 'invalid') "
                f"EXECUTE FUNCTION {trig}()"
            )
        )
    halt = tmp_path / "halt" / "mairui-daily.HALTED"
    halt.parent.mkdir()
    calls: list[str] = []

    def transport_102(path: str, secret: str) -> tuple[int, object]:
        calls.append(path)
        return 102, None

    core = IngestCore(CFG, engine=eng)
    try:
        with eg.single_egress(eng) as lease:
            assert lease is not None
            with pytest.raises(eg.EgressDenied) as ei:
                _mairui(lease, core, eng, lid, uid, halt, transport_102)
            assert ei.value.code == "core_denied"
        assert halt.exists()
        assert halt.read_bytes() == b"licence_status_persist_failed"
        assert oct(halt.stat().st_mode & 0o777) == "0o600"
        assert len(calls) == 1
        # simulated restart: new core, DB still active, HALT present
        core2 = IngestCore(CFG, engine=eng)
        with eg.single_egress(eng) as lease2:
            assert lease2 is not None
            with pytest.raises(eg.EgressDenied) as ei2:
                _mairui(lease2, core2, eng, lid, uid, halt, transport_102)
            assert ei2.value.code == "halt_present"
        assert len(calls) == 1
    finally:
        with eng.begin() as conn:
            conn.execute(text(f"DROP TRIGGER IF EXISTS {trig} ON app.user_data_licences"))
            conn.execute(text(f"DROP FUNCTION IF EXISTS {trig}()"))

    # ② HALT directory unwritable → subprocess exit 74, fixed stderr only
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src/backend") + os.pathsep + env.get("PYTHONPATH", "")
    env["TB116D_DATABASE_URL"] = url
    env["TB116D_LID"] = str(lid)
    env["TB116D_UID"] = str(uid)
    script = r"""
import os, sys, uuid, datetime as dt
from pathlib import Path
import yaml
from sqlalchemy import create_engine
from app.config_files import IngestConfig
from app.ingest import egress as eg
from app.ingest.core import IngestCore
from app.ingest.state import Priority
ROOT = Path(sys.argv[1])
halt_dir = Path(sys.argv[2])
halt = halt_dir / "mairui-daily.HALTED"
# already chmod'd by parent
CFG = yaml.safe_load((ROOT / "config/ingest.yaml").read_text())
cfg = __import__("app.config_files", fromlist=["IngestConfig"]).IngestConfig.model_validate(CFG).licences
# avoid S6 in this file: parent already imported
from app.config_files import IngestConfig as IC
cfg = IC.model_validate(CFG).licences
eng = create_engine(os.environ["TB116D_DATABASE_URL"], hide_parameters=True)
# re-seed a fresh row so we can trip persist-fail without leftover state
import uuid as _uuid
from sqlalchemy import text
uid, lid = _uuid.uuid4(), _uuid.uuid4()
tag = "tb116d_a30_" + _uuid.uuid4().hex[:10]
with eng.begin() as conn:
    conn.execute(text("INSERT INTO app.users(id, username, password_hash, role, status) VALUES (:id,:u,'x','user','approved')"), {"id": uid, "u": "u"+uid.hex[:12]})
    conn.execute(text("INSERT INTO app.user_data_licences(id,user_id,ciphertext,seal_key_version,licence_hmac,tier,status) VALUES (:id,:uid,decode('00','hex'),1,decode(:hm,'hex'),'annual','active')"), {"id": lid, "uid": uid, "hm": _uuid.uuid4().hex})
    tag = "tb116d_a30_" + _uuid.uuid4().hex[:10]
    conn.execute(text("CREATE OR REPLACE FUNCTION " + tag + "() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'no'; END; $$ LANGUAGE plpgsql"))
    conn.execute(text("CREATE TRIGGER " + tag + " BEFORE UPDATE ON app.user_data_licences FOR EACH ROW WHEN (NEW.status='invalid') EXECUTE FUNCTION " + tag + "()"))
core = IngestCore(cfg, engine=eng)
NOW0 = dt.datetime(2026, 11, 9, 19, 30, tzinfo=dt.UTC)
try:
    with eg.single_egress(eng) as lease:
        eg.mairui_get(lease=lease, core=core, engine=eng, licence_id=lid, user_id=uid,
            path="/hslt/list/", secret="x", priority=Priority.P1, clock=lambda: NOW0,
            stop=halt_dir/"S", halt=halt, transport=lambda p,s: (102, None))
finally:
    with eng.begin() as conn:
        conn.execute(text("DROP TRIGGER IF EXISTS " + tag + " ON app.user_data_licences"))
        conn.execute(text("DROP FUNCTION IF EXISTS " + tag + "()"))
"""
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, str(ROOT), str(locked)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            cwd=str(ROOT / "src/backend"),
        )
    finally:
        locked.chmod(0o755)
        # os._exit(74) skips the child's finally: drop its trigger/function here
        # so later cases on the same temp DB are not poisoned (T-B116e).
        with eng.begin() as conn:
            leftovers = conn.execute(
                text(
                    "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON t.tgrelid = c.oid "
                    "WHERE c.relname = 'user_data_licences' AND t.tgname LIKE 'tb116d_a30_%'"
                )
            ).scalars().all()
            for name in leftovers:
                conn.execute(text(f"DROP TRIGGER IF EXISTS {name} ON app.user_data_licences"))
                conn.execute(text(f"DROP FUNCTION IF EXISTS {name}()"))
    assert result.returncode == 74, result.stdout + result.stderr
    err = result.stderr.strip()
    assert err == "ingest 致命：证书状态与停机标志均无法持久化"
    assert "Traceback" not in result.stderr
    assert str(locked) not in result.stderr

    # ③ halt dir unwritable at bootstrap → 78, existing HALT untouched
    planted = tmp_path / "boot" / "mairui-daily.HALTED"
    planted.parent.mkdir()
    planted.write_bytes(b"limit_103_or_429")
    planted.chmod(0o600)
    before = (planted.stat().st_ino, planted.read_bytes(), planted.stat().st_mtime)
    planted.parent.chmod(0o555)
    monkeypatch.setattr("app.ingest.daily_lists.HALT", planted)
    try:
        with pytest.raises(RuntimeError, match="停机标志目录不可写"):
            iw._probe_halt_directory()
    finally:
        planted.parent.chmod(0o755)
    after = (planted.stat().st_ino, planted.read_bytes(), planted.stat().st_mtime)
    assert after[0] == before[0] and after[1] == before[1]
    # subprocess wrapping the same path as main()
    boot_script = r"""
import sys
from pathlib import Path
halt = Path(sys.argv[1])
import app.ingest.daily_lists as dl
dl.HALT = halt
from app.workers import ingest as iw
try:
    iw._probe_halt_directory()
except Exception as exc:
    print(f"ingest 拒绝启动：{type(exc).__name__}", file=sys.stderr)
    sys.exit(78)
sys.exit(0)
"""
    planted.parent.chmod(0o555)
    try:
        result = subprocess.run(
            [sys.executable, "-c", boot_script, str(planted)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
            cwd=str(ROOT / "src/backend"),
        )
    finally:
        planted.parent.chmod(0o755)
    assert result.returncode == 78, result.stdout + result.stderr
    assert planted.read_bytes() == b"limit_103_or_429"


def test_tb116d_a31_flush_level_fault_keeps_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    eng = create_engine(_url(), hide_parameters=True)
    uid, lid = uuid.uuid4(), uuid.uuid4()
    _seed(eng, uid, lid)
    core = IngestCore(CFG, engine=eng)
    core.upsert(
        lid,
        user_id=uid,
        tier=DataLicenceTier.ANNUAL,
        status=DataLicenceStatus.ACTIVE,
        now=NOW0,
        hydrate=False,
    )
    mem = core._user_mem(uid)
    ipl.queue_pending_escalation(
        mem,
        licence_id=lid,
        user_id=uid,
        from_status=DataLicenceStatus.ACTIVE.value,
        upstream_code="429",
        at=NOW0,
    )
    orig = ipl.flush_pending_escalation

    def boom(conn, mem_):
        raise RuntimeError("a31_flush_injected")

    monkeypatch.setattr(ipl, "flush_pending_escalation", boom)
    monkeypatch.setattr(eg.ipl, "flush_pending_escalation", boom)
    calls: list[str] = []
    halt = tmp_path / "H"
    with eg.single_egress(eng) as lease:
        assert lease is not None
        with pytest.raises(eg.EgressDenied) as ei:
            _mairui(lease, core, eng, lid, uid, halt, _transport(calls))
        assert ei.value.code == "core_denied"
    assert mem.pending_escalation is not None
    assert calls == []
    with eng.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM ops.data_licence_events WHERE user_id=:u"),
            {"u": uid},
        ).scalar_one()
    assert n == 0
    assert core.allows(lid, Priority.P0, NOW0 + dt.timedelta(seconds=1), verify=True) is False

    # flush success: pending cleared only after outer commit
    monkeypatch.setattr(ipl, "flush_pending_escalation", orig)
    monkeypatch.setattr(eg.ipl, "flush_pending_escalation", orig)
    uid2, lid2 = uuid.uuid4(), uuid.uuid4()
    _seed(eng, uid2, lid2)
    core2 = IngestCore(CFG, engine=eng)
    core2.upsert(
        lid2,
        user_id=uid2,
        tier=DataLicenceTier.ANNUAL,
        status=DataLicenceStatus.ACTIVE,
        now=NOW0,
        hydrate=False,
    )
    mem2 = core2._user_mem(uid2)
    ipl.queue_pending_escalation(
        mem2,
        licence_id=lid2,
        user_id=uid2,
        from_status=DataLicenceStatus.ACTIVE.value,
        upstream_code="429",
        at=NOW0,
    )
    with eg.single_egress(eng) as lease:
        assert lease is not None
        try:
            _mairui(lease, core2, eng, lid2, uid2, halt, _transport([]))
        except eg.EgressDenied:
            pass
    assert mem2.pending_escalation is None
