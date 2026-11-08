"""Only explicit synthetic Unix PG/Redis; real Alembic env / worker / HTTP facts."""

# ruff: noqa: S101, S108, S106, ANN401, RUF059, PT018
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from argparse import Namespace
from pathlib import Path
from typing import Any

import psycopg
import pytest
import redis
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import sql
from sqlalchemy import create_engine, insert, select, text, update

from app.db.tables.market import securities, trading_calendar
from app.db.tables.notify import notification_refs, notifications
from app.db.tables.users import users
from app.notify.service import append, project
from app.notify.transport import enqueue, flush, publish, replay
from selfchecks import test_p2n02_risk_controls as shared
from selfchecks.test_p2n02_risk_controls import env as env
from selfchecks.test_p2n02_risk_controls import no_network as no_network
from selfchecks.test_tb89_full_migrations import deploy_grants

SOCKET = "/tmp/tb70-p2n06-owned-socket"
REDIS = "unix:///tmp/p2n06-redis/redis.sock?db=0"
ROOT = Path(__file__).resolve().parents[3]
AT = dt.datetime(2026, 11, 9, 2, tzinfo=dt.UTC)


def reset_buffer(client: Any) -> None:
    keys = list(client.scan_iter(match="p2n06:*"))
    if keys:
        client.delete(*keys)


@pytest.fixture
def database() -> Any:
    old = shared.REDIS
    shared.REDIS = REDIS
    name = "tb70_p2n06_" + uuid.uuid4().hex
    url = "postgresql+psycopg://postgres@/" + name + "?host=" + SOCKET
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
    cfg.cmd_opts = Namespace(x=["url=" + url])
    assert ScriptDirectory.from_config(cfg).get_heads() == ["0026"]
    with psycopg.connect(dbname="postgres", user="postgres", host=SOCKET, autocommit=True) as admin:
        assert admin.execute("SHOW listen_addresses").fetchone() == ("",)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            command.upgrade(cfg, "0023")
            engine = create_engine(url, hide_parameters=True)
            owner = uuid.uuid4()
            identifier = uuid.uuid4()
            with engine.begin() as conn:
                conn.execute(
                    insert(users).values(
                        id=owner,
                        username="legacy_p2n06",
                        password_hash="synthetic-never-login",
                        role="user",
                        status="approved",
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO app.notifications(id,user_id,kind,severity,title,"
                        "target_type,created_at) "
                        "VALUES(:id,:owner,'suggestion_change','info',"
                        "'synthetic legacy','none',:at)"
                    ),
                    {"id": identifier, "owner": owner, "at": AT},
                )
            command.upgrade(cfg, "head")
            with engine.begin() as conn:
                row = conn.execute(
                    select(notifications).where(notifications.c.id == identifier)
                ).one()
                assert project(conn, row)["merged_count"] == 1
                assert project(conn, row)["refs"] == []
                assert project(conn, row)["updated_at"] == AT.isoformat()
                assert (
                    conn.execute(
                        text("SELECT version_num FROM public.alembic_version")
                    ).scalar_one()
                    == "0026"
                )
                deploy_grants(conn)
                for code in ["688018.SH", "688073.SH", "300364.SZ", "301218.SZ"]:
                    conn.execute(
                        insert(securities).values(
                            code=code,
                            name="纯合成",
                            type="stock",
                            exchange=code[-2:],
                            board="star" if code.startswith("688") else "chinext",
                            listing_status="listed",
                        )
                    )
            engine.dispose()
            yield url.replace("postgres@", "aia_api@")
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            shared.REDIS = old


def add(
    engine: Any, owner: uuid.UUID, ref: str, at: dt.datetime = AT, severity: str = "attention"
) -> tuple[uuid.UUID, bool]:
    with engine.begin() as conn:
        return append(
            conn,
            owner=owner,
            kind="suggestion_change",
            severity=severity,
            title="规则状态已变化",
            body=None,
            code="688018.SH",
            target_type="none",
            target_id=None,
            ref_type="signal",
            ref_id=str(uuid.uuid5(uuid.NAMESPACE_URL, ref)),
            at=at,
        )


def test_merge_actual_upgrade_http_read_refs_roles_and_replay(env: Any) -> None:
    engine, client, other, owner, stranger, settings = env
    identifier, new = add(engine, owner, "a")
    assert new
    assert add(engine, owner, "a") == (identifier, False)
    assert add(engine, owner, "b", AT + dt.timedelta(seconds=3), "important") == (identifier, True)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT current_user")).scalar_one() == "aia_api"
        for table in (
            "signal_events",
            "signal_states",
            "intraday_universe",
            "notifications",
            "notification_refs",
            "intraday_candidate_refs",
        ):
            for perm in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert conn.execute(
                    text("SELECT has_table_privilege(current_user,:t,:p)"),
                    {"t": "app." + table, "p": perm},
                ).scalar_one()
    assert client.get("/api/v1/notifications/unread-count").json() == {"count": 1}
    rows = client.get("/api/v1/notifications?unread=true").json()["items"]
    assert len(rows) == 1 and rows[0]["merged_count"] == 2 and rows[0]["severity"] == "important"
    assert len(rows[0]["refs"]) == 2
    assert rows[0]["version"] == 2
    assert all(
        x["type"] == "signal" and x["route"] is None and str(uuid.UUID(x["id"])) == x["id"]
        for x in rows[0]["refs"]
    )
    assert other.get("/api/v1/notifications").json()["items"] == []
    assert other.post(f"/api/v1/notifications/{identifier}/read").status_code == 404
    assert client.post(f"/api/v1/notifications/{identifier}/read").status_code == 204
    assert client.get("/api/v1/notifications/unread-count").json() == {"count": 0}
    assert client.get("/api/v1/notifications").json()["items"][0]["version"] == 3
    assert client.post(f"/api/v1/notifications/{identifier}/read").status_code == 204
    assert client.get("/api/v1/notifications").json()["items"][0]["version"] == 3
    add(engine, owner, "a")
    assert client.get("/api/v1/notifications/unread-count").json() == {"count": 0}
    add(engine, owner, "c")
    assert client.get("/api/v1/notifications").json()["items"][0]["version"] == 4
    assert client.get("/api/v1/notifications/unread-count").json() == {"count": 1}
    for i in range(25):
        add(engine, owner, "ref" + str(i))
    assert client.get("/api/v1/notifications").json()["items"][0]["merged_count"] == 28
    assert len(client.get("/api/v1/notifications").json()["items"][0]["refs"]) == 20
    assert add(engine, owner, "new_bucket", AT + dt.timedelta(minutes=10))[0] != identifier
    r = redis.Redis.from_url(REDIS)
    reset_buffer(r)
    anchor = publish(r, owner, "heartbeat", {"at": AT.isoformat()}, AT)
    enqueue(engine, r, owner, identifier, AT)
    events = replay(r, owner, anchor, AT)
    assert events[-1]["event"] == "notification" and events[-1]["data"]["merged_count"] == 28
    assert replay(r, stranger, anchor, AT) == []
    assert replay(r, owner, anchor, AT + dt.timedelta(seconds=601)) == []
    before = {v["id"]: v["version"] for v in client.get("/api/v1/notifications").json()["items"]}
    assert client.post("/api/v1/notifications/read-all").status_code == 204
    after = {v["id"]: v["version"] for v in client.get("/api/v1/notifications").json()["items"]}
    assert after == {k: v + 1 for k, v in before.items()}
    assert client.post("/api/v1/notifications/read-all").status_code == 204
    assert {
        v["id"]: v["version"] for v in client.get("/api/v1/notifications").json()["items"]
    } == after
    r.close()


@pytest.fixture
def seeded(env: Any) -> Any:
    from app.db.tables.licences import user_data_licences
    from app.db.tables.strategy import feature_catalog, strategy_instances, strategy_versions
    from selfchecks.test_tb74_candidates import setup
    from selfchecks.test_tb76_assembly import prepare

    engine, client, other, owner, stranger, settings = env
    rows = setup.__wrapped__(env[:5], None)
    iid = prepare(rows)
    licence = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == rows[6])
            .values(status="paused", paused_by="user")
        )
        inst = conn.execute(select(strategy_instances).where(strategy_instances.c.id == iid)).one()
        ver = conn.execute(
            select(strategy_versions).where(strategy_versions.c.id == inst.strategy_version_id)
        ).one()
        spec = json.loads(json.dumps(ver.config))
        for rule in spec["rules"]:
            rule["expr"] = (
                "f.synthetic_quote > 30"
                if rule["id"] == "E"
                else "f.synthetic_quote < 10"
                if rule["id"] == "X"
                else "f.synthetic_quote < 0"
            )
            rule["eval_time"] = "intraday"
        conn.execute(
            update(strategy_versions).where(strategy_versions.c.id == ver.id).values(config=spec)
        )
        conn.execute(
            insert(feature_catalog).values(
                feature_key="f.synthetic_quote",
                status="verified_live",
                source={"synthetic": True},
                unit="CNY/share",
            )
        )
        conn.execute(
            insert(user_data_licences).values(
                id=licence,
                user_id=owner,
                ciphertext=b"synthetic-only",
                licence_hmac=b"synthetic-only",
                seal_key_version=1,
                tier="free",
                status="active",
            )
        )
        assert (
            conn.execute(
                select(trading_calendar.c.is_open).where(trading_calendar.c.date == AT.date())
            ).scalar_one()
            is True
        )
    return (*env, rows, iid, ver.id, licence)


def receipt(
    seeded: Any, price: str, offset: int, quote_at: dt.datetime | None = None
) -> dict[str, Any]:
    from app.db.tables.reviews import data_snapshots
    from app.intraday.engine import SCHEMA
    from app.workers.assembly import canonical

    engine, _, _, owner, _, _, old, iid, vid, licence = seeded
    at = AT + dt.timedelta(seconds=offset)
    tick = at.astimezone(dt.timezone(dt.timedelta(hours=8))).strftime("%Y%m%dT%H%M%S")
    instrument = {
        "security_code": "688018.SH",
        "board": "star",
        "adjust": "none",
        "currency": "CNY",
        "price_unit": "CNY/share",
        "amount_unit": "CNY",
        "volume_unit": "share",
        "bars": [],
        "gaps": [],
    }
    body = {
        "schema_version": SCHEMA,
        "simulation": True,
        "security_code": "688018.SH",
        "account_id": str(old[5]),
        "tick_id": tick,
        "as_of": at.isoformat(),
        "quote": {"t": (quote_at or at).isoformat(), "price": price, "is_suspended": False},
        "instrument": instrument,
        "sessions": [],
        "factors": [],
        "scalars": [
            {
                "feature_key": "f.synthetic_quote",
                "value": int(price),
                "unit": "CNY/share",
                "date": at.date().isoformat(),
                "available_at": at.isoformat(),
            }
        ],
        "holding": {"quantity": "0"},
        "lots": [],
    }
    with engine.begin() as conn:
        conn.execute(
            insert(data_snapshots).values(
                id=uuid.uuid4(),
                user_id=owner,
                licence_id=licence,
                purpose="signal",
                items=body,
                hash=hashlib.sha256(canonical(body).encode()).hexdigest(),
                created_at=at,
            )
        )
    return {
        "v": 1,
        "licence_id": str(licence),
        "tick_id": tick,
        "dataset": "quotes",
        "codes": ["688018.SH"],
        "quote_ts_max": (quote_at or at).isoformat(),
        "published_at": at.isoformat(),
    }


def test_actual_pubsub_engine_debounce_suggestion_notification_http_and_replay(seeded: Any) -> None:
    from app.db.tables.realtime import (
        intraday_candidate_refs,
        signal_events,
        signal_states,
        suggestions,
    )
    from app.db.tables.signals import candidate_signals
    from app.intraday.consumer import Consumer
    from app.intraday.engine import task

    engine, client, other, owner, stranger, settings, *_ = seeded
    r = redis.Redis.from_url(REDIS)
    reset_buffer(r)
    consumer = Consumer(settings, r)
    # Actual PubSub input -> shared evaluator -> CAS state. No mock evaluator/output.
    for offset, price in [(0, "25"), (5, "25"), (10, "35"), (15, "35")]:
        payload = receipt(seeded, price, offset)
        r.publish("market.updated", json.dumps(payload))
        consumer.pump(AT + dt.timedelta(seconds=offset))
    with engine.connect() as conn:
        events = conn.execute(select(signal_events)).all()
        assert len(events) == 1
        assert (
            events[0].detail["rule_id"] == "E"
            and events[0].from_state == "false"
            and events[0].to_state == "true"
        )
        assert events[0].source_licence_id == seeded[-1]
        assert conn.execute(select(suggestions)).first() is not None
        candidates = conn.execute(select(candidate_signals)).all()
        assert len(candidates) == 1 and candidates[0].origin_signal_event_id == events[0].id
        assert conn.execute(select(intraday_candidate_refs)).first() is not None
        assert (
            conn.execute(select(notifications).where(notifications.c.user_id == owner)).first()
            is not None
        )
        assert len(conn.execute(select(signal_states)).all()) == 1
    assert client.get("/api/v1/signals?security_code=688018.SH").status_code == 200
    projected = client.get("/api/v1/signals?security_code=688018.SH").json()["items"]
    assert len(projected) == 1
    assert projected[0]["instance_id"] == str(seeded[-3])
    from app.db.tables.signals import candidate_signal_events

    with engine.connect() as conn:
        ce = conn.execute(
            select(candidate_signal_events).where(
                candidate_signal_events.c.signal_id == candidates[0].id
            )
        ).one()
        assert ce.detail["signal_event_id"] == str(events[0].id)
    assert other.get("/api/v1/signals?security_code=688018.SH").json()["items"] == []
    assert client.get("/api/v1/notifications/unread-count").json() == {"count": 1}
    assert task(settings, payload) == 0
    assert client.get("/api/v1/notifications").json()["items"][0]["merged_count"] == 1
    # Cadence does not suppress immediate signal/suggestion/candidate events.
    all_events = replay(r, owner, "0", AT + dt.timedelta(seconds=20), require_anchor=False)
    assert {"signal", "suggestion", "candidate_signal"} <= {e["event"] for e in all_events}
    flush(engine, r, AT + dt.timedelta(minutes=1))
    assert "notification" in {
        e["event"]
        for e in replay(r, owner, "0", AT + dt.timedelta(minutes=1), require_anchor=False)
    }
    # Out-of-order older trigger cannot rewind CAS.
    assert task(settings, receipt(seeded, "5", 8)) == 0
    stale = receipt(seeded, "35", 120, quote_at=AT + dt.timedelta(seconds=15))
    assert task(settings, stale) == 1
    assert task(settings, stale) == 0
    with engine.connect() as conn:
        assert len(conn.execute(select(candidate_signals)).all()) == 1
        assert (
            len(
                conn.execute(
                    select(signal_events).where(signal_events.c.trigger_kind == "stale")
                ).all()
            )
            == 1
        )
    consumer.close()
    r.close()


@pytest.mark.parametrize(("cadence", "minutes"), [("1min", 1), ("3min", 3), ("5min", 5)])
def test_actual_cadence_aligned_latest_once(env: Any, cadence: str, minutes: int) -> None:
    engine, client, _, owner, _, _ = env
    assert (
        client.put(
            "/api/v1/notification-preferences", json={"intraday_cadence": cadence}
        ).status_code
        == 200
    )
    r = redis.Redis.from_url(REDIS)
    reset_buffer(r)
    identifier, _ = add(engine, owner, "first", AT + dt.timedelta(seconds=5))
    enqueue(engine, r, owner, identifier, AT + dt.timedelta(seconds=5))
    add(engine, owner, "next", AT + dt.timedelta(seconds=15))
    enqueue(engine, r, owner, identifier, AT + dt.timedelta(seconds=15))
    assert flush(engine, r, AT + dt.timedelta(minutes=minutes, seconds=-1)) == 0
    assert flush(engine, r, AT + dt.timedelta(minutes=minutes)) == 1
    assert flush(engine, r, AT + dt.timedelta(minutes=minutes)) == 0
    events = replay(r, owner, "0", AT + dt.timedelta(minutes=minutes), require_anchor=False)
    assert len(events) == 1
    assert events[0]["data"]["merged_count"] == 2
    r.close()


def test_concurrent_merge_and_unique_ref(env: Any) -> None:
    from concurrent.futures import ThreadPoolExecutor

    engine, _, _, owner, _, _ = env
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: add(engine, owner, "same-ref"), range(8)))
    assert len({v[0] for v in results}) == 1
    assert sum(v[1] for v in results) == 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda x: add(engine, owner, "ref" + str(x)), range(8)))
    with engine.connect() as conn:
        row = conn.execute(select(notifications).where(notifications.c.user_id == owner)).one()
        assert row.merged_count == 9
        assert (
            len(
                conn.execute(
                    select(notification_refs).where(notification_refs.c.notification_id == row.id)
                ).all()
            )
            == 9
        )


def test_reviewed_operands_are_synthetic_only() -> None:
    rows = json.loads((Path(__file__).parent / "fixtures/p2n06_ticks.json").read_text())
    assert len(rows) == 24
    assert [row["index"] for row in rows] == list(range(24))
    assert all(0 <= row["offset_seconds"] <= 720 for row in rows)


def http_sse_once(client: Any, last: str) -> list[dict[str, Any]]:
    import anyio

    messages = []

    async def invoke() -> None:
        disconnected = anyio.Event()
        received = False

        async def receive() -> dict[str, Any]:
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)
            if message["type"] == "http.response.body" and b"event:" in message.get("body", b""):
                disconnected.set()

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
            "headers": [(b"cookie", cookie.encode()), (b"last-event-id", last.encode())],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        with anyio.move_on_after(3):
            await client.app(scope, receive, send)

    anyio.run(invoke)
    return messages


def test_real_http_sse_reconnect_owned_full_notification_and_anonymous(env: Any) -> None:
    engine, client, other, owner, _, _ = env
    now = dt.datetime.now(dt.UTC)
    r = redis.Redis.from_url(REDIS)
    reset_buffer(r)
    assert (
        client.put(
            "/api/v1/notification-preferences", json={"intraday_cadence": "realtime"}
        ).status_code
        == 200
    )
    anchor = publish(r, owner, "heartbeat", {"at": now.isoformat()}, now)
    identifier, _ = add(engine, owner, "live-synthetic", now)
    enqueue(engine, r, owner, identifier, now)
    messages = http_sse_once(client, anchor)
    assert messages[0]["status"] == 200
    body = b"".join(m.get("body", b"") for m in messages).decode()
    assert "event: notification" in body
    assert str(identifier) in body and "merged_count" in body and "refs" in body
    foreign = http_sse_once(other, anchor)
    assert foreign[0]["status"] == 200
    assert str(identifier) not in b"".join(m.get("body", b"") for m in foreign).decode()
    from fastapi.testclient import TestClient

    with TestClient(client.app) as anonymous:
        assert anonymous.get("/api/v1/stream").status_code == 401
    r.close()


def test_unowned_legacy_event_aborts_upgrade_not_guessed(no_network: Any) -> None:
    from selfchecks import test_tb89_full_migrations as legacy

    before = legacy.SOCKET
    legacy.SOCKET = SOCKET
    generator = legacy.fresh_db.__wrapped__()
    try:
        name, cfg = next(generator)
        command.upgrade(cfg, "0023")
        engine = create_engine(
            "postgresql+psycopg://postgres@/" + name + "?host=" + SOCKET, hide_parameters=True
        )
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO app.signal_events(id,scope,security_code,trigger_kind) "
                    "VALUES(:id,'shared','688018.SH','flip')"
                ),
                {"id": uuid.uuid4()},
            )
        with pytest.raises(RuntimeError, match="unowned_signal_events"):
            command.upgrade(cfg, "head")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM app.signal_events")).scalar_one() == 1
            assert conn.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one() not in {"0025", "0026"}
        engine.dispose()
    finally:
        # Prevent this task's Timescale background reconnect during owned DB teardown.
        with psycopg.connect(
            dbname="postgres", user="postgres", host=SOCKET, autocommit=True
        ) as admin:
            admin.execute(
                sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS false").format(sql.Identifier(name))
            )
            admin.execute(
                "SELECT pg_terminate_backend(pid,5000) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()",
                (name,),
            ).fetchall()
        generator.close()
        legacy.SOCKET = before


def test_ta31_actual_http_reset_unknown_expired_cross_user_and_enum(env: Any) -> None:
    from app.notify.transport import reset_reason

    engine, client, other, owner, stranger, _ = env
    now = dt.datetime.now(dt.UTC)
    r = redis.Redis.from_url(REDIS)
    reset_buffer(r)
    expired = publish(
        r, owner, "heartbeat", {"at": now.isoformat()}, now - dt.timedelta(seconds=601)
    )
    latest = publish(r, owner, "heartbeat", {"at": now.isoformat()}, now)
    for header, reason in [
        ("not-an-id", "unknown"),
        (str(int(latest) + 1), "unknown"),
        (expired, "expired"),
    ]:
        assert reset_reason(r, owner, header, now, latest) == reason
        messages = http_sse_once(client, header)
        assert messages[0]["status"] == 200
        body = b"".join(m.get("body", b"") for m in messages).decode()
        assert body.startswith("retry: 3000")
        assert "event: reset" in body
        assert json.dumps({"reason": reason, "latest_event_id": latest}) in body
    messages = http_sse_once(other, latest)
    body = b"".join(m.get("body", b"") for m in messages).decode()
    assert "event: reset" in body and '"latest_event_id": null' in body
    assert '"reason": "unknown"' in body
    assert reset_reason(r, owner, None, now, latest) is None
    assert client.get("/api/v1/meta/enums").json()["enums"]["notification_ref_type"] == [
        "signal",
        "plan_condition",
    ]
    with engine.begin() as conn, pytest.raises(ValueError, match="invalid_notification_ref"):
        append(
            conn,
            owner=owner,
            kind="system",
            severity="info",
            title="synthetic",
            body=None,
            code=None,
            target_type="none",
            target_id=None,
            ref_type="unsupported",
            ref_id=str(uuid.uuid4()),
            at=now,
        )
    r.close()


def test_actual_plan_condition_worker_notification_ref_route_and_replay(env: Any) -> None:
    from app.plans.worker import TASK
    from app.workers import jobs
    from selfchecks.test_p2n07_plans import (
        AT as PLAN_AT,
    )
    from selfchecks.test_p2n07_plans import (
        calendar,
        payload,
    )
    from selfchecks.test_p2n07_plans import (
        receipt as plan_receipt,
    )

    engine, client, other, owner, _, settings = env
    calendar(engine)
    body = payload(
        security_code="688073.SH",
        conditions=[
            {
                "kind": "trigger",
                "type": "price_below",
                "params": {"price": "10"},
                "description": "虚构价格条件",
            }
        ],
    )
    resp = client.post("/api/v1/plans", json=body)
    assert resp.status_code == 201
    identifier = resp.json()["id"]
    plan_receipt(engine, owner, "9")
    r = redis.Redis.from_url(REDIS)
    reset_buffer(r)
    for _ in range(2):
        jobs._push(
            r,
            TASK,
            {"user_id": str(owner), "as_of": (PLAN_AT + dt.timedelta(seconds=10)).isoformat()},
        )
        assert jobs.worker_tick(settings, client=r) == [(TASK, "ok")]
    rows = client.get("/api/v1/notifications").json()["items"]
    assert len(rows) == 1
    assert rows[0]["merged_count"] == 1 and rows[0]["version"] == 1
    assert rows[0]["refs"][0]["type"] == "plan_condition"
    assert rows[0]["refs"][0]["route"] == "/plans/" + identifier
    assert other.get("/api/v1/notifications").json()["items"] == []
    r.close()


def test_reviewed_synthetic_clock_operands_drive_db_bucket_boundaries(env: Any) -> None:
    from collections import Counter

    engine, _, _, owner, _, _ = env
    rows = json.loads((Path(__file__).parent / "fixtures/p2n06_ticks.json").read_text())
    expected = Counter()
    for row in rows:
        add(engine, owner, str(row["index"]), AT + dt.timedelta(seconds=row["offset_seconds"]))
        expected[row["offset_seconds"] // 600] += 1
    with engine.connect() as conn:
        actual = conn.execute(select(notifications).where(notifications.c.user_id == owner)).all()
        assert sorted(r.merged_count for r in actual) == sorted(expected.values())


def test_shared_commit_survives_one_instance_failure_and_recovery(
    seeded: Any, monkeypatch: Any
) -> None:
    from app.db.tables.realtime import intraday_candidate_refs, signal_events
    from app.db.tables.signals import candidate_signals
    from app.db.tables.strategy import strategy_instances
    from app.intraday import engine as rt

    engine, client, _, owner, _, settings, *_ = seeded
    good = seeded[-3]
    bad = uuid.uuid4()
    with engine.begin() as conn:
        inst = conn.execute(select(strategy_instances).where(strategy_instances.c.id == good)).one()
        conn.execute(insert(strategy_instances).values(**(dict(inst._mapping) | {"id": bad})))
    actual = rt.conclusion

    def fault(conn: Any, **kwargs: Any) -> Any:
        if kwargs["instance"].id == bad:
            raise RuntimeError("synthetic-instance-failure")
        return actual(conn, **kwargs)

    monkeypatch.setattr(rt, "conclusion", fault)
    rt.task(settings, receipt(seeded, "25", 0))
    rt.task(settings, receipt(seeded, "25", 5))
    rt.task(settings, receipt(seeded, "35", 10))
    event = receipt(seeded, "35", 15)
    assert rt.task(settings, event) == 1
    with engine.connect() as conn:
        assert len(conn.execute(select(signal_events)).all()) == 1
        assert len(conn.execute(select(candidate_signals)).all()) == 1
        assert len(conn.execute(select(intraday_candidate_refs)).all()) == 1
    monkeypatch.setattr(rt, "conclusion", actual)
    assert rt.task(settings, event) == 0
    with engine.connect() as conn:
        assert len(conn.execute(select(candidate_signals)).all()) == 2
        assert len(conn.execute(select(intraday_candidate_refs)).all()) == 2
        assert len(conn.execute(select(signal_events)).all()) == 1
    assert client.get("/api/v1/notifications/unread-count").json() == {"count": 1}


def test_real_trading_calendar_continuous_session_boundaries(seeded: Any) -> None:
    from zoneinfo import ZoneInfo

    from app.intraday.engine import session

    engine = seeded[0]
    with engine.connect() as conn:
        for stamp, expected in [
            ("2026-11-09T09:29:59", False),
            ("2026-11-09T09:30:00", True),
            ("2026-11-09T11:29:59", True),
            ("2026-11-09T11:30:00", False),
            ("2026-11-09T13:00:00", True),
            ("2026-11-09T15:00:00", False),
            ("2026-11-07T10:00:00", False),
            ("2032-01-05T10:00:00", False),
        ]:
            assert (
                session(
                    conn, dt.datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                )
                is expected
            )


def test_unknown_baseline_not_invented_flip_and_explicit_invalidation_immediate() -> None:
    from app.intraday.state import advance

    ref = {"rule_id": "synthetic", "passed": True, "role": "entry"}
    state, flips = advance({}, [ref], 2, True)
    assert flips == []
    state, flips = advance(state, [ref], 2, True)
    assert flips == [] and state["synthetic"]["value"] is True
    state, flips = advance(state, [dict(ref, passed=False)], 2, True)
    assert flips == []
    _, flips = advance(state, [dict(ref, passed=False)], 2, True)
    assert len(flips) == 1
    _, flips = advance({}, [dict(ref, role="invalidation")], 2, True)
    assert len(flips) == 1
