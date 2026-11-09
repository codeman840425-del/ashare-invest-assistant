"""RV-07 dispatch, retention and queue regressions; dedicated synthetic PG/Redis only."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import sqlite3
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select, text, update

from app.db.tables.licences import user_data_licences
from app.ingest import certificate_bindings as bindings
from app.ingest import daily_lists, live, shared_gate, verification
from app.ingest.intents import VerifyIntent
from app.ingest.shared_gate import GateClosedError, SharedGate
from app.licences import service
from selfchecks import test_tb99c_races as previous

# Reuse only the deliberately isolated fixture and its deny-external-network guard.
database, env, redis_sink = previous.database, previous.env, previous.redis_sink
gate_env = previous.gate_env
base = previous.previous.base
verify = previous.verify
# Related permissions and actual consumer paths are retained on this exact code.
test_compat_permissions = previous.test_compat_permissions
test_compat_three_lists = previous.test_compat_daily_three
test_compat_consumer = previous.test_compat_consumer


@pytest.mark.parametrize("source", ["daily", "verify"])
@pytest.mark.parametrize("hook", ["after_final", "encode", "method_lookup"])
@pytest.mark.parametrize("change", ["STOP", "global"])
def test_revocation_injected_after_final_business_check_never_reaches_http(
    env: Any,
    redis_sink: Any,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    hook: str,
    change: str,
) -> None:
    _wire_case(env, redis_sink, monkeypatch, source, hook, change)


@pytest.mark.parametrize("source", ["daily", "verify"])
def test_final_transport_guard_allows_authorized_owned_send(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    _wire_case(env, redis_sink, monkeypatch, source, "none", "none")


def _wire_case(
    e: Any, rds: Any, monkeypatch: pytest.MonkeyPatch, source: str, hook: str, change: str
) -> None:
    settings = e.settings.model_copy(update={"redis_url": "redis://127.0.0.1:6380/15"})
    e.settings = settings
    rds.delete(settings.ingest_paused_key)
    phase = {"created": False, "checked": False, "injected": False, "guard_locked": False}
    sent = []

    def assert_locked() -> None:
        with e.worker.begin() as conn:
            assert not conn.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,99))"),
                {"key": "data-licence-control:" + str(e.user)},
            ).scalar_one()
        phase["guard_locked"] = True

    def inject() -> None:
        assert phase["checked"]  # Injection must occur AFTER a real final business check.
        assert_locked()
        if phase["injected"]:
            return
        phase["injected"] = True
        if change == "STOP":
            shared_gate.write_stop(e.root / "STOP")
        else:
            rds.set(settings.ingest_paused_key, "1")

    original_send = daily_lists.send

    def send(*args: Any, **kwargs: Any) -> Any:
        check = kwargs["before_send"]

        def checked() -> None:
            check()
            phase["checked"] = True
            if hook == "after_final" and phase["created"]:
                inject()

        kwargs["before_send"] = checked
        return original_send(*args, **kwargs)

    monkeypatch.setattr(daily_lists, "send", send)
    monkeypatch.setattr(verification, "send", send)
    original_quote = daily_lists.quote

    def quote(*args: Any, **kwargs: Any) -> str:
        result = original_quote(*args, **kwargs)
        if hook == "encode":
            inject()
        return result

    monkeypatch.setattr(daily_lists, "quote", quote)

    def paused(current: Any) -> bool:
        if phase["created"] and daily_lists.WIRE_GATE.get() is not None:
            assert_locked()
        return live.send_paused(current)

    monkeypatch.setattr(daily_lists, "send_paused", paused)
    monkeypatch.setattr(verification, "send_paused", paused)

    class Connection:
        status = 200

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            phase["created"] = True

        def set_debuglevel(self, value: int) -> None:
            pass

        @property
        def request(self) -> Any:
            if hook == "method_lookup":
                inject()

            def request(*args: Any, **kwargs: Any) -> None:
                assert phase["guard_locked"]
                sent.append("synthetic-http")

            return request

        def getresponse(self) -> Any:
            return self

        def read(self, maximum: int) -> bytes:
            return json.dumps(
                [{"dm": code[:6], "mc": name} for code, name in base.NAMES.items()]
            ).encode()

        def close(self) -> None:
            pass

    monkeypatch.setattr(daily_lists.http.client, "HTTPSConnection", Connection)
    try:
        outcome = (
            base.run(e, base.batch(e), upstream=daily_lists.wire)
            if source == "daily"
            else verify(e, upstream=daily_lists.wire)
        )
        assert phase["guard_locked"]
        if hook == "none":
            assert outcome == ("fetched" if source == "daily" else "verified")
            assert len(sent) == (3 if source == "daily" else 1)
        else:
            assert phase["injected"]
            assert outcome == ("failed" if source == "daily" else "failed_no_retry")
            assert sent == []
        assert daily_lists.WIRE_GATE.get() is None
        assert daily_lists.WIRE_CHECK.get() is None
        assert daily_lists.WIRE_SETTINGS.get() is None
    finally:
        rds.delete(settings.ingest_paused_key)


@pytest.mark.parametrize(
    ("status", "age_hours", "pause_offset", "kept"),
    [
        ("ip_limited", 23, None, True),
        ("ip_limited", 24, None, False),
        ("quota_exceeded", 25, None, False),
        ("active", 1, None, False),
        ("ip_limited", 25, 2, True),
        ("ip_limited", 1, -1, False),
    ],
)
def test_deleted_binding_retention_uses_db_clock_and_contract_deadline(
    env: Any,
    status: str,
    age_hours: int,
    pause_offset: int | None,
    kept: bool,
) -> None:
    e = env
    with SharedGate(e.root, e.lid, "probe_tb05") as gate:
        gate.bind_certificate(e.plaintext)
    with sqlite3.connect(e.root / bindings.DATABASE) as conn:
        tag = conn.execute("SELECT tag FROM certificates").fetchone()[0]
    with e.owner.begin() as conn:
        now = conn.execute(select(func.now())).scalar_one()
        deleted = now - dt.timedelta(hours=age_hours)
        until = None if pause_offset is None else now + dt.timedelta(hours=pause_offset)
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(
                status=status,
                paused_until=until,
                deleted_at=deleted,
                ciphertext=None,
                licence_hmac=None,
            )
        )
    live.sync_halts(e.collector, e.settings, SimpleNamespace(eval=lambda *a: "1"), e.root)
    with sqlite3.connect(e.root / bindings.DATABASE) as conn:
        result = conn.execute(
            "SELECT expires FROM bindings WHERE licence=?", (str(e.lid),)
        ).fetchone()
        assert bool(result) is kept
        assert bool(conn.execute("SELECT 1 FROM certificates").fetchone()) is kept
        if kept:
            deadline = until if until is not None else deleted + dt.timedelta(hours=24)
            assert result[0] <= deadline.timestamp()
    if not kept:
        assert tag not in (e.root / bindings.DATABASE).read_bytes()


def test_null_pause_binding_expires_on_access_at_exact_24h_without_next_heartbeat(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = env
    with SharedGate(e.root, e.lid, "probe_tb05") as gate:
        gate.bind_certificate(e.plaintext)
    with e.owner.begin() as conn:
        now = conn.execute(select(func.now())).scalar_one()
        deleted = now - dt.timedelta(hours=23)
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(
                status="ip_limited",
                paused_until=None,
                deleted_at=deleted,
                ciphertext=None,
                licence_hmac=None,
            )
        )
    live.sync_halts(e.collector, e.settings, SimpleNamespace(eval=lambda *a: "1"), e.root)
    with sqlite3.connect(e.root / bindings.DATABASE) as conn:
        tag = conn.execute("SELECT tag FROM certificates").fetchone()[0]
    boundary = deleted + dt.timedelta(hours=24)
    monkeypatch.setattr(bindings, "time", SimpleNamespace(time=lambda: boundary.timestamp()))
    assert bindings.identity(e.root, str(e.lid)) is None
    with sqlite3.connect(e.root / bindings.DATABASE) as conn:
        assert conn.execute("SELECT count(*) FROM certificates").fetchone()[0] == 0
    assert tag not in (e.root / bindings.DATABASE).read_bytes()


def _execute_at_owned_clock(e: Any, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls = []
    original = verification.process

    def execute(engine: Any, settings: Any, intent: Any) -> str:
        return original(
            engine,
            settings,
            intent,
            clock=lambda: e.clock[0],
            egress=lambda: base.IP,
            upstream=lambda *a: calls.append(intent) or (200, [{"date": str(e.day)}]),
        )

    monkeypatch.setattr(verification, "process", execute)
    return calls


def test_multiple_queued_intents_do_not_become_unprocessed_pending(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e, rds = env, redis_sink
    calls = _execute_at_owned_clock(e, monkeypatch)
    for _ in range(3):
        service.enqueue_verify(rds, licence_id=e.lid, verification_id=uuid.uuid4())
    group = verification.GROUP + ":" + str(e.lid)
    for remaining in (2, 1, 0):
        assert verification.tick(e.collector, rds, e.settings) == 1
        assert rds.xpending(verification.STREAM, group)["pending"] == 0
        info = next(
            row for row in rds.xinfo_groups(verification.STREAM) if row["name"].decode() == group
        )
        assert info["lag"] == remaining
    assert len(calls) == 1
    # No stranded prefetched entries may block a later pending generation's fallback.
    e.clock[0] += dt.timedelta(seconds=61)
    new_grant = dataclasses.replace(e.verification_grant, receipt_id=uuid.uuid4())
    monkeypatch.setattr(verification, "read_grant", lambda: new_grant)
    with e.owner.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(
                status="pending_verification",
                status_changed_at=e.clock[0],
            )
        )
    assert verification.tick(e.collector, rds, e.settings) == 1
    assert len(calls) == 2


def test_v1_prefetched_unrelated_pending_cannot_block_v2_owned_fallback(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e, rds = env, redis_sink
    calls = _execute_at_owned_clock(e, monkeypatch)
    with e.owner.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(
                status="pending_verification",
                status_changed_at=e.clock[0],
            )
        )
    for _ in range(2):
        service.enqueue_verify(rds, licence_id=uuid.uuid4(), verification_id=uuid.uuid4())
    legacy = "licence-verification-v1:" + str(e.lid)
    rds.xgroup_create(verification.STREAM, legacy, id="0")
    rds.xreadgroup(legacy, "old-prefetch", {verification.STREAM: ">"}, count=32)
    assert rds.xpending(verification.STREAM, legacy)["pending"] == 2
    assert verification.tick(e.collector, rds, e.settings) == 1
    assert len(calls) == 1
    assert rds.xpending(verification.STREAM, legacy)["pending"] == 2
    assert verification.tick(e.collector, rds, e.settings) == 0
    assert len(calls) == 1


def test_v2_group_restart_does_not_replay_v1_logged_receipt(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e, rds = env, redis_sink
    token = uuid.uuid4()
    assert verify(e, intent=VerifyIntent(e.lid, token)) == "verified"
    assert len(e.calls) == 1
    service.enqueue_verify(rds, licence_id=e.lid, verification_id=token)
    legacy = "licence-verification-v1:" + str(e.lid)
    rds.xgroup_create(verification.STREAM, legacy, id="0")
    rds.xreadgroup(legacy, "old-after-http", {verification.STREAM: ">"}, count=32)
    calls = _execute_at_owned_clock(e, monkeypatch)
    assert verification.tick(e.collector, rds, e.settings) == 1
    assert calls == []
    assert rds.xpending(verification.STREAM, legacy)["pending"] == 1
    group = verification.GROUP + ":" + str(e.lid)
    assert rds.xpending(verification.STREAM, group)["pending"] == 0


def test_busy_owned_pending_does_not_prefetch_another_queued_intent(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e, rds = env, redis_sink
    for _ in range(3):
        service.enqueue_verify(rds, licence_id=e.lid, verification_id=uuid.uuid4())
    calls = []
    monkeypatch.setattr(verification, "process", lambda *a: calls.append(1) or "busy_or_closed")
    assert verification.tick(e.collector, rds, e.settings) == 1
    group = verification.GROUP + ":" + str(e.lid)
    assert rds.xpending(verification.STREAM, group)["pending"] == 1
    assert verification.tick(e.collector, rds, e.settings) == 0
    assert rds.xpending(verification.STREAM, group)["pending"] == 1
    assert calls == [1]


@pytest.mark.parametrize("code", ["103", "429"])
def test_cross_certificate_orphan_halt_preserves_conservative_stop_pending_ruling(
    gate_env: Any, code: str
) -> None:
    root, first, other = gate_env
    with SharedGate(root, first, "probe_tb05") as gate:
        gate.bind_certificate("synthetic-first-" + uuid.uuid4().hex)
        gate.trip(code)
    fact = gate.halt_path.read_bytes()
    with SharedGate(root, other, "product_verify") as second:
        second.bind_certificate("synthetic-other-" + uuid.uuid4().hex)
    # Known distinct certificates are separate; erasure loses attribution. Preserve
    # the broader existing stop exactly, pending Chief/architect's explicit ruling.
    now = dt.datetime.now(dt.UTC).timestamp()
    bindings.cleanup(root, {str(other): now + bindings.TTL}, now)
    assert gate.halt_path.read_bytes() == fact
    with pytest.raises(GateClosedError, match="orphan_licence_halted"):
        SharedGate(root, other, "product_verify").acquire()
