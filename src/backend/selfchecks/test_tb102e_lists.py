"""T-B102e receipt withdrawal/recovery/deadline and first-proof failures on isolated PG."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.db.tables.market import master_runs
from app.db.tables.ops import ingest_request_log
from app.db.tables.vendor import master_vendor_batches as batches
from app.db.tables.vendor import master_vendor_list_rows as rows
from app.ingest import daily_lists, verification
from app.ingest.send_cleanup import CleanupPendingError, UnsentCleanup
from app.ingest.send_governance import Permit
from app.ingest.send_state import MinuteLedger
from app.ingest.shared_gate import GateClosedError
from app.master import daily_delivery
from selfchecks import test_tb102_lists as baseline
from selfchecks.test_tb102_lists import RetryStream, UnsentCrash, mode, previous

database = baseline.database
env = baseline.env


@pytest.mark.parametrize("enforce", [True, False])
@pytest.mark.parametrize("overdue", [True, False])
def test_tb102e_revoked_receipt_cannot_ack_unrecovered_busy_crash(
    env: Any, monkeypatch: Any, enforce: bool, overdue: bool
) -> None:
    e = env
    e.settings = mode(e.settings, enforce)
    bid = previous.batch(e)
    proof = e.root / f"unsent-{uuid.uuid5(bid, 'hslt_list')}.json"
    claim = Permit.claim
    cleanup_run = UnsentCleanup.run
    real_process = daily_lists.process
    stage = ["crash"]

    def claim_at(self: Any, path: str) -> None:
        claim(self, path)
        raise GateClosedError("shared_control_busy")

    def cleanup_at(self: Any, *args: Any, **kwargs: Any) -> None:
        if stage[0] == "crash":
            raise UnsentCrash
        if stage[0] == "pending":
            raise CleanupPendingError("unsent_cleanup_pending")
        cleanup_run(self, *args, **kwargs)

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

    monkeypatch.setattr(Permit, "claim", claim_at)
    monkeypatch.setattr(UnsentCleanup, "run", cleanup_at)
    monkeypatch.setattr(daily_lists, "process", process)
    remove_owned = daily_lists.remove_owned
    monkeypatch.setattr(
        daily_lists,
        "remove_owned",
        lambda path, identity: remove_owned(path, identity) if stage[0] != "crash" else None,
    )
    rds = RetryStream({b"kind": daily_lists.KIND.encode(), b"batch_id": str(bid).encode()})

    def tick() -> int:
        return daily_lists.tick(
            e.collector,
            rds,
            clock=lambda: e.clock[0],
            pause=e.pause,
            settings=e.settings,
        )

    with pytest.raises(UnsentCrash):
        tick()
    assert proof.exists()
    assert e.temp.exists()
    assert previous.attempted(e, bid) == ["hslt_list"]
    assert e.calls == rds.acked == rds.jobs == []
    monkeypatch.setattr(daily_lists, "read_grant", lambda: None)
    if overdue:
        e.clock[0] = e.clock[0].replace(hour=23, minute=59, second=59)
    stage[0] = "pending"
    assert tick() == 0
    assert e.calls == rds.acked == rds.jobs == []
    assert proof.exists()
    assert previous.attempted(e, bid) == ["hslt_list"]
    with e.owner.connect() as conn:
        assert (
            conn.execute(select(batches.c.status).where(batches.c.id == bid)).scalar_one()
            == "requested"
        )
    stage[0] = "recover"
    assert tick() == 1
    assert e.calls == []
    assert len(rds.acked) == len(rds.jobs) == 1
    assert not proof.exists()
    assert not e.temp.exists()
    assert previous.attempted(e, bid) == []
    assert json.loads(e.counter.read_text())["records"] == []
    state = MinuteLedger(e.root, e.lid).read(e.clock[0].timestamp())
    assert state["calls"] == []
    assert state["inflight"] is False
    with e.owner.connect() as conn:
        batch = conn.execute(select(batches).where(batches.c.id == bid)).one()
        assert batch.status == "failed"
        assert batch.error_code == (
            "daily_window_expired" if overdue else "authorization_unavailable"
        )


@pytest.mark.parametrize("attempts", [0, 1, 2])
def test_tb102e_deadline_scan_routes_all_attempted_batches_through_recovery(
    env: Any, monkeypatch: Any, attempts: int
) -> None:
    e = env
    bid = previous.batch(e)
    claim = Permit.claim
    cleanup_run = UnsentCleanup.run
    real_process = daily_lists.process
    stage = ["crash"]

    def claim_at(self: Any, path: str) -> None:
        claim(self, path)
        if len(e.calls) == attempts:
            raise GateClosedError("shared_control_busy")

    def cleanup_at(self: Any, *args: Any, **kwargs: Any) -> None:
        if stage[0] == "crash":
            raise UnsentCrash
        cleanup_run(self, *args, **kwargs)

    monkeypatch.setattr(Permit, "claim", claim_at)
    monkeypatch.setattr(UnsentCleanup, "run", cleanup_at)
    with pytest.raises(UnsentCrash):
        previous.run(e, bid)
    assert len(e.calls) == attempts
    assert len(previous.attempted(e, bid)) == attempts + 1
    e.clock[0] = e.clock[0].replace(hour=23, minute=59, second=59)
    monkeypatch.setattr(daily_lists, "read_grant", lambda: None)

    class Published(RetryStream):
        def xadd(self, stream: str, fields: dict[str, str]) -> None:
            assert stream == daily_lists.STREAM
            if fields["batch_id"] == str(bid):
                assert fields == {"kind": daily_lists.KIND, "batch_id": str(bid)}
                self.fields = {key.encode(): value.encode() for key, value in fields.items()}

        def lpush(self, *args: Any) -> None:
            if json.loads(args[1])["args"]["batch_id"] == str(bid):
                super().lpush(*args)

    rds = Published({})
    assert daily_delivery.publish_pending(e.worker, rds, now=e.clock[0]) >= 1
    assert rds.jobs == []  # No worker apply before ingest has recovered cleanup.
    stage[0] = "recover"

    def process(*args: Any, **kwargs: Any) -> str:
        return real_process(
            *args,
            **kwargs,
            upstream=e.wire,
            temp=e.temp,
            stop=e.stop,
            halt=e.halt,
            egress=lambda: pytest.fail("expired batch must not inspect egress"),
        )

    monkeypatch.setattr(daily_lists, "process", process)
    assert (
        daily_lists.tick(
            e.collector,
            rds,
            clock=lambda: e.clock[0],
            pause=e.pause,
            settings=e.settings,
        )
        == 1
    )
    assert len(e.calls) == attempts
    with e.owner.connect() as conn:
        batch = conn.execute(select(batches).where(batches.c.id == bid)).one()
        assert batch.status == "failed"
        assert batch.error_code == "daily_window_expired"
        assert len(batch.datasets) == attempts
        assert len(
            conn.execute(select(rows).where(rows.c.batch_id == bid)).all()
        ) == attempts * len(previous.NAMES)
        assert conn.execute(
            select(master_runs.c.stats).where(master_runs.c.id == batch.master_run_id)
        ).scalar_one()["attempted"] == list(daily_lists.LISTS[:attempts])
    assert list(e.root.glob("unsent-*.json")) == []
    assert len(json.loads(e.counter.read_text())["records"]) == attempts


@pytest.mark.parametrize("kind", ["daily", "verify"])
@pytest.mark.parametrize("point", ["open", "fsync"])
def test_tb102e_first_proof_write_failure_keeps_busy_without_ack_or_refund(
    env: Any, monkeypatch: Any, kind: str, point: str
) -> None:
    e = env
    bid = previous.batch(e)
    vid = uuid.uuid4()
    rid = uuid.uuid5(bid, "hslt_list") if kind == "daily" else vid
    proof = e.root / f"unsent-{rid}.json"
    assert not proof.exists()
    claim = Permit.claim
    reserve = MinuteLedger.reserve
    opened = os.open
    fsync = os.fsync
    real_daily = daily_lists.process
    real_verify = verification.process

    def claim_at(self: Any, path: str) -> None:
        claim(self, path)
        raise GateClosedError("shared_control_busy")

    def reserve_at(self: Any, now: float) -> None:
        reserve(self, now)
        if kind == "verify":
            waiting = e.root / "probe-waiting.lease.json"
            waiting.write_text(json.dumps({"source": "probe_tb05"}))
            os.chmod(waiting, 0o600)

    def open_at(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if Path(path) == proof and point == "open":
            raise PermissionError("synthetic proof creation failure")
        return opened(path, flags, *args, **kwargs)

    def fsync_at(fd: int) -> None:
        if point == "fsync" and Path(os.readlink(f"/proc/self/fd/{fd}")) == proof:
            raise OSError("synthetic proof flush failure")
        fsync(fd)

    def daily_process(*args: Any, **kwargs: Any) -> str:
        return real_daily(
            *args,
            **kwargs,
            upstream=e.wire,
            temp=e.temp,
            stop=e.stop,
            halt=e.halt,
            egress=lambda: previous.IP,
        )

    def verify_process(*args: Any, **kwargs: Any) -> str:
        return real_verify(
            *args,
            **kwargs,
            clock=lambda: e.clock[0],
            upstream=lambda *args: pytest.fail("known busy must never reach HTTP"),
            egress=lambda: previous.IP,
        )

    monkeypatch.setattr(Permit, "claim", claim_at)
    monkeypatch.setattr(MinuteLedger, "reserve", reserve_at)
    monkeypatch.setattr(os, "open", open_at)
    monkeypatch.setattr(os, "fsync", fsync_at)
    monkeypatch.setattr(daily_lists, "process", daily_process)
    monkeypatch.setattr(verification, "process", verify_process)
    if kind == "daily":
        rds = RetryStream({b"kind": daily_lists.KIND.encode(), b"batch_id": str(bid).encode()})
        assert (
            daily_lists.tick(
                e.collector,
                rds,
                clock=lambda: e.clock[0],
                pause=e.pause,
                settings=e.settings,
            )
            == 0
        )
        assert previous.attempted(e, bid) == ["hslt_list"]
        assert len(json.loads(e.counter.read_text())["records"]) == 1
        with e.owner.connect() as conn:
            assert (
                conn.execute(select(batches.c.status).where(batches.c.id == bid)).scalar_one()
                == "requested"
            )
    else:
        rds = RetryStream(
            {
                b"kind": b"verify_licence",
                b"licence_id": str(e.lid).encode(),
                b"verification_id": str(vid).encode(),
            }
        )
        verification.tick(e.collector, rds, e.settings)
        with e.owner.connect() as conn:
            assert (
                conn.execute(
                    select(ingest_request_log.c.status).where(ingest_request_log.c.id == vid)
                ).scalar_one()
                == "queued"
            )
    assert rds.acked == rds.jobs == e.calls == []
    assert proof.exists() is (point != "open")
    state = MinuteLedger(e.root, e.lid).read(e.clock[0].timestamp())
    assert len(state["calls"]) == 1
    assert state["inflight"] is True
