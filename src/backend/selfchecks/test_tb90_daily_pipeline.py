"""Direct B90 integration only: real isolated PG roles, Redis stream and histories.

Upstream/clock/HPKE source use synthetic in-memory seams. No final product mocks,
real credentials, actual external requests or production authorization receipts.
Dedicated containers must be provisioned explicitly; no auto-start/live fixtures.
"""

# ruff: noqa: S101, S108, ANN401
from __future__ import annotations

import datetime as dt
import json
import os
import secrets
import socket
import uuid
from argparse import Namespace
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
import redis
from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy import create_engine, func, insert, select, text, update
from sqlalchemy.exc import ProgrammingError

from app.config import Settings
from app.db.tables.licences import user_data_licences
from app.db.tables.market import master_runs, master_snapshots, trading_calendar
from app.db.tables.notify import notifications
from app.db.tables.users import users
from app.db.tables.vendor import master_vendor_batches as batches
from app.ingest import daily_lists as ingest

# Bound before any monkeypatch so multi-run_synthetic tests wrap the real body.
_REAL_PROCESS = ingest.process
from app.ingest.vault import LicenceVault
from app.licences.seal import seal_licence
from app.main import create_app
from app.master import daily_delivery as daily
from app.master.mairui_snapshot import latest_visible_flags, read_flags
from app.master.vendor import sweep_batches
from app.workers import ingest as ingest_worker
from app.workers import jobs

ROOT = Path(__file__).resolve().parents[2]
from selfchecks.test_tb89_full_migrations import AT, CODES, DAY, NAMES, ROOT, deploy_grants, seed

SOCKET = "/tmp/tb90-pg-socket"
REDIS = "unix:///tmp/tb90-redis/redis.sock?db=0"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    original = socket.socket.connect

    def guarded(sock: socket.socket, address: Any) -> Any:
        assert sock.family == socket.AF_UNIX, "B90 permits dedicated Unix sockets only"
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture
def database() -> Iterator[tuple[str, str]]:
    assert Path(SOCKET + "/.s.PGSQL.5432").exists()
    name = "tb90_" + uuid.uuid4().hex
    url = "postgresql+psycopg://postgres@/" + name + "?host=" + SOCKET
    with psycopg.connect(dbname="postgres", user="postgres", host=SOCKET, autocommit=True) as admin:
        assert admin.execute("SHOW listen_addresses").fetchone() == ("",)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            cfg = Config()
            cfg.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
            cfg.cmd_opts = Namespace(x=["url=" + url])
            command.upgrade(cfg, "head")
            owner = create_engine(url)
            with owner.begin() as conn:
                deploy_grants(conn)
            owner.dispose()
            yield name, url
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def env(
    database: tuple[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Any]:
    _, url = database
    owner = create_engine(url)
    worker = create_engine(url.replace("postgres@", "aia_api@"))
    collector = create_engine(url.replace("postgres@", "aia_ingest@"))
    user, lid = uuid.uuid4(), uuid.uuid4()
    key = X25519PrivateKey.generate()
    synthetic = secrets.token_urlsafe(16)
    sealed = seal_licence(key.public_key(), synthetic, user_id=user, row_id=lid, key_version=1)
    monkeypatch.setattr(
        LicenceVault, "from_secrets", classmethod(lambda cls: LicenceVault({1: key}))
    )
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=SecretStr(url.replace("postgres@", "aia_api@")),
        redis_url=REDIS,
        master_snapshot_path=tmp_path,
    )
    grant = daily.Grant(
        user,
        lid,
        uuid.uuid4(),
        AT - dt.timedelta(days=1),
        AT + dt.timedelta(days=10),
        "synthetic-receipt-digest",
    )
    with owner.begin() as conn:
        seed(conn)
        for offset in range(-1, 11):
            conn.execute(
                text(
                    "INSERT INTO market.trading_calendar(date,is_open) VALUES(:d,true) "
                    "ON CONFLICT(date) DO UPDATE SET is_open=true"
                ),
                {"d": DAY + dt.timedelta(days=offset)},
            )
        conn.execute(
            insert(users).values(
                id=user,
                username="synthetic_" + user.hex[:12],
                password_hash=secrets.token_urlsafe(32),
                role="user",
                status="approved",
            )
        )
        conn.execute(
            insert(user_data_licences).values(
                id=lid,
                user_id=user,
                ciphertext=sealed,
                licence_hmac=secrets.token_bytes(32),
                seal_key_version=1,
                tier="free",
                status="active",
            )
        )
    rds = redis.Redis.from_url(REDIS)
    # This Redis is a newly created dedicated network=none instance, never shared.
    rds.flushdb()
    monkeypatch.setattr(jobs, "_engine", lambda _: worker)
    monkeypatch.setattr(jobs, "_redis", lambda _: rds)
    monkeypatch.setattr(jobs, "_now", lambda: AT)
    monkeypatch.setattr(daily, "read_grant", lambda: grant)
    monkeypatch.setattr(ingest, "read_grant", lambda: grant)
    # T-B116b / T-T51: collection selfchecks use fake transport; open the seam for
    # daily.request (new_batch) AND ingest.process. Do NOT change DAILY_HTTP_LIMIT /
    # live_budget_issue production body — test_tb90_http_budget keeps asserting the gate.
    monkeypatch.setattr(daily, "live_budget_issue", lambda: None)
    monkeypatch.setattr(ingest, "live_budget_issue", lambda: None)
    yield SimpleNamespace(
        owner=owner,
        worker=worker,
        collector=collector,
        settings=settings,
        grant=grant,
        rds=rds,
        root=tmp_path,
        cfg=settings.business.securities.master,
        user=user,
        lid=lid,
        synthetic=synthetic,
    )
    rds.close()
    for engine in (owner, worker, collector):
        engine.dispose()


def new_batch(e: Any) -> uuid.UUID:
    with e.worker.begin() as conn:
        assert conn.execute(text("SELECT session_user")).scalar_one() == "aia_api"
        bid = daily.request(conn, e.grant, AT)
        assert bid is not None
        return bid


def run_synthetic(
    e: Any,
    bid: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: Any = None,
    stop_after: bool = False,
    clock: Any = None,
    preserve_existing: bool = False,
    deployed_entry: bool = False,
) -> tuple[str, list[str], list[float]]:
    calls: list[str] = []
    waits: list[float] = []
    secret = e.synthetic
    stop, halt, temp = e.root / "STOP", e.root / "HALTED", e.root / "daily.tmp"

    def loader(engine: Any, lid: uuid.UUID) -> str:
        assert lid == e.lid
        with engine.connect() as conn:
            assert conn.execute(text("SELECT session_user")).scalar_one() == "aia_ingest"
        return ingest.credential(engine, lid)

    def wire(path: str, value: str) -> tuple[int, object]:
        assert value == secret
        assert temp.stat().st_mode & 0o777 == 0o600
        with e.owner.connect() as conn:
            parent = conn.execute(
                select(master_runs.c.stats)
                .join(batches, batches.c.master_run_id == master_runs.c.id)
                .where(batches.c.id == bid)
            ).scalar_one()
            assert len(parent["attempted"]) == len(calls) + 1  # committed BEFORE HTTP seam
        calls.append(path)
        if stop_after:
            stop.touch()
        if response is not None:
            return response
        return 200, [{"dm": code[:6], "mc": name} for code, name in NAMES.items()]

    def injected(engine: Any, ident: uuid.UUID, grant: daily.Grant | None, **_: Any) -> str:
        # Always call the real process (not a prior injected wrapper from an earlier
        # run_synthetic in the same test — those ignore new wire/temp/halt closures).
        return _REAL_PROCESS(
            engine,
            ident,
            grant,
            clock=clock or (lambda: AT),
            upstream=wire,
            secret_loader=loader,
            temp=temp,
            stop=stop,
            halt=halt,
            pause=waits.append,
        )

    monkeypatch.setattr(ingest, "process", injected)
    # T-B116/b: collection seam uses egress+IngestCore. Budget already opened in env for
    # daily.request; keep ingest patch here for defense in depth. DAILY_HTTP_LIMIT unchanged.
    import yaml
    from app.config_files import IngestConfig
    from app.ingest.core import IngestCore
    from app.ingest import runtime

    cfg = IngestConfig.model_validate(
        yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
    ).licences
    monkeypatch.setattr(daily, "live_budget_issue", lambda: None)
    monkeypatch.setattr(ingest, "live_budget_issue", lambda: None)
    runtime.set_ingest_core(IngestCore(cfg, engine=e.collector))
    daily.publish_pending(e.worker, e.rds)
    if deployed_entry:
        original_tick = ingest.tick

        def fixed_clock_tick(engine: Any, rds: Any, **_: Any) -> int:
            return original_tick(engine, rds, clock=clock or (lambda: AT), pause=waits.append)

        monkeypatch.setattr(ingest, "tick", fixed_clock_tick)
        collector_settings = Settings(
            _env_file=None,
            app_env="test",
            redis_url=REDIS,
            database_url=SecretStr(str(e.collector.url)),
        )
        ingest_worker.write_heartbeat(collector_settings)
        assert e.rds.exists(collector_settings.ingest_heartbeat_key)
    else:
        ingest.tick(
            e.collector, e.rds, clock=clock or (lambda: AT), grant=e.grant, pause=waits.append
        )
    with e.owner.connect() as conn:
        status = conn.execute(select(batches.c.status).where(batches.c.id == bid)).scalar_one()
    if preserve_existing:
        assert temp.read_text() == "other-process-synthetic-file"
    else:
        assert not temp.exists()
    runtime.set_ingest_core(None)
    return status, calls, waits


def test_real_slot_stream_roles_apply_history_pit_and_replay(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = env
    assert jobs.slot_jobs(e.settings, AT - dt.timedelta(seconds=1)) == []
    assert jobs.beat_slots(e.settings, client=e.rds, now=AT) == [jobs.MAIRUI_SNAPSHOT]
    assert jobs.beat_slots(e.settings, client=e.rds, now=AT) == []
    assert jobs.worker_tick(e.settings, client=e.rds) == [(jobs.MAIRUI_SNAPSHOT, "ok")]
    with e.owner.connect() as conn:
        bid = conn.execute(select(batches.c.id)).scalar_one()
    status, calls, waits = run_synthetic(e, bid, monkeypatch, deployed_entry=True)
    assert status == "fetched"
    assert len(calls) == 3
    assert waits == [60, 60]
    # Actual worker queue consumes actual ingest-normalized DB rows, creates the
    # immutable file, snapshot and both histories; no fabricated final delivery.
    assert jobs.worker_tick(e.settings, client=e.rds) == [(daily.APPLY, "ok")]
    with e.worker.connect() as conn:
        row = conn.execute(
            select(master_snapshots).where(master_snapshots.c.source == "mairui_list")
        ).one()
        assert row.fetched_at == AT
        assert row.trade_date == DAY
        assert row.row_count == 4
        assert Path(row.raw_path).exists()
        same = latest_visible_flags(conn, CODES[0], as_of=AT + dt.timedelta(minutes=1))
        nxt = latest_visible_flags(conn, CODES[0], as_of=AT + dt.timedelta(days=1, hours=-9))
        assert same["f.is_st"] is None
        assert nxt["f.is_st"] is False
        assert nxt["f.is_delisting_period"] is False
        for table in ("security_risk_flag_history", "security_listing_status_history"):
            assert (
                conn.execute(
                    text("SELECT count(*) FROM market." + table + " WHERE snapshot_id=:id"),  # noqa: S608 - fixed internal table tuple
                    {"id": row.id},
                ).scalar_one()
                == 4
            )
        parent = conn.execute(
            select(master_runs)
            .join(batches, batches.c.master_run_id == master_runs.c.id)
            .where(batches.c.id == bid)
        ).one()
        assert len(parent.stats["attempted"]) == 3
        assert parent.finished_at == AT
    with e.worker.begin() as conn:
        expected = conn.execute(
            select(master_runs.c.stats)
            .join(batches, batches.c.master_run_id == master_runs.c.id)
            .where(batches.c.id == bid)
        ).scalar_one()["applied_run_id"]
        for _ in range(2):
            assert daily.apply_batch(conn, bid, now=AT, cfg=e.cfg, root=e.root) == expected
    assert new_batch(e) == bid
    assert daily.publish_pending(e.worker, e.rds) == 0
    assert ingest.process(e.collector, bid, e.grant, clock=lambda: AT) == "noop"
    with e.worker.begin() as conn:
        assert sweep_batches(conn, now=AT + dt.timedelta(hours=1)) == []


def test_outbox_lost_publish_recovered_and_late_apply_not_backdated(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = env
    slot = jobs.slot_jobs(e.settings, AT)[0][1]
    e.rds.set(f"{jobs.SLOT_PREFIX}{jobs.MAIRUI_SNAPSHOT}:{slot}", 1)
    # Reproduce crash after old Redis slot NX but before job enqueue. Beat now
    # persists the daily intent even when the Redis slot already exists.
    assert jobs.beat_slots(e.settings, client=e.rds, now=AT) == []
    with e.owner.connect() as conn:
        bid = conn.execute(select(batches.c.id)).scalar_one()
    # DB commit without publish is recovered by the actual periodic worker task.
    assert jobs.mairui_daily_sweep(e.settings) == 1
    status, calls, _ = run_synthetic(e, bid, monkeypatch)
    assert status == "fetched"
    assert len(calls) == 3
    e.rds.delete("jobs:worker")  # simulated crash between durable fetched and apply
    late = AT + dt.timedelta(days=1, hours=-9)
    monkeypatch.setattr(jobs, "_now", lambda: late)
    assert jobs.mairui_daily_sweep(e.settings) == 1
    assert jobs.worker_tick(e.settings, client=e.rds) == [(daily.APPLY, "ok")]
    with e.worker.connect() as conn:
        assert (
            read_flags(conn, CODES[0], DAY, as_of=late - dt.timedelta(seconds=1))["f.is_st"] is None
        )
        assert read_flags(conn, CODES[0], DAY, as_of=late)["f.is_st"] is False
        row = conn.execute(
            select(master_snapshots).where(master_snapshots.c.source == "mairui_list")
        ).one()
        assert row.trade_date == DAY
        assert row.fetched_at == AT


@pytest.mark.parametrize(
    ("status", "body"), [(103, None), (429, None), (200, {"code": 103}), (200, {"status": "429"})]
)
def test_http_and_business_limits_halt_without_retry(
    env: Any, monkeypatch: pytest.MonkeyPatch, status: int, body: Any
) -> None:
    e = env
    bid = new_batch(e)
    state, calls, _ = run_synthetic(e, bid, monkeypatch, response=(status, body))
    assert state == "failed"
    assert len(calls) == 1
    assert (e.root / "HALTED").exists()
    # Restart-local marker loss must not auto-resume a DB-persisted limit halt.
    (e.root / "HALTED").unlink()
    with e.worker.begin() as conn:
        assert daily.request(conn, e.grant, AT + dt.timedelta(days=1)) is None
    assert jobs.worker_tick(e.settings, client=e.rds) == [(daily.APPLY, "ok")]
    with e.worker.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(master_snapshots)
                .where(
                    master_snapshots.c.source == "mairui_list",
                    master_snapshots.c.parse_status == "ok",
                )
            ).scalar_one()
            == 0
        )
        assert (
            latest_visible_flags(conn, CODES[0], as_of=AT + dt.timedelta(days=1))["f.is_st"] is None
        )


@pytest.mark.parametrize(
    "mode",
    [
        "stop_before",
        "stop_after",
        "empty",
        "malformed",
        "uncertain",
        "unauthorized",
    ],
)
def test_failures_keep_old_history_and_never_repeat_uncertain_calls(
    env: Any, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    e = env
    bid = new_batch(e)
    if mode == "stop_before":
        (e.root / "STOP").touch()
    if mode == "uncertain":
        with e.owner.begin() as conn:
            p = conn.execute(
                select(master_runs)
                .join(batches, batches.c.master_run_id == master_runs.c.id)
                .where(batches.c.id == bid)
            ).one()
            conn.execute(
                update(master_runs)
                .where(master_runs.c.id == p.id)
                .values(stats={**p.stats, "attempted": ["hslt_list"]})
            )
    if mode == "unauthorized":
        monkeypatch.setattr(ingest, "read_grant", lambda: None)
    response = (
        (200, [])
        if mode == "empty"
        else ((200, [{"bad": "synthetic"}]) if mode == "malformed" else None)
    )
    state, calls, _ = run_synthetic(
        e,
        bid,
        monkeypatch,
        response=response,
        stop_after=mode == "stop_after",
    )
    assert state == "failed"
    assert len(calls) == (1 if mode in {"stop_after", "empty", "malformed"} else 0)
    assert jobs.worker_tick(e.settings, client=e.rds) == [(daily.APPLY, "ok")]
    with e.worker.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(master_snapshots)
                .where(
                    master_snapshots.c.source == "mairui_list",
                    master_snapshots.c.parse_status == "ok",
                )
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM market.security_listing_status_history "
                    "WHERE valid_until IS NULL"
                )
            ).scalar_one()
            == 4
        )


def test_existing_temp_replaced_and_halt_preserved(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A22 前半段：HALT 在则拒绝且从不自动清除；残留 TEMP 保留。后半段改由 A32 承担。"""
    e = env
    bid = new_batch(e)
    halt, temp = e.root / "HALTED", e.root / "daily.tmp"
    temp.write_text("other-process-synthetic-file")
    temp.chmod(0o600)
    halt.write_bytes(b"limit_103_or_429")
    halt.chmod(0o600)
    # HALT path refuses before TEMP cleanup; keep planted residue for assertion below.
    state, calls, _ = run_synthetic(e, bid, monkeypatch, preserve_existing=True)
    # HALT present → refuse before HTTP; halt file must remain (never auto-cleared).
    assert state == "failed"
    assert calls == []
    assert halt.exists()
    assert halt.read_bytes() == b"limit_103_or_429"
    assert temp.read_text() == "other-process-synthetic-file"


def test_nontrading_and_authorization_missing_never_enqueue(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = env
    with e.owner.begin() as conn:
        conn.execute(
            update(trading_calendar).where(trading_calendar.c.date == DAY).values(is_open=False)
        )
    assert jobs.beat_slots(e.settings, client=e.rds, now=AT) == []
    with e.worker.begin() as conn:
        assert daily.request(conn, e.grant, AT) is None
    monkeypatch.setattr(daily, "read_grant", lambda: None)
    assert jobs.mairui_snapshot_task(e.settings, str(DAY)) == 0
    with e.owner.connect() as conn:
        assert conn.execute(select(func.count()).select_from(batches)).scalar_one() == 0


def test_temp_inode_replacement_and_receipt_permissions(tmp_path: Path) -> None:
    path = tmp_path / "credential.tmp"
    identity = ingest.temporary(path, secrets.token_urlsafe(16))
    replacement = tmp_path / "other.tmp"
    replacement.write_text("other-process-synthetic")
    replacement.replace(path)
    ingest.remove_owned(path, identity)
    assert path.read_text() == "other-process-synthetic"
    path.unlink()
    # No actual grant installed. Explicit synthetic path is server metadata only.
    receipt = tmp_path / "approval.json"
    obj = {
        "kind": daily.KIND,
        "user_id": str(uuid.uuid4()),
        "licence_id": str(uuid.uuid4()),
        "receipt_id": str(uuid.uuid4()),
        "not_before": AT.isoformat(),
        "expires_at": (AT + dt.timedelta(days=1)).isoformat(),
    }
    receipt.write_text(json.dumps(obj))
    receipt.chmod(0o644)
    assert daily.read_grant(receipt) is None
    receipt.chmod(0o444)
    if os.geteuid() == 0:
        assert daily.read_grant(receipt) is not None
    else:
        assert daily.read_grant(receipt) is None
    link = tmp_path / "symlink.json"
    link.symlink_to(receipt)
    assert daily.read_grant(link) is None


def test_deployed_role_acl_is_actual_not_assumed(env: Any) -> None:
    for engine, role in ((env.worker, "aia_api"), (env.collector, "aia_ingest")):
        with engine.connect() as conn:
            assert conn.execute(text("SELECT session_user")).scalar_one() == role
            assert not conn.execute(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            ).scalar_one()
    with env.worker.connect() as conn, pytest.raises(ProgrammingError):
        conn.execute(select(user_data_licences.c.ciphertext))
    with env.collector.connect() as conn, pytest.raises(ProgrammingError):
        conn.execute(text("SELECT * FROM market.master_vendor_list_rows"))
    with env.worker.connect() as conn:
        assert conn.execute(
            text("SELECT has_sequence_privilege(current_user,'market.master_runs_id_seq','USAGE')")
        ).scalar_one()


def test_unread_actual_auth_ownership_read_empty_and_static_route(env: Any) -> None:
    e = env
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=e.settings.database_url,
        redis_url=REDIS,
        app_master_key=SecretStr(secrets.token_urlsafe(32)),
        registration_mode="closed",
        session_cookie_secure=False,
    )
    app = create_app(settings)
    identities = []
    clients = []
    try:
        for _ in range(2):
            uid = uuid.uuid4()
            username = "tb90_" + uid.hex[:12]
            password = secrets.token_urlsafe(20) + "7a"
            with e.owner.begin() as conn:
                conn.execute(
                    insert(users).values(
                        id=uid,
                        username=username,
                        password_hash=PasswordHasher().hash(password),
                        role="user",
                        status="approved",
                    )
                )
            client = TestClient(app)
            clients.append(client)
            identities.append(uid)
            assert (
                client.post(
                    "/api/v1/auth/login", json={"username": username, "password": password}
                ).status_code
                == 200
            )
        path = "/api/v1/notifications/unread-count"
        assert clients[0].get(path).json() == {"count": 0}
        with TestClient(app) as anonymous:
            assert anonymous.get(path).status_code == 401
        with e.owner.begin() as conn:
            for uid, read in [
                (identities[0], None),
                (identities[0], AT),
                (identities[1], None),
                (identities[1], None),
            ]:
                conn.execute(
                    insert(notifications).values(
                        user_id=uid, kind="system", severity="info", title="synthetic", read_at=read
                    )
                )
        response = clients[0].get(path, params={"user_id": str(identities[1])})
        assert response.status_code == 200
        assert response.json() == {"count": 1}
        assert response.headers["cache-control"] == "private, no-store"
        assert clients[1].get(path).json() == {"count": 2}
        with e.owner.begin() as conn:
            conn.execute(
                update(notifications)
                .where(notifications.c.user_id == identities[0])
                .values(read_at=AT)
            )
        assert clients[0].get(path).json() == {"count": 0}
        schema = app.openapi()["components"]["schemas"]["UnreadCount"]
        assert schema["required"] == ["count"]
        assert schema["properties"]["count"]["type"] == "integer"
        assert schema["additionalProperties"] is False
        routes = list(app.openapi()["paths"])  # FastAPI lazy IncludedRouter is not flat.
        assert path in routes
        if "/api/v1/notifications/{id}" in routes:
            assert routes.index(path) < routes.index("/api/v1/notifications/{id}")
    finally:
        for client in clients:
            client.close()


@pytest.mark.parametrize("status", [200, 302, 103, 429, 500])
def test_egress_https_get_single_attempt_no_redirect_and_sanitized_failure(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """B-2: wire deleted; exercise egress private transport with fake HTTPSConnection."""
    assert ingest.limited(200, {"code": 103.0})
    assert ingest.limited(200, [{"error_code": "429"}])
    assert not ingest.limited(200, [{"dm": CODES[0][:6], "mc": "合成103"}])
    assert not hasattr(ingest, "wire")
    value = secrets.token_urlsafe(16)
    calls: list[str] = []
    reads: list[int] = []

    class Connection:
        def set_debuglevel(self, level: int) -> None:
            assert level == 0

        def request(self, method: str, path: str) -> None:
            calls.append(method)
            if status == 500:
                raise RuntimeError(value)

        def getresponse(self) -> Any:
            def read(limit: int) -> bytes:
                reads.append(limit)
                return b"[]"

            return SimpleNamespace(status=status, read=read)

    def connection(host: str, timeout: int) -> Connection:
        assert host == "api.mairuiapi.com"
        assert timeout > 0
        return Connection()

    import inspect

    from app.ingest import egress as eg

    # Default transport via public signature — do not name egress private attrs (S2).
    transport = inspect.signature(eg.mairui_get).parameters["transport"].default

    class _FakeSock:
        def connect(self, address: object) -> None:
            return None

        def close(self) -> None:
            closed.append(True)

    def fake_getaddrinfo(host: str, port: int, *a: object, **k: object) -> list:
        assert host == "api.mairuiapi.com"
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("203.0.113.10", port))]

    monkeypatch.setattr(eg.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(eg.socket.socket, "connect", lambda self, address: None)
    monkeypatch.setattr(eg.ssl, "create_default_context", lambda: SimpleNamespace(
        wrap_socket=lambda raw, server_hostname=None: raw
    ))
    monkeypatch.setattr(eg.http.client, "HTTPSConnection", connection)
    if status == 500:
        with pytest.raises(ingest.DailyHaltError) as caught:
            transport("/synthetic/", value)
        assert value not in str(caught.value)
        assert caught.value.__suppress_context__
    else:
        code, _ = transport("/synthetic/", value)
        assert code == status
    assert calls == ["GET"]
    if status in (103, 429):
        assert reads == []


def test_tb116d_a32_existing_temp_new_trade_date(
    env: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A32（对齐 T-T55）：用新交易日触发第二次批次（不用 owner 把 failed 改回 requested）；
    残留普通文件被替换为 0600 并在成功后清掉；非普通文件 temp_path_not_regular。
    """
    # Unit path first: non-regular leftover (fifo is not unlinked).
    fifo = tmp_path / "fifo.tmp"
    os.mkfifo(fifo)
    with pytest.raises(ingest.DailyHaltError) as caught:
        ingest.temporary(fifo, secrets.token_urlsafe(16))
    assert caught.value.args[0] == "temp_path_not_regular"
    assert fifo.exists()
    assert not fifo.is_file()

    e = env
    temp = e.root / "daily.tmp"
    halt = e.root / "HALTED"
    if halt.exists():
        halt.unlink()
    temp.write_text("stale-again")
    temp.chmod(0o600)
    at2 = AT + dt.timedelta(days=1)
    with e.worker.begin() as conn:
        bid2 = daily.request(conn, e.grant, at2)
    assert bid2 is not None  # 新交易日应产生新批次（不得依赖 failed→requested）
    state, calls, _ = run_synthetic(e, bid2, monkeypatch, clock=lambda: at2)
    assert state == "fetched"
    assert len(calls) == 3
    assert not temp.exists()
