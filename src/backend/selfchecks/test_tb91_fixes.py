"""T-B91 only: synthetic identities/state, actual isolated PG/Redis/HTTP/worker."""

# ruff: noqa: S101, S108, ANN401, F811
from __future__ import annotations

import datetime as dt
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import redis
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as upsert

from app.db.tables.licences import user_data_licences
from app.db.tables.market import daily_bars, realtime_quotes, trading_calendar
from app.db.tables.notify import notifications
from app.db.tables.realtime import daily_reports, suggestions
from app.db.tables.research import action_plans, alerts
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import risk_events
from app.ingest.owned_quotes import record_quote
from app.plans.worker import check
from app.risk.rc1 import SH, assess, load
from app.signals.models import Stops
from app.workers import jobs
from selfchecks import test_p2n02_risk_controls as base
from selfchecks.test_p2n02_risk_controls import env, no_network  # noqa: F401
from selfchecks.test_p2n07_plans import payload

SOCKET = "/tmp/tb70-tb91-owned-socket"
REDIS = "unix:///tmp/tb91-owned-redis/redis.sock?db=0"
AT = dt.datetime(2026, 11, 9, 10, tzinfo=SH)


@pytest.fixture(scope="module")
def database() -> Any:
    old = base.SOCKET, base.REDIS
    base.SOCKET, base.REDIS = SOCKET, REDIS
    gen = base.database.__wrapped__()
    try:
        yield next(gen)
    finally:
        with suppress(StopIteration):
            next(gen)
        base.SOCKET, base.REDIS = old


def days(conn: Any, start: dt.date, end: dt.date) -> None:
    while start <= end:
        q = upsert(trading_calendar).values(date=start, is_open=start.weekday() < 5)
        conn.execute(
            q.on_conflict_do_update(index_elements=["date"], set_={"is_open": q.excluded.is_open})
        )
        start += dt.timedelta(days=1)


def licence(conn: Any, owner: uuid.UUID, at: dt.datetime = AT) -> uuid.UUID:
    identifier = uuid.uuid4()
    conn.execute(
        insert(user_data_licences).values(
            id=identifier,
            user_id=owner,
            status="active",
            tier="free",
            ciphertext=b"purely-synthetic-never-decrypted",
            seal_key_version=1,
            licence_hmac=uuid.uuid4().bytes + uuid.uuid4().bytes,
            created_at=at - dt.timedelta(days=3),
        )
    )
    return identifier


def quote(
    conn: Any,
    settings: Any,
    lid: uuid.UUID,
    last: str,
    prev: str | None,
    at: dt.datetime = AT,
    suspended: bool | None = False,
) -> uuid.UUID:
    return record_quote(
        conn,
        settings,
        licence_id=lid,
        code="688018.SH",
        observed_at=at,
        fetched_at=at,
        now=at,
        price=Decimal(last),
        prev_close=Decimal(prev) if prev else None,
        is_suspended=suspended,
    )


def test_reviewed_synthetic_operands_only() -> None:
    rows = json.loads((Path(__file__).parent / "fixtures/tb91_operands.json").read_text())
    assert len(rows) == 24
    assert [r["index"] for r in rows] == list(range(24))
    assert all(
        r["tag"] == "synthetic" and Decimal(r["last"]) > 0 and Decimal(r["prev_close"]) > 0
        for r in rows
    )


@pytest.mark.parametrize(
    ("kind", "threshold", "last", "prev", "expected"),
    [
        ("price_above", "10", "10", "10", True),
        ("price_below", "10", "10", "10", True),
        ("price_above", "10", "9.99", "10", False),
        ("pct_change", "10", "11", "10", True),
        ("pct_change", "-10", "9", "10", True),
        ("pct_change", "10", "219.9998", "200", False),
        ("pct_change", "10", "219.9999", "200", True),
        ("pct_change", "-10", "180.0002", "200", False),
        ("pct_change", "-10", "180.0001", "200", True),
        ("pct_change", "10", "11", None, None),
    ],
)
def test_actual_owned_production_adapter_signed_and_inclusive(
    env: Any, kind: str, threshold: str, last: str, prev: str | None, expected: bool | None
) -> None:
    engine, client, other, owner, _, settings = env
    body = payload(
        conditions=[
            {
                "kind": "trigger",
                "type": kind,
                "params": {"pct" if kind == "pct_change" else "price": threshold},
                "description": "纯合成条件",
            }
        ]
    )
    response = client.post("/api/v1/plans", json=body)
    assert response.status_code == 201, response.text
    pid = response.json()["id"]
    with engine.begin() as conn:
        days(conn, AT.date(), AT.date())
        lid = licence(conn, owner)
        sid = quote(conn, settings, lid, last, prev)
        assert quote(conn, settings, lid, last, prev) == sid
        result = check(conn, owner, AT + dt.timedelta(seconds=1), app_env="production")
        observed = next(o for o in result["observations"] if o["plan_id"] == pid)
        assert observed["passed"] is expected
        if expected is None:
            assert any(g.endswith(":prev_close") for g in result["gaps"])
        assert bool(result["triggered"]) is (expected is True)
        if expected:
            row = conn.execute(select(alerts).where(alerts.c.user_id == owner)).one()
            assert row.snapshot_id == sid
            assert row.what_happened["evidence_ids"]
            assert check(conn, owner, AT + dt.timedelta(seconds=2))["triggered"] == []
    assert other.get("/api/v1/plans/" + pid).status_code == 404


def test_missing_suspension_and_licence_revocation_refuse_not_shared_fallback(env: Any) -> None:
    engine, client, _, owner, _, settings = env
    response = client.post(
        "/api/v1/plans",
        json=payload(
            conditions=[
                {
                    "kind": "trigger",
                    "type": "price_above",
                    "params": {"price": "10"},
                    "description": "合成",
                }
            ]
        ),
    )
    assert response.status_code == 201
    with engine.begin() as conn:
        days(conn, AT.date(), AT.date())
        lid = licence(conn, owner)
        quote(conn, settings, lid, "11", "10", suspended=None)
        assert check(conn, owner, AT)["triggered"] == []
        quote(conn, settings, lid, "11", "10", at=AT + dt.timedelta(seconds=1))
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == lid)
            .values(status="paused_by_admin")
        )
        result = check(conn, owner, AT + dt.timedelta(seconds=2), app_env="production")
        assert not result["triggered"]
        assert any(g.endswith(":owned_quote_licence_unavailable") for g in result["gaps"])


def test_zero_pct_and_past_date_are_400_without_writes(env: Any) -> None:
    engine, client, _, owner, _, _ = env
    for kind, params in [
        ("pct_change", {"pct": "0"}),
        ("pct_change", {"pct": "-0.0000"}),
        ("date", {"on": str(dt.datetime.now(SH).date() - dt.timedelta(days=1))}),
    ]:
        response = client.post(
            "/api/v1/plans",
            json=payload(
                conditions=[
                    {"kind": "trigger", "type": kind, "params": params, "description": "合成"}
                ]
            ),
        )
        assert response.status_code == 400, response.text
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(action_plans)
                .where(action_plans.c.user_id == owner)
            ).scalar_one()
            == 0
        )


def test_actual_beat_redis_worker_date_rollover_0900_catchup_once(
    env: Any, monkeypatch: Any
) -> None:
    engine, client, _, owner, _, settings = env
    target = dt.date(2026, 11, 14)  # synthetic Saturday -> Monday16
    response = client.post(
        "/api/v1/plans",
        json=payload(
            conditions=[
                {
                    "kind": "trigger",
                    "type": "date",
                    "params": {"on": str(target)},
                    "description": "合成日期",
                }
            ]
        ),
    )
    assert response.status_code == 201, response.text
    with engine.begin() as conn:
        days(conn, target, target + dt.timedelta(days=9))
        before = check(conn, owner, dt.datetime(2026, 11, 16, 8, 59, tzinfo=SH))
        assert before["triggered"] == []
    at = dt.datetime(2026, 11, 21, 9, 1, tzinfo=SH)  # recovery on closed day
    original = jobs.schedule
    assert "plans.conditions_sweep" in original(settings)
    monkeypatch.setattr(
        jobs,
        "schedule",
        lambda s: {"plans.conditions_sweep": original(s)["plans.conditions_sweep"]},
    )
    monkeypatch.setattr(jobs, "_now", lambda: at)
    r = redis.Redis.from_url(REDIS)
    try:
        r.delete(jobs.QUEUE_KEY, jobs.DUE_PREFIX + "plans.conditions_sweep")
        assert jobs.beat_tick(settings, r) == ["plans.conditions_sweep"]
        assert ("plans.conditions_sweep", "ok") in jobs.worker_tick(settings, r)
        assert jobs.beat_tick(settings, r) == []
        jobs._push(r, "plans.conditions_sweep")
        assert ("plans.conditions_sweep", "ok") in jobs.worker_tick(settings, r)
        with engine.connect() as conn:
            alert = conn.execute(select(alerts).where(alerts.c.user_id == owner)).one()
            notice = conn.execute(
                select(notifications).where(notifications.c.user_id == owner)
            ).one()
            assert alert.triggered_at == at
            assert notice.kind == "plan_triggered"
            assert (
                alert.what_happened["evidence"][0]["value"]["scheduled_for"]
                == "2026-11-16T09:00:00+08:00"
            )
    finally:
        r.close()


def test_date_calendar_hole_unknown_and_exact_0900(env: Any) -> None:
    engine, client, _, owner, _, _ = env
    response = client.post(
        "/api/v1/plans",
        json=payload(
            conditions=[
                {
                    "kind": "trigger",
                    "type": "date",
                    "params": {"on": "2026-11-14"},
                    "description": "合成日期",
                }
            ]
        ),
    )
    assert response.status_code == 201
    with engine.begin() as conn:
        days(conn, dt.date(2026, 11, 14), dt.date(2026, 11, 16))
        conn.execute(
            delete(trading_calendar).where(trading_calendar.c.date == dt.date(2026, 11, 15))
        )
        assert check(conn, owner, AT.replace(day=16, hour=9))["triggered"] == []
        days(conn, dt.date(2026, 11, 15), dt.date(2026, 11, 15))
        assert len(check(conn, owner, AT.replace(day=16, hour=9))["triggered"]) == 1


def bar_pairs(
    conn: Any,
    at: dt.datetime,
    *,
    changed: bool = False,
    missing: bool = False,
    start: dt.date | None = None,
) -> None:
    first = start or dt.date(2026, 11, 6)
    days(conn, first, at.date())
    conn.execute(delete(daily_bars).where(daily_bars.c.code == "688018.SH"))
    cursor = first
    while cursor <= at.date():
        if cursor.weekday() < 5:
            fetched = min(dt.datetime.combine(cursor, dt.time(15), SH), at)
            for adj in ("none", "qfq"):
                if missing and adj == "qfq" and cursor == at.date():
                    continue
                value = (
                    Decimal(5) if adj == "qfq" and changed and cursor == at.date() else Decimal(10)
                )
                conn.execute(
                    insert(daily_bars).values(
                        code="688018.SH",
                        trade_date=cursor,
                        adj_type=adj,
                        open=value,
                        high=value,
                        low=value,
                        close=value,
                        fetched_at=fetched,
                    )
                )
        cursor += dt.timedelta(days=1)


@pytest.mark.parametrize("kind", ["normal", "changed", "missing", "future"])
def test_real_pit_price_basis_proves_continuity_or_remains_unknown(env: Any, kind: str) -> None:
    engine, _, _, owner, _, settings = env
    with engine.begin() as conn:
        aid = base.account(conn, owner, cash=Decimal(10000))
        bar_pairs(conn, AT, changed=kind == "changed", missing=kind == "missing")
        if kind == "future":
            conn.execute(
                update(daily_bars)
                .where(
                    daily_bars.c.code == "688018.SH",
                    daily_bars.c.trade_date == AT.date(),
                    daily_bars.c.adj_type == "qfq",
                )
                .values(fetched_at=AT + dt.timedelta(seconds=1))
            )
        conn.execute(delete(realtime_quotes).where(realtime_quotes.c.code == "688018.SH"))
        conn.execute(
            insert(realtime_quotes)
            .values(code="688018.SH", ts=AT, price=9, source="real_all", fetched_at=AT)
            .prefix_with("")
        )
        facts = load(
            conn,
            owner,
            aid,
            "688018.SH",
            settings,
            AT,
            stops_at=AT.replace(day=6, hour=16),
            position_known=True,
        )
        flags, evidence, gaps = assess(
            Stops(stop_loss=Decimal(9), take_profit=None, time_stop_days=None), facts, AT
        )
        assert facts.ex_rights is (
            False if kind == "normal" else True if kind == "changed" else None
        )
        assert bool(flags) is (kind == "normal")
        if flags:
            assert not flags[0].gated_actions
            assert any(e.key.startswith("rc1.price_basis:") for e in evidence)
            assert set(flags[0].evidence_ids) <= {e.id for e in evidence}
        else:
            assert gaps & {"stops_ex_rights", "rc1.stops_basis_unknown"}


@pytest.mark.parametrize(
    "mode", ["known", "cash_missing", "cost_estimate", "mixedcost", "uncomputable", "empty"]
)
def test_daily_actual_money_timestamp_and_empty_semantics(env: Any, mode: str) -> None:
    from app.db.tables.accounts import accounts, import_batches
    from app.db.tables.accounts import broker_position_snapshot_items as items
    from app.db.tables.accounts import broker_position_snapshots as snaps
    from app.reports.service import build

    engine, client, other, owner, _, _ = env
    now = dt.datetime.now(dt.UTC)
    stamp = now - dt.timedelta(days=2)
    if mode == "mixedcost":
        stamp = stamp.replace(hour=2, minute=0, second=0, microsecond=0)
    date = stamp.astimezone(SH).date()
    aid, batch, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        days(conn, date, date)
        if mode != "empty":
            conn.execute(
                insert(accounts).values(id=aid, user_id=owner, name="纯合成", created_at=stamp)
            )
            conn.execute(
                insert(import_batches).values(
                    id=batch, user_id=owner, account_id=aid, kind="positions", status="committed"
                )
            )
            conn.execute(
                insert(snaps).values(
                    id=sid,
                    account_id=aid,
                    import_batch_id=batch,
                    version_no=1,
                    cash_balance=None if mode in {"cash_missing", "uncomputable"} else 1000,
                    as_of=stamp,
                    created_at=stamp,
                )
            )
            conn.execute(
                insert(items).values(
                    id=uuid.uuid4(),
                    snapshot_id=sid,
                    security_code="688018.SH",
                    quantity=200,
                    broker_cost_price=None if mode == "uncomputable" else 8,
                    last_price_ref=10 if mode in {"known", "cash_missing"} else None,
                )
            )
        conn.execute(delete(daily_bars).where(daily_bars.c.code == "688018.SH"))
        if mode == "mixedcost":
            conn.execute(
                insert(items).values(
                    id=uuid.uuid4(),
                    snapshot_id=sid,
                    security_code="688073.SH",
                    quantity=200,
                    broker_cost_price=8,
                    last_price_ref=None,
                )
            )
            conn.execute(
                insert(daily_bars).values(
                    code="688018.SH",
                    trade_date=date,
                    adj_type="none",
                    open=12,
                    high=12,
                    low=12,
                    close=12,
                    fetched_at=dt.datetime.combine(date, dt.time(15), SH),
                )
            )
        rid = build(conn, owner, date, now)
        before = conn.execute(
            select(daily_reports.c.body).where(daily_reports.c.id == rid)
        ).scalar_one()
        account = before["account"]
        if mode in {"uncomputable", "empty"}:
            assert account is None
            assert before["data_as_of"] is None
            assert before["data_status"] == "unavailable"
            assert "account" in {g["key"] for g in before["gaps"]}
        else:
            assert (
                account["total_assets"]
                == {
                    "known": "3000.00",
                    "cash_missing": "2000.00",
                    "cost_estimate": "2600.00",
                    "mixedcost": "5000.00",
                }[mode]
            )
            assert account["cash"] == ("0.00" if mode == "cash_missing" else "1000.00")
            assert account["pnl_day"] is None
            assert dt.datetime.fromisoformat(before["data_as_of"]) == stamp
            assert before["data_status"] == "partial"
            if mode == "cash_missing":
                assert "cash" in {g["key"] for g in before["gaps"]}
        snapshots_before = conn.execute(
            select(func.count()).select_from(data_snapshots)
        ).scalar_one()
    response = client.get("/api/v1/daily-reports/" + str(date))
    assert response.status_code == 200, response.text
    assert other.get("/api/v1/daily-reports/" + str(date)).status_code == 404
    with engine.connect() as conn:
        assert (
            conn.execute(select(daily_reports.c.body).where(daily_reports.c.id == rid)).scalar_one()
            == before
        )
        assert (
            conn.execute(select(func.count()).select_from(data_snapshots)).scalar_one()
            == snapshots_before
        )


def test_legacy_report_projection_no_snapshot_rewrite(env: Any) -> None:
    from app.reports.service import build

    engine, client, _, owner, _, _ = env
    now = dt.datetime.now(dt.UTC)
    day = dt.date(2026, 11, 6)
    with engine.begin() as conn:
        days(conn, day, day)
        rid = build(conn, owner, day, now)
        body = dict(
            conn.execute(select(daily_reports.c.body).where(daily_reports.c.id == rid)).scalar_one()
        )
        body.pop("data_as_of")
        body["account"] = {
            "total_assets": None,
            "cash": None,
            "position_pct": None,
            "pnl_day": None,
            "position_vs_regime": None,
        }
        legacy = uuid.uuid4()
        conn.execute(
            insert(daily_reports).values(
                id=legacy,
                user_id=owner,
                trade_date=day,
                revision=100,
                status="partial",
                summary={"input_hash": uuid.uuid4().hex},
                body=body,
                generated_at=now,
            )
        )
    reply = client.get("/api/v1/daily-reports/" + str(day))
    assert reply.status_code == 200, reply.text
    assert reply.json()["account"] is None
    assert reply.json()["data_as_of"] is None
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(daily_reports.c.body).where(daily_reports.c.id == legacy)
            ).scalar_one()
            == body
        )


def test_actual_p1_dimensions_report_minimum_not_generated_clock(env: Any) -> None:
    from app.reports.service import build
    from selfchecks.test_p2n03_tracking import produced
    from selfchecks.test_p2n04_daily_dimensions import DATE, source

    prepared = produced.__wrapped__(env)
    source(prepared, bad_fund=True)
    engine, _, _, owner, _, _ = env
    with engine.begin() as conn:
        rid = build(conn, owner, DATE, dt.datetime.now(dt.UTC))
        body = conn.execute(
            select(daily_reports.c.body).where(daily_reports.c.id == rid)
        ).scalar_one()
        actual = [
            dt.datetime.fromisoformat(d["data_as_of"])
            for stock in body["stocks"]
            for d in stock["dimensions"]
            if d["facts"] and d["data_as_of"]
        ]
        assert actual
        stamp = dt.datetime.fromisoformat(body["data_as_of"])
        assert stamp <= min(actual)
        assert stamp < dt.datetime.fromisoformat(body["generated_at"])
        assert body["data_status"] == "partial"
        assert any(
            d["data_status"] == "unavailable"
            for stock in body["stocks"]
            for d in stock["dimensions"]
        )


def test_actual_rc1_beat_to_worker_trigger_clear_replay_readonly(
    env: Any, monkeypatch: Any
) -> None:
    from app.risk.worker import TASK
    from selfchecks.test_p2n03_tracking import produced

    engine, client, _, owner, _, settings = env
    prepared = produced.__wrapped__(env)
    from app.db.tables.strategy import strategy_instances, strategy_versions

    instance = prepared[7]
    # A NEW wholly fictional version supplies an explicit stop expression; the
    # existing immutable P1 output and null-stop fixture are not rewritten.
    with engine.begin() as conn:
        base_id = conn.execute(
            select(strategy_instances.c.strategy_version_id).where(
                strategy_instances.c.id == instance
            )
        ).scalar_one()
        original_version = conn.execute(
            select(strategy_versions).where(strategy_versions.c.id == base_id)
        ).one()
        spec = dict(original_version.config)
        spec["stops"] = {"stop_loss": "9", "take_profit": None, "time_stop_days": None}
        version = uuid.uuid4()
        conn.execute(
            insert(strategy_versions).values(
                id=version,
                strategy_id=original_version.strategy_id,
                card_version_id=original_version.card_version_id,
                version_no=2,
                config=spec,
                config_hash=version.hex,
                param_hash=version.hex,
                lifecycle="published",
            )
        )
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == instance)
            .values(strategy_version_id=version)
        )
    jobs.TASKS[jobs.ANALYZE](settings, user_id=str(owner), trade_date="2026-10-30")
    with engine.connect() as conn:
        suggestion = conn.execute(
            select(suggestions)
            .where(
                suggestions.c.user_id == owner,
                suggestions.c.strategies.contains([{"strategy_version_id": str(version)}]),
            )
            .order_by(suggestions.c.created_at.desc(), suggestions.c.id.desc())
            .limit(1)
        ).one()
    stop = Decimal(suggestion.strategies[0]["stops"]["stop_loss"])
    at = AT
    with engine.begin() as conn:
        bar_pairs(conn, at, start=suggestion.created_at.astimezone(SH).date())
        from app.db.tables.market import feature_bars_daily
        from app.db.tables.strategy import feature_catalog

        for key in ("f.limit_up_price", "f.limit_down_price"):
            q = upsert(feature_catalog).values(
                feature_key=key,
                unit="CNY_per_share",
                status="verified_live",
                source={"synthetic": True},
            )
            conn.execute(
                q.on_conflict_do_update(
                    index_elements=["feature_key"],
                    set_={"status": "verified_live", "source": {"synthetic": True}},
                )
            )
        conn.execute(
            insert(feature_bars_daily).values(
                code="688018.SH",
                trade_date=at.date(),
                feature_set_version=suggestion.feature_set_version,
                values={"f.limit_up_price": "12", "f.limit_down_price": "8"},
                computed_at=at,
            )
        )
        conn.execute(delete(realtime_quotes).where(realtime_quotes.c.code == "688018.SH"))
        conn.execute(
            insert(realtime_quotes).values(
                code="688018.SH", ts=at, price=stop, source="real_all", fetched_at=at
            )
        )
        before = conn.execute(
            select(func.count()).select_from(risk_events).where(risk_events.c.user_id == owner)
        ).scalar_one()
    original = jobs.schedule
    assert TASK in original(settings)
    monkeypatch.setattr(jobs, "schedule", lambda s: {TASK: original(s)[TASK]})
    clock = [at]
    monkeypatch.setattr(jobs, "_now", lambda: clock[0])
    r = redis.Redis.from_url(REDIS)
    try:
        r.delete(jobs.QUEUE_KEY, jobs.DUE_PREFIX + TASK)
        assert jobs.beat_tick(settings, r) == [TASK]
        assert (TASK, "ok") in jobs.worker_tick(settings, r)
        jobs._push(r, TASK)
        assert (TASK, "ok") in jobs.worker_tick(settings, r)
        with engine.connect() as conn:
            rows = conn.execute(
                select(risk_events).where(
                    risk_events.c.user_id == owner, risk_events.c.control == "stop_take"
                )
            ).all()
            assert len(rows) == 1
            event = rows[0].detail["payload"]
            assert event["status"] == "active"
            assert event["gated_actions"] == []
            assert any(e["key"].startswith("rc1.price_basis:") for e in event["evidence"])
        client.get("/api/v1/risk-controls/evaluation?security_code=688018.SH")
        clock[0] = at + dt.timedelta(seconds=1)
        with engine.begin() as conn:
            conn.execute(
                insert(realtime_quotes).values(
                    code="688018.SH",
                    ts=clock[0],
                    price=stop + Decimal("0.01"),
                    source="real_all",
                    fetched_at=clock[0],
                )
            )
        jobs._push(r, TASK)
        assert (TASK, "ok") in jobs.worker_tick(settings, r)
        with engine.connect() as conn:
            rows = conn.execute(
                select(risk_events)
                .where(risk_events.c.user_id == owner, risk_events.c.control == "stop_take")
                .order_by(risk_events.c.created_at)
            ).all()
            assert [row.detail["payload"]["status"] for row in rows] == ["active", "cleared"]
            assert before >= 0
        # Post-close path reuses the same job, real daily raw low/high and calendar.
        clock[0] = at.replace(hour=15, minute=1)
        with engine.begin() as conn:
            bar_pairs(conn, clock[0], start=suggestion.created_at.astimezone(SH).date())
            conn.execute(
                update(daily_bars)
                .where(daily_bars.c.code == "688018.SH", daily_bars.c.trade_date == at.date())
                .values(open=stop, high=stop, low=stop, close=stop)
            )
        jobs._push(r, TASK)
        assert (TASK, "ok") in jobs.worker_tick(settings, r)
        with engine.connect() as conn:
            last = conn.execute(
                select(risk_events)
                .where(risk_events.c.user_id == owner, risk_events.c.control == "stop_take")
                .order_by(risk_events.c.created_at.desc())
                .limit(1)
            ).one()
            assert last.detail["payload"]["status"] == "active"
            assert dt.datetime.fromisoformat(last.detail["payload"]["triggered_at"]) == at.replace(
                hour=15
            )

    finally:
        r.close()


@pytest.fixture
def generated_draft(env: Any) -> Any:
    from app.db.tables.market import feature_bars_daily
    from app.db.tables.signals import candidate_signals
    from app.db.tables.strategy import feature_catalog, market_rule_versions
    from selfchecks import test_tb74_candidates as old

    engine, client, _, owner, _, settings = env
    setup = old.setup.__wrapped__(env[:5], None)
    ids = []
    for _ in range(2):
        content = old.signal("sell").model_copy(
            update={
                "stops": Stops(
                    stop_loss=Decimal("22"), take_profit=Decimal("28"), time_stop_days=5
                ),
                "snapshot_id": uuid.uuid4(),
                "valid_until": dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
            }
        )
        persisted = old.persist(setup, content)
        assert persisted["id"] is not None
        ids.append(persisted["id"])
    now = dt.datetime.now(dt.UTC)
    with engine.begin() as conn:
        conn.execute(delete(daily_bars).where(daily_bars.c.code == "688018.SH"))
        lid = licence(conn, owner, now)
        quote(conn, settings, lid, "25", "25", now)
        for key in ("f.limit_up_price", "f.limit_down_price"):
            q = upsert(feature_catalog).values(
                feature_key=key,
                unit="CNY_per_share",
                status="verified_live",
                source={"synthetic": True},
            )
            conn.execute(
                q.on_conflict_do_update(
                    index_elements=["feature_key"],
                    set_={"status": "verified_live", "source": {"synthetic": True}},
                )
            )
        version = conn.execute(
            select(candidate_signals.c.feature_set_version).where(
                candidate_signals.c.id == uuid.UUID(ids[0])
            )
        ).scalar_one()
        q = upsert(feature_bars_daily).values(
            code="688018.SH",
            trade_date=now.astimezone(SH).date(),
            feature_set_version=version,
            values={"f.limit_up_price": "30", "f.limit_down_price": "20"},
            computed_at=now,
        )
        conn.execute(
            q.on_conflict_do_update(
                index_elements=["code", "trade_date", "feature_set_version"],
                set_={"values": q.excluded["values"], "computed_at": now},
            )
        )
        segment = settings.business.market_rules.segment_for(now.astimezone(SH).date())
        rules = segment.model_dump(mode="json")
        rules["fees"]["commission_rate_default_pct"] = "0.03"  # wholly fictional rate
        existing = conn.execute(
            select(market_rule_versions).where(
                market_rule_versions.c.effective_from == now.astimezone(SH).date()
            )
        ).first()
        if existing is None:
            conn.execute(
                insert(market_rule_versions).values(
                    id=uuid.uuid4(), effective_from=now.astimezone(SH).date(), rules=rules
                )
            )
        else:
            assert existing.rules == rules
    response = client.post("/api/v1/plan-drafts", json={"signal_ids": ids})
    assert response.status_code == 201, response.text
    draft = response.json()
    assert draft["status"] == "pending"
    assert len(draft["signal_ids"]) == 2
    answer = {
        "checklist_answers": [
            {"id": q["id"], "answer": "yes", "note": None} for q in draft["judgment_checklist"]
        ],
        "risk_ack": True,
        "chosen_qty": draft["qty_range"]["min"],
        "chosen_price": "25",
        "deviation_ack": False,
    }
    return env, draft, answer


def test_actual_generated_draft_to_confirm_and_owner_scope(generated_draft: Any) -> None:
    from app.db.tables.signals import candidate_signals, plan_drafts

    env, draft, answer = generated_draft
    engine, client, other, owner, _, _ = env
    path = "/api/v1/plan-drafts/" + draft["id"]
    assert other.get(path).status_code == 404
    confirmed = client.post(path + "/confirm", json=answer)
    assert confirmed.status_code == 201, confirmed.text
    assert client.post(path + "/confirm", json=answer).json() == confirmed.json()
    plan = client.get("/api/v1/plans/" + confirmed.json()["plan_id"])
    assert plan.status_code == 200
    assert plan.json()["origin"] == "plan_draft"
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(plan_drafts.c.status).where(plan_drafts.c.id == uuid.UUID(draft["id"]))
            ).scalar_one()
            == "confirmed"
        )
        assert set(
            conn.execute(
                select(candidate_signals.c.state).where(
                    candidate_signals.c.id.in_([uuid.UUID(v) for v in draft["signal_ids"]])
                )
            ).scalars()
        ) == {"confirmed"}
        assert (
            conn.execute(
                select(func.count())
                .select_from(action_plans)
                .where(action_plans.c.user_id == owner)
            ).scalar_one()
            == 1
        )


def test_actual_multi_signal_confirmation_mid_failure_rolls_back(
    generated_draft: Any, monkeypatch: Any
) -> None:
    from fastapi.testclient import TestClient

    from app.db.tables.signals import candidate_signals, plan_draft_confirmations, plan_drafts
    from app.main import create_app
    from app.plans import drafts

    env, draft, answer = generated_draft
    engine, client, _, owner, _, settings = env
    original = drafts.signal_transition
    count = [0]

    def fault(*args: Any, **kwargs: Any) -> Any:
        count[0] += 1
        if count[0] == 2:
            raise RuntimeError("synthetic_transaction_fault")
        return original(*args, **kwargs)

    monkeypatch.setattr(drafts, "signal_transition", fault)
    with TestClient(create_app(settings), raise_server_exceptions=False) as fault_client:
        fault_client.cookies.update(client.cookies)
        fault_client.headers.update({"X-CSRF-Token": client.headers["X-CSRF-Token"]})
        response = fault_client.post("/api/v1/plan-drafts/" + draft["id"] + "/confirm", json=answer)
        assert response.status_code == 500
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(action_plans)
                .where(action_plans.c.user_id == owner)
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                select(func.count())
                .select_from(plan_draft_confirmations)
                .where(plan_draft_confirmations.c.user_id == owner)
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                select(plan_drafts.c.status).where(plan_drafts.c.id == uuid.UUID(draft["id"]))
            ).scalar_one()
            == "pending"
        )
        assert set(
            conn.execute(
                select(candidate_signals.c.state).where(
                    candidate_signals.c.id.in_([uuid.UUID(v) for v in draft["signal_ids"]])
                )
            ).scalars()
        ) == {"drafted"}
    monkeypatch.setattr(drafts, "signal_transition", original)
    assert (
        client.post("/api/v1/plan-drafts/" + draft["id"] + "/confirm", json=answer).status_code
        == 201
    )


@pytest.mark.parametrize("same", [True, False])
def test_actual_confirmation_concurrent_identical_and_conflicting(
    generated_draft: Any, same: bool
) -> None:
    env, draft, answer = generated_draft
    engine, client, _, owner, _, _ = env
    other = dict(answer)
    if not same:
        other["deviation_ack"] = True  # distinct valid explicit acknowledgement

    def send(body: Any) -> Any:
        return client.post("/api/v1/plan-drafts/" + draft["id"] + "/confirm", json=body)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, [answer, other]))
    assert sorted(r.status_code for r in responses) == ([201, 201] if same else [201, 409])
    if same:
        assert responses[0].json() == responses[1].json()
    else:
        assert (
            next(r for r in responses if r.status_code == 409).json()["error"]["code"]
            == "IDEMPOTENCY_CONFLICT"
        )
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(action_plans)
                .where(action_plans.c.user_id == owner)
            ).scalar_one()
            == 1
        )


def test_reviewed_operands_drive_actual_version_rearm_and_owned_worker(env: Any) -> None:
    from fractions import Fraction

    engine, client, _, owner, _, settings = env
    rows = json.loads((Path(__file__).parent / "fixtures/tb91_operands.json").read_text())
    with engine.begin() as conn:
        days(conn, AT.date(), AT.date())
        lid = licence(conn, owner)
    pid, count = None, 0
    for index, row in enumerate(rows):
        body = payload(
            conditions=[
                {
                    "kind": "trigger",
                    "type": "price_above",
                    "params": {"price": row["prev_close"]},
                    "description": "已复核纯合成数值",
                }
            ]
        )
        if pid is None:
            response = client.post("/api/v1/plans", json=body)
            assert response.status_code == 201, response.text
            pid = response.json()["id"]
        else:
            body.update(base_version_no=index, change_reason="纯合成独立操作数重布防")
            response = client.post("/api/v1/plans/" + pid + "/versions", json=body)
            assert response.status_code == 201, response.text
        at = AT + dt.timedelta(seconds=index * 2)
        with engine.begin() as conn:
            quote(conn, settings, lid, row["last"], row["prev_close"], at)
            result = check(conn, owner, at + dt.timedelta(seconds=1), app_env="production")
            expected = Fraction(row["last"]) >= Fraction(row["prev_close"])
            assert result["observations"][0]["passed"] is expected
            assert len(result["triggered"]) == int(expected)
            count += int(expected)
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count()).select_from(alerts).where(alerts.c.user_id == owner)
            ).scalar_one()
            == count
        )


@pytest.mark.parametrize(("seconds", "expected"), [(30, True), (31, None)])
def test_owned_quote_exact_freshness_limit(env: Any, seconds: int, expected: bool | None) -> None:
    engine, client, _, owner, _, settings = env
    assert (
        client.post(
            "/api/v1/plans",
            json=payload(
                conditions=[
                    {
                        "kind": "trigger",
                        "type": "price_above",
                        "params": {"price": "10"},
                        "description": "合成",
                    }
                ]
            ),
        ).status_code
        == 201
    )
    with engine.begin() as conn:
        days(conn, AT.date(), AT.date())
        lid = licence(conn, owner)
        quote(conn, settings, lid, "10", "10")
        result = check(conn, owner, AT + dt.timedelta(seconds=seconds), app_env="production")
        assert result["observations"][0]["passed"] is expected


@pytest.mark.parametrize(("hour", "minute"), [(11, 30), (15, 0)])
def test_condition_uses_fresh_closing_ticks_not_half_open_window(
    env: Any, hour: int, minute: int
) -> None:
    engine, client, _, owner, _, settings = env
    assert (
        client.post(
            "/api/v1/plans",
            json=payload(
                conditions=[
                    {
                        "kind": "trigger",
                        "type": "price_above",
                        "params": {"price": "10"},
                        "description": "合成",
                    }
                ]
            ),
        ).status_code
        == 201
    )
    at = AT.replace(hour=hour, minute=minute)
    with engine.begin() as conn:
        days(conn, at.date(), at.date())
        lid = licence(conn, owner)
        quote(conn, settings, lid, "10", "10", at)
        assert len(check(conn, owner, at, app_env="production")["triggered"]) == 1


def test_ingest_role_source_and_other_owner_no_fallback(env: Any) -> None:
    from sqlalchemy import create_engine

    engine, client, _, owner, other, settings = env
    assert (
        client.post(
            "/api/v1/plans",
            json=payload(
                conditions=[
                    {
                        "kind": "trigger",
                        "type": "price_above",
                        "params": {"price": "10"},
                        "description": "合成",
                    }
                ]
            ),
        ).status_code
        == 201
    )
    with engine.begin() as conn:
        days(conn, AT.date(), AT.date())
        lid = licence(conn, other)
    # Original unchanged grants, actual separate ingest role, no keys decrypted.
    assert engine.url.query.get("host") == SOCKET
    ingest = create_engine(str(engine.url).replace("aia_api@", "aia_ingest@"), hide_parameters=True)
    try:
        with ingest.begin() as conn:
            source = quote(conn, settings, lid, "11", "10")
            stored = conn.execute(
                select(data_snapshots.c.user_id).where(data_snapshots.c.id == source)
            ).scalar_one()
            assert stored == other
        with engine.begin() as conn:
            result = check(conn, owner, AT, app_env="production")
            assert result["triggered"] == []
            assert any(g.endswith(":owned_quote_adapter_missing") for g in result["gaps"])
    finally:
        ingest.dispose()
