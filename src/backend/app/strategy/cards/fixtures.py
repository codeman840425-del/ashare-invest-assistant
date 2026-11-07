# ruff: noqa: ANN401
"""Independent deterministic golden comparison; expectations never enter the interpreter."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from pydantic import Field, JsonValue

from app.config_files import MarketRulesConfig
from app.market_rules.lots import lot_spec
from app.strategy.cards.dsl import Interpreter, parse
from app.strategy.cards.models import ContractModel


class RuleTrace(ContractModel):
    rule_id: str
    dimension: str
    role: str
    expr: str
    passed: bool | None
    input_values: dict[str, JsonValue]
    computed_values: dict[str, JsonValue]


class FixtureRun(ContractModel):
    fixture_id: str
    passed: bool
    mismatches: list[str]
    state: str
    action: str
    rule_ids_passed: list[str]
    reason_codes: list[str]
    reason_details: dict[str, JsonValue]
    lot_rule: dict[str, JsonValue] | None
    rule_traces: list[RuleTrace]
    inputs_missing: list[str] = Field(default_factory=list)


def json_values(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def calculate(
    card: dict[str, Any],
    spec: dict[str, Any],
    *,
    features: dict[str, Any],
    series: dict[str, Any],
    holding: dict[str, Any],
    context: dict[str, Any],
    security: dict[str, Any],
    as_of: dt.date,
    market_rules: MarketRulesConfig,
    feature_keys: set[str],
    columns: dict[str, Any] | None = None,
    materialize: bool = True,
) -> dict[str, Any]:
    """Deliberately cannot accept fixture id, desc or expect. No template-key branching."""
    params = {name: entry["default"] for name, entry in spec["params_schema"].items()}
    held = holding.get("qty", 0) > 0
    traces: list[RuleTrace] = []
    inputs_missing: set[str] = set()
    essential_unknown = False
    veto_unknown = False
    for rule in spec["rules"]:
        parsed = parse(rule["expr"], feature_keys, set(params), rule["role"], rule["eval_time"])
        # Per H15 no holding => no context-bearing rule refs. A plan-bound rule
        # without a bound plan is inapplicable (not an unknown source).
        expression = rule["expr"]
        if ("ctx." in expression or "plan." in expression) and not held:
            continue
        if "plan." in expression and not any(key.startswith("plan.") for key in context):
            continue
        evaluator = Interpreter(features, series, context, params)
        if columns is not None:
            evaluator.columns = columns
        evaluator.materialize = materialize
        passed = evaluator.evaluate(parsed)
        if passed is None:
            inputs_missing.update(
                key.split("@")[0] for key, value in evaluator.inputs.items() if value is None
            )
            if rule["role"] == "veto":
                veto_unknown = True
            if (
                rule["role"] in {"entry", "filter"}
                and rule.get("core", True)
                and rule.get("missing_policy") != "dimension_unknown"
            ):
                essential_unknown = True
            if (
                card.get("mount_policy", "user") == "system_only"
                and rule["role"] in {"exit", "weakening"}
                and rule.get("required_features")
            ):
                essential_unknown = True
        traces.append(
            RuleTrace(
                rule_id=rule["id"],
                dimension=rule["dimension"],
                role=rule["role"],
                expr=expression,
                passed=passed,
                input_values=json_values(evaluator.inputs),
                computed_values=json_values(evaluator.computed),
            )
        )
    hits = {trace.role for trace in traces if trace.passed is True}
    if held:
        if "exit" in hits:
            state = "exit_signal"
        elif "weakening" in hits:
            state = "weakening"
        elif essential_unknown and card.get("mount_policy") == "system_only":
            state = "insufficient_data"
        else:
            state = "hold_ok"
    elif "veto" in hits:
        state = "vetoed"
    elif essential_unknown:
        state = "insufficient_data"
    else:
        required = {
            rule["id"]
            for rule in spec["rules"]
            if rule["role"] in {"entry", "filter"} and rule.get("core", True)
        }
        passed_ids = {trace.rule_id for trace in traces if trace.passed is True}
        state = "entry_ok" if required and required <= passed_ids else "not_triggered"
    action_key = {
        "entry_ok": "entry_all_core_pass",
        "hold_ok": "held_hold",
        "weakening": "weakening",
        "exit_signal": "exit",
    }.get(state, "else")
    action = spec["action_map"].get(
        action_key, "hold" if card.get("mount_policy") == "system_only" else "wait"
    )
    if state == "insufficient_data":
        action = "hold" if card.get("mount_policy") == "system_only" else "wait"
    reasons: list[str] = []
    details: dict[str, JsonValue] = {}
    direction = "sell" if held or card.get("mount_policy") == "system_only" else "buy"
    if (
        direction == "buy"
        and features.get("f.list_days") is not None
        and features["f.list_days"] < 30
    ):
        reasons.append("NEW_LISTING")
    if action in {"sell", "reduce"} and holding.get("sellable", 0) <= 0:
        reasons.append("T1_NOT_SELLABLE")
    locked = features.get("f.limit_locked_down" if direction == "sell" else "f.limit_locked_up")
    limit = features.get("f.limit_down_price" if direction == "sell" else "f.limit_up_price")
    if locked is True and limit is not None:
        reasons.append("LIMIT_LOCKED")
        details["LIMIT_LOCKED"] = {"direction": direction}
    if features.get("f.is_suspended") is True:
        reasons.append("SUSPENDED")
        details["SUSPENDED"] = {"direction": direction}
    if action == "buy" and veto_unknown:
        reasons.append("KEY_DATA_MISSING")
    lot = None
    if action in {"buy", "sell", "reduce"}:
        segment = market_rules.segment_for(as_of)
        if segment is None:
            raise ValueError("market_rule_segment_missing")
        unit = lot_spec(segment, board=security["board"], security_type="stock")
        sellable = holding.get("sellable", 0)
        odd = direction == "sell" and 0 < sellable < unit.odd_lot
        lot = {"min_buy": unit.min_buy, "step": unit.step, "odd_lot_sell_all": odd}
        if odd:
            lot["sell_qty"] = sellable
    return {
        "state": state,
        "action": action,
        "rule_ids_passed": [trace.rule_id for trace in traces if trace.passed is True],
        "reason_codes": reasons,
        "reason_details": details,
        "lot_rule": lot,
        "rule_traces": traces,
        "inputs_missing": sorted(inputs_missing),
    }


def run_fixtures(
    card: dict[str, Any],
    spec: dict[str, Any],
    fixtures: list[dict[str, Any]],
    market_rules: MarketRulesConfig,
    feature_keys: set[str],
) -> list[FixtureRun]:
    runs = []
    for fixture in fixtures:
        actual = calculate(
            card,
            spec,
            features=fixture.get("features", {}),
            series=fixture.get("series", {}),
            holding=fixture.get("holding", {}),
            context={**fixture.get("ctx", {}), **fixture.get("plan", {})},
            security=fixture["security"],
            as_of=dt.date.fromisoformat(fixture["as_of"]),
            market_rules=market_rules,
            feature_keys=feature_keys,
        )
        expected = fixture["expect"]
        mismatches = [
            key
            for key, value in expected.items()
            if (
                set(actual.get(key, [])) != set(value)
                if key == "reason_codes"
                else actual.get(key) != value
            )
        ]
        # An omitted reason_codes means exactly none, not "unchecked".
        if "reason_codes" not in expected and actual["reason_codes"]:
            mismatches.append("reason_codes")
        runs.append(
            FixtureRun(
                fixture_id=fixture["id"], passed=not mismatches, mismatches=mismatches, **actual
            )
        )
    return runs
