"""T-B102f real product classification with isolated roles and synthetic oversized responses."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select, update

from app.db.tables.licences import data_licence_events, user_data_licence_status
from app.db.tables.market import master_runs
from app.db.tables.notify import notifications
from app.db.tables.ops import ingest_request_log
from app.db.tables.vendor import master_vendor_batches as batches
from app.ingest import daily_lists, verification
from app.ingest.intents import VerifyIntent
from app.ingest.send_governance import Permit
from app.ingest.send_state import MinuteLedger
from app.ingest.shared_gate import GateClosedError
from app.master import daily_delivery
from selfchecks import test_tb102_lists as baseline
from selfchecks.test_tb102_lists import previous

database = baseline.database
env = baseline.env


@pytest.mark.parametrize("kind", ["daily", "verify"])
@pytest.mark.parametrize("code", ["103", "429", None])
def test_tb102f_oversized_limit_classifies_and_notifies_without_network_mislabel(
    env: Any, monkeypatch: Any, kind: str, code: str | None
) -> None:
    e = env
    start = b'{"message":"' + b"x" * 131072 + b'",'
    if code == "103":
        start += b'"error":"103:unfinished'
    elif code == "429":
        start += b'"error":{"code":429,"padding":"'
    else:
        start += b'"data":"'
    payload = start + b"x" * (16 * 1024 * 1024)
    connected: list[bool] = []
    vid = uuid.uuid4()
    bid = previous.batch(e) if kind == "daily" else None

    class Connection:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            connected.append(True)

        def set_debuglevel(self, value: int) -> None:
            pass

        def request(self, *args: Any, **kwargs: Any) -> None:
            pass

        def getresponse(self) -> Any:
            return SimpleNamespace(status=200, read=lambda count: payload[:count])

        def close(self) -> None:
            assert (e.root / "STOP").exists() is (code is not None)

    monkeypatch.setattr(daily_lists.http.client, "HTTPSConnection", Connection)
    if kind == "daily":
        assert previous.run(e, bid, upstream=daily_lists.wire) == "failed"
        assert len(json.loads(e.counter.read_text())["records"]) == 1
        with e.owner.connect() as conn:
            batch = conn.execute(select(batches).where(batches.c.id == bid)).one()
            stats = conn.execute(
                select(master_runs.c.stats).where(master_runs.c.id == batch.master_run_id)
            ).scalar_one()
            assert bool(stats.get("upstream_halted")) is (code is not None)
    else:
        assert verification.process(
            e.collector,
            e.settings,
            VerifyIntent(e.lid, vid),
            clock=lambda: e.clock[0],
            upstream=daily_lists.wire,
            egress=lambda: previous.IP,
        ) == ("failed" if code else "failed_no_retry")
        with e.owner.connect() as conn:
            logged = conn.execute(
                select(ingest_request_log).where(ingest_request_log.c.id == vid)
            ).one()
            assert logged.mairui_code == code
            assert logged.status == ("failed" if code else "queued")
    assert connected == [True]
    with e.owner.connect() as conn:
        state = conn.execute(
            select(user_data_licence_status).where(user_data_licence_status.c.id == e.lid)
        ).one()
        assert state.last_error_code == (code or "network")
        events = conn.execute(
            select(data_licence_events).where(data_licence_events.c.licence_id == e.lid)
        ).all()
        if code:
            assert state.status == "ip_limited"
            assert len(events) == 1
            assert events[0].event == "ip_limited"
            assert events[0].upstream_code == code
            notices = (
                conn.execute(
                    select(notifications.c.user_id).where(
                        notifications.c.user_id.in_([e.user, e.admin])
                    )
                )
                .scalars()
                .all()
            )
            assert set(notices) == {e.user, e.admin}
        else:
            assert events == []
    assert e.plaintext not in e.logs.text


class FlowStream(baseline.RetryStream):
    def __init__(self, bid: uuid.UUID) -> None:
        super().__init__({b"kind": daily_lists.KIND.encode(), b"batch_id": str(bid).encode()})
        self.bid = bid
        self.paused = False
        self.claims = 0
        self.added: list[Any] = []

    def exists(self, key: str) -> bool:
        assert key == "ingest:paused"
        return self.paused

    def xadd(self, stream: str, fields: dict[str, str]) -> None:
        if fields["batch_id"] == str(self.bid):
            assert stream == daily_lists.STREAM
            self.added.append(fields)

    def lpush(self, *args: Any) -> None:
        if json.loads(args[1])["args"]["batch_id"] == str(self.bid):
            super().lpush(*args)

    def xautoclaim(self, *args: Any, **kwargs: Any) -> Any:
        self.claims += 1
        return super().xautoclaim(*args, **kwargs)


def invoke_tick(e: Any, rds: Any, monkeypatch: Any) -> int:
    real_process = daily_lists.process

    def process(*args: Any, **kwargs: Any) -> str:
        return real_process(
            *args,
            **kwargs,
            upstream=e.wire,
            temp=e.temp,
            stop=e.stop,
            halt=e.halt,
            egress=lambda: previous.IP,
        )

    with monkeypatch.context() as patch:
        patch.setattr(daily_lists, "process", process)
        return daily_lists.tick(
            e.collector,
            rds,
            clock=lambda: e.clock[0],
            grant=e.grant,
            pause=e.pause,
            settings=e.settings,
        )


@pytest.mark.parametrize("point", ["before_attempt", "after_attempt"])
@pytest.mark.parametrize("late", [False, True])
def test_tb102f_first_proof_creation_failure_second_tick_stays_safe(
    env: Any, monkeypatch: Any, point: str, late: bool
) -> None:
    e = env
    bid = previous.batch(e)
    proof = e.root / f"unsent-{uuid.uuid5(bid, 'hslt_list')}.json"
    assert not proof.exists()
    real_check, real_claim = Permit.check, Permit.claim
    opened = os.open
    first = [True]

    def check(self: Any) -> None:
        real_check(self)
        if point == "before_attempt" and first[0]:
            first[0] = False
            raise GateClosedError("shared_control_busy")

    def claim(self: Any, path: str) -> None:
        real_claim(self, path)
        if point == "after_attempt" and first[0]:
            first[0] = False
            raise GateClosedError("shared_control_busy")

    def open_at(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if Path(path) == proof:
            raise PermissionError("synthetic proof create failure")
        return opened(path, flags, *args, **kwargs)

    monkeypatch.setattr(Permit, "check", check)
    monkeypatch.setattr(Permit, "claim", claim)
    monkeypatch.setattr(os, "open", open_at)
    rds = FlowStream(bid)
    assert invoke_tick(e, rds, monkeypatch) == 0
    assert e.calls == rds.acked == rds.jobs == []
    assert previous.attempted(e, bid) == (["hslt_list"] if point == "after_attempt" else [])
    assert not proof.exists()
    if late:
        e.clock[0] = e.clock[0].replace(hour=23, minute=59, second=59)
        daily_delivery.publish_pending(e.worker, rds, now=e.clock[0])
        with e.worker.begin() as conn:
            parent_id = daily_delivery.apply_batch(conn, bid, now=e.clock[0], cfg=None, root=e.root)
            assert (
                conn.execute(
                    select(master_runs.c.finished_at).where(master_runs.c.id == parent_id)
                ).scalar_one()
                is None
            )
    result = invoke_tick(e, rds, monkeypatch)
    should_expire = late and point == "before_attempt"
    assert result == int(should_expire)
    assert e.calls == []
    assert len(rds.acked) == len(rds.jobs) == int(should_expire)
    assert len(json.loads(e.counter.read_text())["records"]) == 1
    minute = MinuteLedger(e.root, e.lid).read(e.clock[0].timestamp())
    assert len(minute["calls"]) == 1
    assert minute["inflight"] is True
    with e.owner.connect() as conn:
        batch = conn.execute(select(batches).where(batches.c.id == bid)).one()
        assert batch.status == ("failed" if should_expire else "expired" if late else "requested")
        if should_expire:
            assert batch.error_code == "daily_window_expired"


@pytest.mark.parametrize("paused_by", ["pause", "replay"])
@pytest.mark.parametrize("window", ["within", "cutoff", "crossday", "legacy_expired"])
@pytest.mark.parametrize("partial", [False, True])
def test_tb102f_r8_scan_pause_replay_resume_r9_expired_adjudication(
    env: Any, monkeypatch: Any, paused_by: str, window: str, partial: bool
) -> None:
    e = env
    bid = previous.batch(e)
    if partial:

        def busy(seconds: float) -> None:
            raise GateClosedError("shared_control_busy")

        assert previous.run(e, bid, pause=busy) == "busy"
        assert len(e.calls) == 1
    if window == "cutoff":
        e.clock[0] = e.clock[0].replace(hour=23, minute=59, second=59)
    elif window == "crossday":
        e.clock[0] += dt.timedelta(days=1)
    elif window == "legacy_expired":
        with e.owner.begin() as conn:
            conn.execute(
                update(batches)
                .where(batches.c.id == bid)
                .values(status="expired", error_code="deadline_exceeded")
            )
    rds = FlowStream(bid)
    rds.paused = paused_by == "pause"
    if paused_by == "replay":
        monkeypatch.setenv("MAIRUI_MODE", "replay")
    daily_delivery.publish_pending(e.worker, rds, now=e.clock[0])
    assert rds.added == rds.jobs == []
    assert invoke_tick(e, rds, monkeypatch) == 0
    assert rds.claims == 0
    assert rds.acked == []
    assert len(e.calls) == int(partial)
    with e.owner.connect() as conn:
        batch = conn.execute(select(batches).where(batches.c.id == bid)).one()
        assert batch.status == ("requested" if window == "within" else "expired")
        assert len(batch.datasets) == int(partial)
    if window != "within":
        with e.worker.begin() as conn:
            parent_id = daily_delivery.apply_batch(conn, bid, now=e.clock[0], cfg=None, root=e.root)
            assert (
                conn.execute(
                    select(master_runs.c.finished_at).where(master_runs.c.id == parent_id)
                ).scalar_one()
                is None
            )
    # Both verification and daily consumers must leave PEL untouched while closed.
    assert verification.tick(e.collector, rds, e.settings) == 0
    assert rds.claims == 0
    rds.paused = False
    monkeypatch.setenv("MAIRUI_MODE", "live")
    daily_delivery.publish_pending(e.worker, rds, now=e.clock[0])
    assert len(rds.added) == 1
    assert rds.jobs == []
    assert invoke_tick(e, rds, monkeypatch) == 1
    expired = window in {"cutoff", "crossday"}
    assert len(e.calls) == (int(partial) if expired else 3)
    with e.owner.connect() as conn:
        batch = conn.execute(select(batches).where(batches.c.id == bid)).one()
        assert batch.status == ("failed" if expired else "fetched")
        assert batch.error_code == ("daily_window_expired" if expired else None)
        assert len(batch.datasets) == (int(partial) if expired else 3)
    before = len(e.calls)
    assert invoke_tick(e, rds, monkeypatch) == 1  # Duplicate PEL claim is business-idempotent.
    assert len(e.calls) == before
    rds.added.clear()
    daily_delivery.publish_pending(e.worker, rds, now=e.clock[0])
    assert rds.added == []  # fetched/finally failed now take only the apply path.


@pytest.mark.parametrize(
    "case", ["replay", "settings_off", "held", "deleted", "unapproved", "wrong_licence"]
)
def test_tb102f_verification_permissions_still_reject(
    env: Any, monkeypatch: Any, case: str
) -> None:
    baseline.test_tb102c_verification_permission_boundaries(env, case, monkeypatch)


@pytest.mark.parametrize(
    "case", ["missing_receipt", "replay", "no_certificate", "wrong_licence", "egress"]
)
def test_tb102f_daily_permissions_still_reject(env: Any, monkeypatch: Any, case: str) -> None:
    baseline.test_tb102_product_authorization_egress_not_bypassed(env, monkeypatch, case)


@pytest.mark.parametrize("late", [False, True])
@pytest.mark.parametrize(
    ("kind", "fault"), [("daily", "fsync"), ("verify", "open"), ("verify", "fsync")]
)
def test_tb102f_proof_failure_two_ticks_recover_only_with_valid_proof(
    env: Any, monkeypatch: Any, kind: str, fault: str, late: bool
) -> None:
    e = env
    bid, vid = previous.batch(e), uuid.uuid4()
    rid = uuid.uuid5(bid, "hslt_list") if kind == "daily" else vid
    proof = e.root / f"unsent-{rid}.json"
    waiting = e.root / "probe-waiting.lease.json"
    assert not proof.exists()
    opened, synced = os.open, os.fsync
    reserve, claim = MinuteLedger.reserve, Permit.claim
    real_verify = verification.process
    inject, fail = [True], [True]

    def reserve_at(self: Any, now: float) -> None:
        reserve(self, now)
        if kind == "verify" and inject[0]:
            inject[0] = False
            waiting.write_text(json.dumps({"source": "probe_tb05"}))
            os.chmod(waiting, 0o600)

    def claim_at(self: Any, path: str) -> None:
        claim(self, path)
        if kind == "daily" and inject[0]:
            inject[0] = False
            raise GateClosedError("shared_control_busy")

    def open_at(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if Path(path) == proof and fault == "open":
            raise PermissionError("synthetic missing cleanup proof")
        return opened(path, flags, *args, **kwargs)

    def sync_at(fd: int) -> None:
        if fault == "fsync" and fail[0] and Path(os.readlink(f"/proc/self/fd/{fd}")) == proof:
            fail[0] = False
            raise OSError("synthetic cleanup proof fsync failure")
        synced(fd)

    def upstream(*args: Any) -> Any:
        e.calls.append(True)
        return 200, [{"date": str(e.day)}]

    def process(*args: Any, **kwargs: Any) -> str:
        return real_verify(
            *args, **kwargs, clock=lambda: e.clock[0], upstream=upstream, egress=lambda: previous.IP
        )

    monkeypatch.setattr(MinuteLedger, "reserve", reserve_at)
    monkeypatch.setattr(Permit, "claim", claim_at)
    monkeypatch.setattr(os, "open", open_at)
    monkeypatch.setattr(os, "fsync", sync_at)
    monkeypatch.setattr(verification, "process", process)
    monkeypatch.setattr(verification, "publish_status", lambda *args: None)
    rds = FlowStream(bid)
    if kind == "verify":
        rds.fields = {
            b"kind": b"verify_licence",
            b"licence_id": str(e.lid).encode(),
            b"verification_id": str(vid).encode(),
        }

    def tick() -> int:
        return (
            invoke_tick(e, rds, monkeypatch)
            if kind == "daily"
            else verification.tick(e.collector, rds, e.settings)
        )

    tick()
    assert e.calls == rds.acked == []
    assert proof.exists() is (fault == "fsync")
    assert not (e.root / "single-egress.lease.json").exists()
    assert list(e.root.glob("*.halt.json")) == []
    if waiting.exists():
        assert waiting.parent == e.root
        assert json.loads(waiting.read_text())["source"] == "probe_tb05"
        waiting.unlink()
    if late:
        e.clock[0] = e.clock[0].replace(hour=23, minute=59, second=59)
        if kind == "daily":
            daily_delivery.publish_pending(e.worker, rds, now=e.clock[0])
    tick()
    assert len(e.calls) == ((0 if late else 3) if kind == "daily" else int(fault == "fsync"))
    assert len(rds.acked) == int(fault == "fsync")
    assert not proof.exists()
    if kind == "daily" and late:
        with e.owner.connect() as conn:
            batch = conn.execute(select(batches).where(batches.c.id == bid)).one()
            assert batch.status == "failed"
            assert batch.error_code == "daily_window_expired"
        assert json.loads(e.counter.read_text())["records"] == []
        assert previous.attempted(e, bid) == []
        assert MinuteLedger(e.root, e.lid).read(e.clock[0].timestamp())["inflight"] is False
    if fault == "open":
        with e.owner.connect() as conn:
            assert (
                conn.execute(
                    select(ingest_request_log.c.status).where(ingest_request_log.c.id == vid)
                ).scalar_one()
                == "queued"
            )
        assert MinuteLedger(e.root, e.lid).read(e.clock[0].timestamp())["inflight"] is True
