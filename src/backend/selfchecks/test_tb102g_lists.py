"""T-B102g isolated PG + real Redis: durability, pause, lstat and stream dedup guards."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
import redis
from sqlalchemy import select, update

from app.db.tables.market import master_runs
from app.db.tables.vendor import master_vendor_batches as batches
from app.ingest import daily_lists
from app.ingest.send_governance import Permit
from app.ingest.send_state import MinuteLedger
from app.ingest.shared_gate import GateClosedError
from app.master import daily_delivery
from app.master.daily_stream import acknowledge, pending_key, publish_once
from selfchecks import test_tb102_lists as baseline
from selfchecks.test_tb102f_lists import invoke_tick

previous = baseline.previous
database = baseline.database


@pytest.fixture
def env(database: Any, tmp_path: Path, monkeypatch: Any, caplog: Any) -> Any:
    source = baseline.env.__wrapped__(database, tmp_path, monkeypatch, caplog)
    e = next(source)
    yield e
    # Only the synthetic rows owned by this fixture; keep later outbox scans scoped.
    with e.owner.begin() as conn:
        conn.execute(
            update(master_runs)
            .where(
                master_runs.c.id.in_(
                    select(batches.c.master_run_id).where(batches.c.source_licence_id == e.lid)
                )
            )
            .values(finished_at=e.clock[0])
        )
    with contextlib.suppress(StopIteration):
        next(source)


@pytest.fixture
def stream(env: Any) -> Any:
    if os.environ.get("TB102G_ISOLATED_REDIS") != "1":
        pytest.skip("explicit network-none tb102g Redis required")
    client = redis.Redis(host="127.0.0.1", port=6380, db=15)
    assert client.config_get("dbfilename") == {"dbfilename": "tb102g-isolated.rdb"}
    client.flushdb()
    yield client
    client.flushdb()
    client.close()


def age(rds: Any) -> None:
    for row in rds.xpending_range(daily_lists.STREAM, daily_lists.GROUP, "-", "+", 100):
        rds.xclaim(
            daily_lists.STREAM,
            daily_lists.GROUP,
            "daily-single",
            0,
            [row["message_id"]],
            idle=60001,
        )


def batch_status(e: Any, bid: uuid.UUID) -> Any:
    with e.owner.connect() as conn:
        return conn.execute(select(batches).where(batches.c.id == bid)).one()


@pytest.mark.parametrize("point", ["between", "after_claim"])
@pytest.mark.parametrize("enforce", [True, False])
def test_tb102g_each_endpoint_pause_preserves_busy_and_resumes_once(
    env: Any, stream: Any, monkeypatch: Any, point: str, enforce: bool
) -> None:
    e, rds = env, stream
    e.settings = baseline.mode(e.settings, enforce)
    bid = previous.batch(e)
    pause, claim = e.pause, Permit.claim
    inject = [True]

    def wait(seconds: float) -> None:
        pause(seconds)
        if point == "between" and inject[0]:
            inject[0] = False
            rds.set("ingest:paused", "1")

    def claim_at(self: Any, path: str) -> None:
        claim(self, path)
        if point == "after_claim" and inject[0]:
            inject[0] = False
            rds.set("ingest:paused", "1")

    e.pause = wait
    monkeypatch.setattr(Permit, "claim", claim_at)
    assert daily_delivery.publish_pending(e.worker, rds, now=e.clock[0]) == 1
    assert invoke_tick(e, rds, monkeypatch) == 0
    assert len(e.calls) == int(point == "between")
    assert batch_status(e, bid).status == "requested"
    assert len(batch_status(e, bid).datasets) == int(point == "between")
    assert rds.xpending(daily_lists.STREAM, daily_lists.GROUP)["pending"] == 1
    assert rds.llen("jobs:worker") == 0
    assert len(json.loads(e.counter.read_text())["records"]) == int(point == "between")
    assert list(e.root.glob("unsent-*.json")) == []
    assert daily_delivery.publish_pending(e.worker, rds, now=e.clock[0]) == 0
    assert rds.xlen(daily_lists.STREAM) == 1
    rds.delete("ingest:paused")
    age(rds)
    assert invoke_tick(e, rds, monkeypatch) == 1
    assert len(e.calls) == 3
    assert batch_status(e, bid).status == "fetched"
    assert rds.xpending(daily_lists.STREAM, daily_lists.GROUP)["pending"] == 0
    assert rds.get(pending_key(bid)) is None


@pytest.mark.parametrize("fault", [errno.EACCES, errno.EIO])
def test_tb102g_cleanup_lstat_failure_two_ticks_never_ack_or_fail(
    env: Any, stream: Any, monkeypatch: Any, fault: int
) -> None:
    e, rds = env, stream
    bid = previous.batch(e)
    proof = e.root / f"unsent-{uuid.uuid5(bid, 'hslt_list')}.json"
    original = Path.lstat
    blocked = [True]

    def lstat(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path == proof and blocked[0]:
            raise OSError(fault, "synthetic cleanup lstat I/O")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", lstat)
    assert daily_delivery.publish_pending(e.worker, rds, now=e.clock[0]) == 1
    for _ in range(2):
        if rds.xinfo_groups(daily_lists.STREAM):
            age(rds)
        assert invoke_tick(e, rds, monkeypatch) == 0
        assert batch_status(e, bid).status == "requested"
        assert e.calls == []
        assert rds.llen("jobs:worker") == 0
    assert rds.xpending(daily_lists.STREAM, daily_lists.GROUP)["pending"] == 1
    blocked[0] = False
    age(rds)
    assert invoke_tick(e, rds, monkeypatch) == 1
    assert len(e.calls) == 3


class Crash(BaseException):
    pass


@pytest.mark.parametrize("crash", [False, True])
@pytest.mark.parametrize("fault", ["file", "directory"])
def test_tb102g_unconfirmed_proof_requires_fsync_before_any_compensation(
    env: Any, stream: Any, monkeypatch: Any, crash: bool, fault: str
) -> None:
    e, rds = env, stream
    bid = previous.batch(e)
    proof = e.root / f"unsent-{uuid.uuid5(bid, 'hslt_list')}.json"
    sync, claim, remove_owned = os.fsync, Permit.claim, daily_lists.remove_owned
    first, fail, crashed = [True], [True], [False]

    def claim_at(self: Any, path: str) -> None:
        claim(self, path)
        if first[0]:
            first[0] = False
            raise GateClosedError("shared_control_busy")

    def sync_at(fd: int) -> None:
        path = Path(os.readlink(f"/proc/self/fd/{fd}"))
        target = path == proof if fault == "file" else path == e.root and proof.exists()
        if fail[0] and target:
            if crash and not crashed[0]:
                crashed[0] = True
                raise Crash
            raise OSError("synthetic unconfirmed proof fsync")
        sync(fd)

    monkeypatch.setattr(Permit, "claim", claim_at)
    monkeypatch.setattr(os, "fsync", sync_at)
    monkeypatch.setattr(
        daily_lists,
        "remove_owned",
        lambda path, identity: None if crashed[0] else remove_owned(path, identity),
    )
    assert daily_delivery.publish_pending(e.worker, rds, now=e.clock[0]) == 1
    if crash:
        with pytest.raises(Crash):
            invoke_tick(e, rds, monkeypatch)
    else:
        assert invoke_tick(e, rds, monkeypatch) == 0
    assert json.loads(proof.read_text())["durability"] == "unconfirmed"
    for _ in range(2):
        age(rds)
        assert invoke_tick(e, rds, monkeypatch) == 0
        assert previous.attempted(e, bid) == ["hslt_list"]
        assert len(json.loads(e.counter.read_text())["records"]) == 1
        assert MinuteLedger(e.root, e.lid).read(e.clock[0].timestamp())["inflight"] is True
        assert e.calls == []
        assert batch_status(e, bid).status == "requested"
        assert rds.llen("jobs:worker") == 0
    fail[0] = False
    monkeypatch.setattr(daily_lists, "remove_owned", remove_owned)
    age(rds)
    assert invoke_tick(e, rds, monkeypatch) == 1
    assert len(e.calls) == 3
    assert not proof.exists()
    assert len(json.loads(e.counter.read_text())["records"]) == 3


def test_tb102g_continuous_busy_scans_keep_one_stream_entry_and_pel(
    env: Any, stream: Any, monkeypatch: Any
) -> None:
    e, rds = env, stream
    bid = previous.batch(e)
    assert daily_delivery.publish_pending(e.worker, rds, now=e.clock[0]) == 1
    fd = os.open(e.root / "send-control.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        for _ in range(20):
            if rds.xinfo_groups(daily_lists.STREAM):
                age(rds)
            assert invoke_tick(e, rds, monkeypatch) == 0
            assert daily_delivery.publish_pending(e.worker, rds, now=e.clock[0]) == 0
            assert rds.xlen(daily_lists.STREAM) == 1
            assert rds.xpending(daily_lists.STREAM, daily_lists.GROUP)["pending"] == 1
            assert e.calls == []
            assert rds.pttl(pending_key(bid)) == -1
            e.pause(60)
    finally:
        os.close(fd)
    age(rds)
    assert invoke_tick(e, rds, monkeypatch) == 1
    assert len(e.calls) == 3
    assert rds.get(pending_key(bid)) is None


@pytest.mark.parametrize("loss", ["trimmed", "wrong_hint"])
def test_tb102g_db_outbox_repairs_missing_or_mismatched_hint(
    env: Any, stream: Any, loss: str
) -> None:
    e, rds = env, stream
    bid = previous.batch(e)
    assert daily_delivery.publish_pending(e.worker, rds, now=e.clock[0]) == 1
    old = rds.get(pending_key(bid))
    if loss == "trimmed":
        rds.xdel(daily_lists.STREAM, old)
    else:
        other = rds.xadd(
            daily_lists.STREAM, {"kind": daily_lists.KIND, "batch_id": str(uuid.uuid4())}
        )
        rds.set(pending_key(bid), other)
    assert daily_delivery.publish_pending(e.worker, rds, now=e.clock[0]) == 1
    current = rds.get(pending_key(bid))
    assert current != old
    assert rds.xrange(daily_lists.STREAM, current, current)[0][1][b"batch_id"] == str(bid).encode()
    assert daily_delivery.publish_pending(e.worker, rds, now=e.clock[0]) == 0
    assert e.calls == []


def test_tb102g_atomic_publish_and_stale_ack_preserve_current_hint(env: Any, stream: Any) -> None:
    e, rds = env, stream
    bid = previous.batch(e)
    with ThreadPoolExecutor(max_workers=4) as workers:
        sent = list(
            workers.map(
                lambda _: publish_once(rds, daily_lists.STREAM, daily_lists.KIND, bid), range(12)
            )
        )
    assert sum(sent) == 1
    assert rds.xlen(daily_lists.STREAM) == 1
    rds.xgroup_create(daily_lists.STREAM, daily_lists.GROUP, id="0")
    old = rds.xreadgroup(daily_lists.GROUP, "test", {daily_lists.STREAM: ">"})[0][1][0][0]
    newer = rds.xadd(daily_lists.STREAM, {"kind": daily_lists.KIND, "batch_id": str(bid)})
    rds.set(pending_key(bid), newer)
    acknowledge(rds, daily_lists.STREAM, daily_lists.GROUP, bid, old)
    assert rds.get(pending_key(bid)) == newer
    assert rds.xpending(daily_lists.STREAM, daily_lists.GROUP)["pending"] == 0


@pytest.mark.parametrize(
    "case", ["replay", "settings_off", "held", "deleted", "unapproved", "wrong_licence"]
)
def test_tb102g_verify_permissions(env: Any, monkeypatch: Any, case: str) -> None:
    baseline.test_tb102c_verification_permission_boundaries(env, case, monkeypatch)


@pytest.mark.parametrize(
    "case", ["missing_receipt", "replay", "no_certificate", "wrong_licence", "egress"]
)
def test_tb102g_daily_permissions(env: Any, monkeypatch: Any, case: str) -> None:
    baseline.test_tb102_product_authorization_egress_not_bypassed(env, monkeypatch, case)
