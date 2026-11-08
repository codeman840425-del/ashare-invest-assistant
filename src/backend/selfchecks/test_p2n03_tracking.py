"""Direct tracking tests only, synthetic clock/data; no real market/certificates.

The 20 decimal pairs are reviewed DeepSeek draft VALUES, never expected answers.
Run with explicit network=none p2n03 PG/Redis; every DB is created/dropped here.
"""

# ruff: noqa: S101, S108, ANN401, F811
from __future__ import annotations

import datetime as dt
import json
import uuid
from argparse import Namespace
from collections.abc import Iterator
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any

import psycopg
import pytest
import redis
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.tables.market import daily_bars, trading_calendar
from app.db.tables.realtime import suggestion_tracking, suggestions
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import feature_catalog, strategies, strategy_instances
from app.tracking.engine import BEIJING, close_at, direction, due_date, evaluate, interval_return
from app.tracking.service import OBS_SCHEMA, digest, stat
from app.tracking.worker import TASK
from app.workers import jobs
from app.workers.daily import ANALYZE
from selfchecks.test_p2n02_risk_controls import env, no_network  # noqa: F401
from selfchecks.test_tb89_full_migrations import deploy_grants

ROOT = Path(__file__).resolve().parents[3]
SOCKET = "/tmp/tb70-p2n03-pg-socket"
REDIS = "unix:///tmp/p2n03-redis/redis.sock?db=0"
PAIRS = json.loads((Path(__file__).parent / "fixtures/p2n03_arithmetic.json").read_text())


@pytest.fixture(scope="module")
def database() -> Iterator[str]:
    # env's Redis reference is explicitly rebound to THIS dedicated server.
    from selfchecks import test_p2n02_risk_controls as shared

    before = shared.REDIS
    shared.REDIS = REDIS
    name = "tb70_p2n03_" + uuid.uuid4().hex
    url = "postgresql+psycopg://postgres@/" + name + "?host=" + SOCKET
    assert Path(SOCKET + "/.s.PGSQL.5432").exists()
    with psycopg.connect(dbname="postgres", user="postgres", host=SOCKET, autocommit=True) as admin:
        assert admin.execute("SHOW listen_addresses").fetchone() == ("",)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            cfg = Config()
            cfg.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
            cfg.cmd_opts = Namespace(x=["url=" + url])
            command.upgrade(cfg, "head")
            engine = create_engine(url, hide_parameters=True)
            with engine.begin() as conn:
                deploy_grants(conn)
                from app.db.tables.market import securities

                for code in ["688018.SH", "688073.SH", "300364.SZ", "301218.SZ"]:
                    conn.execute(
                        insert(securities).values(
                            code=code,
                            name="纯合成",
                            type="stock",
                            exchange=code[-2:],
                            board="star" if code[:3] == "688" else "chinext",
                            listing_status="listed",
                        )
                    )
            engine.dispose()
            yield url.replace("postgres@", "aia_api@")
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            shared.REDIS = before


def sample() -> dict[str, Any]:
    start = dt.date(2031, 1, 3)
    calendar = {
        start + dt.timedelta(days=i): i not in {1, 2, 8, 9, 15, 16, 22, 23} for i in range(35)
    }
    opened = [d for d, yes in calendar.items() if yes and d > start]
    bars, indices, facts = [], [], {}
    for i, day in enumerate(opened):
        clock = close_at(day)
        for target, value in [(bars, Decimal(100) + i), (indices, Decimal(100) + Decimal(i) / 2)]:
            target.append(
                {
                    "trade_date": day.isoformat(),
                    "open": str(value),
                    "high": str(value + 2),
                    "low": str(value - 1),
                    "close": str(value + 1),
                    "amount": "10000",
                    "first_seen_at": clock.isoformat(),
                    "is_final": True,
                }
            )
        facts[day.isoformat()] = {
            "is_suspended": False,
            "limit_locked_up": False,
            "limit_locked_down": False,
        }
    instrument = {
        "adjust": "none",
        "currency": "CNY",
        "price_unit": "CNY/share",
        "amount_unit": "CNY",
        "volume_unit": "share",
        "bars": bars,
    }
    return {
        "conclusion": {
            "strategy_version_id": uuid.uuid4(),
            "instance_id": uuid.uuid4(),
            "action": "buy",
        },
        "created": dt.datetime.combine(start, dt.time(17), BEIJING),
        "period": 1,
        "calendar": calendar,
        "instrument": instrument,
        "benchmark": {"bars": indices},
        "factors": [
            {"date": start.isoformat(), "available_at": close_at(start).isoformat(), "value": "1"}
        ],
        "facts": facts,
        "forced_hold": False,
        "now": close_at(opened[-1]),
    }


@pytest.mark.parametrize("pair", PAIRS, ids=[p["label"] for p in PAIRS])
def test_reviewed_arithmetic_pair_with_independent_fraction_oracle(pair: dict[str, str]) -> None:
    result = interval_return(Decimal(pair["start"]), Decimal(pair["end"]))
    exact = (Fraction(pair["end"]) - Fraction(pair["start"])) * 100 / Fraction(pair["start"])
    with localcontext() as ctx:
        ctx.prec = 64
        expected = Decimal(exact.numerator) / Decimal(exact.denominator)
        assert abs(result - expected) < Decimal("1e-58")


@pytest.mark.parametrize("period", [1, 5, 20])
def test_real_calendar_boundaries_entry_reference_independent_qfq_and_benchmark(
    period: int,
) -> None:
    args = sample()
    args["period"] = period
    due = due_date(args["created"], period, args["calendar"])
    args["now"] = close_at(due) - dt.timedelta(microseconds=1)
    assert evaluate(**args).state == "pending"
    args["now"] = close_at(due)
    result = evaluate(**args)
    assert result.state == "complete"
    assert result.entry_at.date() == due_date(args["created"], 1, args["calendar"])
    assert result.exit_at == close_at(due)
    assert result.entry_price == Decimal(100)
    assert result.benchmark_entry_price == Decimal(100)
    assert result.return_pct == Decimal(period)
    assert result.direction_correct == (result.excess_pct > 0)
    assert not result.cost_applied
    assert set(result.evidence_ids) == {e.id for e in result.evidence}
    # Corporate-action fixture: rebase BOTH endpoints to identical qfq@due.
    if period > 1:
        args["factors"].append(
            {"date": due.isoformat(), "available_at": close_at(due).isoformat(), "value": "2"}
        )
        # Explicit fictional two-for-one ex-rights action: raw prices halve
        # on the event day while same-asof qfq return is continuous.
        event = next(r for r in args["instrument"]["bars"] if r["trade_date"] == due.isoformat())
        for field in ["open", "high", "low", "close"]:
            event[field] = str(Decimal(event[field]) / 2)
        adjusted = evaluate(**args)
        assert adjusted.entry_price == Decimal(50)
        assert adjusted.exit_price == result.exit_price / 2
        assert adjusted.return_pct == result.return_pct


@pytest.mark.parametrize(
    ("action", "excess", "expected"),
    [
        ("buy", "1", True),
        ("add", "-1", False),
        ("sell", "-1", True),
        ("reduce", "1", False),
        ("hold", "1", True),
        ("hold", "1.01", False),
        ("wait", "1", None),
    ],
)
def test_six_actions_direction_not_inverted(
    action: str, excess: str, expected: bool | None
) -> None:
    assert direction(action, Decimal(excess), 1) is expected


@pytest.mark.parametrize(
    "case", ["suspended", "up", "down", "forced", "hold_suspended", "wait", "unknown"]
)
def test_untradable_excluded_unknown_never_enter_valid_n(case: str) -> None:
    args = sample()
    day = due_date(args["created"], 1, args["calendar"]).isoformat()
    expected = "untradable"
    if case == "suspended":
        args["facts"][day]["is_suspended"] = True
    elif case == "up":
        args["facts"][day]["limit_locked_up"] = True
    elif case == "down":
        args["conclusion"]["action"] = "sell"
        args["facts"][day]["limit_locked_down"] = True
    elif case == "forced":
        args["conclusion"]["action"] = "hold"
        args["forced_hold"] = True
        expected = "excluded"
    elif case == "hold_suspended":
        args["conclusion"]["action"] = "hold"
        args["facts"][day]["is_suspended"] = True
        expected = "untradable"
    elif case == "wait":
        args["conclusion"]["action"] = "wait"
        expected = "excluded"
    else:
        args["facts"][day]["is_suspended"] = None
        expected = "unavailable"
    result = evaluate(**args)
    assert result.state == expected
    assert result.direction_correct is None
    if expected in {"untradable", "excluded"}:
        assert result.exclusion_reason


def test_missing_benchmark_factors_calendar_and_future_knowledge() -> None:
    args = sample()
    args["benchmark"]["bars"] = []
    result = evaluate(**args)
    assert result.state == "complete"
    assert result.return_pct is not None
    assert result.excess_pct is None
    assert result.direction_correct is None
    args["factors"][0]["available_at"] = (args["now"] + dt.timedelta(days=1)).isoformat()
    assert evaluate(**args).state == "unavailable"
    args["calendar"].pop(args["created"].date() + dt.timedelta(days=1))
    with pytest.raises(ValueError, match="tracking_calendar_not_covered"):
        evaluate(**args)


def test_intraday_next_minute_open_and_no_unverified_qfq_bridge() -> None:
    args = sample()
    args["created"] = args["created"].replace(hour=10, minute=0, second=20)
    args["minutes"] = [{"ts": args["created"].replace(minute=2, second=0), "open": Decimal(100)}]
    result = evaluate(**args)
    assert result.entry_at == args["created"].replace(minute=1, second=0)
    assert result.state == "unavailable"
    assert result.entry_price is None
    assert "minute_qfq_bridge_unverified" in {g.key for g in result.gaps}


def test_stat_thresholds_and_no_auto_feedback() -> None:
    for count in [0, 1, 4, 5, 29, 30]:
        result = stat([Decimal(2)] * count, "synthetic")
        assert result.n == count
        assert (result.value is None) == (count < 5)
        assert result.small_sample == (count < 30)


@pytest.fixture
def produced(env: Any) -> Any:
    from selfchecks.test_tb74_candidates import setup as make_setup
    from selfchecks.test_tb76_assembly import prepare

    engine, _, _, owner, _, settings = env
    setup = make_setup.__wrapped__(env[:5], None)
    instance = prepare(setup)
    with engine.begin() as conn:
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == setup[6])
            .values(status="paused", paused_by="user")
        )
        conn.execute(
            pg_insert(feature_catalog)
            .values(
                feature_key="f.close_qfq",
                status="verified_live",
                source={"synthetic": True},
                unit="CNY/share",
            )
            .on_conflict_do_nothing()
        )
    jobs.TASKS[ANALYZE](settings, user_id=str(owner), trade_date="2026-10-30")
    with engine.connect() as conn:
        suggestion = conn.execute(select(suggestions).where(suggestions.c.user_id == owner)).one()
    return (*env, suggestion, instance)


def seed_market(env: Any, suggestion: Any) -> dt.datetime:
    engine, _, _, owner, _, _ = env
    with engine.begin() as conn:
        days = {r.date: r.is_open for r in conn.execute(select(trading_calendar))}
        due = due_date(suggestion.created_at, 20, days)
        opened = sorted(
            d for d, yes in days.items() if yes and suggestion.created_at.date() < d <= due
        )
        for i, day in enumerate(opened):
            for code, value in [
                (
                    "688018.SH",
                    (
                        suggestion.reference_price
                        if suggestion.reference_price is not None
                        else Decimal(100)
                    )
                    * Decimal("1.01")
                    * (1 + i / Decimal(200)),
                ),
                ("000300.SH", Decimal(100) + i / Decimal(4)),
            ]:
                conn.execute(
                    pg_insert(daily_bars)
                    .values(
                        code=code,
                        trade_date=day,
                        adj_type="none",
                        open=value,
                        high=value * Decimal("1.02"),
                        low=value * Decimal("0.99"),
                        close=value * Decimal("1.01"),
                        volume=2000,
                        amount=200000,
                        fetched_at=close_at(day),
                    )
                    .on_conflict_do_update(
                        index_elements=["code", "trade_date", "adj_type"],
                        set_={
                            "open": value,
                            "high": value * Decimal("1.02"),
                            "low": value * Decimal("0.99"),
                            "close": value * Decimal("1.01"),
                            "fetched_at": close_at(day),
                        },
                    )
                )
        for period in [1, 5, 20]:
            end = due_date(suggestion.created_at, period, days)
            content = {
                "schema_version": OBS_SCHEMA,
                "instruments": {
                    "688018.SH": {
                        "factors": [
                            {
                                "date": suggestion.created_at.date().isoformat(),
                                "available_at": suggestion.created_at.isoformat(),
                                "value": "1",
                            }
                        ],
                        "facts": {
                            d.isoformat(): {
                                "available_at": close_at(d).isoformat(),
                                "values": {
                                    "is_suspended": False,
                                    "limit_locked_up": False,
                                    "limit_locked_down": False,
                                },
                            }
                            for d in opened
                            if d <= end
                        },
                    }
                },
            }
            conn.execute(
                insert(data_snapshots).values(
                    id=uuid.uuid4(),
                    user_id=owner,
                    purpose="report",
                    hash=digest(content),
                    items=content,
                    created_at=close_at(end),
                )
            )
    return close_at(due) + dt.timedelta(hours=3)


def enqueue(settings: Any, owner: uuid.UUID, at: dt.datetime) -> list[tuple[str, str]]:
    client = redis.Redis.from_url(REDIS)
    try:
        assert client.llen(jobs.QUEUE_KEY) == 0
        jobs._push(client, TASK, {"user_id": str(owner), "as_of": at.isoformat()})
        return jobs.worker_tick(settings, client=client)
    finally:
        client.close()


def test_actual_p1_worker_tracking_snapshots_api_replay_pit_and_ownership(produced: Any) -> None:
    engine, client, stranger, owner, _other, settings, suggestion, instance = produced
    url = "/api/v1/suggestions/" + str(suggestion.id) + "/tracking"
    assert client.get(url).json()["results"] == []
    assert stranger.get(url).status_code == 404
    at = seed_market(produced[:6], suggestion)
    assert enqueue(settings, owner, at) == [(TASK, "ok")]
    response = client.get(url)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [r["horizon_days"] for r in body["results"]] == [1, 5, 20]
    assert all(r["state"] == "complete" for r in body["results"])
    assert all(Decimal(r["entry_price"]) != suggestion.reference_price for r in body["results"])
    assert all(r["instance_id"] == str(instance) for r in body["results"])
    assert all(
        body["t" + str(p)]["n"] == 1 and body["t" + str(p)]["value"] is None for p in [1, 5, 20]
    )
    with engine.begin() as conn:
        rows = conn.execute(
            select(suggestion_tracking).where(suggestion_tracking.c.suggestion_id == suggestion.id)
        ).all()
        assert len(rows) == 3
        snapshots = [r.snapshot_id for r in rows]
        conn.execute(
            update(daily_bars)
            .where(daily_bars.c.code == "688018.SH")
            .values(close=Decimal(999), fetched_at=at + dt.timedelta(days=1))
        )
    assert enqueue(settings, owner, at + dt.timedelta(days=2)) == [(TASK, "ok")]
    assert client.get(url).json() == body
    with engine.begin() as conn:
        assert [
            r.snapshot_id
            for r in conn.execute(
                select(suggestion_tracking).where(
                    suggestion_tracking.c.suggestion_id == suggestion.id
                )
            )
        ] == snapshots
        version = suggestion.strategies[0]["strategy_version_id"]
        from app.db.tables.strategy import strategy_versions

        strategy = conn.execute(
            select(strategy_versions.c.strategy_id).where(
                strategy_versions.c.id == uuid.UUID(version)
            )
        ).scalar_one()
        conn.execute(
            update(strategies).where(strategies.c.id == strategy).values(owner_user_id=None)
        )
    aggregate = f"/api/v1/strategies/{strategy}/versions/{version}/tracking"
    site = stranger.get(aggregate + "?scope=site").json()
    assert site["by_horizon"][0]["avg_return_pct"]["n"] == 1
    assert stranger.get(aggregate).json()["by_horizon"][0]["avg_return_pct"]["n"] == 0
    assert "688018" not in json.dumps(site)
    assert str(owner) not in json.dumps(site)
    assert "results" not in site


def test_no_skipping_missing_immediate_minute_or_lunch_break() -> None:
    args = sample()
    args["created"] = args["created"].replace(hour=10, minute=0, second=20)
    args["minutes"] = [{"ts": args["created"].replace(minute=3, second=0)}]
    result = evaluate(**args)
    assert result.entry_at is None
    assert "next_minute_bar" in {g.key for g in result.gaps}
    args["created"] = args["created"].replace(hour=11, minute=29, second=30)
    args["minutes"] = [{"ts": args["created"].replace(hour=13, minute=1, second=0)}]
    result = evaluate(**args)
    assert result.entry_at == args["created"].replace(hour=13, minute=0, second=0)
    assert result.state == "unavailable"  # No unverified minute qfq bridge.


def test_benchmark_future_revision_is_not_historical_knowledge() -> None:
    args = sample()
    due = due_date(args["created"], 1, args["calendar"])
    args["benchmark"]["bars"][0]["first_seen_at"] = (
        close_at(due) + dt.timedelta(days=1)
    ).isoformat()
    result = evaluate(**args)
    assert result.return_pct is not None
    assert result.benchmark_return_pct is None
    assert result.excess_pct is None
    assert "benchmark_prices" in {g.key for g in result.gaps}


def test_affected_p2n02_business_worker_remains_connected(env: Any, monkeypatch: Any) -> None:
    from selfchecks.test_p2n02_risk_controls import (
        test_real_business_worker_settings_snapshot_events_and_readonly_projection,
    )

    # The imported case expects a fresh global SYNTHETIC feature key. Nothing
    # is deleted from a shared DB: this fixture owns its networkless test DB.
    with env[0].begin() as conn:
        conn.execute(delete(feature_catalog).where(feature_catalog.c.feature_key == "f.close_qfq"))
    test_real_business_worker_settings_snapshot_events_and_readonly_projection(env, monkeypatch)


def test_actual_multiple_strategy_versions_are_independently_persisted(env: Any) -> None:
    from selfchecks.test_tb74_candidates import setup as make_setup
    from selfchecks.test_tb76_assembly import prepare

    engine, client, _, owner, _, settings = env
    setup = make_setup.__wrapped__(env[:5], None)
    instances = {prepare(setup), prepare(setup)}
    with engine.begin() as conn:
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == setup[6])
            .values(status="paused", paused_by="user")
        )
        conn.execute(
            pg_insert(feature_catalog)
            .values(
                feature_key="f.close_qfq",
                status="verified_live",
                source={"synthetic": True},
                unit="CNY/share",
            )
            .on_conflict_do_nothing()
        )
    jobs.TASKS[ANALYZE](settings, user_id=str(owner), trade_date="2026-10-30")
    with engine.connect() as conn:
        suggestion = conn.execute(select(suggestions).where(suggestions.c.user_id == owner)).one()
    at = seed_market(env, suggestion)
    assert enqueue(settings, owner, at) == [(TASK, "ok")]
    body = client.get(f"/api/v1/suggestions/{suggestion.id}/tracking").json()
    assert len(body["results"]) == 6
    for period in [1, 5, 20]:
        subset = [r for r in body["results"] if r["horizon_days"] == period]
        assert len({r["strategy_version_id"] for r in subset}) == 2
        assert {uuid.UUID(r["instance_id"]) for r in subset} == instances
        assert all(r["state"] == "complete" for r in subset)
        assert body["t" + str(period)]["n"] == 2
        assert body["t" + str(period)]["value"] is None


@pytest.mark.parametrize(("period", "threshold"), [(1, "1"), (5, "2"), (20, "5")])
@pytest.mark.parametrize("sign", [Decimal(1), Decimal(-1)])
def test_hold_band_exact_inclusive_and_epsilon_outside(
    period: int, threshold: str, sign: Decimal
) -> None:
    assert direction("hold", sign * Decimal(threshold), period) is True
    assert direction("hold", sign * (Decimal(threshold) + Decimal("0.000001")), period) is False


@pytest.mark.parametrize("action", ["buy", "add", "sell", "reduce"])
def test_zero_excess_is_not_a_direction_win(action: str) -> None:
    assert direction(action, Decimal(0), 1) is False


def test_last_minute_uses_next_session_but_never_raw_as_qfq() -> None:
    args = sample()
    args["created"] = args["created"].replace(hour=14, minute=59, second=30)
    day = due_date(args["created"], 1, args["calendar"])
    args["minutes"] = [{"ts": dt.datetime.combine(day, dt.time(9, 31), BEIJING)}]
    result = evaluate(**args)
    assert result.entry_at == dt.datetime.combine(day, dt.time(9, 30), BEIJING)
    assert result.state == "unavailable"
    assert result.entry_price is None


def test_api_empty_anonymous_foreign_unknown_version_and_no_get_side_effect(produced: Any) -> None:
    from fastapi.testclient import TestClient

    engine, client, stranger, _owner, _other, _settings, suggestion, _instance = produced
    url = f"/api/v1/suggestions/{suggestion.id}/tracking"
    with TestClient(client.app) as anonymous:
        assert anonymous.get(url).status_code == 401
    assert stranger.get(url).status_code == 404
    response = client.get(url)
    assert response.status_code == 200
    body = response.json()
    assert body["results"] == []
    assert body["t1"]["n"] == 0
    assert body["t1"]["value"] is None
    assert body["gaps"]
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(suggestion_tracking.c.suggestion_id).where(
                    suggestion_tracking.c.suggestion_id == suggestion.id
                )
            ).first()
            is None
        )
    # Contract checked from app, not presumed public OpenAPI URL configuration.
    paths = client.app.openapi()["paths"]
    assert "/api/v1/suggestions/{identifier}/tracking" in paths
    assert (
        client.get(
            f"/api/v1/strategies/{uuid.uuid4()}/versions/{uuid.uuid4()}/tracking"
        ).status_code
        == 404
    )


def test_pending_wall_clock_replay_keeps_same_rows_and_snapshot_ids(produced: Any) -> None:
    engine, client, _, owner, _, settings, suggestion, _ = produced
    seed_market(produced[:6], suggestion)
    at = suggestion.created_at + dt.timedelta(minutes=1)
    assert enqueue(settings, owner, at) == [(TASK, "ok")]
    path = f"/api/v1/suggestions/{suggestion.id}/tracking"
    before = client.get(path).json()
    assert all(r["state"] == "pending" for r in before["results"])

    def ids() -> list[Any]:
        with engine.connect() as conn:
            return (
                conn.execute(
                    select(suggestion_tracking.c.snapshot_id)
                    .where(suggestion_tracking.c.suggestion_id == suggestion.id)
                    .order_by(suggestion_tracking.c.horizon_days)
                )
                .scalars()
                .all()
            )

    snapshots = ids()
    assert len(snapshots) == 3
    assert enqueue(settings, owner, at + dt.timedelta(minutes=5)) == [(TASK, "ok")]
    assert ids() == snapshots
    assert client.get(path).json() == before


def test_actual_minute_cache_rejects_future_timestamp_and_future_fetch(env: Any) -> None:
    from app.db.tables.market import minute_bars
    from app.tracking.service import minutes

    day = dt.date(2026, 11, 2)
    start = dt.datetime.combine(day, dt.time(10), BEIJING)
    with env[0].begin() as conn:
        for i, fetched in [(0, start), (1, start), (2, start + dt.timedelta(days=1))]:
            conn.execute(
                insert(minute_bars).values(
                    code="688018.SH",
                    ts=start + dt.timedelta(minutes=i),
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    volume=2000,
                    amount=200000,
                    source="pro_history",
                    fetched_at=fetched,
                )
            )
        assert [r["ts"] for r in minutes(conn, "688018.SH", day, start)] == [start]
        assert [
            r["ts"] for r in minutes(conn, "688018.SH", day, start + dt.timedelta(minutes=3))
        ] == [start, start + dt.timedelta(minutes=1)]
