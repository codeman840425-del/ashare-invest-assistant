"""T-B99 real isolated PG/ACL; synthetic HPKE/upstream/clock, no external network."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
import json
import os
import socket
import uuid
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import create_engine, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError

from app.common.errors import AppError
from app.config import Settings
from app.db.tables.licences import data_licence_events, user_data_licence_holds, user_data_licences
from app.db.tables.market import master_runs, trading_calendar
from app.db.tables.notify import notifications
from app.db.tables.ops import ingest_request_log
from app.db.tables.users import users
from app.db.tables.vendor import master_vendor_batches as batches
from app.ingest import daily_lists as ingest
from app.ingest import shared_gate, verification
from app.ingest.intents import VerifyIntent
from app.ingest.live import sync_halts
from app.ingest.shared_gate import GateClosedError, SharedGate
from app.ingest.vault import LicenceVault
from app.licences.seal import seal_licence
from app.master import daily_delivery as daily
from selfchecks.test_tb89_full_migrations import NAMES, deploy_grants, seed

PORT = int(os.environ.get("TB99_ISOLATED_PORT", "55499"))
DSN = f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/tb99_test"
ROOT = Path(__file__).resolve().parents[3]
IP = "192.0.2.10"


@pytest.fixture(scope="module")
def database() -> Any:
    if PORT not in {5432, 55499} or os.environ.get("TB99_ISOLATED_DATABASE_URL") != DSN:
        pytest.skip("explicit disposable tb99_test on its dedicated loopback port required")
    engine = create_engine(DSN, hide_parameters=True)
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
    cfg.cmd_opts = Namespace(x=["url=" + DSN])
    command.upgrade(cfg, "head")
    with engine.begin() as conn:
        assert conn.execute(text("SELECT current_database()")).scalar_one() == "tb99_test"
        deploy_grants(conn)
        seed(conn)
    counter = [0]
    yield engine, counter
    engine.dispose()


@pytest.fixture
def env(database: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    owner_engine, counter = database
    original = socket.socket.connect

    def local_only(sock: Any, address: Any) -> Any:
        assert address[:2] in {("127.0.0.1", PORT), ("127.0.0.1", 6380)}, (
            "external network forbidden"
        )
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)
    counter[0] += 1
    day = dt.date(2031, 1, 2) + dt.timedelta(days=counter[0])
    clock = [dt.datetime.combine(day, dt.time(18), dt.timezone(dt.timedelta(hours=8)))]
    user, lid, admin = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    key = X25519PrivateKey.generate()
    plaintext = "synthetic-" + uuid.uuid4().hex
    with owner_engine.begin() as conn:
        for ident, role in ((user, "user"), (admin, "admin")):
            conn.execute(
                insert(users).values(
                    id=ident,
                    username="tb99_" + ident.hex[:10],
                    role=role,
                    status="approved",
                    password_hash=uuid.uuid4().hex,
                )
            )
        conn.execute(
            insert(user_data_licences).values(
                id=lid,
                user_id=user,
                provider="mairui",
                ciphertext=seal_licence(
                    key.public_key(), plaintext, user_id=user, row_id=lid, key_version=1
                ),
                licence_hmac=uuid.uuid4().bytes + uuid.uuid4().bytes,
                seal_key_version=1,
                tier="free",
                status="active",
            )
        )
        conn.execute(insert(trading_calendar).values(date=day, is_open=True))
    collector = create_engine(DSN.replace("postgres@", "aia_ingest@"), hide_parameters=True)
    worker = create_engine(DSN.replace("postgres@", "aia_api@"), hide_parameters=True)
    settings = Settings(_env_file=None, app_env="test", data_licence_settings_enabled=True)
    grant = daily.Grant(
        user,
        lid,
        uuid.uuid4(),
        clock[0] - dt.timedelta(days=1),
        clock[0] + dt.timedelta(days=1),
        "synthetic-receipt",
    )
    root = tmp_path / "shared"
    root.mkdir(mode=0o700)
    (root / "policy.json").write_text(
        json.dumps(
            {
                "schema": "mairui-shared/v1",
                "egress_ip": IP,
                "licences": {str(lid): {"per_minute_limit": 150}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MAIRUI_MODE", "live")
    monkeypatch.setenv("MAIRUI_SHARED_STATE_DIR", str(root))
    monkeypatch.setenv("MAIRUI_SOURCE_LICENCE_ID", str(lid))
    monkeypatch.setattr(daily, "read_grant", lambda: grant)
    monkeypatch.setattr(ingest, "read_grant", lambda: grant)
    from app.ingest.verification_grants import VerificationGrant

    verification_grant = VerificationGrant(user, lid, uuid.uuid4(), grant.start, grant.end)
    monkeypatch.setattr(verification, "read_grant", lambda: verification_grant)
    monkeypatch.setattr(verification, "send_paused", lambda _: False)
    monkeypatch.setattr(ingest, "send_paused", lambda _: False)
    monkeypatch.setattr(LicenceVault, "from_secrets", classmethod(lambda _: LicenceVault({1: key})))
    monkeypatch.setattr(shared_gate, "time", SimpleNamespace(time=lambda: clock[0].timestamp()))
    calls, waits = [], []

    def pause(seconds: float) -> None:
        waits.append(seconds)
        clock[0] += dt.timedelta(seconds=seconds)

    def wire(path: str, value: str) -> Any:
        assert value == plaintext
        state = json.loads(
            SharedGate(root, lid, "product_daily").state_path.read_text(encoding="utf-8")
        )
        assert state["inflight"] is True
        calls.append((path, clock[0]))
        return 200, [{"dm": code[:6], "mc": name} for code, name in NAMES.items()]

    yield SimpleNamespace(
        owner=owner_engine,
        worker=worker,
        collector=collector,
        settings=settings,
        user=user,
        lid=lid,
        admin=admin,
        grant=grant,
        verification_grant=verification_grant,
        root=root,
        clock=clock,
        day=day,
        temp=tmp_path / "daily.tmp",
        stop=tmp_path / "legacy-STOP",
        halt=tmp_path / "legacy-HALTED",
        calls=calls,
        waits=waits,
        pause=pause,
        wire=wire,
        plaintext=plaintext,
        seal_key=key,
    )
    collector.dispose()
    worker.dispose()


def batch(e: Any) -> uuid.UUID:
    with e.worker.begin() as conn:
        bid = daily.request(conn, e.grant, e.clock[0])
    assert bid is not None
    return bid


def run(e: Any, bid: uuid.UUID, **kwargs: Any) -> str:
    return ingest.process(
        e.collector,
        bid,
        e.grant,
        clock=lambda: e.clock[0],
        upstream=kwargs.pop("upstream", e.wire),
        temp=e.temp,
        stop=e.stop,
        halt=e.halt,
        pause=kwargs.pop("pause", e.pause),
        settings=e.settings,
        egress=lambda: IP,
        **kwargs,
    )


def attempted(e: Any, bid: uuid.UUID) -> Any:
    with e.owner.connect() as conn:
        return conn.execute(
            select(master_runs.c.stats)
            .join(batches, batches.c.master_run_id == master_runs.c.id)
            .where(batches.c.id == bid)
        ).scalar_one()["attempted"]


def test_daily_three_order_interval_and_no_fourth_request(env: Any) -> None:
    e = env
    bid = batch(e)
    assert run(e, bid) == "fetched"
    assert [row[0] for row in e.calls] == ["/hslt/list/", "/bj/list/all/", "/kc/list/all/"]
    assert all(
        (right[1] - left[1]).total_seconds() >= 60
        for left, right in zip(e.calls, e.calls[1:], strict=False)
    )
    assert len(attempted(e, bid)) == 3
    assert run(e, bid) == "noop"
    assert len(e.calls) == 3
    assert not e.temp.exists()


@pytest.mark.parametrize("case", ["early", "closed", "unknown", "next_day", "deadline"])
def test_window_failures_make_zero_http(env: Any, case: str) -> None:
    e = env
    if case == "next_day":
        bid = batch(e)
        e.clock[0] += dt.timedelta(days=1)
        assert run(e, bid) == "expired"
    else:
        if case == "early":
            e.clock[0] -= dt.timedelta(seconds=1)
        elif case == "deadline":
            e.clock[0] = e.clock[0].replace(hour=23, minute=59, second=59)
        else:
            with e.owner.begin() as conn:
                if case == "unknown":
                    conn.execute(trading_calendar.delete().where(trading_calendar.c.date == e.day))
                else:
                    conn.execute(
                        update(trading_calendar)
                        .where(trading_calendar.c.date == e.day)
                        .values(is_open=False)
                    )
        if case == "unknown":
            with e.worker.begin() as conn, pytest.raises(AppError) as error:
                daily.request(conn, e.grant, e.clock[0])
            assert error.value.details == {"issue": "CALENDAR_NOT_COVERED"}
        else:
            with e.worker.begin() as conn:
                assert daily.request(conn, e.grant, e.clock[0]) is None
    assert e.calls == []
    assert not e.temp.exists()


@pytest.mark.parametrize("source", ["probe_tb05", "probe_tb86"])
def test_probe_lease_blocks_product_then_product_blocks_probe(env: Any, source: str) -> None:
    e = env
    bid = batch(e)
    with SharedGate(e.root, e.lid, source):
        assert run(e, bid) == "busy"
        assert attempted(e, bid) == []
        assert e.calls == []
    with SharedGate(e.root, e.lid, "product_daily"), pytest.raises(GateClosedError, match="busy"):
        SharedGate(e.root, e.lid, source).acquire()
    assert run(e, bid) == "fetched"


@pytest.mark.parametrize(
    "upstream", [(429, {}), (200, {"error": "103: synthetic"}), (200, "429: synthetic")]
)
def test_product_limit_latches_probe_and_deduplicates_notices(env: Any, upstream: Any) -> None:
    e = env
    bid = batch(e)
    calls = []

    def limited(path: str, value: str) -> Any:
        calls.append(path)
        return upstream

    assert run(e, bid, upstream=limited) == "failed"
    assert len(calls) == len(attempted(e, bid)) == 1
    for source in ("probe_tb05", "probe_tb86", "product_daily"):
        with pytest.raises(GateClosedError, match="halted"):
            SharedGate(e.root, e.lid, source).acquire()

    class RedisSink:
        def eval(self, *args: Any) -> str:
            return "1"

    sync_halts(e.collector, e.settings, RedisSink(), e.root)
    sync_halts(e.collector, e.settings, RedisSink(), e.root)
    with e.owner.connect() as conn:
        row = conn.execute(
            select(user_data_licences.c.status, user_data_licences.c.paused_until).where(
                user_data_licences.c.id == e.lid
            )
        ).one()
        assert row.status == "ip_limited"
        assert row.paused_until == e.clock[0] + dt.timedelta(seconds=120)
        assert (
            conn.execute(
                select(func.count())
                .select_from(data_licence_events)
                .where(
                    data_licence_events.c.licence_id == e.lid,
                    data_licence_events.c.event == "ip_limited",
                )
            ).scalar_one()
            == 1
        )
        assert (
            conn.execute(
                select(func.count())
                .select_from(notifications)
                .where(notifications.c.user_id.in_([e.user, e.admin]))
            ).scalar_one()
            == 2
        )
    e.clock[0] += dt.timedelta(hours=2)
    with pytest.raises(GateClosedError, match="halted"):
        SharedGate(e.root, e.lid, "product_daily").acquire()


def test_stop_during_wait_and_uncertain_transport_never_retry(env: Any) -> None:
    e = env
    bid = batch(e)

    def stop_wait(seconds: float) -> None:
        e.pause(seconds)
        (e.root / "STOP").touch()

    assert run(e, bid, pause=stop_wait) == "failed"
    assert len(e.calls) == len(attempted(e, bid)) == 1
    assert run(e, bid) == "busy"
    assert not e.temp.exists()


def test_daily_uncertain_transport_preserves_reservation_and_never_retries(env: Any) -> None:
    e = env
    bid = batch(e)
    calls = []

    def uncertain(path: str, secret: str) -> Any:
        calls.append(path)
        raise TimeoutError("synthetic failure")

    assert run(e, bid, upstream=uncertain) == "failed"
    assert len(calls) == len(attempted(e, bid)) == 1
    assert run(e, bid, upstream=uncertain) == "busy"
    assert (e.root / "single-egress.lease.json").exists()
    assert shared_gate.bound_halt(e.root, e.lid).exists()
    assert not e.temp.exists()


def test_verification_is_owned_durable_and_separate_from_three_list_calls(env: Any) -> None:
    e = env
    with e.owner.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(status="pending_verification")
        )
    intent = VerifyIntent(e.lid, uuid.uuid4())
    calls = []

    def verify_wire(path: str, secret: str) -> Any:
        assert secret == e.plaintext
        calls.append(path)
        return 200, [{"date": str(e.day)}]

    assert (
        verification.process(
            e.collector,
            e.settings,
            intent,
            clock=lambda: e.clock[0],
            upstream=verify_wire,
            egress=lambda: IP,
        )
        == "verified"
    )
    assert calls == [f"/tcalendar/list/{e.day.year}/"]
    assert (
        verification.process(
            e.collector,
            e.settings,
            intent,
            clock=lambda: e.clock[0],
            upstream=verify_wire,
            egress=lambda: IP,
        )
        == "already_attempted"
    )
    with e.owner.connect() as conn:
        assert (
            conn.execute(
                select(user_data_licences.c.status).where(user_data_licences.c.id == e.lid)
            ).scalar_one()
            == "active"
        )
        assert (
            conn.execute(
                select(func.count())
                .select_from(ingest_request_log)
                .where(ingest_request_log.c.licence_id == e.lid)
            ).scalar_one()
            == 1
        )
    assert run(e, batch(e)) == "fetched"
    assert (
        len(e.calls) == 3
    )  # Verification is 1 additional request, never taken from the list budget.
    assert e.waits[0] >= 60


@pytest.mark.parametrize(
    ("code", "status"),
    [("101", "quota_exceeded"), ("102", "invalid"), ("503", "pending_verification")],
)
def test_verification_preserves_existing_quota_invalid_and_backoff_rules(
    env: Any, code: str, status: str
) -> None:
    e = env
    with e.owner.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(status="pending_verification")
        )
    calls = []

    def upstream(path: str, secret: str) -> Any:
        calls.append(path)
        return (503, None) if code == "503" else (200, {"error": code})

    result = verification.process(
        e.collector,
        e.settings,
        VerifyIntent(e.lid, uuid.uuid4()),
        clock=lambda: e.clock[0],
        upstream=upstream,
        egress=lambda: IP,
    )
    assert result == "failed"
    assert len(calls) == 1
    with e.owner.connect() as conn:
        row = conn.execute(select(user_data_licences).where(user_data_licences.c.id == e.lid)).one()
        assert row.status == status
        assert row.last_error_code == code
        if code != "102":
            assert row.paused_until > e.clock[0]
        assert row.consecutive_failures == int(code == "503")


@pytest.mark.parametrize(
    "case", ["replay", "settings_off", "held", "deleted", "unapproved", "wrong_licence"]
)
def test_verification_permission_failures_do_not_read_secret(
    env: Any, case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = env
    lid = e.lid
    if case == "replay":
        monkeypatch.setenv("MAIRUI_MODE", "replay")
    elif case == "settings_off":
        e.settings = e.settings.model_copy(update={"data_licence_settings_enabled": False})
    elif case == "wrong_licence":
        lid = uuid.uuid4()
    else:
        with e.owner.begin() as conn:
            if case == "held":
                conn.execute(insert(user_data_licence_holds).values(user_id=e.user))
            elif case == "deleted":
                conn.execute(
                    update(user_data_licences)
                    .where(user_data_licences.c.id == e.lid)
                    .values(deleted_at=e.clock[0], ciphertext=None, licence_hmac=None)
                )
            else:
                conn.execute(update(users).where(users.c.id == e.user).values(status="pending"))

    def forbidden(*args: Any) -> Any:
        pytest.fail("permission failure must not read a credential or issue HTTP")

    result = verification.process(
        e.collector,
        e.settings,
        VerifyIntent(lid, uuid.uuid4()),
        clock=lambda: e.clock[0],
        upstream=forbidden,
        egress=forbidden,
        secret_loader=forbidden,
    )
    assert result in {"closed", "unavailable", "busy_or_closed", "authorization_unavailable"}
    with e.worker.connect() as conn, pytest.raises(DBAPIError):
        conn.execute(select(user_data_licences.c.ciphertext))


@pytest.fixture
def redis_sink(env: Any) -> Any:
    import redis

    url = "redis://127.0.0.1:6380/15"
    if os.environ.get("TB99_ISOLATED_REDIS_URL") != url:
        pytest.skip("explicit disposable T-B99 Redis required")
    client = redis.Redis.from_url(url)
    assert client.ping()
    client.delete(verification.STREAM)
    yield client
    client.delete(verification.STREAM)
    client.close()


def test_probe_waiting_batch_expires_without_any_http(env: Any, redis_sink: Any) -> None:
    e, rds = env, redis_sink
    bid = batch(e)
    with SharedGate(e.root, e.lid, "probe_tb05"):
        assert run(e, bid) == "busy"
        e.clock[0] += dt.timedelta(days=1)
        daily.publish_pending(e.worker, rds, now=e.clock[0])
        with e.owner.connect() as conn:
            assert (
                conn.execute(select(batches.c.status).where(batches.c.id == bid)).scalar_one()
                == "expired"
            )
    assert run(e, bid) == "noop"
    assert e.calls == []
    assert attempted(e, bid) == []
    assert all(
        fields.get(b"batch_id") != str(bid).encode() for _, fields in rds.xrange(daily.STREAM)
    )


@pytest.mark.parametrize("delivery", ["stream", "fallback", "pending"])
def test_verification_real_redis_consumer_and_fallback_are_once_only(
    env: Any, redis_sink: Any, delivery: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.licences.service import enqueue_verify

    e, rds = env, redis_sink
    with e.owner.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(status="pending_verification", status_changed_at=e.clock[0])
        )
    token = uuid.uuid4()
    calls = []
    real_process = verification.process

    def upstream(path: str, secret: str) -> Any:
        assert secret == e.plaintext
        calls.append(path)
        return 200, [{"date": str(e.day)}]

    def execute(engine: Any, settings: Any, intent: Any) -> str:
        return real_process(
            engine,
            settings,
            intent,
            clock=lambda: e.clock[0],
            upstream=upstream,
            egress=lambda: IP,
        )

    monkeypatch.setattr(verification, "process", execute)
    if delivery != "fallback":
        enqueue_verify(rds, licence_id=e.lid, verification_id=token)
    if delivery == "pending":
        rds.xgroup_create(verification.STREAM, verification.GROUP, id="0")
        messages = rds.xreadgroup(verification.GROUP, "old", {verification.STREAM: ">"})
        mid = messages[0][1][0][0]
        assert verification.tick(e.collector, rds, e.settings) == 0
        assert calls == []  # Recent pending stream ownership forbids DB fallback.
        rds.xclaim(verification.STREAM, verification.GROUP, "old", 0, [mid], idle=60001)
    assert verification.tick(e.collector, rds, e.settings) == 1
    assert verification.tick(e.collector, rds, e.settings) == 0
    assert calls == [f"/tcalendar/list/{e.day.year}/"]
    assert rds.xpending(verification.STREAM, verification.GROUP)["pending"] == 0
    bodies = rds.hvals(f"p2n06:sse:{e.user}:body")
    assert len(bodies) == 1
    event = json.loads(bodies[0])
    assert event["event"] == "data_licence"
    assert set(event["data"]) == {"status", "verification_id", "last_error_code", "at"}
    assert event["data"]["status"] == "active"
    assert e.plaintext not in bodies[0].decode()
    assert rds.hvals(f"p2n06:sse:{e.admin}:body") == []


def test_verification_unknown_transport_keeps_log_latch_and_never_falls_back(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.licences.service import enqueue_verify

    e, rds = env, redis_sink
    with e.owner.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == e.lid)
            .values(status="pending_verification", status_changed_at=e.clock[0])
        )
    calls = []
    real_process = verification.process

    def failed(path: str, secret: str) -> Any:
        calls.append(path)
        raise TimeoutError("synthetic transport failure")

    def execute(engine: Any, settings: Any, intent: Any) -> str:
        return real_process(
            engine,
            settings,
            intent,
            clock=lambda: e.clock[0],
            upstream=failed,
            egress=lambda: IP,
        )

    monkeypatch.setattr(verification, "process", execute)
    enqueue_verify(rds, licence_id=e.lid, verification_id=uuid.uuid4())
    assert verification.tick(e.collector, rds, e.settings) == 1
    assert verification.tick(e.collector, rds, e.settings) == 0
    assert len(calls) == 1
    assert (e.root / "single-egress.lease.json").exists()
    assert shared_gate.bound_halt(e.root, e.lid).exists()
    with e.owner.connect() as conn:
        row = conn.execute(select(user_data_licences).where(user_data_licences.c.id == e.lid)).one()
        assert row.last_error_code == "network"
        assert row.consecutive_failures == 1
        assert row.paused_until > e.clock[0]
        assert (
            conn.execute(
                select(func.count())
                .select_from(ingest_request_log)
                .where(
                    ingest_request_log.c.licence_id == e.lid,
                )
            ).scalar_one()
            == 1
        )


def test_verification_malformed_stream_message_is_acknowledged_without_http(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e, rds = env, redis_sink
    rds.xadd(verification.STREAM, {"kind": "verify_licence", "licence_id": "bad"})

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("malformed intent must not reach verification")

    monkeypatch.setattr(verification, "process", forbidden)
    assert verification.tick(e.collector, rds, e.settings) == 0
    assert rds.xpending(verification.STREAM, verification.GROUP)["pending"] == 0


@pytest.mark.parametrize(("mode", "paused"), [("replay", False), ("live", True), ("live", False)])
def test_worker_heartbeat_dispatch_respects_replay_and_pause(
    env: Any, redis_sink: Any, monkeypatch: pytest.MonkeyPatch, mode: str, paused: bool
) -> None:
    from pydantic import SecretStr

    from app.workers import ingest as worker

    e, rds = env, redis_sink
    settings = e.settings.model_copy(
        update={
            "database_url": SecretStr(DSN.replace("postgres@", "aia_ingest@")),
            "redis_url": "redis://127.0.0.1:6380/15",
        }
    )
    monkeypatch.setenv("MAIRUI_MODE", mode)
    rds.delete(settings.ingest_paused_key)
    if paused:
        rds.set(settings.ingest_paused_key, "1")
    calls = []
    monkeypatch.setattr(verification, "tick", lambda *a: calls.append("verify"))
    monkeypatch.setattr(ingest, "tick", lambda *a, **kw: calls.append("daily"))
    try:
        worker.write_heartbeat(settings)
        assert rds.exists(settings.ingest_heartbeat_key)
        assert calls == (["verify", "daily"] if mode == "live" and not paused else [])
    finally:
        rds.delete(settings.ingest_paused_key)
