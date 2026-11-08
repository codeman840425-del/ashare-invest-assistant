"""Deterministic per-rule debouncing. No investment rules or thresholds."""

from __future__ import annotations

from typing import Any


def advance(
    old: dict[str, Any], values: list[dict[str, Any]], rounds: int, immediate: bool
) -> tuple[dict[str, Any], list[tuple[dict[str, Any], object, object]]]:
    states = {k: dict(v) for k, v in old.items()}
    flips = []
    for ref in values:
        key = ref["rule_id"]
        value = ref["passed"]
        prior = states.get(key, {"value": None, "pending_value": None, "pending_count": 0})
        current = dict(prior)
        if value is None or value == prior["value"]:
            current.update(pending_value=None, pending_count=0)
        else:
            count = prior.get("pending_count", 0) + 1 if prior.get("pending_value") == value else 1
            current.update(pending_value=value, pending_count=count)
            required = (
                1 if ref["role"] == "invalidation" and immediate and value is True else rounds
            )
            if count >= required:
                current.update(value=value, pending_value=None, pending_count=0)
                if prior["value"] is not None or (
                    ref["role"] == "invalidation" and immediate and value is True
                ):
                    flips.append((ref, prior["value"], value))
        states[key] = current
    return states, flips
