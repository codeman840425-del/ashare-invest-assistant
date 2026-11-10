"""Version-local applicability matching, not an invented trading rule or fallback."""

from __future__ import annotations

from typing import Any


def regime_source(card: dict[str, Any], spec: dict[str, Any]) -> str | None:
    criteria = spec.get("applicability", card.get("applicability", {})) or {}
    if "market_regime" not in criteria:
        return None
    declared: set[str] = {need["feature_key"] for need in card.get("data_needs", [])}
    declared.update(
        key for rule in spec.get("rules", []) for key in rule.get("required_features", [])
    )
    candidates = declared & {"f.market_regime", "f.market_regime_idx"}
    if len(candidates) != 1:
        raise ValueError("applicability_regime_source_missing_or_mixed")
    source = next(iter(candidates))
    if spec.get("applicability_eval_source", source) != source:
        raise ValueError("applicability_bound_source_mismatch")
    return source


def evaluate(
    card: dict[str, Any], spec: dict[str, Any], features: dict[str, Any]
) -> dict[str, Any] | None:
    source = regime_source(card, spec)
    if source is None:
        return None
    value = features.get(source)
    choices = (spec.get("applicability", card.get("applicability", {})) or {})["market_regime"]
    return {
        "source": source,
        "value": value,
        "matched": None if value is None else value in choices,
    }
