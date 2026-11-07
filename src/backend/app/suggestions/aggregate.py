"""Contract §5.2 matrix and counting, without synthesizing an investment conclusion."""

from __future__ import annotations

import datetime as dt
from collections import Counter
from decimal import Decimal
from typing import Any

from app.schemas.enums import Dimension
from app.suggestions.models import SuggestionInput


def assemble(content: SuggestionInput, candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    strategies: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    blocks = []
    for conclusion in sorted(content.conclusions, key=lambda c: str(c.instance_id)):
        row = conclusion.model_dump(mode="json", exclude={"signal"})
        raw = conclusion.signal.model_dump(mode="json")
        # A suggestion merges evidence namespaces from different source snapshots.
        # Prefixing references avoids confusing two unrelated local E1 observations.
        namespace = str(conclusion.instance_id) + ":"

        def reference(value: dict[str, Any], namespace: str = namespace) -> dict[str, Any]:
            return {**value, "evidence_ids": [namespace + v for v in value["evidence_ids"]]}

        evidence.extend({**e, "id": namespace + e["id"]} for e in raw["evidence"])
        row.update(
            {key: raw[key] for key in ["t_leg", "score", "confidence", "stops", "valid_until"]}
        )
        row["action"] = raw["proposed_action"]
        row["confidence"]["value"] = float(row["confidence"]["value"])
        for key in ["rule_refs", "model_refs", "counter_evidence", "invalidation"]:
            row[key] = [reference(value) for value in raw[key]]
        row["reasons"] = [reference(value) for value in row["reasons"]]
        for view in row["dimension_views"]:
            view["rules"] = [reference(rule) for rule in view["rules"]]
        flags.extend(reference(value) for value in raw["risk_flags"])
        strategies.append(row)
        blocks.append({key: raw[key] for key in ["data_status", "data_as_of", "gaps"]})
    strategies.sort(
        key=lambda s: (
            -(s["score"] or 0) * Decimal(s["priority_weight"]),
            s["strategy_key"],
            s["instance_id"],
        )
    )
    matrix = []
    divergence = []
    for dimension in Dimension:
        cells = []
        for strategy in strategies:
            for view in strategy["dimension_views"]:
                if view["dimension"] != dimension:
                    continue
                support = [r for r in view["rules"] if r["role"] in {"entry", "filter", "hold"}]
                exits = [
                    r
                    for r in view["rules"]
                    if r["role"] in {"weakening", "exit"} and r["passed"] is not None
                ]
                ids = list(
                    dict.fromkeys(
                        e for r in support if r["passed"] is True for e in r["evidence_ids"]
                    )
                )[:3]
                cells.append(
                    {
                        "strategy_key": strategy["strategy_key"],
                        "strategy_version_id": strategy["strategy_version_id"],
                        "view": view["view"],
                        "score": view["score"],
                        "key_evidence_ids": ids,
                        "rules_passed": sum(r["passed"] is True for r in support),
                        "rules_total": len(support),
                        "exit_hits": sum(r["passed"] is True for r in exits),
                        "exit_total": len(exits),
                    }
                )
        divergent = {"bullish", "bearish"} <= {c["view"] for c in cells}
        matrix.append({"dimension": dimension.value, "divergent": divergent, "cells": cells})
        if divergent:
            divergence.append(
                {
                    "dimensions": [dimension.value],
                    "summary": "同一维度策略观点不同，分别保留原结论",
                    "resolving_info": [],
                }
            )
    n = len(strategies)
    pairs = {(s["action"], s["t_leg"]) for s in strategies}
    status = (
        "none"
        if n == 0
        else "single"
        if n == 1
        else "unanimous"
        if len(pairs) == 1
        else "divergent"
    )
    executable: list[str] = []
    blocked: list[str] = []
    reason_ids: list[str] = []
    for strategy in strategies:
        identifier = strategy["candidate_signal_id"]
        if identifier is None:
            continue
        candidate = candidates[identifier]
        reason_ids.extend(candidate["reason_ids"])
        (blocked if candidate["blocked"] else executable).append(identifier)
    blocks.append(content.model_dump(mode="json", include={"data_status", "data_as_of", "gaps"}))
    gaps = [gap for block in blocks for gap in block["gaps"]]
    return {
        "security_code": content.security_code,
        "snapshot_id": str(content.snapshot_id),
        "feature_set_version": content.feature_set_version,
        "strategies": strategies,
        "dimension_matrix": matrix,
        "consensus": {"status": status, "actions": dict(Counter(s["action"] for s in strategies))},
        "divergence": divergence,
        "risk_flags": flags,
        "evidence": evidence,
        "candidate_signal_ids": sorted(executable + blocked),
        "plan_draft_ids": [],
        "executability": {
            "status": "executable" if executable else "blocked" if blocked else "not_applicable",
            "reason_ids": sorted(set(reason_ids)),
            "executable_signal_ids": sorted(executable),
            "blocked_signal_ids": sorted(blocked),
        },
        "horizon_assessment": {
            "suitable": content.model_dump(mode="json")["suitable"],
            "user_overridden": content.user_overridden,
        },
        "data_status": next(iter({b["data_status"] for b in blocks}))
        if len({b["data_status"] for b in blocks}) == 1
        else "partial",
        "data_as_of": min(dt.datetime.fromisoformat(b["data_as_of"]) for b in blocks).isoformat(),
        "gaps": gaps,
        "explanation": {
            "source": "template",
            "text": "；".join(s["strategy_name"] + "：" + s["action"] for s in strategies)
            or "无可用策略结论",
            "llm_call_id": None,
        },
    }
