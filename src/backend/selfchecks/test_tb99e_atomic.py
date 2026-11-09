"""RV-08/R3A: real POSIX writer exclusion, atomic DELETE retention, bounded queue.

Dedicated PostgreSQL/Redis, real business roles, synthetic HPKE and transport.
"""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
import json
import os
import select as select_io
import subprocess
import sys
import threading
import uuid
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError

from app.db.tables.licences import user_data_licences
from app.ingest import certificate_bindings as bindings
from app.ingest import daily_lists, live, send_control, shared_gate, verification
from app.ingest.intents import VerifyIntent
from app.ingest.shared_gate import GateClosedError, SharedGate
from app.licences import service
from selfchecks import test_tb99_daily as base


@pytest.fixture(scope="module")
def database() -> Any:
    if os.environ.get("TB99_ISOLATED_DATABASE_URL") != base.DSN or base.PORT not in {5432, 55499}:
        pytest.skip("explicit disposable tb99_test required")
    engine = create_engine(base.DSN, hide_parameters=True)
    cfg = Config()
    cfg.set_main_option("script_location", str(base.ROOT / "src/backend/migrations"))
    cfg.cmd_opts = Namespace(x=["url=" + base.DSN])
    with engine.begin() as conn:
        assert conn.execute(text("SELECT current_database()")).scalar_one() == "tb99_test"
        conn.execute(
            text("""DO $$ BEGIN
          IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='aia_ingest') THEN
            CREATE ROLE aia_ingest LOGIN;
          END IF;
        END $$""")
        )
    command.upgrade(cfg, "head")
    with engine.begin() as conn:
        base.deploy_grants(conn)  # Reapply the real broad grants: RLS must still protect tags.
        base.seed(conn)
    yield engine, [0]
    engine.dispose()


parent_env = base.env
redis_sink = base.redis_sink
test_compat_three_lists = base.test_daily_three_order_interval_and_no_fourth_request
test_compat_permissions = base.test_verification_permission_failures_do_not_read_secret


@pytest.fixture
def env(parent_env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    e = parent_env
    with e.owner.begin() as conn:
        conn.execute(
            text("TRUNCATE ingest_private.mairui_gate_bindings, ingest_private.mairui_gate_scopes")
        )
    reference = tmp_path / "synthetic-db-reference"
    reference.write_text(base.DSN.replace("postgres@", "aia_ingest@"))
    reference.chmod(0o400)
    monkeypatch.setenv("MAIRUI_SHARED_DATABASE_URL_FILE", str(reference))
    e.settings = e.settings.model_copy(update={"redis_url": "redis://127.0.0.1:6380/15"})
    monkeypatch.setattr(daily_lists, "send_paused", live.send_paused)
    monkeypatch.setattr(verification, "send_paused", live.send_paused)
    yield e
    bindings.engine_from_environment().dispose()
    bindings._configured_engine.cache_clear()


def verify(e: Any, upstream: Any) -> str:
    return verification.process(
        e.collector,
        e.settings,
        VerifyIntent(e.lid, uuid.uuid4()),
        clock=lambda: e.clock[0],
        upstream=upstream,
        egress=lambda: base.IP,
    )


def _writer(e: Any, rds: Any, kind: str) -> None:
    if kind == "STOP":
        shared_gate.write_stop(e.root / "STOP")
    else:
        live.set_global_pause(e.settings, True, client=rds)


@pytest.mark.parametrize("source", ["daily", "verify", "tb05", "tb86"])
@pytest.mark.parametrize("kind", ["STOP", "pause"])
def test_writer_after_final_guard_cannot_commit_before_actual_http(
    env: Any,
    redis_sink: Any,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    kind: str,
) -> None:
    import fcntl

    e, rds = env, redis_sink
    rds.delete(e.settings.ingest_paused_key)
    attempted, committed = threading.Event(), threading.Event()
    events = []
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="control-writer")
    writer_future = None
    original_flock = fcntl.flock

    def flock(fd: int, operation: int) -> None:
        if threading.current_thread().name.startswith("control-writer"):
            attempted.set()  # Exactly at the real kernel-lock attempt.
        original_flock(fd, operation)

    monkeypatch.setattr(fcntl, "flock", flock)

    def writer() -> None:
        _writer(e, rds, kind)
        events.append("writer_committed")
        committed.set()

    def http(*args: Any, **kwargs: Any) -> Any:
        nonlocal writer_future
        assert send_control.owned(e.root)
        # This callback is the actual transport boundary, AFTER every final check.
        writer_future = pool.submit(writer)
        assert attempted.wait(timeout=2)
        assert not committed.is_set()
        with (
            (e.root / "send-control.lock").open("rb") as lockfile,
            pytest.raises(BlockingIOError),
        ):
            original_flock(lockfile.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        events.append("http")
        return 200, [{"dm": code[:6], "mc": name} for code, name in base.NAMES.items()]

    class ProductConnection:
        status = 200

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.body = []

        def set_debuglevel(self, value: int) -> None:
            pass

        def request(self, *args: Any, **kwargs: Any) -> None:
            _, self.body = http()

        def getresponse(self) -> Any:
            return self

        def read(self, maximum: int) -> bytes:
            return json.dumps(self.body).encode()

        def close(self) -> None:
            pass

    monkeypatch.setattr(daily_lists.http.client, "HTTPSConnection", ProductConnection)
    try:
        if source == "verify":
            assert verify(e, daily_lists.wire) == "verified"
        elif source == "daily":

            def wait(seconds: float) -> None:
                assert writer_future is not None
                writer_future.result(timeout=3)
                e.pause(seconds)

            assert base.run(e, base.batch(e), upstream=daily_lists.wire, pause=wait) == "failed"
        elif source == "tb05":
            from probes import common

            gate = SharedGate(e.root, e.lid, "probe_tb05")
            gate.acquire()
            gate.confirm_egress(base.IP)
            monkeypatch.setenv("MAIRUI_LICENCE", e.plaintext)
            monkeypatch.setattr(common, "STOP_FILE", e.root / "unused-legacy-STOP")

            def request(*args: Any, **kwargs: Any) -> Any:
                http()
                return SimpleNamespace(status_code=200, text="[]", history=[], headers={})

            ctx = common.RunCtx(
                dry_run=False,
                base="https://api.mairuiapi.com",
                pro_base="https://pro.mairuiapi.com",
                run_id="synthetic",
                run_dir=e.root,
                samples_dir=e.root,
                stop_file=gate.stop,
                call_log=e.root / "calls.jsonl",
                min_interval=0,
                session=SimpleNamespace(request=request),
                shared_gate=gate,
            )
            monkeypatch.setattr(common, "_ctx", ctx)
            monkeypatch.setattr(common, "connection_stats", dict)
            try:
                common.call("synthetic", "/synthetic/{licence}")
            finally:
                gate.release()
        else:
            from probes import tb86_history as probe

            counter = e.root / "synthetic.count"
            counter.write_text(
                json.dumps({"schema": "T-B86/v1", "total": 0, "records": [], "halted": False})
            )
            counter.chmod(0o600)

            class Connection:
                status = 200

                def request(self, *args: Any, **kwargs: Any) -> None:
                    http()

                def getresponse(self) -> Any:
                    return self

                def read(self, maximum: int) -> bytes:
                    return b'[{"t":"synthetic","sf":0}]'

                def close(self) -> None:
                    pass

            monkeypatch.setenv("MAIRUI_LICENCE", e.plaintext)
            monkeypatch.setattr(probe, "public_egress", lambda: base.IP)
            monkeypatch.setattr(probe, "validate_notices", lambda *a: None)
            monkeypatch.setattr(probe, "SingleConnection", Connection)
            monkeypatch.setattr(probe.time, "sleep", lambda *a: writer_future.result(timeout=3))
            result = probe.execute(
                counter=counter,
                stop=e.root / "legacy-STOP",
                secret_path=e.root / "synthetic.tmp",
                root=e.root / "results",
            )
            assert result["new_reserved_calls"] <= 2
            assert not (e.root / "synthetic.tmp").exists()
        assert writer_future is not None
        writer_future.result(timeout=3)
        assert events == ["http", "writer_committed"]
        with pytest.raises(GateClosedError, match="STOP"):
            SharedGate(e.root, e.lid, "product_verify").acquire()
    finally:
        pool.shutdown(wait=True)
        rds.delete(e.settings.ingest_paused_key)


def test_independent_process_stop_writer_waits_until_actual_wire_returns(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = env
    child = None
    read_fd, write_fd = os.pipe()
    script = (
        "import os,sys,fcntl; from app.ingest.shared_gate import write_stop; "
        "from pathlib import Path; original=fcntl.flock\n"
        "def locked(fd,op):\n"
        " os.write(int(sys.argv[1]),b'x'); original(fd,op)\n"
        "fcntl.flock=locked\n"
        "write_stop(Path(os.environ['MAIRUI_SHARED_STATE_DIR'])/'STOP')\n"
    )

    class Connection:
        status = 200

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_debuglevel(self, value: int) -> None:
            pass

        def request(self, *args: Any, **kwargs: Any) -> None:
            nonlocal child
            assert send_control.owned(e.root)
            child = subprocess.Popen(  # noqa: S603 - fixed interpreter/script and an OS pipe fd only
                [sys.executable, "-c", script, str(write_fd)],
                pass_fds=(write_fd,),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            assert select_io.select([read_fd], [], [], 3)[0]
            assert os.read(read_fd, 1) == b"x"
            assert child.poll() is None
            assert not (e.root / "STOP").exists()

        def getresponse(self) -> Any:
            return self

        def read(self, maximum: int) -> bytes:
            return b"[1]"

        def close(self) -> None:
            pass

    monkeypatch.setattr(daily_lists.http.client, "HTTPSConnection", Connection)
    try:
        assert verify(e, daily_lists.wire) == "verified"
        assert child is not None
        assert child.wait(timeout=3) == 0
        assert (e.root / "STOP").exists()
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=3)
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.parametrize("kind", ["STOP", "pause"])
def test_writer_winning_critical_section_results_in_zero_http(
    env: Any, redis_sink: Any, kind: str
) -> None:
    e, rds = env, redis_sink
    _writer(e, rds, kind)
    sent = []
    assert verify(e, lambda *a: sent.append(1)) == "busy_or_closed"
    assert sent == []
    rds.delete(e.settings.ingest_paused_key)


def test_same_thread_stop_injected_inside_critical_section_refuses_send(env: Any) -> None:
    e = env
    with send_control.critical(e.root), pytest.raises(GateClosedError, match="reentry_refused"):
        shared_gate.write_stop(e.root / "STOP")
    assert not (e.root / "STOP").exists()


@pytest.mark.parametrize("local_time", [-1e12, 1e12])
def test_delete_sets_24h_retention_atomically_without_heartbeat_or_local_clock(
    env: Any, monkeypatch: pytest.MonkeyPatch, local_time: float
) -> None:
    e = env
    bindings.bind(e.root, str(e.lid), e.plaintext)
    monkeypatch.setattr(shared_gate, "time", SimpleNamespace(time=lambda: local_time))
    with e.worker.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(
                status="ip_limited",
                paused_until=None,
            )
        )
        assert service.delete_licence(conn, user_id=e.user, settings=e.settings)
    # No heartbeat or live.sync_halts call has run. Both facts commit together.
    with e.owner.connect() as conn:
        row = conn.execute(
            text(
                "SELECT l.deleted_at,b.expires_at,s.detached_at FROM app.user_data_licences l "
                "JOIN ingest_private.mairui_gate_bindings b ON b.licence_id=l.id "
                "JOIN ingest_private.mairui_gate_scopes s ON s.id=b.scope_id WHERE l.id=:id"
            ),
            {"id": e.lid},
        ).one()
        assert row.expires_at == row.deleted_at + dt.timedelta(hours=24)
        assert row.detached_at is not None
    assert bindings.identity(e.root, str(e.lid)) is None
    with e.owner.begin() as conn:
        conn.execute(text("UPDATE ingest_private.mairui_gate_bindings SET expires_at=now()"))
    bindings.cleanup(e.root)
    with e.owner.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM ingest_private.mairui_gate_bindings")
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize("hours", [0, 2])
def test_delete_nonnull_pause_uses_exact_db_deadline(env: Any, hours: int) -> None:
    e = env
    bindings.bind(e.root, str(e.lid), e.plaintext)
    with e.worker.begin() as conn:
        until = conn.execute(select(func.now())).scalar_one() + dt.timedelta(hours=hours)
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(
                status="ip_limited",
                paused_until=until,
            )
        )
        service.delete_licence(conn, user_id=e.user, settings=e.settings)
    with e.owner.connect() as conn:
        row = conn.execute(
            text("SELECT expires_at FROM ingest_private.mairui_gate_bindings")
        ).first()
        if hours:
            assert row.expires_at == until
        else:
            assert row is None


@pytest.mark.parametrize("bad", ["symlink", "hardlink", "mode", "directory"])
def test_send_mutex_refuses_unsafe_file_even_with_privileged_test_uid(env: Any, bad: str) -> None:
    e = env
    lock = e.root / "send-control.lock"
    if bad == "directory":
        e.root.chmod(0o707)
    elif bad == "symlink":
        lock.symlink_to(e.root / "absent")
    else:
        lock.touch(mode=0o600)
        if bad == "mode":
            lock.chmod(0o644)
        else:
            os.link(lock, e.root / "second-link")
    with pytest.raises(GateClosedError), send_control.critical(e.root):
        pytest.fail("unsafe control inode was accepted")


@pytest.mark.parametrize("cooled", [False, True])
def test_delete_rollback_preserves_binding_and_original_retention(env: Any, cooled: bool) -> None:
    e = env
    scope = bindings.bind(e.root, str(e.lid), e.plaintext)
    with e.worker.connect() as conn:
        tx = conn.begin()
        if cooled:
            conn.execute(
                update(user_data_licences)
                .where(user_data_licences.c.id == e.lid)
                .values(
                    status="ip_limited",
                    paused_until=None,
                )
            )
        service.delete_licence(conn, user_id=e.user, settings=e.settings)
        tx.rollback()
    assert bindings.identity(e.root, str(e.lid)) == scope
    with e.owner.connect() as conn:
        assert (
            conn.execute(
                text("SELECT expires_at FROM ingest_private.mairui_gate_bindings")
            ).scalar_one()
            is None
        )


@pytest.mark.parametrize(("mode", "paused"), [("replay", False), ("live", True)])
def test_binding_worker_purges_expired_tags_without_shared_directory_or_dispatch(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch, mode: str, paused: bool
) -> None:
    from pydantic import SecretStr

    from app.workers import ingest as worker

    e, rds = env, redis_sink
    scope = bindings.bind(e.root, str(e.lid), e.plaintext)
    with e.worker.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(status="ip_limited", paused_until=None)
        )
        service.delete_licence(conn, user_id=e.user, settings=e.settings)
    with e.owner.begin() as conn:
        conn.execute(text("UPDATE ingest_private.mairui_gate_bindings SET expires_at=now()"))
    settings = e.settings.model_copy(
        update={"database_url": SecretStr(base.DSN.replace("postgres@", "aia_ingest@"))}
    )
    monkeypatch.delenv("MAIRUI_SHARED_STATE_DIR")
    monkeypatch.setenv("MAIRUI_MODE", mode)
    monkeypatch.setattr(worker.time, "time", lambda: 0)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("replay/paused retention cleanup must not dispatch")

    monkeypatch.setattr(verification, "tick", forbidden)
    monkeypatch.setattr(daily_lists, "tick", forbidden)
    rds.delete(settings.ingest_paused_key)
    if paused:
        rds.set(settings.ingest_paused_key, "1")
    try:
        worker.write_heartbeat(settings)
        assert rds.exists(settings.ingest_heartbeat_key)
        with e.owner.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM ingest_private.mairui_gate_bindings")
                ).scalar_one()
                == 0
            )
            assert (
                conn.execute(
                    text("SELECT detached_at FROM ingest_private.mairui_gate_scopes WHERE id=:id"),
                    {"id": uuid.UUID(scope)},
                ).scalar_one()
                is not None
            )
    finally:
        rds.delete(settings.ingest_paused_key)


def test_binding_cleanup_refuses_owner_or_api_identity(env: Any) -> None:
    e = env
    for engine in (e.owner, e.worker):
        with pytest.raises(GateClosedError, match="role_refused"):
            bindings.cleanup(e.root, engine=engine)


def test_private_binding_rows_stay_hidden_after_real_role_bootstrap(env: Any) -> None:
    e = env
    bindings.bind(e.root, str(e.lid), e.plaintext)
    with e.worker.connect() as conn:
        assert conn.execute(text("SELECT tag FROM ingest_private.mairui_gate_bindings")).all() == []
    with e.worker.begin() as conn:
        conn.execute(text("SET LOCAL row_security=off"))
        with pytest.raises(DBAPIError):
            conn.execute(text("SELECT tag FROM ingest_private.mairui_gate_bindings"))
    with e.worker.connect() as conn, pytest.raises(DBAPIError):
        conn.execute(select(user_data_licences.c.ciphertext))


@pytest.mark.parametrize("expiry", ["cooling", "expired", "different"])
def test_r3a_same_certificate_restores_only_unexpired_owned_tombstone(
    env: Any, monkeypatch: pytest.MonkeyPatch, expiry: str
) -> None:
    e = env
    monkeypatch.setattr(service, "current_public_key", lambda _: (1, e.seal_key.public_key()))
    with SharedGate(e.root, e.lid, "probe_tb05") as gate:
        gate.bind_certificate(e.plaintext)
        gate.trip("103")
    fact = gate.halt_path.read_bytes()
    with e.owner.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(
                licence_hmac=service.licence_hmac(e.settings, e.plaintext),
                status="ip_limited",
                paused_until=func.now() + dt.timedelta(hours=1),
            )
        )
    with e.worker.begin() as conn:
        service.delete_licence(conn, user_id=e.user, settings=e.settings)
    if expiry == "expired":
        with e.owner.begin() as conn:
            conn.execute(text("UPDATE ingest_private.mairui_gate_bindings SET expires_at=now()"))
            conn.execute(text("UPDATE app.user_data_licence_cooldowns SET paused_until=now()"))
    value = e.plaintext if expiry != "different" else e.plaintext + "-new"
    with e.worker.begin() as conn:
        result = service.set_licence(
            conn,
            e.settings,
            user_id=e.user,
            licence=value,
            tier="free",
            has_quant_pro=False,
            expires_on=None,
        )
    lid = result.row.id
    policy = json.loads((e.root / "policy.json").read_text())
    policy["licences"][str(lid)] = {"per_minute_limit": 150}
    (e.root / "policy.json").write_text(json.dumps(policy))
    gate2 = SharedGate(e.root, lid, "probe_tb05")
    gate2.acquire()
    try:
        if expiry == "cooling":
            with pytest.raises(GateClosedError, match="licence_halted"):
                gate2.bind_certificate(value)
            assert gate2.halt_path == gate.halt_path
        else:
            gate2.bind_certificate(value)
            assert gate2.halt_path != gate.halt_path
    finally:
        gate2.release()
    assert gate.halt_path.read_bytes() == fact


@pytest.mark.parametrize("global_stop", ["unknown", "STOP"])
def test_r3a_detached_scope_does_not_block_other_certificate_but_global_stops_do(
    env: Any, global_stop: str
) -> None:
    e = env
    with SharedGate(e.root, e.lid, "probe_tb05") as gate:
        gate.bind_certificate(e.plaintext)
        gate.trip("429")
    fact = gate.halt_path.read_bytes()
    with pytest.raises(GateClosedError, match="licence_halted"):
        SharedGate(e.root, e.lid, "probe_tb05").acquire()
    with e.owner.begin() as conn:
        lid = uuid.uuid4()
        conn.execute(
            insert(user_data_licences).values(
                id=lid,
                user_id=e.admin,
                provider="mairui",
                ciphertext=b"synthetic",
                licence_hmac=uuid.uuid4().bytes * 2,
                seal_key_version=1,
                tier="free",
                status="active",
            )
        )
    policy = json.loads((e.root / "policy.json").read_text())
    policy["licences"][str(lid)] = {"per_minute_limit": 150}
    (e.root / "policy.json").write_text(json.dumps(policy))
    with SharedGate(e.root, lid, "product_verify") as other:
        other.bind_certificate("synthetic-" + uuid.uuid4().hex)
    with e.worker.begin() as conn:
        service.delete_licence(conn, user_id=e.user, settings=e.settings)
    with SharedGate(e.root, lid, "product_verify"):
        pass
    assert gate.halt_path.read_bytes() == fact
    with pytest.raises(GateClosedError, match="detached"):
        SharedGate(e.root, e.lid, "probe_tb05").acquire()
    if global_stop == "STOP":
        shared_gate.write_stop(e.root / "STOP")
    else:
        unknown = e.root / ("state-" + uuid.uuid4().hex + ".halt.json")
        unknown.write_text("{}")
    with pytest.raises(GateClosedError, match=r"STOP|unknown_scope"):
        SharedGate(e.root, lid, "product_verify").acquire()


def test_queue_drains_history_and_active_test_intent_in_one_bounded_tick(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e, rds = env, redis_sink
    for _ in range(19):
        service.enqueue_verify(rds, licence_id=uuid.uuid4(), verification_id=uuid.uuid4())
    token = uuid.uuid4()
    service.enqueue_verify(rds, licence_id=e.lid, verification_id=token)
    calls = []
    original = verification.process

    def process(engine: Any, settings: Any, intent: Any) -> str:
        return original(
            engine,
            settings,
            intent,
            clock=lambda: e.clock[0],
            egress=lambda: base.IP,
            upstream=lambda *a: calls.append(intent.verification_id) or (200, [1]),
        )

    monkeypatch.setattr(verification, "process", process)
    assert verification.tick(e.collector, rds, e.settings) == 1
    assert calls == [token]
    assert rds.xpending(verification.STREAM, verification.GROUP + ":" + str(e.lid))["pending"] == 0


def test_queue_processes_all_claimed_messages_and_caps_at_twenty(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e, rds = env, redis_sink
    for _ in range(25):
        service.enqueue_verify(rds, licence_id=e.lid, verification_id=uuid.uuid4())
    calls = []
    original = verification.process

    def process(engine: Any, settings: Any, intent: Any) -> str:
        return original(
            engine,
            settings,
            intent,
            clock=lambda: e.clock[0],
            egress=lambda: base.IP,
            upstream=lambda *a: calls.append(1) or (200, [1]),
        )

    monkeypatch.setattr(verification, "process", process)
    assert verification.tick(e.collector, rds, e.settings) == 20
    assert verification.tick(e.collector, rds, e.settings) == 5
    assert verification.tick(e.collector, rds, e.settings) == 0
    assert calls == [1]
    assert rds.xpending(verification.STREAM, verification.GROUP + ":" + str(e.lid))["pending"] == 0


def test_single_migration_head_and_nonempty_gate_facts_refuse_downgrade(env: Any) -> None:
    e = env
    cfg = Config()
    cfg.set_main_option("script_location", str(base.ROOT / "src/backend/migrations"))
    cfg.cmd_opts = Namespace(x=["url=" + base.DSN])
    assert ScriptDirectory.from_config(cfg).get_heads() == ["0029"]
    bindings.bind(e.root, str(e.lid), e.plaintext)
    with pytest.raises(Exception, match="mairui_gate_facts_require_authorized_archive"):
        command.downgrade(cfg, "0028")
    with e.owner.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0029"
