"""T-B102 actual product list process, isolated PG/roles/HPKE, synthetic transport.

Only explicit disposable DSN+cluster are allowed. No deployment/real credential
or external network. The daily dispatch is real, including inode accounting.
"""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import fcntl
import json
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, select, text, update

from app.api.v1 import admin as admin_routes
from app.api.v1 import data_licence as licence_routes
from app.auth import deps
from app.common.errors import install_exception_handlers
from app.config import get_settings
from app.db.tables.licences import user_data_licences
from app.db.tables.market import master_runs
from app.db.tables.vendor import master_vendor_batches as batches
from app.db.tables.vendor import master_vendor_list_rows as rows
from app.ingest import daily_lists, send_control
from app.ingest.shared_gate import write_stop
from selfchecks import test_tb99_daily as previous


@pytest.fixture(scope="module")
def database() -> Any:
    if os.environ.get("TB99_ISOLATED_DATABASE_URL") != previous.DSN or previous.PORT != 5432:
        pytest.skip("explicit isolated tb99_test DSN required")
    engine = create_engine(previous.DSN, hide_parameters=True)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SHOW cluster_name")).scalar_one() == "tb102-isolated"
    finally:
        engine.dispose()
    yield from previous.database.__wrapped__()


@pytest.fixture
def env(database: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: Any) -> Any:
    source = previous.env.__wrapped__(database, tmp_path, monkeypatch)
    e = next(source)
    e.counter = e.root / "daily_lists.count"
    e.counter.write_text(json.dumps({"schema": "mairui-daily/v1", "records": []}), encoding="utf-8")
    os.chmod(e.counter, 0o600)
    caplog.set_level("INFO", logger="app.ingest.send_governance")
    e.logs = caplog
    e.settings = mode(e.settings, True)

    def wire(path: str, secret: str) -> Any:
        assert secret == e.plaintext
        assert send_control.owned(e.root)
        ledger = json.loads(e.counter.read_text(encoding="utf-8"))
        assert len(ledger["records"]) == len(e.calls) + 1
        e.calls.append((path, e.clock[0]))
        return 200, [{"dm": code[:6], "mc": name} for code, name in previous.NAMES.items()]

    e.wire = wire
    yield e
    with contextlib.suppress(StopIteration):
        next(source)


def mode(settings: Any, enforce: bool) -> Any:
    ingest = settings.business.ingest
    return settings.model_copy(
        update={
            "business": settings.business.model_copy(
                update={
                    "ingest": ingest.model_copy(
                        update={
                            "send_governance": ingest.send_governance.model_copy(
                                update={"enforce": enforce}
                            )
                        }
                    )
                }
            )
        }
    )


def logged(e: Any) -> list[Any]:
    return [
        json.loads(record.getMessage().split("send_governance ", 1)[1])
        for record in e.logs.records
        if record.name == "app.ingest.send_governance"
        and '"would_block":true' in record.getMessage()
    ]


def test_tb102_product_three_order_intervals_receipt_and_no_replay(env: Any) -> None:
    e = env
    bid = previous.batch(e)
    assert previous.run(e, bid) == "fetched"
    assert [path for path, at in e.calls] == list(daily_lists.PATHS.values())
    assert len(json.loads(e.counter.read_text())["records"]) == 3
    assert all(
        (right[1] - left[1]).total_seconds() >= 60
        for left, right in zip(e.calls, e.calls[1:], strict=False)
    )
    assert previous.run(e, bid) == "noop"
    assert len(e.calls) == 3
    assert not e.temp.exists()


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_product_common_stop_strong_zero_http_or_bypass_three(
    env: Any, enforce: bool
) -> None:
    e = env
    e.settings = mode(e.settings, enforce)
    bid = previous.batch(e)
    write_stop(e.root / "STOP")
    if enforce:
        assert previous.run(e, bid) == "failed"
        assert e.calls == []
        assert len(json.loads(e.counter.read_text())["records"]) == 1
    else:

        def observing(path: str, secret: str) -> Any:
            e.calls.append(path)
            return 200, [{"dm": "600519", "mc": "synthetic"}]

        assert previous.run(e, bid, upstream=observing) == "fetched"
        assert len(e.calls) == len(json.loads(e.counter.read_text())["records"]) == 3
        assert [row["code"] for row in logged(e)] == ["bypass_stop_would_block"] * 3
    assert not e.temp.exists()
    assert e.plaintext not in e.logs.text


def test_tb102_product_daily_limit_global_across_batches(env: Any) -> None:
    e = env
    bid = previous.batch(e)
    assert previous.run(e, bid) == "fetched"
    # Another authorized logical batch cannot turn a DB row's fresh [] into a fresh day budget.
    other = uuid.uuid4()
    with e.owner.begin() as conn:
        original = conn.execute(select(batches).where(batches.c.id == bid)).one()
        p = conn.execute(
            select(master_runs).where(master_runs.c.id == original.master_run_id)
        ).one()
        new_parent = conn.execute(
            master_runs.insert()
            .values(
                trigger="beat_1800",
                started_at=e.clock[0],
                status=None,
                stats={**p.stats, "batch_id": str(other), "attempted": []},
            )
            .returning(master_runs.c.id)
        ).scalar_one()
        conn.execute(
            batches.insert().values(
                id=other,
                master_run_id=new_parent,
                source_licence_id=e.lid,
                status="requested",
                attempt=1,
                requested_at=e.clock[0],
                deadline_at=original.deadline_at,
                datasets=[],
            )
        )
    assert previous.run(e, other) == "failed"
    assert len(e.calls) == len(json.loads(e.counter.read_text())["records"]) == 3
    assert logged(e)[-1]["snapshot"]["daily_count"] == 3


@pytest.mark.parametrize("response", ["exception", "credential_echo", "limit"])
def test_tb102_product_errors_count_stop_and_preserve_redaction(env: Any, response: str) -> None:
    e = env
    bid = previous.batch(e)

    def wire(path: str, secret: str) -> Any:
        e.calls.append(path)
        if response == "exception":
            raise RuntimeError("synthetic URL/" + secret)
        if response == "credential_echo":
            return 200, [{"dm": "600519", "mc": quote(secret, safe="")}]
        return 429, None

    assert previous.run(e, bid, upstream=wire) == "failed"
    assert len(e.calls) == len(json.loads(e.counter.read_text())["records"]) == 1
    assert not e.temp.exists()
    assert e.plaintext not in e.logs.text
    assert (e.root / "STOP").exists() is (response == "limit")
    with e.owner.connect() as conn:
        assert conn.execute(select(rows).where(rows.c.batch_id == bid)).all() == []


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_product_corrupt_accounting_never_bypassed(env: Any, enforce: bool) -> None:
    e = env
    bid = previous.batch(e)
    e.counter.write_text("{truncated", encoding="utf-8")
    e.settings = mode(e.settings, enforce)
    assert previous.run(e, bid) == "failed"
    assert e.calls == []
    assert e.counter.read_text() == "{truncated"
    assert not e.temp.exists()


@pytest.mark.parametrize(
    "case", ["missing_receipt", "replay", "no_certificate", "wrong_licence", "egress"]
)
def test_tb102_product_authorization_egress_not_bypassed(
    env: Any, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    e = env
    bid = previous.batch(e)
    e.settings = mode(e.settings, False)
    if case == "missing_receipt":
        monkeypatch.setattr(daily_lists, "read_grant", lambda: None)
    elif case == "replay":
        monkeypatch.setenv("MAIRUI_MODE", "replay")
    elif case in {"no_certificate", "wrong_licence"}:
        with e.owner.begin() as conn:
            conn.execute(
                update(user_data_licences)
                .where(user_data_licences.c.id == e.lid)
                .values(
                    deleted_at=e.clock[0],
                    ciphertext=None,
                    licence_hmac=None,
                )
            )
    if case == "egress":
        result = daily_lists.process(
            e.collector,
            bid,
            e.grant,
            clock=lambda: e.clock[0],
            settings=e.settings,
            upstream=e.wire,
            temp=e.temp,
            stop=e.stop,
            halt=e.halt,
            egress=lambda: "192.0.2.11",
            secret_loader=lambda *args: pytest.fail("egress failure must precede credential load"),
        )
    else:
        result = previous.run(
            e, bid, secret_loader=lambda *args: pytest.fail("authorization failure")
        )
    assert result in {"failed", "authorization_unavailable", "live_transport_closed"}
    assert e.calls == []
    assert json.loads(e.counter.read_text())["records"] == []


def test_tb102_http_missing_session_and_nonadmin_shape_remain_404(env: Any) -> None:
    e = env
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(admin_routes.router, prefix="/admin")
    app.include_router(licence_routes.router)
    app.dependency_overrides[deps.get_engine] = lambda: e.worker
    app.dependency_overrides[deps.get_redis] = lambda: None
    app.dependency_overrides[get_settings] = lambda: e.settings
    store = type("Store", (), {"get": lambda self, token: None})()
    app.dependency_overrides[deps.get_session_store] = lambda: store

    async def request(path: str) -> int:
        statuses = []

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                statuses.append(message["status"])

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [],
                "client": ("127.0.0.1", 1),
                "server": ("127.0.0.1", 80),
            },
            receive,
            send,
        )
        return int(statuses[0])

    assert asyncio.run(request("/admin/ingest/status")) == 404
    store.get = lambda token: type("Session", (), {"user_id": str(e.user)})()
    assert asyncio.run(request("/admin/ingest/status")) == 404


@pytest.mark.parametrize("enforce", [True, False])
def test_tb102_product_window_decision_uses_governance_in_both_modes(
    env: Any, enforce: bool
) -> None:
    e = env
    bid = previous.batch(e)
    e.clock[0] -= dt.timedelta(seconds=1)
    e.settings = mode(e.settings, enforce)
    assert previous.run(e, bid) == "failed"
    assert e.calls == []
    assert json.loads(e.counter.read_text())["records"] == []
    with e.owner.connect() as conn:
        assert (
            conn.execute(select(batches.c.error_code).where(batches.c.id == bid)).scalar_one()
            == "daily_window_expired"
        )


@pytest.mark.parametrize("enforce", [True, False])
@pytest.mark.parametrize("busy", ["flock", "probe_lease"])
def test_tb102b_r4_busy_keeps_batch_and_stream_then_retries(
    env: Any,
    monkeypatch: Any,
    enforce: bool,
    busy: str,
) -> None:
    e = env
    e.settings = mode(e.settings, enforce)
    bid = previous.batch(e)
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

    monkeypatch.setattr(daily_lists, "process", process)

    rds = RetryStream({b"kind": daily_lists.KIND.encode(), b"batch_id": str(bid).encode()})
    fd = None
    lease = e.root / "single-egress.lease.json"
    try:
        if busy == "flock":
            fd = os.open(e.root / "send-control.lock", os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            lease.write_text(json.dumps({"source": "probe_f21", "token": "synthetic"}))
            os.chmod(lease, 0o600)
        assert (
            daily_lists.tick(
                e.collector,
                rds,
                clock=lambda: e.clock[0],
                grant=e.grant,
                pause=e.pause,
                settings=e.settings,
            )
            == 0
        )
        with e.owner.connect() as conn:
            b = conn.execute(select(batches).where(batches.c.id == bid)).one()
            stats = conn.execute(
                select(master_runs.c.stats).where(
                    master_runs.c.id == b.master_run_id,
                )
            ).scalar_one()
            assert b.status == "requested"
            assert b.error_code is None
            assert not stats.get("attempted")
        assert e.calls == rds.acked == rds.jobs == []
        assert json.loads(e.counter.read_text())["records"] == []
        assert not (e.root / f"{e.lid}.requests.json").exists()
        assert not e.temp.exists()
    finally:
        if fd is not None:
            os.close(fd)
        if busy == "probe_lease":
            # This exact temporary synthetic fixture was created above, never a live lease.
            assert lease.parent == e.root
            assert json.loads(lease.read_text())["source"] == "probe_f21"
            lease.unlink()
    assert (
        daily_lists.tick(
            e.collector,
            rds,
            clock=lambda: e.clock[0],
            grant=e.grant,
            pause=e.pause,
            settings=e.settings,
        )
        == 1
    )
    assert len(e.calls) == 3
    assert len(rds.acked) == len(rds.jobs) == 1
    with e.owner.connect() as conn:
        assert (
            conn.execute(select(batches.c.status).where(batches.c.id == bid)).scalar_one()
            == "fetched"
        )


class RetryStream:
    def __init__(self, fields: dict[bytes, bytes]) -> None:
        self.fields = fields
        self.acked: list[Any] = []
        self.jobs: list[Any] = []
        self.publish_hints: set[str] = set()

    def eval(self, script: str, key_count: int, *args: Any) -> int:
        from app.master.daily_stream import ACK, PUBLISH_ONCE

        assert key_count == 2
        stream, marker, first, second = args
        if script == PUBLISH_ONCE:
            if marker in self.publish_hints:
                return 0
            self.xadd(stream, {"kind": first, "batch_id": second})
            self.publish_hints.add(marker)
            return 1
        assert script == ACK
        self.xack(stream, first, second)
        self.publish_hints.discard(marker)
        return 1

    def xadd(self, *args: Any) -> None:
        raise AssertionError("this stream fixture does not publish")

    def exists(self, key: str) -> bool:
        assert key == "ingest:paused"
        return False

    def xgroup_create(self, *args: Any, **kwargs: Any) -> None:
        pass

    def xautoclaim(self, *args: Any, **kwargs: Any) -> Any:
        return b"0-0", [(b"1-0", self.fields)]

    def xack(self, *args: Any) -> None:
        self.acked.append(args)

    def lpush(self, *args: Any) -> None:
        self.jobs.append(args)


@pytest.mark.parametrize("enforce", [True, False])
@pytest.mark.parametrize("point", ["after_first", "after_reservation", "before_wire"])
def test_tb102c_busy_interleaving_resumes_without_replay_or_ack(
    env: Any,
    monkeypatch: Any,
    enforce: bool,
    point: str,
) -> None:
    from app.ingest.send_governance import Governance, Permit

    e = env
    e.settings = mode(e.settings, enforce)
    bid = previous.batch(e)
    inject = [True]
    fd: list[int] = []
    waiting = e.root / "probe-waiting.lease.json"
    real_pause = e.pause
    real_snapshot = Governance._snapshot_record
    real_claim = Permit.claim
    real_process = daily_lists.process

    def probe() -> None:
        waiting.write_text(json.dumps({"source": "probe_tb05"}))
        os.chmod(waiting, 0o600)

    def pause(seconds: float) -> None:
        real_pause(seconds)
        if inject[0] and point == "after_first":
            lock = os.open(e.root / "send-control.lock", os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fd.append(lock)
            inject[0] = False

    def snapshot(self: Any, *args: Any, **kwargs: Any) -> None:
        real_snapshot(self, *args, **kwargs)
        if inject[0] and point == "after_reservation":
            probe()
            inject[0] = False

    def claim(self: Any, path: str) -> None:
        real_claim(self, path)
        if inject[0] and point == "before_wire":
            probe()
            inject[0] = False

    def process(*args: Any, **kwargs: Any) -> str:
        upstream = (
            daily_lists.wire
            if point == "before_wire" and not e.calls and waiting.exists() is False and inject[0]
            else e.wire
        )
        return real_process(
            *args,
            **kwargs,
            upstream=upstream,
            temp=e.temp,
            stop=e.stop,
            halt=e.halt,
            egress=lambda: previous.IP,
        )

    if point == "before_wire":
        monkeypatch.setattr(
            daily_lists.http.client,
            "HTTPSConnection",
            lambda *args, **kwargs: pytest.fail("busy must precede connection"),
        )
    monkeypatch.setattr(Governance, "_snapshot_record", snapshot)
    monkeypatch.setattr(Permit, "claim", claim)
    monkeypatch.setattr(daily_lists, "process", process)
    rds = RetryStream({b"kind": daily_lists.KIND.encode(), b"batch_id": str(bid).encode()})
    try:
        assert (
            daily_lists.tick(
                e.collector,
                rds,
                clock=lambda: e.clock[0],
                grant=e.grant,
                pause=pause,
                settings=e.settings,
            )
            == 0
        )
        assert rds.acked == rds.jobs == []
        assert len(e.calls) == int(point == "after_first")
        ledger = json.loads(e.counter.read_text())["records"]
        assert len(ledger) == int(point == "after_first")
        assert all(row["finished_at"] is not None for row in ledger)
        with e.owner.connect() as conn:
            b = conn.execute(select(batches).where(batches.c.id == bid)).one()
            stats = conn.execute(
                select(master_runs.c.stats).where(master_runs.c.id == b.master_run_id)
            ).scalar_one()
            assert b.status == "requested"
            assert stats["attempted"] == (["hslt_list"] if point == "after_first" else [])
            assert len(b.datasets) == int(point == "after_first")
    finally:
        for lock in fd:
            os.close(lock)
        if waiting.exists():
            assert waiting.parent == e.root
            assert json.loads(waiting.read_text())["source"] == "probe_tb05"
            waiting.unlink()
    assert (
        daily_lists.tick(
            e.collector,
            rds,
            clock=lambda: e.clock[0],
            grant=e.grant,
            pause=real_pause,
            settings=e.settings,
        )
        == 1
    )
    assert len(e.calls) == 3
    assert [path for path, at in e.calls] == list(daily_lists.PATHS.values())
    assert len(rds.acked) == len(rds.jobs) == 1
    assert len(json.loads(e.counter.read_text())["records"]) == 3
    with e.owner.connect() as conn:
        assert len(conn.execute(select(rows).where(rows.c.batch_id == bid)).all()) == 3 * len(
            previous.NAMES
        )


@pytest.mark.parametrize("point", ["flock", "after_reservation"])
def test_tb102c_verification_lock_before_reserve_and_busy_keeps_intent(
    env: Any,
    monkeypatch: Any,
    point: str,
) -> None:
    from app.db.tables.ops import ingest_request_log
    from app.ingest import verification
    from app.ingest.intents import VerifyIntent
    from app.ingest.send_state import MinuteLedger

    e = env
    with e.owner.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(status="pending_verification")
        )
    intent = VerifyIntent(e.lid, uuid.uuid4())
    original = verification.process
    inject = [point == "after_reservation"]
    waiting = e.root / "probe-waiting.lease.json"
    reserve = MinuteLedger.reserve
    calls: list[str] = []

    def racing_reserve(self: Any, now: float) -> None:
        reserve(self, now)
        if inject[0]:
            waiting.write_text(json.dumps({"source": "probe_tb05"}))
            os.chmod(waiting, 0o600)
            inject[0] = False

    def upstream(path: str, secret: str) -> Any:
        assert send_control.owned(e.root)
        calls.append(path)
        return 200, [{"date": str(e.day)}]

    def process(*args: Any, **kwargs: Any) -> str:
        return original(
            *args, **kwargs, clock=lambda: e.clock[0], upstream=upstream, egress=lambda: previous.IP
        )

    monkeypatch.setattr(MinuteLedger, "reserve", racing_reserve)
    monkeypatch.setattr(verification, "process", process)
    monkeypatch.setattr(verification, "publish_status", lambda *args: None)
    rds = RetryStream(
        {
            b"kind": b"verify_licence",
            b"licence_id": str(e.lid).encode(),
            b"verification_id": str(intent.verification_id).encode(),
        }
    )
    fd = None
    try:
        if point == "flock":
            fd = os.open(e.root / "send-control.lock", os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verification.tick(e.collector, rds, e.settings)
        assert calls == rds.acked == []
        with e.owner.connect() as conn:
            assert (
                conn.execute(
                    select(ingest_request_log).where(
                        ingest_request_log.c.id == intent.verification_id
                    )
                ).all()
                == []
            )
        for path in e.root.glob("*.requests.json"):
            state = json.loads(path.read_text())
            assert state["calls"] == []
            assert state["inflight"] is False
        assert list(e.root.glob("*.halt.json")) == []
        assert not (e.root / "single-egress.lease.json").exists()
    finally:
        if fd is not None:
            os.close(fd)
        if waiting.exists():
            assert waiting.parent == e.root
            assert json.loads(waiting.read_text())["source"] == "probe_tb05"
            waiting.unlink()
    verification.tick(e.collector, rds, e.settings)
    assert len(calls) == len(rds.acked) == 1


@pytest.mark.parametrize(
    "case", ["replay", "settings_off", "held", "deleted", "unapproved", "wrong_licence"]
)
def test_tb102c_verification_permission_boundaries(env: Any, case: str, monkeypatch: Any) -> None:
    previous.test_verification_permission_failures_do_not_read_secret(env, case, monkeypatch)


class UnsentCrash(BaseException):
    pass


@pytest.mark.parametrize("enforce", [True, False])
@pytest.mark.parametrize("point", ["before_clear", "before_refund", "after_minute", "after_daily"])
def test_tb102d_daily_busy_crash_recovers_without_failed_ack(
    env: Any,
    monkeypatch: Any,
    enforce: bool,
    point: str,
) -> None:
    from sqlalchemy import event

    from app.ingest.send_governance import Permit
    from app.ingest.send_state import MinuteLedger

    e = env
    e.settings = mode(e.settings, enforce)
    bid = previous.batch(e)
    waiting = e.root / "probe-waiting.lease.json"
    proof = e.root / f"unsent-{uuid.uuid5(bid, 'hslt_list')}.json"
    armed = [True]
    first = [True]
    claim = Permit.claim
    cancel = MinuteLedger.cancel_unsent
    unlink = Path.unlink
    remove_owned = daily_lists.remove_owned
    real_process = daily_lists.process

    def racing_claim(self: Any, path: str) -> None:
        claim(self, path)
        if first[0]:
            waiting.write_text(json.dumps({"source": "probe_tb05"}))
            os.chmod(waiting, 0o600)

    def crash() -> None:
        armed[0] = False
        raise UnsentCrash

    def before_sql(
        conn: Any, cursor: Any, statement: str, params: Any, context: Any, many: bool
    ) -> None:
        if (
            point == "before_clear"
            and armed[0]
            and proof.exists()
            and statement.startswith("UPDATE market.master_runs")
        ):
            crash()

    def cancel_at(self: Any) -> None:
        if armed[0] and point == "before_refund":
            crash()
        cancel(self)
        if armed[0] and point == "after_minute":
            crash()

    def unlink_at(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path == proof and armed[0] and point == "after_daily":
            crash()
        return unlink(path, *args, **kwargs)

    def process(*args: Any, **kwargs: Any) -> str:
        return real_process(
            *args,
            **kwargs,
            upstream=daily_lists.wire if first[0] else e.wire,
            temp=e.temp,
            stop=e.stop,
            halt=e.halt,
            egress=lambda: previous.IP,
        )

    monkeypatch.setattr(Permit, "claim", racing_claim)
    monkeypatch.setattr(MinuteLedger, "cancel_unsent", cancel_at)
    monkeypatch.setattr(Path, "unlink", unlink_at)
    monkeypatch.setattr(
        daily_lists,
        "remove_owned",
        lambda path, identity: remove_owned(path, identity) if not first[0] else None,
    )
    monkeypatch.setattr(daily_lists, "process", process)
    event.listen(e.collector, "before_cursor_execute", before_sql)
    rds = RetryStream({b"kind": daily_lists.KIND.encode(), b"batch_id": str(bid).encode()})
    try:
        with pytest.raises(UnsentCrash):
            daily_lists.tick(
                e.collector,
                rds,
                clock=lambda: e.clock[0],
                grant=e.grant,
                pause=e.pause,
                settings=e.settings,
            )
        assert rds.acked == e.calls == []
        assert proof.is_file()
        assert e.temp.exists() is (point != "after_daily")  # Model SIGKILL skipping finally.
        with e.owner.connect() as conn:
            assert (
                conn.execute(select(batches.c.status).where(batches.c.id == bid)).scalar_one()
                == "requested"
            )
            assert previous.attempted(e, bid) == (["hslt_list"] if point == "before_clear" else [])
        assert waiting.parent == e.root
        assert json.loads(waiting.read_text())["source"] == "probe_tb05"
        waiting.unlink()
        first[0] = False
        assert (
            daily_lists.tick(
                e.collector,
                rds,
                clock=lambda: e.clock[0],
                grant=e.grant,
                pause=e.pause,
                settings=e.settings,
            )
            == 1
        )
        assert len(rds.acked) == 1
        assert len(e.calls) == len(json.loads(e.counter.read_text())["records"]) == 3
        assert not proof.exists()
        assert not e.temp.exists()
    finally:
        event.remove(e.collector, "before_cursor_execute", before_sql)


@pytest.mark.parametrize("point", ["after_minute", "before_queued_delete"])
def test_tb102d_verify_busy_crash_recovers_queued_and_owned_lease(
    env: Any,
    monkeypatch: Any,
    point: str,
) -> None:
    from sqlalchemy import event

    from app.db.tables.ops import ingest_request_log
    from app.ingest import verification
    from app.ingest.send_state import MinuteLedger

    e = env
    with e.owner.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(status="pending_verification")
        )
    vid = uuid.uuid4()
    waiting = e.root / "probe-waiting.lease.json"
    proof = e.root / f"unsent-{vid}.json"
    armed = [True]
    inject = [True]
    reserve = MinuteLedger.reserve
    cancel = MinuteLedger.cancel_unsent
    real_process = verification.process
    calls: list[str] = []

    def racing_reserve(self: Any, now: float) -> None:
        reserve(self, now)
        if inject[0]:
            waiting.write_text(json.dumps({"source": "probe_tb05"}))
            os.chmod(waiting, 0o600)
            inject[0] = False

    def cancel_at(self: Any) -> None:
        cancel(self)
        if armed[0] and point == "after_minute":
            armed[0] = False
            raise UnsentCrash

    def before_sql(
        conn: Any, cursor: Any, statement: str, params: Any, context: Any, many: bool
    ) -> None:
        if (
            armed[0]
            and point == "before_queued_delete"
            and proof.exists()
            and statement.startswith("DELETE FROM ops.ingest_request_log")
        ):
            armed[0] = False
            raise UnsentCrash

    def upstream(path: str, secret: str) -> Any:
        calls.append(path)
        return 200, [{"date": str(e.day)}]

    def process(*args: Any, **kwargs: Any) -> str:
        return real_process(
            *args, **kwargs, clock=lambda: e.clock[0], upstream=upstream, egress=lambda: previous.IP
        )

    monkeypatch.setattr(MinuteLedger, "reserve", racing_reserve)
    monkeypatch.setattr(MinuteLedger, "cancel_unsent", cancel_at)
    monkeypatch.setattr(verification, "process", process)
    monkeypatch.setattr(verification, "publish_status", lambda *args: None)
    event.listen(e.collector, "before_cursor_execute", before_sql)
    rds = RetryStream(
        {
            b"kind": b"verify_licence",
            b"licence_id": str(e.lid).encode(),
            b"verification_id": str(vid).encode(),
        }
    )
    try:
        with pytest.raises(UnsentCrash):
            verification.tick(e.collector, rds, e.settings)
        assert calls == rds.acked == []
        assert proof.is_file()
        with e.owner.connect() as conn:
            assert (
                conn.execute(
                    select(ingest_request_log.c.status).where(ingest_request_log.c.id == vid)
                ).scalar_one()
                == "dropped"
            )
        assert waiting.parent == e.root
        assert json.loads(waiting.read_text())["source"] == "probe_tb05"
        waiting.unlink()
        verification.tick(e.collector, rds, e.settings)
        assert len(calls) == len(rds.acked) == 1
        assert not proof.exists()
        assert not (e.root / "single-egress.lease.json").exists()
        with e.owner.connect() as conn:
            assert (
                conn.execute(
                    select(ingest_request_log.c.status).where(ingest_request_log.c.id == vid)
                ).scalar_one()
                == "done"
            )
    finally:
        event.remove(e.collector, "before_cursor_execute", before_sql)


@pytest.mark.parametrize("enforce", [True, False])
@pytest.mark.parametrize("point", ["deadline", "cutoff", "crossday"])
def test_tb102d_partial_busy_batch_expires_before_dispatch_and_new_day_needs_new_receipt(
    env: Any,
    monkeypatch: Any,
    enforce: bool,
    point: str,
) -> None:
    from dataclasses import replace

    from app.db.tables.market import trading_calendar
    from app.master import daily_delivery

    e = env
    e.settings = mode(e.settings, enforce)
    bid = previous.batch(e)
    fd: list[int] = []

    def pause(seconds: float) -> None:
        e.pause(seconds)
        lock = os.open(e.root / "send-control.lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd.append(lock)

    try:
        assert previous.run(e, bid, pause=pause) == "busy"
        assert len(e.calls) == 1
    finally:
        for lock in fd:
            os.close(lock)
    with e.owner.connect() as conn:
        deadline = conn.execute(
            select(batches.c.deadline_at).where(batches.c.id == bid)
        ).scalar_one()
    if point == "deadline":
        e.clock[0] = deadline
    elif point == "cutoff":
        e.clock[0] = e.clock[0].replace(hour=23, minute=59, second=59)
    else:
        e.clock[0] += dt.timedelta(days=365)
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

    monkeypatch.setattr(daily_lists, "process", process)
    rds = RetryStream({b"kind": daily_lists.KIND.encode(), b"batch_id": str(bid).encode()})
    assert (
        daily_lists.tick(
            e.collector,
            rds,
            clock=lambda: e.clock[0],
            grant=e.grant,
            pause=e.pause,
            settings=e.settings,
        )
        == 1
    )
    assert len(rds.acked) == len(e.calls) == 1
    with e.owner.connect() as conn:
        b = conn.execute(select(batches).where(batches.c.id == bid)).one()
        assert b.status == "failed"
        assert b.error_code == "daily_window_expired"
        assert len(b.datasets) == 1
        assert len(conn.execute(select(rows).where(rows.c.batch_id == bid)).all()) == len(
            previous.NAMES
        )
    if point == "crossday":
        # Synthetic new authorization is explicit; the old receipt is not renewed.
        old_grant = e.grant
        e.grant = replace(
            old_grant,
            receipt_id=uuid.uuid4(),
            start=e.clock[0] - dt.timedelta(hours=1),
            end=e.clock[0] + dt.timedelta(hours=1),
            digest="synthetic-new-day-receipt",
        )
        monkeypatch.setattr(daily_delivery, "read_grant", lambda: e.grant)
        monkeypatch.setattr(daily_lists, "read_grant", lambda: e.grant)
        with e.owner.begin() as conn:
            conn.execute(trading_calendar.insert().values(date=e.clock[0].date(), is_open=True))
        other = previous.batch(e)
        assert other != bid
        monkeypatch.setattr(daily_lists, "process", real_process)
        assert previous.run(e, other) == "fetched"
        assert len(e.calls) == len(json.loads(e.counter.read_text())["records"]) == 4


@pytest.mark.parametrize("shape", ["dangling", "symlink", "directory"])
def test_tb102d_verify_stop_is_checked_before_any_reservation(env: Any, shape: str) -> None:
    from app.db.tables.ops import ingest_request_log
    from app.ingest import verification
    from app.ingest.intents import VerifyIntent

    e = env
    stop = e.root / "STOP"
    if shape == "directory":
        stop.mkdir()
    else:
        target = e.root / "synthetic-stop"
        if shape == "symlink":
            target.write_text("synthetic stop")
        stop.symlink_to(target)

    def forbidden(*args: Any) -> Any:
        pytest.fail("STOP must precede credential, egress and HTTP")

    assert (
        verification.process(
            e.collector,
            e.settings,
            VerifyIntent(e.lid, uuid.uuid4()),
            clock=lambda: e.clock[0],
            upstream=forbidden,
            egress=forbidden,
            secret_loader=forbidden,
        )
        == "busy_or_closed"
    )
    with e.owner.connect() as conn:
        assert (
            conn.execute(
                select(ingest_request_log).where(ingest_request_log.c.licence_id == e.lid)
            ).all()
            == []
        )
    assert list(e.root.glob("*.requests.json")) == []


def test_tb102d_unknown_temporary_file_remains_busy_without_deletion(env: Any) -> None:
    e = env
    bid = previous.batch(e)
    e.temp.write_text("synthetic unknown temporary")
    os.chmod(e.temp, 0o600)
    before = e.temp.stat().st_ino
    assert previous.run(e, bid) == "busy"
    assert e.temp.stat().st_ino == before
    assert e.calls == []
    with e.owner.connect() as conn:
        assert (
            conn.execute(select(batches.c.status).where(batches.c.id == bid)).scalar_one()
            == "requested"
        )


def test_tb102d_unsafe_recovery_proof_is_not_followed_or_acked(env: Any) -> None:
    e = env
    bid = previous.batch(e)
    proof = e.root / f"unsent-{uuid.uuid5(bid, 'hslt_list')}.json"
    proof.symlink_to(e.root / "missing")
    assert previous.run(e, bid) == "busy"
    assert e.calls == []
    assert json.loads(e.counter.read_text())["records"] == []
    with e.owner.connect() as conn:
        assert (
            conn.execute(select(batches.c.status).where(batches.c.id == bid)).scalar_one()
            == "requested"
        )
