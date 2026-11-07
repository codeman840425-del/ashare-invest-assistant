"""T-A16 confidence, computed only from evaluated rules and numeric DSL operands."""

from __future__ import annotations

import ast
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import Field

from app.signals.models import Model
from app.strategy.cards.dsl import Interpreter, parse, symbol


class MarginRule(Model):
    rule_id: str
    value: str
    threshold: str
    scale: str
    scale_kind: Literal["declared", "atr14", "abs_threshold"]
    margin: float = Field(ge=0, le=1)
    weight: str


class ConfidenceComponents(Model):
    data_completeness: float = Field(ge=0, le=1)
    dimension_agreement: float | None = Field(ge=0, le=1)
    condition_margin: float | None = Field(ge=0, le=1)
    margin_rules: list[MarginRule]


def numeric(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except InvalidOperation:
        return None


def components(
    *,
    refs: list[dict[str, Any]],
    views: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    frame: dict[str, Any],
    params: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """No fixture IDs/expectations accepted; use the sole DSL interpreter for operands."""
    d = Decimal(sum(r["passed"] is not None for r in refs)) / len(refs) if refs else Decimal(0)
    directions = Counter(v["view"] for v in views if v["view"] in {"bullish", "bearish"})
    count = sum(directions.values())
    a = Decimal(max(directions.values())) / count if count >= 2 else None
    known = {r["id"]: r for r in rules}
    margins: list[MarginRule] = []
    total, weight_sum = Decimal(0), Decimal(0)
    for ref in refs:
        if ref["passed"] is None or ref["role"] not in {
            "entry",
            "filter",
            "hold",
            "weakening",
            "exit",
        }:
            continue
        rule = known[ref["rule_id"]]
        node, temporal, _ = parse(
            rule["expr"], set(registry), set(params), rule["role"], rule["eval_time"]
        )
        if temporal or not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        if any(
            isinstance(n, ast.Constant) and isinstance(n.value, (str, bool)) for n in ast.walk(node)
        ):
            continue
        evaluator = Interpreter(frame["features"], frame["series"], frame["context"], params)
        value = numeric(evaluator.value(node.left))
        threshold = numeric(evaluator.value(node.comparators[0]))
        if value is None or threshold is None:
            continue
        declared = rule.get("margin_scale")
        if isinstance(declared, str) and declared.startswith("p."):
            declared = params.get(declared[2:])
        scale = numeric(declared)
        kind: Literal["declared", "atr14", "abs_threshold"] = "declared"
        if scale is None or scale <= 0:
            # ATR is used only when the left operand itself is a price feature.
            # No inference of dimensions from a composed arithmetic expression.
            key = symbol(node.left)
            price_unit = registry.get(key or "", {}).get("unit") in {"元"}
            scale = (
                numeric(evaluator.value(ast.parse("atr(14)", mode="eval").body))
                if price_unit
                else None
            )
            kind = "atr14"
        if scale is None or scale <= 0:
            scale, kind = abs(threshold), "abs_threshold"
        weight = numeric(rule.get("weight", 1))
        if scale <= 0 or weight is None or weight <= 0:
            continue
        margin = min(Decimal(1), abs(value - threshold) / scale)
        total += weight * margin
        weight_sum += weight
        margins.append(
            MarginRule(
                rule_id=ref["rule_id"],
                value=str(value),
                threshold=str(threshold),
                scale=str(scale),
                scale_kind=kind,
                margin=float(margin),
                weight=str(weight),
            )
        )
    m = total / weight_sum if weight_sum else None
    value = (Decimal("0.5") * d + Decimal("0.3") * (a or 0) + Decimal("0.2") * (m or 0)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return {
        "level": "high"
        if value >= Decimal("0.70")
        else "medium"
        if value >= Decimal("0.40")
        else "low",
        "value": float(value),
        "components": ConfidenceComponents(
            data_completeness=float(d),
            dimension_agreement=float(a) if a is not None else None,
            condition_margin=float(m) if m is not None else None,
            margin_rules=margins,
        ).model_dump(),
    }
