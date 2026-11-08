"""Direct T-A27 synthetic / isolated checks; no real data or network."""

# ruff: noqa: S101, S108, ANN401, F811
from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.tables.realtime import suggestion_tracking, suggestions
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import (
    feature_catalog,
    strategies,
    strategy_instances,
    strategy_versions,
)
from app.tracking.engine import evaluate, path_metrics
from app.tracking.models import Result
from app.tracking.service import bind_instances, profit_loss
from app.tracking.worker import TASK
from app.workers import jobs
from app.workers.daily import ANALYZE
from selfchecks import test_p2n03_tracking as base
from selfchecks.test_p2n02_risk_controls import env, no_network  # noqa: F401
from selfchecks.test_p2n03_tracking import produced  # noqa: F401

OPERANDS = json.loads((Path(__file__).parent / "fixtures/ta27_paths.json").read_text())


@pytest.fixture(scope="module")
def database() -> Any:
    before = (base.SOCKET, base.REDIS)
    base.SOCKET, base.REDIS = ("/tmp/tb70-ta27-pg-socket", "unix:///tmp/ta27-redis/redis.sock?db=0")
    try:
        yield from base.database.__wrapped__()
    finally:
        base.SOCKET, base.REDIS = before


@pytest.mark.parametrize("row", OPERANDS, ids=[r["label"] for r in OPERANDS])
def test_reviewed_values_independent_all_pairs_fraction_oracle(row: Any) -> None:
    values = [Fraction(v) for v in row["values"]]
    worst = min(((b / a - 1) * 100 for i, a in enumerate(values) for b in values[i:]))
    best = max(Fraction(0), max((v / values[0] - 1) * 100 for v in values))

    def quantized(v: Any) -> Decimal:
        return (Decimal(v.numerator) / Decimal(v.denominator)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )

    assert path_metrics([Decimal(v) for v in row["values"]]) == (quantized(worst), quantized(best))


@pytest.mark.parametrize(
    ("prices", "expected"),
    [
        (["10", "12", "15"], ("0", "50")),
        (["10", "8", "6"], ("-40", "0")),
        (["10", "10", "10"], ("0", "0")),
        (["10", "20", "15"], ("-25", "100")),
        (["3", "2"], ("-33.3333", "0")),
    ],
)
def test_explicit_rise_fall_flat_peak_trough_and_four_places(prices: Any, expected: Any) -> None:
    assert path_metrics(list(map(Decimal, prices))) == tuple(map(Decimal, expected))


@pytest.mark.parametrize("bad", [[], ["0", "2"], ["-1", "2"], ["NaN"], ["Infinity"]])
def test_invalid_or_zero_denominator_not_calculated(bad: Any) -> None:
    with pytest.raises(ValueError, match="invalid_tracking_path"):
        path_metrics(list(map(Decimal, bad)))


@pytest.mark.parametrize("action", ["buy", "add", "sell", "reduce", "hold", "wait"])
def test_daily_close_path_not_high_low_or_action_inversion(action: Any) -> None:
    args = base.sample()
    args["period"] = 5
    args["conclusion"]["action"] = action
    for bar, price in zip(args["instrument"]["bars"][:5], [12, 20, 15, 18, 14], strict=True):
        bar.update(open="10", close=str(price), high="100", low="1")
    result = evaluate(**args)
    assert result.max_drawdown_pct == Decimal("-30.0000")
    assert result.max_runup_pct == Decimal("100.0000")
    assert len([e for e in result.evidence if e.key.startswith("path_qfq:")]) == 5
    assert "drawdown_runup_path_definition" not in {g.key for g in result.gaps}
    assert set(result.evidence_ids) <= {e.id for e in result.evidence}


def test_t1_only_two_points_and_missing_intermediate_skips_without_fill() -> None:
    args = base.sample()
    args["instrument"]["bars"][0].update(open="10", close="8", high="100", low="1")
    result = evaluate(**args)
    assert (result.max_drawdown_pct, result.max_runup_pct) == (Decimal("-20"), Decimal("0"))
    args["period"] = 5
    missing = args["instrument"]["bars"].pop(2)["trade_date"]
    result = evaluate(**args)
    assert result.max_drawdown_pct is not None
    assert result.max_runup_pct is not None
    assert "qfq_path_missing_sessions" in {g.key for g in result.gaps}
    assert missing in next(e.value for e in result.evidence if e.key == "path_skipped_sessions")
    assert all(e.key != "path_qfq:" + missing for e in result.evidence)


@pytest.mark.parametrize("endpoint", ["entry", "exit", "factor", "minute"])
def test_unknown_endpoints_or_bridge_preserve_null_gap(endpoint: Any) -> None:
    args = base.sample()
    if endpoint == "factor":
        args["factors"] = []
    elif endpoint == "minute":
        args["created"] = args["created"].replace(hour=10)
    else:
        args["period"] = 5
        args["instrument"]["bars"].pop(0 if endpoint == "entry" else 4)
    result = evaluate(**args)
    assert result.max_drawdown_pct is None
    assert result.max_runup_pct is None
    assert result.gaps


def observation(value: Any, action: Any = "buy", state: Any = "complete") -> Result:
    return Result(
        strategy_version_id=uuid.uuid4(),
        instance_id=uuid.uuid4(),
        action=action,
        horizon_days=1,
        state=state,
        return_pct=Decimal(value),
        exclusion_reason="synthetic" if state in {"excluded", "untradable"} else None,
    )


@pytest.mark.parametrize(
    ("values", "expected", "n", "no_losses"),
    [
        (["2", "4", "6", "-2", "-4"], "1.3333", 5, False),
        (["-1"] * 5, "0", 5, False),
        (["1"] * 5, None, 5, True),
        (["0"] * 10, None, 0, True),
        (["1", "-1", "0"], None, 2, False),
        ([], None, 0, True),
    ],
)
def test_profit_loss_formula_exclusion_and_zero_denominator(
    values: Any, expected: Any, n: Any, no_losses: Any
) -> None:
    result, gaps = profit_loss([observation(v) for v in values], "1 trading days")
    assert result.value == (Decimal(expected) if expected is not None else None)
    assert result.n == n
    assert bool(gaps) is no_losses
    assert all(g.key == "no_losing_samples" for g in gaps)


def test_ratio_n_threshold_actions_and_states() -> None:
    base_rows = [observation("4", action="hold"), observation("2", action="add")]
    base_rows += [observation("-2") for _ in range(3)]
    ignored = [observation("999", action=a) for a in ["sell", "reduce", "wait"]]
    ignored += [
        observation("999", state=s) for s in ["pending", "excluded", "untradable", "unavailable"]
    ]
    result, gaps = profit_loss(base_rows + ignored, "5 trading days")
    assert result.n == 5
    assert result.value == Decimal("1.5000")
    assert result.small_sample
    assert not gaps
    assert profit_loss(base_rows[:4], "x")[0].value is None
    assert profit_loss(base_rows * 6, "x")[0].n == 30
    assert profit_loss(base_rows * 6, "x")[0].small_sample is False


def test_actual_worker_multiple_instances_earliest_then_uuid_and_frozen(env: Any) -> None:
    from selfchecks.test_tb74_candidates import setup as make_setup
    from selfchecks.test_tb76_assembly import prepare

    engine, client, stranger, owner, other, settings = env
    setup = make_setup.__wrapped__(env[:5], None)
    original = prepare(setup)
    earliest = uuid.UUID(int=2**128 - 2)
    tied = uuid.UUID(int=2**128 - 1)
    with engine.begin() as conn:
        template = dict(
            conn.execute(select(strategy_instances).where(strategy_instances.c.id == original))
            .one()
            ._mapping
        )
        version = template["strategy_version_id"]
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == setup[6])
            .values(status="paused", paused_by="user")
        )
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == original)
            .values(created_at=dt.datetime(2026, 10, 29, tzinfo=dt.UTC))
        )
        for identifier in [earliest, tied]:
            conn.execute(
                insert(strategy_instances).values(
                    **{
                        **template,
                        "id": identifier,
                        "created_at": dt.datetime(2026, 10, 28, tzinfo=dt.UTC),
                    }
                )
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
        generation = conn.execute(
            select(data_snapshots).where(data_snapshots.c.id == suggestion.snapshot_id)
        ).one()
        assert len(generation._mapping["items"]["input"]["conclusions"]) == 3
        with pytest.raises(ValueError, match="binding_unavailable"):
            bind_instances(conn, other, generation._mapping["items"]["input"]["conclusions"])
    at = base.seed_market(env, suggestion)
    assert base.enqueue(settings, owner, at) == [(TASK, "ok")]
    url = f"/api/v1/suggestions/{suggestion.id}/tracking"
    body = client.get(url).json()
    assert len(body["results"]) == 3
    assert all(r["instance_id"] == str(earliest) for r in body["results"])
    for row in body["results"]:
        assert row["max_drawdown_pct"] is not None
        assert row["max_runup_pct"] is not None
        assert {e["value"] for e in row["evidence"] if e["key"] == "other_instance"} == {
            str(original),
            str(tied),
        }
        assert body["t" + str(row["horizon_days"])]["n"] == 1
    with engine.connect() as conn:
        stored = conn.execute(
            select(data_snapshots)
            .join(suggestion_tracking, suggestion_tracking.c.snapshot_id == data_snapshots.c.id)
            .where(suggestion_tracking.c.suggestion_id == suggestion.id)
        ).all()
        assert all(
            r._mapping["items"]["algorithm_version"] == "p2n03-deterministic-ta27-v2"
            for r in stored
        )
        for r in stored:
            cutoff = dt.datetime.fromisoformat(r._mapping["items"]["as_of"])
            for bar in r._mapping["items"]["raw_stock"]["bars"]:
                assert dt.datetime.fromisoformat(bar["first_seen_at"]) <= cutoff
        strategy = conn.execute(
            select(strategy_versions.c.strategy_id).where(strategy_versions.c.id == version)
        ).scalar_one()
    with engine.begin() as conn:
        conn.execute(
            update(strategies).where(strategies.c.id == strategy).values(owner_user_id=None)
        )
        conn.execute(
            update(strategy_instances)
            .where(strategy_instances.c.id == original)
            .values(created_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC))
        )
    aggregate = f"/api/v1/strategies/{strategy}/versions/{version}/tracking"
    site = stranger.get(aggregate + "?scope=site").json()
    assert all(r["avg_return_pct"]["n"] == 1 for r in site["by_horizon"])
    assert all(
        r["profit_loss_ratio"]["n"] == 0 and r["profit_loss_ratio"]["value"] is None
        for r in site["by_horizon"]
    )
    assert all(r["action"] == "sell" for r in body["results"])
    assert "no_losing_samples" in {g["key"] for g in site["gaps"]}
    assert stranger.get(aggregate).json()["by_horizon"][0]["avg_return_pct"]["n"] == 0
    for secret in [str(owner), str(earliest), str(tied), "688018"]:
        assert secret not in json.dumps(site)
    assert stranger.get(url).status_code == 404
    assert base.enqueue(settings, owner, at + dt.timedelta(days=2)) == [(TASK, "ok")]
    assert client.get(url).json() == body


def test_existing_versions_do_not_merge(env: Any) -> None:
    base.test_actual_multiple_strategy_versions_are_independently_persisted(env)


def test_existing_frozen_pit_owner_api_path(produced: Any) -> None:
    base.test_actual_p1_worker_tracking_snapshots_api_replay_pit_and_ownership(produced)


def test_half_up_storage_and_future_intermediate_path_price() -> None:
    assert path_metrics([Decimal("100"), Decimal("101.23455")])[1] == Decimal("1.2346")
    assert path_metrics([Decimal("100"), Decimal("98.76545")])[0] == Decimal("-1.2346")
    args = base.sample()
    args["period"] = 5
    due = base.due_date(args["created"], 5, args["calendar"])
    args["now"] = base.close_at(due)
    bar = args["instrument"]["bars"][2]
    missing = bar["trade_date"]
    bar.update(
        close="999", high="1000", first_seen_at=(args["now"] + dt.timedelta(days=1)).isoformat()
    )
    result = evaluate(**args)
    assert result.max_runup_pct == Decimal("5.0000")
    assert result.max_drawdown_pct == Decimal("0.0000")
    assert all(e.key != "path_qfq:" + missing for e in result.evidence)
    assert "qfq_path_missing_sessions" in {g.key for g in result.gaps}


def test_api_ratio_reads_persisted_engine_observations_and_excludes_n(produced: Any) -> None:
    """Synthetic history fixture, not a claim of production collection/approval."""
    from app.tracking.service import SCHEMA, digest

    engine, client, stranger, owner, _other, _settings, suggestion, instance = produced
    version = uuid.UUID(suggestion.strategies[0]["strategy_version_id"])
    cases = [
        ("buy", 2, False),
        ("add", 4, False),
        ("hold", 6, False),
        ("buy", -2, False),
        ("buy", -4, False),
        ("buy", 0, False),
        ("sell", 10, False),
        ("wait", 1, False),
        ("buy", 1, True),
    ]
    with engine.begin() as conn:
        strategy = conn.execute(
            select(strategy_versions.c.strategy_id).where(strategy_versions.c.id == version)
        ).scalar_one()
        conn.execute(
            update(strategies).where(strategies.c.id == strategy).values(owner_user_id=None)
        )
        for seq, (action, change, suspended) in enumerate(cases, 2):
            args = base.sample()
            args["conclusion"].update(
                strategy_version_id=version, instance_id=instance, action=action
            )
            end = Decimal(100) + change
            args["instrument"]["bars"][0].update(
                open="100", close=str(end), high=str(max(100, end) + 1), low=str(min(100, end) - 1)
            )
            day = args["instrument"]["bars"][0]["trade_date"]
            args["facts"][day]["is_suspended"] = suspended
            result = evaluate(**args)
            identifier, snapshot = uuid.uuid4(), uuid.uuid4()
            body = {
                "schema_version": SCHEMA,
                "algorithm_version": "p2n03-deterministic-ta27-v2",
                "as_of": args["now"].isoformat(),
                "results": [result.model_dump(mode="json")],
                "raw_stock": args["instrument"],
                "raw_benchmark": args["benchmark"],
            }
            conn.execute(
                insert(suggestions).values(
                    **{
                        **dict(suggestion._mapping),
                        "id": identifier,
                        "seq_no": seq,
                        "status": "superseded",
                        "created_at": args["created"],
                    }
                )
            )
            conn.execute(
                insert(data_snapshots).values(
                    id=snapshot,
                    user_id=owner,
                    purpose="review",
                    hash=digest(body),
                    items=body,
                    created_at=args["now"],
                )
            )
            conn.execute(
                insert(suggestion_tracking).values(
                    suggestion_id=identifier,
                    horizon_days=1,
                    due_date=dt.date.fromisoformat(day),
                    status="done",
                    snapshot_id=snapshot,
                )
            )
        before = conn.execute(
            select(data_snapshots.c.id).where(data_snapshots.c.user_id == owner)
        ).all()
    url = f"/api/v1/strategies/{strategy}/versions/{version}/tracking"
    response = client.get(url)
    assert response.status_code == 200
    horizon = response.json()["by_horizon"][0]
    assert horizon["profit_loss_ratio"]["n"] == 5
    assert Decimal(horizon["profit_loss_ratio"]["value"]) == Decimal("1.3333")
    assert horizon["avg_return_pct"]["n"] == 7  # flat + sell count here, not in ratio.
    assert horizon["excluded_count"] == 1
    assert horizon["untradable_count"] == 1
    site = stranger.get(url + "?scope=site").json()
    assert site["by_horizon"] == response.json()["by_horizon"]
    assert stranger.get(url).json()["by_horizon"][0]["profit_loss_ratio"]["n"] == 0
    for private in [str(owner), str(instance), "688018"]:
        assert private not in json.dumps(site)
    with engine.connect() as conn:
        after = conn.execute(
            select(data_snapshots.c.id).where(data_snapshots.c.user_id == owner)
        ).all()
        assert set(before) == set(after)
