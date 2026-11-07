"""Read-only evaluation boundary shared by future daily/incremental callers.

No candidate persistence, lifecycle promotion, user-policy invention or provider IO.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any

from sqlalchemy.engine import Connection

from app.config_files import MarketRulesConfig
from app.features.pipeline import prepare
from app.replay.baseline import read
from app.strategy.cards.fixtures import calculate


class RuleEvaluator:
    def evaluate(
        self,
        *,
        card: dict[str, Any],
        spec: dict[str, Any],
        frame: dict[str, Any],
        holding: dict[str, Any],
        security: dict[str, Any],
        market_rules: MarketRulesConfig,
        registry: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        columns: dict[str, Any] = {}
        args = {
            "card": card,
            "spec": spec,
            "features": frame["features"],
            "series": frame["series"],
            "context": frame["context"],
            "holding": holding,
            "security": security,
            "as_of": frame["as_of"].astimezone(dt.timezone(dt.timedelta(hours=8))).date(),
            "market_rules": market_rules,
            "feature_keys": set(registry),
            "columns": columns,
        }
        # Assemble once via the sole producer, then the rule pass reads frozen columns.
        calculate(**args, materialize=True)
        result = calculate(**args, materialize=False)
        evidence: list[dict[str, Any]] = []
        refs = []
        for trace in result["rule_traces"]:
            ids = []
            inputs = list(trace.input_values.items())
            atr_source = trace.input_values.get("atr_source")
            if isinstance(atr_source, dict):
                for feature, values in atr_source.items():
                    if isinstance(values, list):
                        inputs.extend((feature, value) for value in values)
            for key, value in inputs:
                feature = key.split("@")[0]
                if feature not in registry:
                    continue
                identifier = f"e{len(evidence) + 1}"
                ids.append(identifier)
                evidence.append(
                    {
                        "id": identifier,
                        "key": feature,
                        "value": value,
                        "unit": registry[feature]["unit"],
                        "provider": "system",
                        "endpoint": None,
                        "data_as_of": frame["data_as_of"] or frame["as_of"],
                        "fetched_at": frame["as_of"],
                        "epistemic_type": "hypothesis",
                    }
                )
            refs.append(
                {
                    "rule_id": trace.rule_id,
                    "snippet_id": None,
                    "snippet_version": None,
                    "role": trace.role,
                    "dimension": trace.dimension,
                    "passed": trace.passed,
                    "value": json.dumps(
                        {"inputs": trace.input_values, "computed": trace.computed_values},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "threshold": trace.expr,
                    "evidence_ids": ids,
                }
            )
        return {
            **result,
            "rule_refs": refs,
            "evidence": evidence,
            "gaps": frame["gaps"],
            "feature_set_version": frame["feature_set_version"],
            "as_of": frame["as_of"],
            "columns": {key: column.value for key, column in columns.items()},
        }


def evaluate_snapshot(
    conn: Connection,
    *,
    user_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    security_code: str,
    as_of: dt.datetime,
    card: dict[str, Any],
    spec: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    market_rules: MarketRulesConfig,
    factors: list[dict[str, Any]],
    scalars: list[dict[str, Any]] | None = None,
    holding: dict[str, Any] | None = None,
    lots: list[dict[str, Any]] | None = None,
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = read(
        conn, user_id, snapshot_id
    )  # identical foreign/missing 404, no global data fallback
    instrument = next(
        (row for row in payload["instruments"] if row["security_code"] == security_code), None
    )
    if instrument is None:
        raise ValueError("security_not_in_snapshot")
    frame = prepare(
        instrument,
        payload["sessions"],
        as_of=as_of,
        factors=factors,
        scalars=scalars,
        registry=registry,
        lots=lots,
        entry=entry,
    )
    result = RuleEvaluator().evaluate(
        card=card,
        spec=spec,
        frame=frame,
        holding=holding or {},
        security={"board": instrument["board"]},
        market_rules=market_rules,
        registry=registry,
    )
    return {
        **result,
        "snapshot_id": str(snapshot_id),
        "security_code": security_code,
        "simulation": True,
    }
