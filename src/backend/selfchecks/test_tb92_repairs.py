"""T-B92 only; dedicated Unix PG/Redis, fictional identities and deterministic inputs."""

# ruff: noqa: S101, S108, ANN401, E501
from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import json
import uuid
from argparse import Namespace
from pathlib import Path
from typing import Any

import anyio
import psycopg
import pytest
import redis
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import sql
from sqlalchemy import create_engine, insert, select, text, update
from sqlalchemy.exc import DBAPIError

from app.auth.sessions import SESSION_COOKIE, SessionStore
from app.cli.delete_user_data import build_plan, run_purge
from app.db.tables.licences import user_data_licences
from app.db.tables.market import securities
from app.db.tables.notify import notification_refs, notifications
from app.db.tables.realtime import signal_event_projections, signal_events, suggestions
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import strategies, strategy_cards, strategy_instances, strategy_versions
from app.db.tables.users import users
from app.intraday.engine import handoff, task
from app.notify.service import append
from app.notify.transport import publish
from app.workers.assembly import canonical
from selfchecks import test_p2n02_risk_controls as base
from selfchecks import test_p2n06_intraday as old
from selfchecks.test_p2n02_risk_controls import env as env
from selfchecks.test_p2n02_risk_controls import no_network as no_network
from selfchecks.test_tb89_full_migrations import deploy_grants

ROOT = Path(__file__).resolve().parents[3]
SOCKET = "/tmp/tb70-tb92-owned-pg"
REDIS = "unix:///tmp/tb92-owned-redis/redis.sock?db=0"
OPERANDS = json.loads((Path(__file__).parent / "fixtures/tb92_operands.json").read_text())


@pytest.fixture
def fresh_db() -> Any:
    name = "tb70_tb92_" + uuid.uuid4().hex
    url = "postgresql+psycopg://postgres@/" + name + "?host=" + SOCKET
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
    cfg.cmd_opts = Namespace(x=["url=" + url])
    assert ScriptDirectory.from_config(cfg).get_heads() == ["0027"]
    with psycopg.connect(dbname="postgres", user="postgres", host=SOCKET, autocommit=True) as admin:
        assert admin.execute("SHOW listen_addresses").fetchone() == ("",)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            yield url, cfg
        finally:
            admin.execute(
                sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS false").format(sql.Identifier(name))
            )
            admin.execute(
                "SELECT pg_terminate_backend(pid,5000) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()",
                (name,),
            ).fetchall()
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def grants(conn: Any) -> None:
    # Isolated rehearsal of the ops delta, NOT an edit to deployment grants.
    conn.execute(text("REVOKE ALL ON app.signal_event_projections FROM aia_api, aia_ingest"))
    conn.execute(text("GRANT SELECT,INSERT ON app.signal_event_projections TO aia_api"))
    for table in (
        "notification_refs",
        "intraday_candidate_refs",
        "signal_events",
        "signal_states",
        "intraday_universe",
    ):
        conn.execute(text(f"REVOKE ALL ON app.{table} FROM aia_ingest"))
    for table in ("notification_refs", "intraday_candidate_refs", "signal_events"):
        conn.execute(text(f"REVOKE UPDATE,DELETE ON app.{table} FROM aia_api"))
    conn.execute(text("REVOKE UPDATE,DELETE ON app.signal_states FROM aia_api"))
    conn.execute(
        text(
            "GRANT UPDATE(last_tick_id,rule_states,state,changed_at) ON app.signal_states TO aia_api"
        )
    )
    conn.execute(text("REVOKE SELECT,UPDATE,DELETE ON app.intraday_universe FROM aia_api"))
    conn.execute(
        text(
            "GRANT SELECT(trade_date,source_licence_id,security_code,computed_at),UPDATE(computed_at) ON app.intraday_universe TO aia_api"
        )
    )
    conn.execute(
        text(
            "REVOKE ALL ON app.notification_refs,app.intraday_candidate_refs,app.signal_event_projections FROM aia_maint"
        )
    )
    conn.execute(
        text("GRANT SELECT(source_licence_id),DELETE ON market.master_vendor_batches TO aia_maint")
    )
    for table, cols in (
        ("notification_refs", "notification_id"),
        ("intraday_candidate_refs", "instance_id"),
        (
            "signal_event_projections",
            "user_id",
        ),
        ("signal_states", "id,source_licence_id"),
        ("intraday_universe", "source_licence_id"),
        ("signal_events", "source_licence_id"),
    ):
        conn.execute(text(f"GRANT SELECT({cols}),DELETE ON app.{table} TO aia_maint"))


@pytest.fixture
def database(fresh_db: Any) -> Any:
    url, cfg = fresh_db
    command.upgrade(cfg, "head")
    root = create_engine(url)
    with root.begin() as conn:
        deploy_grants(conn)
        grants(conn)
        for code in base.CODES:
            conn.execute(
                insert(securities).values(
                    code=code,
                    name="Synthetic",
                    type="stock",
                    exchange=code[-2:],
                    board="star" if code in base.CODES[:2] else "chinext",
                    listing_status="listed",
                )
            )
    root.dispose()
    before = base.REDIS
    base.REDIS = REDIS
    try:
        yield url.replace("postgres@", "aia_api@")
    finally:
        base.REDIS = before


@pytest.fixture
def seeded(env: Any) -> Any:
    result = inspect.unwrap(old.seeded)(env)
    # Public fictional templates, so this user has no intentionally retained
    # authored-strategy blocker. Never alter the actual purge blocker policy.
    engine, _, _, owner, *_ = env
    with engine.begin() as c:
        c.execute(
            update(strategies).where(strategies.c.owner_user_id == owner).values(owner_user_id=None)
        )
        c.execute(
            update(strategy_cards)
            .where(strategy_cards.c.owner_user_id == owner)
            .values(owner_user_id=None)
        )
    return result


def facts(conn: Any) -> Any:
    tables = (
        "signal_events",
        "signal_states",
        "intraday_universe",
        "candidate_signals",
        "intraday_candidate_refs",
        "signal_event_projections",
        "notifications",
        "notification_refs",
        "suggestions",
        "data_snapshots",
    )
    return {
        t: sorted(conn.execute(text(f"SELECT to_jsonb(t)::text FROM app.{t} t")).scalars())  # noqa: S608 - fixed table tuple
        for t in tables
    }


def roundtrip(url: str, cfg: Config, expected: Any) -> None:
    root = create_engine(url)
    command.downgrade(cfg, "0024")
    with root.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0024"
        for table in (
            "notification_refs_rollback",
            "intraday_candidate_refs_rollback",
            "signal_event_projections_rollback",
            "p2n06_rollback_0025",
        ):
            assert conn.execute(
                text("SELECT to_regclass(:name)"), {"name": "app." + table}
            ).scalar_one()
        assert conn.execute(text("SELECT count(*) FROM app.signal_events")).scalar_one() == len(
            expected["signal_events"]
        )
        assert conn.execute(
            text("SELECT count(*) FROM app.notification_refs_rollback")
        ).scalar_one() == len(expected["notification_refs"])
        assert conn.execute(
            text("SELECT count(*) FROM app.signal_event_projections_rollback")
        ).scalar_one() == len(expected["signal_event_projections"])
    command.upgrade(cfg, "head")
    with root.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0027"
        assert facts(conn) == expected
        assert (
            conn.execute(
                text("SELECT count(*) FROM pg_constraint WHERE NOT convalidated")
            ).scalar_one()
            == 0
        )
    root.dispose()


def test_legacy_nonempty_proof_refs_upgrade_downgrade_reupgrade(fresh_db: Any) -> None:
    url, cfg = fresh_db
    command.upgrade(cfg, "0023")
    root = create_engine(url)
    uid, lid, sid, eid, notice = [uuid.uuid4() for _ in range(5)]
    body = {"schema_version": "synthetic-legacy-v1", "security_code": "688018.SH"}
    detail = {"input_snapshot_id": str(sid), "kind": "rule_flip"}
    with root.begin() as c:
        c.execute(
            insert(users).values(
                id=uid,
                username="tb92_" + uid.hex[:16],
                password_hash=uuid.uuid4().hex,
                status="approved",
                role="user",
            )
        )
        c.execute(
            insert(user_data_licences).values(
                id=lid,
                user_id=uid,
                status="active",
                tier="free",
                ciphertext=b"synthetic",
                licence_hmac=uuid.uuid4().bytes,
                seal_key_version=1,
            )
        )
        c.execute(
            insert(data_snapshots).values(
                id=sid,
                user_id=uid,
                licence_id=lid,
                purpose="signal",
                items=body,
                hash=hashlib.sha256(canonical(body).encode()).hexdigest(),
                created_at=old.AT,
            )
        )
        c.execute(
            text(
                "INSERT INTO app.signal_events(id,scope,security_code,trigger_kind,detail,created_at) VALUES(:id,'shared','688018.SH','flip',CAST(:d AS jsonb),:at)"
            ),
            {"id": eid, "d": json.dumps(detail), "at": old.AT},
        )
        c.execute(
            text(
                "INSERT INTO app.notifications(id,user_id,kind,severity,title,target_type,read_at,created_at) VALUES(:id,:u,'suggestion_change','info','old body','none',:at,:at)"
            ),
            {"id": notice, "u": uid, "at": old.AT},
        )
    command.upgrade(cfg, "head")
    with root.begin() as c:
        legacy = c.execute(select(signal_events).where(signal_events.c.id == eid)).one()
        assert legacy.source_licence_id == lid
        assert legacy.input_snapshot_id == sid
        assert legacy.detail == detail
        assert legacy.legacy_binding_unknown is True
        assert c.execute(select(signal_event_projections)).first() is None
        before = c.execute(select(notifications).where(notifications.c.id == notice)).one()
        assert before.read_at == old.AT
        assert before.version == before.merged_count == 1
        assert before.refs == []
        for row in OPERANDS:
            ref = uuid.uuid4()
            c.execute(
                insert(signal_events).values(
                    id=ref,
                    source_licence_id=lid,
                    scope="shared",
                    security_code="688018.SH",
                    trigger_kind="flip",
                    detail={"kind": "rule_flip"},
                    created_at=old.AT,
                )
            )
            append(
                c,
                owner=uid,
                kind="suggestion_change",
                severity="attention",
                title="synthetic new",
                body="not real",
                code="688018.SH",
                target_type="none",
                target_id=None,
                ref_type="signal",
                ref_id=str(ref),
                at=old.AT + dt.timedelta(seconds=row["offset_seconds"]),
            )
        all_rows = c.execute(select(notifications).where(notifications.c.user_id == uid)).all()
        combined = next(r for r in all_rows if r.id != notice)
        assert combined.merged_count == combined.version == 24
        assert len(combined.refs) == 20
        c.execute(
            update(notifications)
            .where(notifications.c.id == combined.id)
            .values(read_at=old.AT + dt.timedelta(minutes=5), version=25)
        )
        expected = facts(c)
    roundtrip(url, cfg, expected)
    root.dispose()


def test_unprovable_legacy_refuses_without_erasing(fresh_db: Any) -> None:
    url, cfg = fresh_db
    command.upgrade(cfg, "0023")
    root = create_engine(url)
    with root.begin() as c:
        c.execute(
            text(
                "INSERT INTO app.signal_events(id,scope,security_code,trigger_kind) VALUES(:id,'shared','688018.SH','flip')"
            ),
            {"id": uuid.uuid4()},
        )
    with pytest.raises(RuntimeError, match="unowned_signal_events"):
        command.upgrade(cfg, "head")
    with root.connect() as c:
        assert c.execute(text("SELECT count(*) FROM app.signal_events")).scalar_one() == 1
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() not in {
            "0025",
            "0026",
            "0027",
        }
    root.dispose()


def test_multi_instance_frozen_single_archive_ref_and_roundtrip(seeded: Any, fresh_db: Any) -> None:
    engine, client, other, owner, _, settings, *_ = seeded
    iid = seeded[-3]
    with engine.begin() as c:
        original = c.execute(select(strategy_instances).where(strategy_instances.c.id == iid)).one()
        expected = []
        for row in OPERANDS:
            values = dict(original._mapping)
            ident = iid if row["index"] == 1 else uuid.uuid4()
            at = old.AT - dt.timedelta(days=1) + dt.timedelta(seconds=row["offset_seconds"] // 30)
            if ident == iid:
                c.execute(
                    update(strategy_instances)
                    .where(strategy_instances.c.id == iid)
                    .values(created_at=at)
                )
            else:
                values.update(id=ident, created_at=at)
                c.execute(insert(strategy_instances).values(**values))
            expected.append((at, ident))
    expected_ids = [ident for _, ident in sorted(expected, key=lambda x: (x[0], x[1]))]
    r = redis.Redis.from_url(REDIS)
    old.reset_buffer(r)
    for offset, price in [(0, "25"), (5, "25"), (10, "35"), (15, "35")]:
        payload = old.receipt(seeded, price, offset)
        task(settings, payload)
    projected = client.get("/api/v1/signals?security_code=688018.SH")
    assert projected.status_code == 200, projected.text
    item = projected.json()["items"][0]
    assert item["instance_ids"] == [str(i) for i in expected_ids[:20]]
    assert item["instance_id"] == str(expected_ids[0])
    eid = uuid.UUID(item["signal_event_id"])
    with engine.connect() as c:
        assert c.execute(text("SELECT current_user")).scalar_one() == "aia_api"
        assert not c.execute(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
        ).scalar_one()
        for table in (
            "notification_refs",
            "intraday_candidate_refs",
            "signal_events",
            "signal_event_projections",
        ):
            assert not c.execute(
                text("SELECT has_table_privilege(current_user,:t,'UPDATE,DELETE')"),
                {"t": "app." + table},
            ).scalar_one()
        for table in (
            "notification_refs",
            "intraday_candidate_refs",
            "signal_events",
            "signal_states",
            "intraday_universe",
            "signal_event_projections",
        ):
            assert not c.execute(
                text("SELECT has_table_privilege('aia_ingest',:t,'SELECT,INSERT,UPDATE,DELETE')"),
                {"t": "app." + table},
            ).scalar_one()
        assert len(c.execute(select(suggestions).where(suggestions.c.user_id == owner)).all()) == 1
        assert (
            c.execute(
                text("SELECT count(*) FROM app.intraday_candidate_refs WHERE event_id=:e"),
                {"e": eid},
            ).scalar_one()
            == 24
        )
        assert (
            c.execute(select(notifications).where(notifications.c.user_id == owner))
            .one()
            .merged_count
            == 1
        )
    assert other.get("/api/v1/signals?security_code=688018.SH").json()["items"] == []
    with engine.begin() as c:
        c.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id.in_(expected_ids))
            .values(status="paused", paused_by="user")
        )
    assert client.get("/api/v1/signals?security_code=688018.SH").json()["items"][0] == item
    assert handoff(settings, eid, r) == 0
    assert task(settings, payload) == 0
    # A later independent version event carries, not recomputes, all 24 frozen
    # conclusions from the now-paused instances. One archive/ref for each event.
    with engine.connect() as c:
        prior = c.execute(
            select(data_snapshots.c["items"])
            .join(suggestions, suggestions.c.snapshot_id == data_snapshots.c.id)
            .where(suggestions.c.user_id == owner)
        ).scalar_one()
        original_conclusions = prior["input"]["conclusions"]
        prior_id = c.execute(
            select(suggestions.c.snapshot_id).where(suggestions.c.user_id == owner)
        ).scalar_one()
        policy = c.execute(
            text("SELECT * FROM app.engine_policies WHERE id=:p"),
            {"p": prior["input"]["engine_policy_id"]},
        ).one()
        version = c.execute(
            select(strategy_versions).where(strategy_versions.c.id == seeded[-2])
        ).one()
        notification = c.execute(
            select(notifications).where(notifications.c.user_id == owner)
        ).one()
    from app.suggestions.models import Conclusion
    from app.suggestions.service import verified_carried
    from app.workers.assembly import archive_conclusions

    with (
        engine.connect() as c,
        pytest.raises(ValueError, match="carried_archive_not_owned_current"),
    ):
        verified_carried(c, seeded[4], "688018.SH", prior_id, old.AT + dt.timedelta(minutes=1))
    altered = [Conclusion.model_validate(row) for row in original_conclusions]
    altered[0] = altered[0].model_copy(update={"strategy_name": "fictional_tamper"})
    # A copied proof must not exempt a modified paused-instance conclusion.
    with (
        pytest.raises(ValueError, match="suggestion_instance_not_active_or_version_mismatch"),
        engine.begin() as c,
    ):
        archive_conclusions(c, owner, "688018.SH", altered, policy, carry_from_snapshot_id=prior_id)
    assert client.post("/api/v1/notifications/" + str(notification.id) + "/read").status_code == 204
    with engine.begin() as c:
        new_version = dict(version._mapping)
        new_vid = uuid.uuid4()
        new_version.update(id=new_vid, version_no=version.version_no + 1)
        c.execute(insert(strategy_versions).values(**new_version))
        new_inst = dict(original._mapping)
        new_iid = uuid.uuid4()
        new_inst.update(
            id=new_iid,
            strategy_version_id=new_vid,
            derived_strategy_version_id=None,
            status="active",
            paused_by=None,
        )
        c.execute(insert(strategy_instances).values(**new_inst))
    for offset, price in [(20, "25"), (25, "25"), (30, "35"), (35, "35")]:
        payload = old.receipt(seeded, price, offset)
        task(settings, payload)
    with engine.connect() as c:
        archives = c.execute(
            select(suggestions).where(suggestions.c.user_id == owner).order_by(suggestions.c.seq_no)
        ).all()
        assert len(archives) == 2
        newest = c.execute(
            select(data_snapshots.c["items"]).where(data_snapshots.c.id == archives[-1].snapshot_id)
        ).scalar_one()["input"]["conclusions"]
        assert len(newest) == 25
        carried = {v["instance_id"]: v for v in newest if v["instance_id"] != str(new_iid)}
        assert carried == {v["instance_id"]: v for v in original_conclusions}
        note = c.execute(select(notifications).where(notifications.c.user_id == owner)).one()
        assert note.merged_count == 2
        assert note.version == 3
        assert note.read_at is None
        assert len(c.execute(select(notification_refs)).all()) == 2
    assert task(settings, payload) == 0
    with pytest.raises(DBAPIError, match="projection_owner_mismatch"), engine.begin() as c:
        c.execute(
            insert(signal_event_projections).values(
                event_id=eid, user_id=seeded[4], instance_ids=[]
            )
        )
    url, cfg = fresh_db
    root = create_engine(url)
    with root.connect() as c:
        before = facts(c)
    roundtrip(url, cfg, before)
    with root.begin() as c:
        deploy_grants(c)
        grants(c)
    # Exact maintenance role; no SET ROLE and no real user operation.
    maint = create_engine(url.replace("postgres@", "aia_maint@"))
    # Maintenance privilege alone and a foreign user's purging flag are NOT ownership.
    for foreign_purge in (False, True):
        with pytest.raises(DBAPIError) as refused, maint.begin() as c:  # noqa: PT012 - atomic negative transaction
            if foreign_purge:
                c.execute(update(users).where(users.c.id == seeded[4]).values(status="purging"))
            c.execute(text("SELECT set_config('app.purge_user_id',:u,true)"), {"u": str(owner)})
            c.execute(text("DELETE FROM app.signal_events WHERE id=:e"), {"e": eid})
        assert refused.value.orig.sqlstate == "23001"
    with maint.begin() as c:
        assert c.execute(text("SELECT session_user,current_user")).one() == (
            "aia_maint",
            "aia_maint",
        )
        plan = build_plan(c, owner)
        assert not plan.blockers
        assert not plan.unknown_triggers
        result = run_purge(c, plan)
        assert result["delete:app.signal_events"] == 2
    with root.connect() as c:
        assert c.execute(select(users.c.id).where(users.c.id == owner)).first() is None
        assert c.execute(select(users.c.id).where(users.c.id == seeded[4])).first() is not None
        assert c.execute(select(signal_events)).first() is None
    maint.dispose()
    root.dispose()
    r.close()


@pytest.mark.parametrize("revoke_on", ["retry", "first_cached"])
def test_initial_http_sse_revoked_session_stops_cached_frames(env: Any, revoke_on: str) -> None:
    _engine, client, _, owner, _, _settings = env
    r = redis.Redis.from_url(REDIS)
    old.reset_buffer(r)
    now = dt.datetime.now(dt.UTC)
    anchor = publish(r, owner, "heartbeat", {"at": now.isoformat()}, now)
    for n in range(3):
        publish(r, owner, "quote", {"synthetic_index": n}, now)
    store = SessionStore(r, idle_ttl_s=1800, absolute_ttl_s=3600)
    frames = []

    async def invoke() -> None:
        received = False

        async def receive() -> dict:
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await anyio.sleep_forever()

        async def send(message: dict) -> None:
            frames.append(message)
            body = message.get("body", b"")
            if (revoke_on == "retry" and b"retry:" in body) or (
                revoke_on == "first_cached" and b"event: quote" in body
            ):
                session = store.get(client.cookies.get(SESSION_COOKIE))
                assert session is not None
                store.delete(session)

        cookie = "; ".join(k + "=" + v for k, v in client.cookies.items())
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/stream",
            "raw_path": b"/api/v1/stream",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"cookie", cookie.encode()), (b"last-event-id", anchor.encode())],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        with anyio.fail_after(3):
            await client.app(scope, receive, send)

    anyio.run(invoke)
    body = b"".join(m.get("body", b"") for m in frames)
    assert frames[0]["status"] == 200
    assert body.count(b"event: quote") == (0 if revoke_on == "retry" else 1)
    assert b"heartbeat" not in body
    r.close()


@pytest.mark.parametrize(
    ("count", "candidate_index", "expected_index"), [(0, None, None), (2, None, 0), (2, 1, 1)]
)
def test_primary_candidate_precedence_without_fabricated_products(
    count: int, candidate_index: int | None, expected_index: int | None
) -> None:
    from types import SimpleNamespace

    from app.intraday.engine import primary_instance

    instances = [SimpleNamespace(id=uuid.UUID(int=n + 1)) for n in range(count)]
    refs = {} if candidate_index is None else {instances[candidate_index].id: uuid.uuid4()}
    chosen = primary_instance(instances, refs)
    assert chosen is (None if expected_index is None else instances[expected_index])


def test_conditional_old_key_conflict_refuses_atomically(seeded: Any, fresh_db: Any) -> None:
    _engine, *_ = seeded
    url, cfg = fresh_db
    root = create_engine(url)
    with root.begin() as c:
        first = c.execute(
            select(user_data_licences).where(user_data_licences.c.id == seeded[-1])
        ).one()
        second = dict(first._mapping)
        second.update(
            id=uuid.uuid4(),
            status="paused_by_admin",
            deleted_at=dt.datetime.now(dt.UTC),
            ciphertext=None,
            licence_hmac=None,
        )
        c.execute(insert(user_data_licences).values(**second))
        for lid in (first.id, second["id"]):
            c.execute(
                text(
                    "INSERT INTO app.signal_states(id,source_licence_id,security_code,strategy_version_id,params_hash) VALUES(:id,:lid,'688018.SH',:v,'synthetic-collision')"
                ),
                {"id": uuid.uuid4(), "lid": lid, "v": seeded[-2]},
            )
        before = facts(c)
    with pytest.raises(RuntimeError, match="old_unique_key_conflict:signal_states"):
        command.downgrade(cfg, "0024")
    with root.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0027"
        assert facts(c) == before
    root.dispose()


def test_existing_old_0026_additive_unknown_binding_and_refs_preserved(fresh_db: Any) -> None:
    url, cfg = fresh_db
    command.upgrade(cfg, "0026")
    root = create_engine(url)
    uid, lid, eid = [uuid.uuid4() for _ in range(3)]
    with root.begin() as c:
        # Exact pre-amendment 0026 layout: flag absent, uniqueness not partial.
        c.execute(text("ALTER TABLE app.signal_events DROP COLUMN legacy_binding_unknown"))
        c.execute(
            text(
                "ALTER TABLE app.signal_events ADD CONSTRAINT uq_signal_events_shared_tick UNIQUE(source_licence_id,security_code,strategy_version_id,params_hash,rule_id,tick_id)"
            )
        )
        c.execute(
            text(
                "ALTER TABLE app.signal_events ADD CONSTRAINT uq_signal_events_user_tick UNIQUE(user_id,security_code,trigger_kind,tick_id)"
            )
        )
        c.execute(
            insert(users).values(
                id=uid,
                username="legacy_" + uid.hex[:16],
                password_hash=uuid.uuid4().hex,
                role="user",
                status="approved",
            )
        )
        c.execute(
            insert(user_data_licences).values(
                id=lid,
                user_id=uid,
                ciphertext=b"synthetic",
                licence_hmac=uuid.uuid4().bytes,
                seal_key_version=1,
                status="active",
                tier="free",
            )
        )
        c.execute(
            text(
                "INSERT INTO app.signal_events(id,source_licence_id,scope,security_code,trigger_kind,created_at,detail) VALUES(:e,:l,'shared','688018.SH','flip',:at,'{\"kind\":\"rule_flip\"}')"
            ),
            {"e": eid, "l": lid, "at": old.AT},
        )
        _nid, _ = append(
            c,
            owner=uid,
            kind="suggestion_change",
            severity="attention",
            title="synthetic old26",
            body=None,
            code="688018.SH",
            target_type="none",
            target_id=None,
            ref_type="signal",
            ref_id=str(eid),
            at=old.AT,
        )
        old_notes = list(
            c.execute(text("SELECT to_jsonb(n)::text FROM app.notifications n")).scalars()
        )
        old_refs = list(
            c.execute(text("SELECT to_jsonb(n)::text FROM app.notification_refs n")).scalars()
        )
    command.upgrade(cfg, "head")
    with root.connect() as c:
        row = c.execute(select(signal_events).where(signal_events.c.id == eid)).one()
        assert row.source_licence_id == lid
        assert row.legacy_binding_unknown is True
        assert c.execute(select(signal_event_projections)).first() is None
        assert (
            list(c.execute(text("SELECT to_jsonb(n)::text FROM app.notifications n")).scalars())
            == old_notes
        )
        assert (
            list(c.execute(text("SELECT to_jsonb(n)::text FROM app.notification_refs n")).scalars())
            == old_refs
        )
    root.dispose()
