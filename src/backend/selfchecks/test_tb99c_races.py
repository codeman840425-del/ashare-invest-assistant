"""RV-06 negatives at check/action boundaries; disposable PG/Redis and synthetic data."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import json
import os
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text, update

from app.db.tables.licences import user_data_licences
from app.ingest import certificate_bindings as bindings
from app.ingest import daily_lists, live, shared_gate, verification, verification_grants
from app.ingest.shared_gate import GateClosedError, SharedGate
from app.licences import service
from selfchecks import test_tb99b_guards as previous

# Explicitly isolated fixture; its socket guard rejects all external connections.
database, env, redis_sink = previous.database, previous.env, previous.redis_sink
gate_env = previous.gate_env
verify = previous.verify
test_compat_daily_three = previous.test_compat_daily_three
test_compat_consumer = previous.test_compat_verify_consumer
test_compat_malformed = (
    previous.base.test_verification_malformed_stream_message_is_acknowledged_without_http
)
test_compat_uncertain = (
    previous.base.test_verification_unknown_transport_keeps_log_latch_and_never_falls_back
)
test_compat_heartbeat = previous.base.test_worker_heartbeat_dispatch_respects_replay_and_pause
test_compat_permissions = previous.base.test_verification_permission_failures_do_not_read_secret


@pytest.mark.parametrize("boundary", ["wait", "reserve"])
def test_legacy_stop_appearing_after_initial_check_prevents_probe_http(
    gate_env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    from probes import common

    root, lid, _ = gate_env
    legacy = tmp_path / "legacy-STOP"
    monkeypatch.setattr(common, "STOP_FILE", legacy)
    monkeypatch.setenv("MAIRUI_LICENCE", "synthetic-stop-race")
    gate = SharedGate(root, lid, "probe_tb05")
    gate.acquire()
    gate.confirm_egress(previous.IP)
    sent, sleeps = [], []
    seconds = [100.0]

    def sleep(delay: float) -> None:
        sleeps.append(delay)
        seconds[0] += delay
        shared_gate.write_stop(legacy)

    real_reserve = gate.reserve

    def reserve() -> None:
        real_reserve()
        shared_gate.write_stop(legacy)

    monkeypatch.setattr(common, "time", SimpleNamespace(monotonic=lambda: seconds[0], sleep=sleep))
    if boundary == "reserve":
        monkeypatch.setattr(gate, "reserve", reserve)
    ctx = common.RunCtx(
        dry_run=False,
        base="https://api.mairuiapi.com",
        pro_base="https://pro.mairuiapi.com",
        run_id="synthetic-race",
        run_dir=tmp_path,
        samples_dir=tmp_path,
        stop_file=gate.stop,
        call_log=tmp_path / "calls.jsonl",
        min_interval=10 if boundary == "wait" else 0,
        last_call=100,
        session=SimpleNamespace(request=lambda *a, **k: sent.append(1)),
        shared_gate=gate,
    )
    monkeypatch.setattr(common, "_ctx", ctx)
    with pytest.raises((GateClosedError, common.LimitHit), match="STOP"):
        common.call("synthetic", "/synthetic/{licence}")
    assert sent == []
    assert shared_gate.stop_present(root / "STOP")
    assert len(sleeps) == (1 if boundary == "wait" else 0)
    if sleeps:
        assert sleeps[0] <= 0.25
    gate.release()


@pytest.mark.parametrize("target_exists", [False, True])
def test_stop_symlink_is_validated_consistently_by_writer_and_mapper(
    gate_env: Any, tmp_path: Path, target_exists: bool
) -> None:
    root, lid, _ = gate_env
    target, legacy = tmp_path / "target", tmp_path / "legacy-STOP"
    if target_exists:
        target.touch()
    try:
        legacy.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    if target_exists:
        shared_gate.write_stop(legacy)
        assert shared_gate.stop_present(legacy)
    else:
        with pytest.raises(GateClosedError, match="STOP_invalid"):
            shared_gate.write_stop(legacy)
        with pytest.raises(GateClosedError, match="STOP_invalid"):
            shared_gate.stop_present(legacy)
    assert shared_gate.map_legacy_stop(legacy)
    with pytest.raises(GateClosedError, match="STOP"):
        SharedGate(root, lid, "product_verify").acquire()


def test_dangling_public_stop_never_counts_as_a_successfully_written_stop(
    gate_env: Any, tmp_path: Path
) -> None:
    root, lid, _ = gate_env
    try:
        (root / "STOP").symlink_to(tmp_path / "absent")
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    with pytest.raises(GateClosedError, match="STOP_invalid"):
        shared_gate.write_stop(root / "STOP")
    with pytest.raises(GateClosedError, match="STOP_invalid"):
        SharedGate(root, lid, "probe_tb86").acquire()


@pytest.mark.parametrize("change", ["pause", "delete", "global", "STOP", "grant"])
def test_verification_revocation_after_final_status_check_prevents_send(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    e, rds = env, redis_sink
    e.settings = e.settings.model_copy(update={"redis_url": "redis://127.0.0.1:6380/15"})
    rds.delete(e.settings.ingest_paused_key)
    monkeypatch.setattr(verification, "send_paused", live.send_paused)
    original = verification.send

    def raced(*args: Any, **kwargs: Any) -> Any:
        # This is AFTER the transaction's initial final_check, BEFORE send's own
        # boundary check. Direct SQL deliberately bypasses the service fence here.
        if change in {"pause", "delete"}:
            with e.owner.begin() as conn:
                conn.execute(
                    update(user_data_licences)
                    .where(user_data_licences.c.id == e.lid)
                    .values(
                        **(
                            {"status": "paused_by_admin"}
                            if change == "pause"
                            else {
                                "deleted_at": e.clock[0],
                                "ciphertext": None,
                                "licence_hmac": None,
                            }
                        )
                    )
                )
        elif change == "global":
            rds.set(e.settings.ingest_paused_key, "1")
        elif change == "STOP":
            shared_gate.write_stop(e.root / "STOP")
        else:
            monkeypatch.setattr(verification, "read_grant", lambda: None)
        return original(*args, **kwargs)

    monkeypatch.setattr(verification, "send", raced)
    try:
        assert verify(e) == "failed_no_retry"
        assert e.calls == []
    finally:
        rds.delete(e.settings.ingest_paused_key)


def test_pause_committed_before_send_fence_wins(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    e = env
    original = verification.lock_control

    def raced(conn: Any, uid: uuid.UUID) -> None:
        with e.worker.begin() as api:
            service.hold(api, uid)
        original(conn, uid)

    monkeypatch.setattr(verification, "lock_control", raced)
    assert verify(e) == "failed_no_retry"
    assert e.calls == []


@pytest.mark.parametrize("operation", ["hold", "delete", "replace"])
def test_api_control_and_actual_send_are_in_one_serial_order(
    env: Any, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    e = env
    started, committed = threading.Event(), threading.Event()
    original = verification.allowed_before_send
    pool = ThreadPoolExecutor(max_workers=1)
    future = None

    def pause_api() -> None:
        with e.worker.begin() as conn:
            started.set()
            if operation == "hold":
                service.hold(conn, e.user)
            elif operation == "delete":
                service.delete_licence(conn, user_id=e.user, settings=e.settings)
            else:
                service.set_licence(
                    conn,
                    e.settings,
                    user_id=e.user,
                    licence=e.plaintext + "-replacement",
                    tier="free",
                    has_quant_pro=False,
                    expires_on=None,
                )
        committed.set()

    monkeypatch.setattr(service, "current_public_key", lambda _: (1, e.seal_key.public_key()))

    def checked(*args: Any) -> bool:
        nonlocal future
        result = original(*args)
        if result and future is None:
            future = pool.submit(pause_api)
            assert started.wait(timeout=2)
        return result

    def upstream(*args: Any) -> Any:
        assert started.is_set()
        assert not committed.is_set()
        # Prove the mutex is owned by the sender under the actual aia_api ACL.
        with e.worker.begin() as conn:
            assert not conn.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,99))"),
                {"key": "data-licence-control:" + str(e.user)},
            ).scalar_one()
        e.calls.append("synthetic-http")
        return 200, [{"date": str(e.day)}]

    monkeypatch.setattr(verification, "allowed_before_send", checked)
    try:
        assert verify(e, upstream=upstream) == "verified"
        assert future is not None
        future.result(timeout=3)
        assert committed.is_set()
        assert len(e.calls) == 1
        e.clock[0] += dt.timedelta(seconds=61)
        assert verify(e) in {"already_attempted", "unavailable"}
        assert len(e.calls) == 1
    finally:
        pool.shutdown(wait=True)


def test_real_wire_rechecks_after_connection_construction(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = env
    sent = []

    class Connection:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            shared_gate.write_stop(e.root / "STOP")

        def set_debuglevel(self, value: int) -> None:
            pass

        def request(self, *args: Any, **kwargs: Any) -> None:
            sent.append(1)

        def close(self) -> None:
            pass

    monkeypatch.setattr(daily_lists.http.client, "HTTPSConnection", Connection)
    assert verify(e, upstream=daily_lists.wire) == "failed_no_retry"
    assert sent == []


def test_binding_filenames_are_random_and_tags_are_keyed_and_erasable(gate_env: Any) -> None:
    root, lid, _ = gate_env
    secret = "synthetic-" + uuid.uuid4().hex
    with SharedGate(root, lid, "probe_tb05") as gate:
        gate.bind_certificate(secret)
        name = gate.halt_path.name
    digest = hashlib.sha256(b"mairui-shared/v1\0" + secret.encode()).hexdigest()
    assert name.startswith("state-")
    assert len(name.removesuffix(".halt.json")) == 38
    assert not list(root.glob("*.binding.json"))
    assert all(digest not in path.name and secret not in path.name for path in root.iterdir())
    with sqlite3.connect(root / bindings.DATABASE) as conn:
        tag = conn.execute("SELECT tag FROM certificates").fetchone()[0]
        assert tag != bytes.fromhex(digest)
    assert secret.encode() not in (root / bindings.DATABASE).read_bytes()
    bindings.cleanup(root, {}, dt.datetime.now(dt.UTC).timestamp())
    with sqlite3.connect(root / bindings.DATABASE) as conn:
        assert conn.execute("SELECT count(*) FROM certificates").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM bindings").fetchone()[0] == 0
    assert tag not in (root / bindings.DATABASE).read_bytes()
    assert not list(root.glob("*-wal"))
    assert not list(root.glob("*-journal"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX private binding storage")
@pytest.mark.parametrize("invalid", ["mode", "symlink", "hardlink", "key_mode", "key_missing"])
def test_binding_storage_permission_and_link_negatives(
    gate_env: Any, tmp_path: Path, invalid: str
) -> None:
    root, lid, _ = gate_env
    with SharedGate(root, lid, "probe_tb05") as first:
        first.bind_certificate("synthetic-private-binding")
    path = root / bindings.DATABASE
    if invalid == "mode":
        path.chmod(0o644)
    elif invalid == "symlink":
        moved = root / "synthetic-storage"
        path.rename(moved)
        path.symlink_to(moved)
    elif invalid == "hardlink":
        os.link(path, tmp_path / "synthetic-hardlink")
    elif invalid == "key_mode":
        (root / bindings.KEY).chmod(0o644)
    else:
        (root / bindings.KEY).unlink()
    with (
        pytest.raises(GateClosedError, match=r"private|missing"),
        SharedGate(root, lid, "probe_tb05") as gate,
    ):
        gate.bind_certificate("synthetic-private-binding")


def test_binding_corruption_cannot_choose_a_state_path(gate_env: Any) -> None:
    root, lid, _ = gate_env
    with SharedGate(root, lid, "probe_tb05") as gate:
        gate.bind_certificate("synthetic-corruption")
    with sqlite3.connect(root / bindings.DATABASE) as conn:
        conn.execute("UPDATE bindings SET certificate = ?", ("../../synthetic",))
    with pytest.raises(GateClosedError, match="binding_invalid"):
        SharedGate(root, lid, "probe_tb05").acquire()


def test_binding_expiry_erases_tag_without_reopening_a_halted_certificate(
    gate_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lid, other = gate_env
    now = [1000.0]
    clock = SimpleNamespace(time=lambda: now[0])
    monkeypatch.setattr(bindings, "time", clock)
    monkeypatch.setattr(shared_gate, "time", clock)
    with SharedGate(root, lid, "probe_tb05") as gate:
        gate.bind_certificate("synthetic-expiry")
        gate.trip("103")
    fact = gate.halt_path.read_bytes()
    now[0] += bindings.TTL
    assert bindings.identity(root, str(lid)) is None
    with sqlite3.connect(root / bindings.DATABASE) as conn:
        assert conn.execute("SELECT count(*) FROM certificates").fetchone()[0] == 0
    assert gate.halt_path.read_bytes() == fact
    with pytest.raises(GateClosedError, match="orphan_licence_halted"):
        SharedGate(root, other, "probe_tb86").acquire()


@pytest.mark.parametrize("fact", ["halt", "inflight", "recent"])
def test_erasing_binding_never_resets_halt_or_request_facts(gate_env: Any, fact: str) -> None:
    root, lid, other = gate_env
    gate = SharedGate(root, lid, "probe_tb05")
    gate.acquire()
    gate.bind_certificate("synthetic-erasure-does-not-reset")
    gate.confirm_egress(previous.IP)
    if fact == "halt":
        gate.trip("429")
    else:
        gate.reserve()
        if fact == "recent":
            gate.complete()
    gate.release()
    state = {p.name: p.read_bytes() for p in root.glob("state-*.json")}
    bindings.cleanup(root, {}, dt.datetime.now(dt.UTC).timestamp())
    assert {p.name: p.read_bytes() for p in root.glob("state-*.json")} == state
    with pytest.raises(GateClosedError, match=r"orphan.*(halted|budget)"):
        SharedGate(root, other, "product_verify").acquire()


def test_deleted_binding_cleanup_runs_while_global_ingest_is_paused(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import SecretStr

    from app.workers import ingest as worker

    e, rds = env, redis_sink
    with SharedGate(e.root, e.lid, "probe_tb05") as gate:
        gate.bind_certificate(e.plaintext)
    with e.worker.begin() as conn:
        service.delete_licence(conn, user_id=e.user, settings=e.settings)
    settings = e.settings.model_copy(
        update={
            "database_url": SecretStr(previous.base.DSN.replace("postgres@", "aia_ingest@")),
            "redis_url": "redis://127.0.0.1:6380/15",
        }
    )
    rds.set(settings.ingest_paused_key, "1")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("paused heartbeat reached live work")

    monkeypatch.setattr(verification, "tick", forbidden)
    monkeypatch.setattr(daily_lists, "tick", forbidden)
    try:
        worker.write_heartbeat(settings)
    finally:
        rds.delete(settings.ingest_paused_key)
    assert shared_gate.bound_halt(e.root, e.lid).name == str(e.lid) + ".halt.json"
    with sqlite3.connect(e.root / bindings.DATABASE) as conn:
        assert conn.execute("SELECT count(*) FROM certificates").fetchone()[0] == 0


@pytest.mark.parametrize(("days", "valid"), [(29, True), (30, True), (31, False), (365, False)])
def test_grant_cannot_outlive_request_log_dedup(days: int, valid: bool) -> None:
    now = dt.datetime.now(dt.UTC)
    lid = uuid.uuid4()
    grant = verification_grants.VerificationGrant(
        uuid.uuid4(),
        lid,
        uuid.uuid4(),
        now - dt.timedelta(minutes=1),
        now - dt.timedelta(minutes=1) + dt.timedelta(days=days),
    )
    assert grant.valid(lid, now) is valid
    assert not grant.valid(lid, grant.end)
    assert not dataclasses.replace(grant, max_http_requests=True).valid(lid, now)


@pytest.mark.skipif(os.name == "nt", reason="root-owned POSIX receipt")
@pytest.mark.parametrize("case", ["long", "expired", "future", "valid"])
def test_receipt_parser_rejects_long_or_currently_expired_authorization(
    tmp_path: Path, case: str
) -> None:
    now = dt.datetime.now(dt.UTC)
    start, end = now - dt.timedelta(minutes=1), now + dt.timedelta(minutes=1)
    if case == "long":
        end = start + dt.timedelta(days=31)
    elif case == "expired":
        end = now - dt.timedelta(seconds=1)
    elif case == "future":
        start, end = now + dt.timedelta(minutes=1), now + dt.timedelta(minutes=2)
    path = tmp_path / "verification.json"
    path.write_text(
        json.dumps(
            {
                "kind": "mairui_licence_verification",
                "user_id": str(uuid.uuid4()),
                "licence_id": str(uuid.uuid4()),
                "receipt_id": str(uuid.uuid4()),
                "not_before": start.isoformat(),
                "expires_at": end.isoformat(),
                "max_http_requests": 1,
            }
        )
    )
    path.chmod(0o444)
    assert (verification_grants.read_grant(path) is not None) is (case == "valid")


def test_unrelated_legacy_pending_does_not_block_authorized_fallback(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from redis.exceptions import ResponseError

    e, rds = env, redis_sink
    with e.owner.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(
                status="pending_verification",
            )
        )
    service.enqueue_verify(rds, licence_id=uuid.uuid4(), verification_id=uuid.uuid4())
    with contextlib.suppress(ResponseError):
        rds.xgroup_create(verification.STREAM, verification.GROUP, id="0", mkstream=True)
    rds.xreadgroup(verification.GROUP, "old-consumer", {verification.STREAM: ">"}, count=32)
    assert rds.xpending(verification.STREAM, verification.GROUP)["pending"]
    calls = []
    original = verification.process

    def process(engine: Any, settings: Any, intent: Any) -> str:
        assert intent.licence_id == e.lid
        return original(
            engine,
            settings,
            intent,
            clock=lambda: e.clock[0],
            egress=lambda: previous.IP,
            upstream=lambda *a: calls.append(intent) or (200, [{"date": str(e.day)}]),
        )

    monkeypatch.setattr(verification, "process", process)
    assert verification.tick(e.collector, rds, e.settings) == 1
    assert len(calls) == 1
    assert rds.xpending(verification.STREAM, verification.GROUP)["pending"]
    e.clock[0] += dt.timedelta(seconds=61)
    assert verification.tick(e.collector, rds, e.settings) == 0
    assert len(calls) == 1


def test_own_recent_pending_prevents_duplicate_fallback(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e, rds = env, redis_sink
    with e.owner.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(
                status="pending_verification",
            )
        )
    group = verification.GROUP + ":" + str(e.lid)
    rds.xgroup_create(verification.STREAM, group, id="$", mkstream=True)
    service.enqueue_verify(rds, licence_id=e.lid, verification_id=uuid.uuid4())
    rds.xreadgroup(group, "own-consumer", {verification.STREAM: ">"}, count=1)
    calls = []
    monkeypatch.setattr(verification, "process", lambda *a, **k: calls.append(1))
    assert verification.tick(e.collector, rds, e.settings) == 0
    assert calls == []
