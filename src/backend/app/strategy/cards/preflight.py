# ruff: noqa: ANN401
"""All-errors semantic preflight. A formal handoff is not a waiver of plan 2.5.14.

No config generation, DB writes, or promotion when any card is invalid.
"""

from __future__ import annotations

import ast
import copy
import math
import re
from decimal import Decimal
from typing import Any

from app.schemas.enums import Dimension, Horizon, RuleRole
from app.strategy.cards.dsl import CONTEXT, parse, symbol
from app.strategy.cards.importing import _block, prepare_documents
from app.strategy.universe_norm import normalize_universe


def feature_registry(document: str) -> dict[str, dict[str, Any]]:
    """Only the explicitly versioned research feature block, not arbitrary examples."""
    blocks = [
        block
        for block in re.findall(r"^```yaml\n(.*?)^```", document, re.M | re.S)
        if block.startswith("feature_spec_version:")
    ]
    if len(blocks) != 1:
        raise ValueError("feature_spec_block_count")
    rows = _block(blocks[0])["features"]
    result = {row["feature_key"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("duplicate_feature_key")
    return result


def parameter_valid(value: Any, schema: dict[str, Any]) -> bool:
    typ = schema.get("type")
    if typ == "bool":
        return type(value) is bool
    if typ == "enum":
        return value in schema.get("choices", []) and type(value) in {int, float, str, bool}
    if typ not in {"int", "float"} or (
        type(value) is not int if typ == "int" else type(value) not in {int, float}
    ):
        return False
    if any(
        type(schema.get(key)) not in {int, float} or not math.isfinite(schema[key])
        for key in ("min", "max", "step")
    ):
        return False
    if not math.isfinite(value):
        return False
    v, lo, hi, step = (
        Decimal(str(item)) for item in (value, schema["min"], schema["max"], schema["step"])
    )
    return step > 0 and lo <= v <= hi and (v - lo) % step == 0


def check_adjust(tree: ast.expr, registry: dict[str, dict[str, Any]]) -> None:
    """Only price-valued operands carry an adjustment basis; enum regime is not a price."""

    def basis(node: ast.AST) -> set[str]:
        name = symbol(node)
        if name in registry:
            definition = registry[name]
            return {definition["adjust"]} if definition["unit"] == "CNY_per_share" else set()
        if (
            name in CONTEXT
            and name
            and any(key in name for key in ("price", "stop_loss", "take_profit", "highest_close"))
        ):
            return {"qfq" if name.endswith("_qfq") else "none"}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "atr":
            return {"qfq"}
        values: set[str] = set()
        for child in ast.iter_child_nodes(node):
            values |= basis(child)
        if len(values) > 1:
            raise ValueError("adjust_mismatch")
        return values

    basis(tree)


def _runtime_universe(item: Any, spec: dict[str, Any]) -> None:
    """Apply v1 official-card universe rewrite onto the staged card block."""
    card = item.blocks.get("strategy-card") or {}
    universe = card.get("universe")
    if not isinstance(universe, dict):
        return
    if "screen" in spec:
        screen = spec.get("screen")
    elif "screen" in card:
        screen = card.get("screen")
    else:
        screen = None
    card["universe"] = normalize_universe(universe, screen=screen)


def preflight(
    documents: list[str], registry: dict[str, dict[str, Any]]
) -> tuple[list[Any], list[dict[str, str]]]:
    staged = prepare_documents(documents)
    errors: list[dict[str, str]] = []
    for item in staged:
        key = item.identity.key
        card: dict[str, Any] = copy.deepcopy(item.blocks["strategy-card"])
        spec: dict[str, Any] = copy.deepcopy(item.blocks.get("strategy-spec") or {})
        validation: dict[str, Any] = item.blocks.get("validation") or {}

        def fail(path: str, issue: str, key: str = key) -> None:
            errors.append({"key": key, "path": path, "issue": issue})

        for field in (
            "category",
            "horizons",
            "hypothesis",
            "dimensions",
            "counter_evidence",
            "invalidation",
            "exit",
            "data_needs",
            "epistemic",
        ):
            if field not in card:
                fail(field, "required")
        if card.get("category") not in {
            "trend",
            "momentum",
            "reversal",
            "breakout",
            "value",
            "quality",
            "dividend",
            "low_vol",
            "event",
            "intraday_t",
            "risk",
        }:
            fail("category", "invalid_enum")
        if not card.get("horizons") or any(
            h not in {v.value for v in Horizon} for h in card.get("horizons", [])
        ):
            fail("horizons", "invalid_enum")
        if card.get("mount_policy", "user") not in {"system_only", "user"}:
            fail("mount_policy", "invalid_enum")
        if card.get("risk_level", "normal") not in {"normal", "high"}:
            fail("risk_level", "invalid_enum")
        if not isinstance(card.get("hypothesis"), dict) or not card["hypothesis"].get(
            "falsified_by"
        ):
            fail("hypothesis", "required_falsified_by")
        if not spec:
            _runtime_universe(item, spec)
            continue  # L1-only cards are legal, never runnable
        params = spec.get("params_schema") or spec.get("params") or {}
        if isinstance(params, list):
            params = {definition["name"]: definition for definition in params}
        epistemic = card.get("epistemic", {})
        if epistemic.get("hypothesis") not in {"fact", "estimate", "hypothesis"}:
            fail("epistemic.hypothesis", "required_epistemic_annotation")
        for name, definition in params.items():
            if not all(
                part in definition for part in ("type", "default", "min", "max", "step")
            ) or not (definition.get("desc") or definition.get("说明")):
                fail("params_schema." + name, "parameter_schema_incomplete")
            elif not parameter_valid(definition["default"], definition):
                fail("params_schema." + name, "parameter_default_invalid")
            if epistemic.get("params_schema." + name) not in {"fact", "estimate", "hypothesis"}:
                fail("epistemic.params_schema." + name, "required_threshold_epistemic")
        rules = spec.get("rules", [])
        ids = [rule.get("id", rule.get("rule_id")) for rule in rules]
        if len(ids) != len(set(ids)):
            fail("rules", "duplicate_rule_id")
        roles = {rule.get("role") for rule in rules}
        system_only = card.get("mount_policy") == "system_only"
        if system_only:
            if (
                not roles <= {"exit", "weakening", "counter", "invalidation"}
                or not roles & {"exit", "weakening"}
                or any(value in {"buy", "add"} for value in spec.get("action_map", {}).values())
            ):
                fail("mount_policy", "invalid_system_only")
        elif "entry" not in roles or not (
            spec.get("stops", {}).get("stop_loss") or spec.get("stops", {}).get("time_stop_days")
        ):
            fail("rules", "g1_entry_stop_required")
        if not {"counter", "invalidation"} <= roles:
            fail("rules", "g1_counter_invalidation_required")
        if not set(spec.get("action_map", {})) <= {
            "entry_all_core_pass",
            "held_hold",
            "weakening",
            "exit",
            "else",
        }:
            fail("action_map", "invalid_action_map_key")
        for index, rule in enumerate(rules):
            path = f"rules[{index}]"
            if rule.get("role") not in {v.value for v in RuleRole} or rule.get("dimension") not in {
                v.value for v in Dimension
            }:
                fail(path, "invalid_rule_enum")
            if rule.get("eval_time") not in {"daily_close", "intraday_1m", "event"}:
                fail(path, "eval_time_required")
            if rule.get("status") == "to_quantify":
                fail(path, "rule_not_quantified")
            if any(
                feature not in registry
                for feature in rule.get("required_features", rule.get("data", []))
            ):
                fail(path, "unknown_feature")
            try:
                tree, _, _ = parse(
                    rule.get("expr"), set(registry), set(params), rule["role"], rule["eval_time"]
                )
                check_adjust(tree, registry)
            except (ValueError, KeyError) as error:
                fail(path, str(error))
        for section, accepted in {
            "entry": {"entry"},
            "counter_evidence": {"counter"},
            "invalidation": {"invalidation"},
            "exit": {"exit", "hold", "weakening"},
        }.items():
            if not card.get(section) and not (section == "entry" and system_only):
                fail(section, "required_rule_list")
            for index, entry in enumerate(card.get(section, [])):
                if "ref" in entry:
                    rule = next(
                        (r for r in rules if r.get("id", r.get("rule_id")) == entry["ref"]), None
                    )
                    if rule is None or rule["role"] not in accepted:
                        fail(f"{section}[{index}]", "invalid_rule_ref")
                    elif entry.get("expr") and re.sub(r"\s+", "", entry["expr"]) != re.sub(
                        r"\s+", "", rule["expr"]
                    ):
                        fail(f"{section}[{index}]", "ref_expr_mismatch")
        for need in card.get("data_needs", []):
            if need.get("feature_key") not in registry:
                fail("data_needs", "unknown_feature")
        if not {"fixture", "trigger_stats"} <= set(validation.get("methods", [])):
            fail("validation.methods", "required_validation_method")
        fixtures = validation.get("fixtures", [])
        if len(fixtures) < 6:
            fail("validation.fixtures", "minimum_six_fixtures")
        fixture_ids = [fixture["id"] for fixture in fixtures]
        if len(set(fixture_ids)) != len(fixture_ids):
            fail("validation.fixtures", "duplicate_fixture_id")
        for index, fixture in enumerate(fixtures):
            for feature in set(fixture.get("features", {})) | set(fixture.get("series", {})):
                if feature not in registry:
                    fail(f"validation.fixtures[{index}]", "fixture_key_not_in_catalog")
            expected = fixture.get("expect", {})
            for reason in set(expected.get("reason_codes", [])) & {"LIMIT_LOCKED", "SUSPENDED"}:
                if expected.get("reason_details", {}).get(reason, {}).get("direction") not in {
                    "buy",
                    "sell",
                }:
                    fail(f"validation.fixtures[{index}]", "reason_direction_required")
        # No G1–G7 success is implied by this check. G2 live data, G5 wiring,
        # G6 history/quota, G7 administrator review are independent gates.
        _runtime_universe(item, spec)
    return staged, errors
