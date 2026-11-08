"""RC1 T-A26 only: synthetic prices/identity, isolated real PG/Redis, zero market calls."""

# ruff: noqa: S101, ANN401, F811
from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import insert, select

from app.db.tables.market import daily_bars, realtime_quotes
from app.db.tables.strategy import risk_events
from app.risk.evaluation import Inputs, assessed
from app.risk.events import record
from app.risk.rc1 import SH, Facts, assess, load, segment
from app.schemas.enums import Action, Horizon
from app.signals.models import Stops
from selfchecks.test_p2n02_risk_controls import database, env, no_network  # noqa: F401
from selfchecks.test_ta15_risk import STAR, context
from selfchecks.test_ta15_risk import config as hook_config

PAIRS = json.loads((Path(__file__).parent / "fixtures/ta26_price_pairs.json").read_text())
AT = dt.datetime(2026, 11, 2, 10, tzinfo=SH)
CAL = {dt.date(2026, 11, i): i not in {7, 8} for i in range(2, 11)}


@pytest.fixture(scope="module", autouse=True)
def own_redis() -> Any:
    from selfchecks import test_p2n02_risk_controls as prior

    old = prior.REDIS
    prior.REDIS = "unix:///tmp/ta26-redis/redis.sock?db=0"
    yield
    prior.REDIS = old


def facts(**kw: Any) -> Facts:
    return replace(
        Facts(
            observed_at=AT,
            last=Decimal(10),
            stale_seconds=30,
            ex_rights=False,
            held=True,
            start=AT.date(),
            calendar=CAL,
        ),
        **kw,
    )


def stops(loss: str | None = "9", take: str | None = "11", days: int | None = None) -> Stops:
    return Stops(
        stop_loss=Decimal(loss) if loss else None,
        take_profit=Decimal(take) if take else None,
        time_stop_days=days,
    )


@pytest.mark.parametrize("pair", PAIRS, ids=[p["label"] for p in PAIRS])
def test_reviewed_operands_independent_cent_comparison(pair: dict[str, str]) -> None:
    # DeepSeek supplies VALUES only; integer cents supplies the independent predicate.
    fs, ev, gaps = assess(stops(pair["boundary"], None), facts(last=Decimal(pair["observed"])), AT)
    assert bool(fs) == (
        int(Decimal(pair["observed"]) * 100) <= int(Decimal(pair["boundary"]) * 100)
    )
    assert not gaps
    assert all(not f.gated_actions and f.quantity_cap is None for f in fs)
    assert all(set(f.evidence_ids) <= {e.id for e in ev} for f in fs)


@pytest.mark.parametrize(
    "kind",
    [
        "loss",
        "profit",
        "both_close",
        "stale",
        "missing",
        "future",
        "exrights",
        "basis_unknown",
        "missing_calendar",
    ],
)
def test_price_boundaries_precedence_and_unknown(kind: str) -> None:
    f = facts()
    at = AT
    expected = "stop_loss"
    if kind == "loss":
        f.last = Decimal(9)
    elif kind == "profit":
        f.last = Decimal(11)
        expected = "take_profit"
    elif kind == "both_close":
        at = AT.replace(hour=16)
        f = replace(
            f,
            mode="close",
            low=Decimal(9),
            high=Decimal(11),
            observed_at=AT.replace(hour=15),
            fetched_at=at,
        )
    elif kind == "stale":
        f.observed_at = AT - dt.timedelta(seconds=31)
        expected = ""
    elif kind == "missing":
        f.last = None
        expected = ""
    elif kind == "future":
        f.observed_at = AT + dt.timedelta(seconds=1)
        expected = ""
    elif kind == "exrights":
        f.ex_rights = True
        expected = ""
    elif kind == "basis_unknown":
        f.ex_rights = None
        expected = ""
    else:
        f.calendar = {}
        expected = ""
    fs, ev, gaps = assess(stops(), f, at)
    assert bool(fs) == bool(expected)
    if expected:
        assert fs[0].message.endswith(expected)
        assert not gaps
        if kind == "both_close":
            assert (
                next(e for e in ev if e.key == "rc1.event_at:stop_loss").value
                == AT.replace(hour=15).isoformat()
            )
            assert all(e.fetched_at == at for e in ev)
    else:
        assert gaps


def test_exact_stale_threshold_is_fresh() -> None:
    fs, _, gaps = assess(
        stops(), facts(last=Decimal(9), observed_at=AT - dt.timedelta(seconds=30)), AT
    )
    assert len(fs) == 1
    assert not gaps


@pytest.mark.parametrize(
    ("hour", "minute", "expected"), [(14, 59, False), (15, 0, True), (16, 0, True)]
)
def test_day_zero_nth_trading_close_inclusive_suspension_counts(
    hour: int, minute: int, expected: bool
) -> None:
    # Stock suspended on Nov3 still counts: ONLY exchange calendar controls the clock.
    at = dt.datetime(2026, 11, 4, hour, minute, tzinfo=SH)
    fs, ev, gaps = assess(stops(None, None, 2), facts(), at)
    assert bool(fs) == expected
    assert not gaps
    if expected:
        assert (
            next(e for e in ev if e.key == "rc1.event_at:time_stop").value
            == "2026-11-04T15:00:00+08:00"
        )


@pytest.mark.parametrize(
    "case", ["no_start", "unknown_held", "calendar_hole", "closed_start", "future_start", "flat"]
)
def test_time_unknowns_and_no_holding_never_hit(case: str) -> None:
    f = facts()
    at = dt.datetime(2026, 11, 9, 16, tzinfo=SH)
    if case == "no_start":
        f.start = None
    elif case == "unknown_held":
        f.held = None
    elif case == "calendar_hole":
        f.calendar = {k: v for k, v in CAL.items() if k != dt.date(2026, 11, 7)}
    elif case == "closed_start":
        f.start = dt.date(2026, 11, 7)
    elif case == "future_start":
        f.start = dt.date(2026, 11, 10)
    else:
        f.held = False
    fs, _, gaps = assess(stops(None, None, 1), f, at)
    assert not fs
    assert bool(gaps) == (case != "flat")


def test_ledger_clear_then_reopen_and_unknown_origin() -> None:
    def trade(day: int, side: str, qty: int) -> dict[str, Any]:
        return {
            "trade_date": dt.date(2026, 11, day),
            "traded_at": dt.datetime(2026, 11, day, 10, tzinfo=SH),
            "side": side,
            "quantity": Decimal(qty),
        }

    rows = [trade(2, "buy", 100), trade(3, "sell", 100), trade(4, "buy", 200)]
    assert segment(rows, Decimal(200)) == dt.date(2026, 11, 4)
    assert segment(rows, Decimal(300)) is None
    assert segment(rows[1:], Decimal(100)) is None
    assert segment([trade(2, "buy", 100), trade(2, "sell", 100)], Decimal(0)) is None


@pytest.mark.parametrize("action", list(Action))
def test_rc1_trigger_never_adds_action_gates(action: Action) -> None:
    ctx = context()
    for key, val in [("limit_down_price", "8"), ("limit_up_price", "12")]:
        ctx.observations[key] = ctx.observations["price"].model_copy(
            update={"id": key, "key": key, "value": val}
        )
    result, controls = assessed(
        hook_config("rc1_stop_take"),
        Inputs(None, ctx, STAR, True, [], facts(last=Decimal(9))),
        action=action,
        horizon=Horizon.SHORT,
        stops=stops(),
        at=AT,
    )
    assert controls[0]["state"] == "triggered"
    assert all(
        not f.gated_actions and f.quantity_cap is None
        for f in result.flags
        if f.control == "stop_take"
    )


def test_real_raw_cache_sources_and_close_timestamp(env: Any) -> None:
    engine, _, _, owner, _, settings = env
    with engine.begin() as conn:
        from app.aggregates.calendar import seed_calendar
        from app.reference_files import load_reference_file

        seed_calendar(
            conn,
            load_reference_file(
                Path(__file__).resolve().parents[3] / "config", "trading_calendar.json"
            ),
        )
        conn.execute(
            insert(realtime_quotes).values(
                code="688018.SH", ts=AT, price=9, source="ssjy_more", fetched_at=AT
            )
        )
        f = load(conn, owner, None, "688018.SH", settings, AT, stops_at=AT, position_known=False)
        fs, _, _ = assess(stops(), f, AT)
        assert fs[0].message.endswith("stop_loss")
        assert f.endpoint == "market.realtime_quotes:raw"
        # Raw and qfq rows intentionally disagree: qfq must never trigger RC1.
        at = AT.replace(hour=16)
        for adjust, low, high in [
            ("none", Decimal(9), Decimal(11)),
            ("qfq", Decimal(1), Decimal(2)),
        ]:
            conn.execute(
                insert(daily_bars).values(
                    code="688018.SH",
                    trade_date=AT.date(),
                    adj_type=adjust,
                    open=(low + high) / 2,
                    low=low,
                    high=high,
                    close=(low + high) / 2,
                    fetched_at=at,
                )
            )
        f = load(conn, owner, None, "688018.SH", settings, at, stops_at=at, position_known=False)
        fs, _ev, gaps = assess(stops(), f, at)
        assert len(fs) == 1
        assert fs[0].message.endswith("stop_loss")
        assert not gaps
        assert f.low == 9
        assert f.high == 11
        assert f.observed_at == AT.replace(hour=15)
        old = load(conn, owner, None, "688018.SH", settings, at, stops_at=AT, position_known=False)
        assert old.ex_rights is None  # No canonical ex-rights proof: never invent false.


def test_real_events_trigger_clear_idempotent_and_current_clear_evidence(env: Any) -> None:
    engine, client, _, owner, _, _ = env
    ctx = context()
    for key, val in [("limit_down_price", "8"), ("limit_up_price", "12")]:
        ctx.observations[key] = ctx.observations["price"].model_copy(
            update={"id": key, "key": key, "value": val}
        )
    cfg = hook_config("rc1_stop_take")
    instance = uuid.uuid4()

    def evaluate(f: Facts, at: dt.datetime) -> tuple[Any, Any]:
        return assessed(
            cfg,
            Inputs(None, ctx, STAR, True, [], f),
            action=Action.SELL,
            horizon=Horizon.SHORT,
            stops=stops(),
            at=at,
        )

    def persist(f: Facts, at: dt.datetime) -> None:
        result, controls = evaluate(f, at)
        with engine.begin() as conn:
            record(
                conn,
                owner=owner,
                account_id=None,
                instance_id=instance,
                code="688018.SH",
                name="纯合成",
                controls=controls,
                evidence=[e.model_dump(mode="json") for e in result.evidence],
                at=at,
            )

    point = AT - dt.timedelta(seconds=2)
    persist(facts(last=Decimal(9), observed_at=point), AT)
    persist(facts(last=Decimal(9), observed_at=point), AT)
    persist(facts(ex_rights=None), AT + dt.timedelta(seconds=1))  # unknown never clears
    persist(
        facts(last=Decimal(10), observed_at=AT + dt.timedelta(seconds=2)),
        AT + dt.timedelta(seconds=2),
    )
    persist(
        facts(last=Decimal(10), observed_at=AT + dt.timedelta(seconds=2)),
        AT + dt.timedelta(seconds=2),
    )
    with engine.connect() as conn:
        rows = conn.execute(
            select(risk_events)
            .where(risk_events.c.user_id == owner)
            .order_by(risk_events.c.created_at)
        ).all()
        assert len(rows) == 2
        assert rows[0].detail["payload"]["triggered_at"] == point.isoformat()
        cleared = rows[1].detail["payload"]
        assert cleared["status"] == "cleared"
        assert "rc1.price_check" in {e["key"] for e in cleared["evidence"]}
        assert set(cleared["evidence_ids"]) == {e["id"] for e in cleared["evidence"]}
    before = len(rows)
    client.get("/api/v1/risk-controls/evaluation?security_code=688018.SH")
    with engine.connect() as conn:
        assert (
            len(conn.execute(select(risk_events).where(risk_events.c.user_id == owner)).all())
            == before
        )


def test_affected_defaults_remain_fixed_and_shape_matches_user_override(env: Any) -> None:
    from selfchecks.test_p2n02_risk_controls import (
        test_six_defaults_strict_atomic_partial_and_history,
    )

    test_six_defaults_strict_atomic_partial_and_history(env)


def test_affected_legacy_clamp_boundary() -> None:
    from selfchecks.test_p2n02_risk_controls import (
        test_rc1_prices_clamp_null_time_stop_gap_and_rc4_hundred,
    )

    test_rc1_prices_clamp_null_time_stop_gap_and_rc4_hundred()


def test_real_p1_worker_integration_compatibility(env: Any, monkeypatch: Any) -> None:
    from selfchecks.test_p2n02_risk_controls import (
        test_real_business_worker_settings_snapshot_events_and_readonly_projection,
    )

    test_real_business_worker_settings_snapshot_events_and_readonly_projection(env, monkeypatch)


@pytest.mark.parametrize(("hour", "expected"), [(14, False), (15, True)])
def test_weekend_not_counted_as_trading_day(hour: int, expected: bool) -> None:
    at = dt.datetime(2026, 11, 9, hour, tzinfo=SH)
    fs, _, gaps = assess(stops(None, None, 5), facts(), at)
    assert bool(fs) == expected
    assert not gaps


def test_actual_owned_ledger_segment_reopen_and_foreign_account_isolation(env: Any) -> None:
    from app.aggregates.calendar import seed_calendar
    from app.db.tables.accounts import accounts, trades
    from app.reference_files import load_reference_file

    engine, _, _, owner, other, settings = env
    aid = uuid.uuid4()
    at = dt.datetime(2026, 11, 6, 16, tzinfo=SH)
    with engine.begin() as conn:
        seed_calendar(
            conn,
            load_reference_file(
                Path(__file__).resolve().parents[3] / "config", "trading_calendar.json"
            ),
        )
        conn.execute(insert(accounts).values(id=aid, user_id=owner, name="纯合成段", created_at=AT))
        for day, side, qty in [(2, "buy", 200), (3, "sell", 200), (4, "buy", 400)]:
            stamp = AT.replace(day=day)
            conn.execute(
                insert(trades).values(
                    id=uuid.uuid4(),
                    account_id=aid,
                    user_id=owner,
                    security_code="688018.SH",
                    side=side,
                    quantity=qty,
                    price=10,
                    amount=qty * 10,
                    trade_date=stamp.date(),
                    traded_at=stamp,
                    source="manual",
                    created_at=stamp,
                )
            )
        # Real importing updates BOTH trades and the rebuilt holdings projection.
        pending = load(
            conn, owner, aid, "688018.SH", settings, at, stops_at=AT, position_known=True
        )
        assert pending.held is None
        assert pending.start is None
        from app.importing.pipeline import rebuild_holdings

        rebuild_holdings(conn, aid)
        f = load(conn, owner, aid, "688018.SH", settings, at, stops_at=AT, position_known=True)
        assert f.held is True
        assert f.start == dt.date(2026, 11, 4)
        fs, ev, gaps = assess(stops(None, None, 2), f, at)
        assert len(fs) == 1
        assert not gaps
        assert (
            next(e for e in ev if e.key == "rc1.event_at:time_stop").value
            == "2026-11-06T15:00:00+08:00"
        )
        other_f = load(
            conn, other, aid, "688018.SH", settings, at, stops_at=AT, position_known=True
        )
        assert other_f.held is None
        assert other_f.start is None


def test_opening_balance_origin_unknown_until_explicit_flat_then_reopen() -> None:
    rows = [
        {
            "trade_date": dt.date(2026, 11, 3),
            "traded_at": None,
            "side": "sell",
            "quantity": Decimal(200),
        },
        {
            "trade_date": dt.date(2026, 11, 4),
            "traded_at": None,
            "side": "buy",
            "quantity": Decimal(400),
        },
    ]
    assert segment(rows, Decimal(400), Decimal(200)) == dt.date(2026, 11, 4)
    assert segment(rows[1:], Decimal(600), Decimal(200)) is None


@pytest.mark.parametrize("invalid", [0, -1])
def test_nonpositive_legacy_stop_price_is_unknown_not_trigger(invalid: int) -> None:
    fs, _, gaps = assess(stops(str(invalid), "11"), facts(last=Decimal(12)), AT)
    assert not fs
    assert "rc1.invalid_stop_price" in gaps


@pytest.mark.parametrize("invalid", [0, -1])
def test_nonpositive_legacy_days_do_not_index_or_invent_day_zero_trigger(invalid: int) -> None:
    fs, _, gaps = assess(stops(None, None, invalid), facts(), AT)
    assert not fs
    assert "rc1.invalid_time_stop_days" in gaps


def test_multiple_strategy_threshold_evidence_never_overwrites() -> None:
    ctx = context()
    for key, val in [("limit_down_price", "8"), ("limit_up_price", "12")]:
        ctx.observations[key] = ctx.observations["price"].model_copy(
            update={"id": key, "key": key, "value": val}
        )
    results = []
    for threshold in ["9", "10"]:
        result, _ = assessed(
            hook_config("rc1_stop_take"),
            Inputs(None, ctx, STAR, True, [], facts(last=Decimal("8.5"))),
            action=Action.HOLD,
            horizon=Horizon.SHORT,
            stops=stops(threshold, "11"),
            at=AT,
        )
        results.append(result)
    merged = {e.id: e for result in results for e in result.evidence}
    for result, threshold in zip(results, ["9", "10"], strict=True):
        flag = next(f for f in result.flags if f.control == "stop_take")
        referred = [merged[i] for i in flag.evidence_ids]
        assert next(e for e in referred if e.key == "rc1.stop_loss").value == threshold


def test_rc1_default_fixed_same_shape_user_override_and_readonly_400(env: Any) -> None:
    client = env[1]
    before = client.get("/api/v1/risk-controls").json()

    def shape(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: shape(v) for k, v in value.items()}
        if isinstance(value, list):
            return [shape(v) for v in value]
        return type(value).__name__

    assert all(shape(r["params"]) == shape(r["default"]) for r in before)
    default = before[0]["default"]
    assert default == {"long_horizon_default_stop_pct": "-20", "clamp_to_price_limit": True}
    body = {
        "control": "stop_take",
        "enabled": False,
        "params": {"long_horizon_default_stop_pct": "-25", "clamp_to_price_limit": False},
    }
    response = client.put("/api/v1/risk-controls", json=[{**body, "default": default}])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get("/api/v1/risk-controls").json() == before
    response = client.put("/api/v1/risk-controls", json=[body])
    assert response.status_code == 200
    changed = client.get("/api/v1/risk-controls").json()[0]
    assert changed["source"] == "user"
    assert changed["enabled"] is False
    assert changed["default"] == default
    assert changed["params"] != default
    assert "enabled" not in changed["default"]
