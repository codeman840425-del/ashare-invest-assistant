# ruff: noqa: S101, ANN401, F811
"""Only explicit synthetic exposure, membership and lot facts; no strategy invention."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.config import Settings
from app.market_rules.lots import LotSpec
from app.signals.models import Stops
from app.suggestions.risk import RiskContext, apply_risk, evaluate_risk
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401
from selfchecks.test_tb74_candidates import setup, signal  # noqa: F401
from selfchecks.test_tb75_suggestions import conclusion, observation

ROWS = json.loads((Path(__file__).parent / "fixtures/ta15_synthetic.json").read_text())
STAR = LotSpec(200, 1, 200, 100000)
CHINEXT = LotSpec(100, 100, 100, 300000)
STOPS = Stops(stop_loss=None, take_profit=None, time_stop_days=None)


def config(control: str) -> Any:
    base = Settings(_env_file=None).business.risk_controls
    raw = base.model_dump()
    for key, value in raw.items():
        if key.startswith("rc"):
            value["enabled"] = key == control
    return type(base).model_validate(raw)


def context(
    *,
    total: str = "90000",
    sector: str = "40",
    memberships: list[str] | None = None,
    missing: str | None = None,
    leg: str | None = None,
) -> RiskContext:
    memberships = (
        ["sw_l1.synthetic"] if memberships is None and missing != "membership" else memberships
    )
    metrics = {
        "total_assets": "100000",
        "total_value": total,
        "price": "10.00",
        "proposed_quantity": 400,
        "market_regime": "uptrend",
        "sw_l1.synthetic": sector,
    }
    if memberships is not None:
        metrics["sector_memberships"] = json.dumps(memberships)
    if missing in metrics:
        metrics.pop(missing)
    return RiskContext.model_validate(
        {
            "observations": {k: observation(k, v) for k, v in metrics.items()},
            "regime": None if missing == "market_regime" else "uptrend",
            "sector_memberships": memberships,
            "t_leg": leg,
            "trade_action": None,
            "plan_action": None,
            "invalidated": None,
            "plan_stop_loss": None,
        }
    )


def run(
    ctx: RiskContext,
    *,
    action: str = "buy",
    control: str = "rc3_total_exposure",
    lot: LotSpec = STAR,
) -> Any:
    return evaluate_risk(config(control), ctx, action=action, horizon="swing", stops=STOPS, lot=lot)


@pytest.mark.parametrize("action", ["buy", "add"])
@pytest.mark.parametrize("total", ["90000", "91000"])
def test_rc3_equal_or_above_cap(action: str, total: str) -> None:
    result = run(context(total=total), action=action)
    assert result.flags[0].gated_actions == ["buy", "add"]
    assert result.quantity_cap == 0
    assert result.gate_details[0].code == "REGIME_MISMATCH"
    assert result.gate_details[0].detail["cause"] == "total_exposure_at_cap"
    assert not result.gaps


@pytest.mark.parametrize("action", ["sell", "reduce", "hold", "wait"])
@pytest.mark.parametrize("control", ["rc3_total_exposure", "rc4_sector_concentration"])
def test_decreasing_or_noop_never_blocked(action: str, control: str) -> None:
    result = run(context(sector="45"), action=action, control=control)
    assert all(not f.gated_actions for f in result.flags)
    assert not result.gate_details


@pytest.mark.parametrize("leg", ["sell_first", "buy_first"])
@pytest.mark.parametrize("control", ["rc3_total_exposure", "rc4_sector_concentration"])
def test_t_legs_not_gated(leg: str, control: str) -> None:
    result = run(context(sector="45", leg=leg), control=control)
    assert all(not f.gated_actions for f in result.flags)
    assert result.quantity_cap is None


@pytest.mark.parametrize("row", ROWS)
def test_projected_cap_rounds_explicit_lot_without_inferring_board(row: dict[str, Any]) -> None:
    # Explicit input board assignment from the four-code synthetic fixture contract.
    lot = STAR if row["code"] in {"688018.SH", "688073.SH"} else CHINEXT
    ctx = context(total="88010")  # room 1990 / declared synthetic price 10 = 199 shares
    result = run(ctx, lot=lot)
    assert result.quantity_cap == (0 if lot is STAR else 100)
    assert bool(result.flags[0].gated_actions) == (lot is STAR)
    assert (
        result.gate_details == []
        if lot is CHINEXT
        else result.gate_details[0].detail["cause"] == "quantity_cap_below_min_buy"
    )


def test_projected_equal_cap_not_gated_and_lower_bound_only_advisory() -> None:
    equal = run(context(total="86000"))
    assert not equal.flags
    lower = run(context(total="10000"))
    assert lower.flags[0].gated_actions == []
    assert lower.quantity_cap is None


def test_sector_membership_threshold_projection_and_missing_facts() -> None:
    cap = run(context(sector="40"), control="rc4_sector_concentration")
    assert cap.flags[0].gated_actions == ["buy", "add"]
    assert cap.gate_details[0].code == "SECTOR_EXPOSURE_EXCEEDED"
    assert cap.gate_details[0].detail["sector"] == "sw_l1.synthetic"
    assert Decimal(cap.gate_details[0].detail["current_pct"]) == 40
    projected = run(context(sector="38.01"), control="rc4_sector_concentration", lot=CHINEXT)
    assert projected.quantity_cap == 100
    assert projected.flags[0].gated_actions == []
    other = run(context(sector="90", memberships=[]), control="rc4_sector_concentration")
    assert all(not f.gated_actions for f in other.flags)
    unknown = run(context(sector="90", missing="membership"), control="rc4_sector_concentration")
    assert "sector_memberships" in unknown.gaps
    absent = run(context(missing="sw_l1.synthetic"), control="rc4_sector_concentration")
    assert "sw_l1.synthetic" in absent.gaps
    regime = run(context(missing="market_regime"))
    assert "market_regime" in regime.gaps
    assert not regime.flags


def test_actual_candidate_retains_rc3_runtime_detail(setup: Any) -> None:
    from app.db.tables.signals import candidate_signals

    result = run(context())
    applied = apply_risk(signal("buy"), result, gaps=[])
    c = conclusion(setup, override=applied)
    with setup[0].connect() as conn:
        row = conn.execute(
            select(candidate_signals).where(candidate_signals.c.id == c.candidate_signal_id)
        ).one()
        gate = next(g for g in row.gate_results if g["gate"] == "gate_risk_total_exposure")
        assert gate["code"] == "REGIME_MISMATCH"
        assert gate["detail"]["cause"] == "total_exposure_at_cap"
        assert row.state == "blocked"


def test_unclassified_no_gate_and_missing_lot_is_partial() -> None:
    unknown = run(context(memberships=["sw_l1.未分类"]), control="rc4_sector_concentration")
    assert all(not f.gated_actions for f in unknown.flags)
    outcome = evaluate_risk(
        config("rc3_total_exposure"),
        context(total="88010"),
        action="buy",
        horizon="swing",
        stops=STOPS,
    )
    assert outcome.gaps == ["market_lot_rules"]
    from app.signals.models import Gap

    applied = apply_risk(
        signal("buy"),
        outcome,
        gaps=[Gap(key="market_lot_rules", reason="no_source", message="合成测试缺少明确手数")],
    )
    assert applied.data_status == "partial"
    assert "risk_details" not in signal("buy").model_dump(mode="json")
