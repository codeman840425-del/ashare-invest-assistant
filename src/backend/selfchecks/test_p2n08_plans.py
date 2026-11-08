"""RC6 owned PIT projection only, no worker/DB acceptance claimed."""

# ruff: noqa: S101,ANN401
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from app.feedback.plans import Facts, Plan, Trade, assess, select_plan
from app.risk.evaluation import Inputs, assessed, earliest_as_of, observation
from app.schemas.enums import Action, Horizon
from app.signals.models import Stops
from app.suggestions.risk import RiskContext
from selfchecks.test_p2n08_core import config
from selfchecks.test_p2n08_pause import OPERANDS, cases

OWNER = uuid.UUID(int=31)
OTHER = uuid.UUID(int=32)
ACCOUNT = uuid.UUID(int=41)
CODE = "688018.SH"
AT = dt.datetime.fromisoformat("2026-11-02T16:00:00+08:00")
CHECKS = ("opposite_side", "qty_over_plan")


def point(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value)


def plan(value: dict[str, Any]) -> Plan:
    return Plan(
        value["id"],
        OWNER,
        ACCOUNT,
        CODE,
        value["side"],
        Decimal(value["qty"]) if "qty" in value else None,
        point(value["from"]),
        point(value["until"]) if value["until"] else None,
        point(value["from"]),
        point(value["until"]) if value["until"] else None,
    )


def trade(value: dict[str, Any]) -> Trade:
    at = point(value["executed_at"])
    return Trade(
        value["id"],
        OWNER,
        ACCOUNT if value["account"] == "synthetic_a" else uuid.UUID(int=999),
        CODE if value["security"] == "synthetic_s" else "688073.SH",
        value["side"],
        Decimal(value["qty"]),
        at,
        at,
        value["voided"],
    )


def facts(case: dict[str, Any]) -> Facts:
    return Facts(
        OWNER,
        ACCOUNT,
        CODE,
        (plan(case["plan"]),),
        tuple(trade(t) for t in case["trades"]),
        AT,
        True,
    )


@pytest.mark.parametrize(("case", "expected"), cases("-088"))
def test_golden088_quantity_projection(case: Any, expected: Any) -> None:
    source = facts(case)
    result = assess(source, at=AT, checks=("qty_over_plan",))
    assert result.quantities[source.plans[0].id] == Decimal(expected["cumulative_qty"])
    assert bool(result.flags) == expected["triggered"]
    assert len(result.logical_keys) == expected["logical_events"]
    assert not result.gaps
    assert assess(source, at=AT, checks=("qty_over_plan",)) == result
    assert all(not f.gated_actions for f in result.flags)


@pytest.mark.parametrize(("case", "expected"), cases("-089"))
def test_golden089_version_selection(case: Any, expected: Any) -> None:
    at = (
        point(case["trade_at"]) if "trade_at" in case else dt.date.fromisoformat(case["trade_date"])
    )
    t = Trade("synthetic", OWNER, ACCOUNT, CODE, case["trade_side"], Decimal(1), at, AT)
    result = select_plan(tuple(plan(p) for p in case["versions"]), t, at=AT)
    assert (result.plan.id if result.plan else None) == expected["selected"]
    assert result.opposite == expected["opposite_side"]
    assert bool(result.gaps) == expected["gap"]
    assert ("unknown" if result.gaps else "ok") == expected["state"]


def sample() -> Facts:
    return facts(cases("-088")[0][0])


def test_scope_pit_duplicate_correction_and_missing_coverage() -> None:
    source = sample()
    first = source.trades[0]
    # Reviewed pure-synthetic operands supply redundant input multiplicities.
    repeated = source.trades + tuple(first for _ in OPERANDS[:2])
    assert assess(replace(source, trades=repeated), at=AT, checks=CHECKS) == assess(
        source, at=AT, checks=CHECKS
    )
    outsiders = (
        replace(first, owner=OTHER, quantity=Decimal(999)),
        replace(first, id="foreign_code", code="688073.SH", quantity=Decimal(999)),
        replace(first, id="future", available_at=AT + dt.timedelta(seconds=1)),
        replace(first, id="future_execution", executed_at=AT + dt.timedelta(seconds=1)),
    )
    assert assess(
        replace(source, trades=source.trades + outsiders), at=AT, checks=CHECKS
    ) == assess(source, at=AT, checks=CHECKS)
    assert not assess(replace(source, coverage_complete=False), at=AT, checks=CHECKS).flags
    assert assess(
        replace(source, coverage_at=AT - dt.timedelta(seconds=1)), at=AT, checks=CHECKS
    ).gaps
    conflict = assess(
        replace(source, trades=(*source.trades, replace(first, voided=True))), at=AT, checks=CHECKS
    )
    assert conflict.gaps == ("plan_trade_revision_unresolved",)
    assert not conflict.flags
    cancelled = replace(source.trades[1], voided=True, quantity=Decimal(-60))
    corrected = assess(replace(source, trades=(first, cancelled)), at=AT, checks=CHECKS)
    assert corrected.quantities[source.plans[0].id] == Decimal(60)
    assert not corrected.flags
    wrong_owner = replace(source, plans=(replace(source.plans[0], owner=OTHER),))
    assert assess(wrong_owner, at=AT, checks=CHECKS).gaps
    assert not assess(wrong_owner, at=AT, checks=CHECKS).flags


def test_exact_decimal_date_only_without_change_and_future_version_knowledge() -> None:
    source = sample()
    p = replace(
        source.plans[0], start=point("2026-10-30T09:00:00+08:00"), end=None, end_known_at=None
    )
    date_only = replace(source.trades[0], executed_at=AT.date())
    assert select_plan((p,), date_only, at=AT).plan == p
    future_end = replace(
        p, end=point("2026-11-02T10:00:00+08:00"), end_known_at=AT + dt.timedelta(seconds=1)
    )
    assert select_plan((future_end,), source.trades[-1], at=AT).plan == future_end
    assert select_plan((replace(p, end=AT, end_known_at=None),), date_only, at=AT).gaps
    with pytest.raises(ValueError, match="timezone"):
        select_plan((p,), replace(date_only, executed_at=dt.datetime(2026, 11, 2, 15)), at=AT)
    t1 = replace(source.trades[0], quantity=Decimal(100))
    t2 = replace(source.trades[1], quantity=Decimal("0.000000000000000000000000000001"))
    result = assess(replace(source, plans=(p,), trades=(t1, t2)), at=AT, checks=("qty_over_plan",))
    assert result.flags
    assert result.quantities[p.id] == Decimal("100.000000000000000000000000000001")


def source_input(source: Facts) -> Inputs:
    return Inputs(
        source.account,
        RiskContext(
            observations={},
            regime=None,
            trade_action=None,
            plan_action=None,
            invalidated=None,
            plan_stop_loss=None,
        ),
        None,
        False,
        [],
        owner_id=OWNER,
        security_code=CODE,
        rc6=source,
    )


def evaluate(source: Inputs, cfg: Any = None) -> tuple[Any, Any]:
    return assessed(
        cfg or config(),
        source,
        action=Action.HOLD,
        horizon=Horizon.SHORT,
        stops=Stops(stop_loss=None, take_profit=None, time_stop_days=None),
        at=AT,
    )


def test_existing_evaluation_adapter_bindings_disabled_and_partial_not_ok() -> None:
    source = source_input(sample())
    result, controls = evaluate(source)
    rc6 = controls[-1]
    assert rc6["state"] == "triggered"
    assert rc6["flags"][0]["gated_actions"] == []
    assert {g["key"] for g in rc6["gaps"]} == {
        "plan_check_not_connected:held_after_invalidation",
        "plan_check_not_connected:buy_without_stop",
        "plan_check_not_connected:buy_during_wait",
    }
    ids = {e.id for e in result.evidence}
    assert all(set(f.evidence_ids) <= ids for f in result.flags)
    assert not result.pause_required
    _, controls = evaluate(replace(source, owner_id=OTHER))
    assert controls[-1]["state"] == "unknown"
    assert not controls[-1]["flags"]
    _, controls = evaluate(replace(source, security_code="688073.SH"))
    assert controls[-1]["state"] == "unknown"
    _, controls = evaluate(replace(source, rc6=None))
    assert controls[-1]["state"] == "unknown"
    assert "business_facts_not_connected" in {g["key"] for g in controls[-1]["gaps"]}
    normal = replace(sample(), trades=(sample().trades[0],))
    _, controls = evaluate(source_input(normal))
    assert controls[-1]["state"] == "unknown"  # remaining three checks lack sources
    cfg = config()
    cfg = cfg.model_copy(
        update={
            "rc6_plan_violation": cfg.rc6_plan_violation.model_copy(update={"checks": list(CHECKS)})
        }
    )
    _, controls = evaluate(source_input(normal), cfg)
    assert controls[-1]["state"] == "ok"
    cfg = cfg.model_copy(
        update={"rc6_plan_violation": cfg.rc6_plan_violation.model_copy(update={"enabled": False})}
    )
    _, controls = evaluate(source, cfg)
    assert controls[-1]["state"] == "disabled"
    assert not controls[-1]["flags"]


def test_evaluation_oldest_operand_never_settings_newest_or_unknown_time() -> None:
    old = observation("price", "10", AT - dt.timedelta(minutes=2), "synthetic")
    new = observation("assets", "100", AT - dt.timedelta(minutes=1), "synthetic")
    policy = observation("settings", "test", AT, "synthetic")
    assert earliest_as_of([old, new, policy]) == old.data_as_of
    assert earliest_as_of([policy]) is None
    assert earliest_as_of([old, new.model_copy(update={"data_as_of": None})]) is None
