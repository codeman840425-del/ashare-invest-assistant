"""Slice1: pure arithmetic and research fictional golden inputs only."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.config_files import HealthFeedbackConfig, RiskControlsConfig
from app.feedback.core import (
    Fill,
    HealthDay,
    Metric,
    NavPoint,
    Observation,
    account_drawdown,
    closed_losses,
    health,
    priority_weight,
    rc5_state,
    simulated_failures,
)

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = json.loads((ROOT / "docs/strategies/golden/P2N-R08_golden.json").read_text())["cases"]
OPERANDS = json.loads((Path(__file__).parent / "fixtures/p2n08_operands.json").read_text())
MAPPING = {"intraday_t": 1, "short": 5, "swing": 20, "long": 20}
AT = dt.datetime(2026, 12, 31, 15, tzinfo=dt.timezone(dt.timedelta(hours=8)))


def ident(s: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, "fictional-p2n08:" + s)


OWNER, ACCOUNT, VERSION = ident("self"), ident("synthetic_a"), ident("v1")


def config() -> RiskControlsConfig:
    raw = yaml.safe_load((ROOT / "config/risk_controls.yaml").read_text())
    return RiskControlsConfig.model_validate(raw)


def scenarios(suffix: str) -> list[Any]:
    r = next(r for r in GOLDEN if r["id"].endswith(suffix))
    return list(zip(r["input"]["scenarios"], r["expected"]["results"], strict=True))


def observation(r: dict[str, Any]) -> Observation:
    return Observation(
        ident(r["owner"]),
        ident(r["strategy_version"]),
        ident(r["suggestion_id"]),
        ident(r["instance_id"]),
        dt.datetime.fromisoformat(r["instance_created_at"]),
        r.get("horizon"),
        r["horizon_days"],
        r["state"],
        r["direction_correct"],
        dt.datetime.fromisoformat(r["exit_at"]) if r["exit_at"] else None,
        dt.datetime(2026, 11, 1, tzinfo=dt.UTC),
        (r["suggestion_id"],),
    )


def days(n: int) -> list[dt.date]:
    # Deliberately fictional calendar, not an inferred exchange calendar.
    return [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(n)]


@pytest.mark.parametrize(("case", "expected"), scenarios("-084"))
def test_golden_084(case: Any, expected: Any) -> None:
    m = simulated_failures(
        OWNER,
        ident(case["strategy_version"]),
        [observation(r) for r in case["observations"]],
        config().rc5_loss_streak_drawdown,
        version_horizon=case["version_horizon"],
        at=AT,
    )
    assert (m.value, m.triggered, list(m.gaps)) == (
        expected["trailing_failures"],
        expected["triggered"],
        expected["gap_codes"],
    )


@pytest.mark.parametrize(("case", "expected"), scenarios("-085"))
def test_golden_085(case: Any, expected: Any) -> None:
    rows = [
        Fill(
            OWNER,
            ident(r["account"]),
            r["security"],
            ident(r["id"]),
            dt.datetime.fromisoformat(r["executed_at"]),
            dt.datetime.fromisoformat(r["executed_at"]),
            r["side"],
            Decimal(r["qty"]),
            Decimal(r["price"]),
            Decimal(r["fee"]),
            (r["id"],),
        )
        for r in case["fills"]
    ]
    result = closed_losses(OWNER, ACCOUNT, rows, config().rc5_loss_streak_drawdown, at=AT)
    assert [s.pnl for s in result.segments] == [Decimal(v) for v in expected["closed_pnl"]]
    assert (result.metric.value, result.metric.triggered, bool(result.metric.gaps)) == (
        expected["trailing_losses"],
        expected["triggered"],
        expected["gap"],
    )


@pytest.mark.parametrize(("case", "expected"), scenarios("-087"))
def test_golden_087(case: Any, expected: Any) -> None:
    calendar = days(len(case["weights"]))
    rows = [
        HealthDay(d, case["n"], Decimal(w), Decimal(r))
        for d, w, r in zip(calendar, case["weights"], case["robustness"], strict=True)
    ]
    result = health(
        case["state"],
        calendar,
        rows,
        internal_enabled=case["enabled"],
        baseline=Decimal(case["baseline"]),
        config=HealthFeedbackConfig(internal_recover_ratio=Decimal(case["recover_ratio"])),
    )
    assert (result.state, result.high_streak) == (expected["state"], expected["joint_streak"])


@pytest.mark.parametrize(("case", "expected"), scenarios("-090"))
def test_golden_090(case: Any, expected: Any) -> None:
    calendar = days(len(case["weights"]))
    rows = [
        HealthDay(d, case["n"], Decimal(w))
        for d, w in zip(calendar, case["weights"], strict=True)
        if w is not None
    ]
    result = health(
        case["state"], calendar, rows, internal_enabled=False, baseline=None, config=None
    )
    assert (result.state, result.low_streak, result.high_streak, bool(result.gaps)) == (
        expected["state"],
        expected["low_streak"],
        expected["high_streak"],
        expected["gap"],
    )


def test_config_mapping_override_not_fixed_five_and_missing_closed() -> None:
    cfg = config().rc5_loss_streak_drawdown
    assert cfg.sim_fail_horizon_by_horizon == MAPPING
    case = scenarios("-084")[1][0]
    rows = [observation(r) for r in case["observations"]]
    override = cfg.model_copy(update={"sim_fail_horizon_by_horizon": {**MAPPING, "short": 1}})
    assert (
        simulated_failures(OWNER, VERSION, rows, override, version_horizon=None, at=AT).value == 0
    )
    missing = cfg.model_copy(update={"sim_fail_horizon_by_horizon": None})
    m = simulated_failures(OWNER, VERSION, rows, missing, version_horizon=None, at=AT)
    assert m.value is None
    assert m.gaps == ("sim_fail_horizon_config_missing",)
    assert rc5_state(missing, [m]) == "unknown"


@pytest.mark.parametrize(
    "mapping",
    [{**MAPPING, "swing": True}, {**MAPPING, "short": "5"}, {"short": 5}, {**MAPPING, "long": 10}],
)
def test_invalid_config_not_coerced(mapping: Any) -> None:
    raw = config().model_dump()
    raw["rc5_loss_streak_drawdown"]["sim_fail_horizon_by_horizon"] = mapping
    with pytest.raises(ValidationError):
        RiskControlsConfig.model_validate(raw)


def test_owned_pit_missing_proof_and_idempotent_read() -> None:
    rows = [observation(r) for r in scenarios("-084")[0][0]["observations"]]
    cfg = config().rc5_loss_streak_drawdown
    result = simulated_failures(OWNER, VERSION, rows, cfg, version_horizon=None, at=AT)
    assert result.triggered is True
    other = simulated_failures(ident("stranger"), VERSION, rows, cfg, version_horizon=None, at=AT)
    assert other.value == 0
    assert other.gaps == ("sim_fail_observations_missing",)
    future = [replace(r, available_at=AT + dt.timedelta(seconds=1)) for r in rows]
    assert simulated_failures(OWNER, VERSION, future, cfg, version_horizon=None, at=AT).gaps == (
        "sim_fail_observations_missing",
    )
    no_proof = [replace(r, evidence_ids=()) for r in rows]
    assert (
        "sim_fail_evidence_missing"
        in simulated_failures(OWNER, VERSION, no_proof, cfg, version_horizon=None, at=AT).gaps
    )
    assert simulated_failures(OWNER, VERSION, rows, cfg, version_horizon=None, at=AT) == result


@pytest.mark.parametrize(
    ("last", "triggered"), [("90.0001", False), ("90", True), ("89.9999", True)]
)
def test_drawdown_threshold_no_fake_nav(last: str, triggered: bool) -> None:
    cfg = config().rc5_loss_streak_drawdown
    rows = [
        NavPoint(
            OWNER,
            ACCOUNT,
            AT - dt.timedelta(days=1),
            AT - dt.timedelta(days=1),
            Decimal(100),
            ("peak",),
        ),
        NavPoint(OWNER, ACCOUNT, AT, AT, Decimal(last), ("current",)),
    ]
    result = account_drawdown(OWNER, ACCOUNT, rows, cfg, at=AT, complete_history=True)
    assert (result.value, result.triggered) == (100 - Decimal(last), triggered)
    assert result.evidence_ids == ("current", "peak")
    assert (
        account_drawdown(ident("other"), ACCOUNT, rows, cfg, at=AT, complete_history=True).value
        is None
    )
    assert account_drawdown(OWNER, ACCOUNT, rows, cfg, at=AT, complete_history=False).value is None
    assert (
        account_drawdown(
            OWNER,
            ACCOUNT,
            [replace(rows[0], value=None), rows[1]],
            cfg,
            at=AT,
            complete_history=True,
        ).value
        is None
    )


def test_nav_zero_future_revision_unknown() -> None:
    cfg = config().rc5_loss_streak_drawdown
    r = NavPoint(OWNER, ACCOUNT, AT, AT, Decimal(0), ("zero",))
    assert account_drawdown(OWNER, ACCOUNT, [r], cfg, at=AT, complete_history=True).value is None
    assert (
        account_drawdown(
            OWNER,
            ACCOUNT,
            [replace(r, value=Decimal(10), available_at=AT + dt.timedelta(seconds=1))],
            cfg,
            at=AT,
            complete_history=True,
        ).value
        is None
    )
    assert account_drawdown(
        OWNER, ACCOUNT, [replace(r, value=Decimal(10)), r], cfg, at=AT, complete_history=True
    ).gaps == ("account_nav_revision_unresolved",)


def test_synthetic_operands_costs_corrections_scope() -> None:
    cfg = config().rc5_loss_streak_drawdown
    fills = []
    for r in OPERANDS:
        i = r["index"]
        at = AT - dt.timedelta(minutes=100 - i * 2)
        fills.extend(
            [
                Fill(
                    OWNER,
                    ACCOUNT,
                    "688018.SH",
                    ident(f"b{i}"),
                    at,
                    at,
                    "buy",
                    Decimal(200),
                    Decimal(100),
                    Decimal(0),
                    (f"b{i}",),
                ),
                Fill(
                    OWNER,
                    ACCOUNT,
                    "688018.SH",
                    ident(f"s{i}"),
                    at + dt.timedelta(seconds=1),
                    at + dt.timedelta(seconds=1),
                    "sell",
                    Decimal(200),
                    Decimal(100) + Decimal(r["delta"]),
                    Decimal(r["amount"]),
                    (f"s{i}",),
                ),
            ]
        )
    result = closed_losses(OWNER, ACCOUNT, fills, cfg, at=AT)
    assert closed_losses(OWNER, ACCOUNT, fills + fills, cfg, at=AT) == result
    assert [s.pnl for s in result.segments] == [
        Decimal(200) * r["delta"] - r["amount"] for r in OPERANDS
    ]
    assert closed_losses(ident("other"), ACCOUNT, fills, cfg, at=AT).segments == ()
    assert closed_losses(OWNER, ident("other_account"), fills, cfg, at=AT).segments == ()
    corrected = [replace(f, active=False) if f.id == fills[-1].id else f for f in fills]
    assert len(closed_losses(OWNER, ACCOUNT, corrected, cfg, at=AT).segments) == 23
    assert (
        closed_losses(
            OWNER,
            ACCOUNT,
            [replace(f, available_at=AT + dt.timedelta(seconds=1)) for f in fills],
            cfg,
            at=AT,
        ).segments
        == ()
    )


def test_weights_sample_floor_clamp_unknown_and_user_switch() -> None:
    assert priority_weight(20, 10, Decimal(0), enabled=True).raw == Decimal(1)
    assert priority_weight(20, 0, Decimal(0), enabled=True).health_weight == Decimal(".6")
    for row in OPERANDS:
        assert priority_weight(
            19, 0, Decimal(row["delta"]), enabled=True
        ).priority_weight == Decimal(1)
        r = priority_weight(100, 0, Decimal(row["delta"]), enabled=True)
        assert Decimal(".3") <= r.health_weight <= Decimal("1.2")
        off = priority_weight(100, 0, Decimal(row["delta"]), enabled=False)
        assert off.health_weight == r.health_weight
        assert off.raw == r.raw
        assert off.priority_weight == Decimal(1)
    assert priority_weight(10000, 10000, Decimal(1000), enabled=True).health_weight == Decimal(
        "1.2"
    )
    assert priority_weight(10000, 0, Decimal(-1000), enabled=True).health_weight == Decimal(".3")
    assert priority_weight(20, 10, None, enabled=True).health_weight is None
    with pytest.raises(ValueError, match="feedback_sample_count_invalid"):
        priority_weight(20, 21, Decimal(0), enabled=True)


@pytest.mark.parametrize("state", ["draft", "simulating", "retired"])
def test_non_health_lifecycle_never_promoted_or_retired(state: str) -> None:
    calendar = days(30)
    result = health(
        state,
        calendar,
        [HealthDay(d, 100, Decimal(".3")) for d in calendar],
        internal_enabled=False,
        baseline=None,
        config=None,
    )
    assert result.state == state
    assert result.proposed_action == "none"


def test_health_internal_config_override_review_no_retire_calendar_gap() -> None:
    calendar = days(20)
    result = health(
        "published",
        calendar,
        [HealthDay(d, 20, Decimal(".5")) for d in calendar],
        internal_enabled=False,
        baseline=None,
        config=None,
    )
    assert result.state == "observing"
    assert result.proposed_action == "review"
    rows = [HealthDay(d, 20, Decimal(".9"), Decimal(80)) for d in calendar]
    missing = health(
        "observing", calendar, rows, internal_enabled=True, baseline=Decimal(100), config=None
    )
    assert missing.state == "observing"
    assert missing.high_streak == 0
    assert "health_internal_recover_ratio_missing" in missing.gaps
    override = health(
        "observing",
        calendar,
        rows,
        internal_enabled=True,
        baseline=Decimal(100),
        config=HealthFeedbackConfig(internal_recover_ratio=Decimal(".9")),
    )
    assert override.state == "observing"
    assert override.high_streak == 0
    assert (
        health("observing", None, rows, internal_enabled=False, baseline=None, config=None).state
        == "observing"
    )
    assert (
        health(
            "observing", calendar, rows, internal_enabled=False, baseline=None, config=None
        ).state
        == "published"
    )


def test_rc5_read_result_never_pauses_or_gates_actions() -> None:
    cfg = config().rc5_loss_streak_drawdown
    assert rc5_state(cfg, [Metric(None, None, gaps=("missing",))]) == "unknown"
    assert rc5_state(cfg, [Metric(3, True), Metric(None, None)]) == "triggered"
    assert rc5_state(cfg, [Metric(0, False)]) == "unknown"
    assert rc5_state(cfg, [Metric(0, False)] * 3) == "ok"
    assert rc5_state(cfg.model_copy(update={"enabled": False}), [Metric(5, True)]) == "disabled"


@pytest.mark.parametrize("count", [2, 3, 4, 5, 6])
def test_exact_loss_and_failure_thresholds(count: int) -> None:
    cfg = config().rc5_loss_streak_drawdown
    fills = []
    observations = []
    for i in range(count):
        at = AT - dt.timedelta(minutes=100 - i * 2)
        fills.extend(
            [
                Fill(
                    OWNER,
                    ACCOUNT,
                    "688018.SH",
                    ident(f"open{i}"),
                    at,
                    at,
                    "buy",
                    Decimal(200),
                    Decimal(10),
                    Decimal(1),
                    (f"open{i}",),
                ),
                Fill(
                    OWNER,
                    ACCOUNT,
                    "688018.SH",
                    ident(f"close{i}"),
                    at + dt.timedelta(seconds=1),
                    at + dt.timedelta(seconds=1),
                    "sell",
                    Decimal(200),
                    Decimal(10),
                    Decimal(0),
                    (f"close{i}",),
                ),
            ]
        )
        observations.append(
            Observation(
                OWNER,
                VERSION,
                ident(f"sugg{i}"),
                ident(f"inst{i}"),
                at - dt.timedelta(days=1),
                "short",
                cfg.sim_fail_horizon_by_horizon["short"],
                "complete",
                False,
                at,
                at,
                (f"result{i}",),
            )
        )
    losses = closed_losses(OWNER, ACCOUNT, fills, cfg, at=AT).metric
    failures = simulated_failures(OWNER, VERSION, observations, cfg, version_horizon=None, at=AT)
    assert losses.value == count
    assert losses.triggered is (count >= cfg.closed_loss_streak)
    assert failures.value == count
    assert failures.triggered is (count >= cfg.strategy_sim_fail_streak)


def test_invalid_result_types_do_not_clear_streak_and_legacy_config_shape() -> None:
    cfg = config().rc5_loss_streak_drawdown
    row = next(
        observation(r)
        for r in scenarios("-084")[0][0]["observations"]
        if r["state"] == "complete"
        and r["owner"] == "self"
        and r["strategy_version"] == "v1"
        and r["horizon"] == "intraday_t"
    )
    conflict = replace(row, direction_correct=not row.direction_correct)
    assert simulated_failures(
        OWNER, VERSION, [row, conflict], cfg, version_horizon=None, at=AT
    ).gaps == ("sim_fail_result_revision_unresolved",)
    bad = replace(row, direction_correct="false")
    result = simulated_failures(OWNER, VERSION, [bad], cfg, version_horizon=None, at=AT)
    assert "sim_fail_result_unknown" in result.gaps
    bad_period = replace(row, horizon_days=True)
    result = simulated_failures(OWNER, VERSION, [bad_period], cfg, version_horizon=None, at=AT)
    assert "sim_fail_horizon_unknown" in result.gaps
    raw = yaml.safe_load((ROOT / "config/risk_controls.yaml").read_text())
    raw["rc5_loss_streak_drawdown"].pop("sim_fail_horizon_by_horizon", None)
    raw.pop("health", None)
    legacy = RiskControlsConfig.model_validate(raw).model_dump(mode="json")
    assert "sim_fail_horizon_by_horizon" not in legacy["rc5_loss_streak_drawdown"]
    assert "health" not in legacy
