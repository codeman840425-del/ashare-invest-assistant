"""Promotion preparation only: no automatic G7, no promotion from an incomplete report."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import Decimal
from typing import Any

import yaml
from sqlalchemy import Connection, insert, select

from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.db.tables.strategy import (
    feature_catalog,
    strategies,
    strategy_card_versions,
    strategy_cards,
    strategy_promotion_reviews,
    strategy_versions,
)
from app.schemas.enums import Action, Horizon
from app.signals.models import Evidence, Stops
from app.strategy.cards.fixtures import run_fixtures
from app.strategy.cards.preflight import preflight
from app.strategy.g6 import Overlap, compare, missing_history_gate
from app.suggestions.risk import RiskContext, evaluate_risk


def prepare(
    conn: Connection, owner: uuid.UUID, card_id: uuid.UUID, settings: Settings
) -> uuid.UUID:
    card = conn.execute(select(strategy_cards).where(strategy_cards.c.id == card_id)).first()
    if card is None or card.owner_user_id not in {None, owner}:
        raise AppError(ErrorCode.NOT_FOUND)
    cv = conn.execute(
        select(strategy_card_versions)
        .where(strategy_card_versions.c.card_id == card_id)
        .order_by(strategy_card_versions.c.version_no.desc())
        .limit(1)
    ).first()
    if cv is None:
        raise AppError(ErrorCode.NOT_FOUND)
    version = (
        conn.execute(
            select(strategy_versions)
            .join(strategies, strategies.c.id == strategy_versions.c.strategy_id)
            .where(
                strategy_versions.c.card_version_id == cv.id,
                (strategies.c.owner_user_id.is_(None) | (strategies.c.owner_user_id == owner)),
            )
            .order_by(strategy_versions.c.version_no.desc())
            .limit(1)
        ).first()
        if cv
        else None
    )
    if version is None:
        raise AppError(ErrorCode.NOT_FOUND)
    config = version.config
    spec = config.get(
        "spec",
        {
            k: v
            for k, v in config.items()
            if k not in {"mount_policy", "source_hash", "validation", "gates_missing"}
        },
    )
    fields = {k: v for k, v in cv.fields.items() if k not in {"narrative", "source_hash"}}
    validation = config.get("validation") or {}
    registry = {
        r.feature_key: {"unit": r.unit, "adjust": r.adjust, "status": r.status}
        for r in conn.execute(
            select(
                feature_catalog.c.feature_key,
                feature_catalog.c.unit,
                feature_catalog.c.adjust,
                feature_catalog.c.status,
            )
        )
    }
    document = "\n".join(
        "```yaml " + key + "\n" + yaml.safe_dump(value, allow_unicode=True) + "```"
        for key, value in [
            ("strategy-card", fields),
            ("strategy-spec", spec),
            ("validation", validation),
        ]
    )
    _, errors = preflight([document], registry)
    categories: dict[str, list[dict[str, str]]] = {"G1": [], "G2": [], "G3": [], "G4": []}
    for error in errors:
        path, issue = error["path"], error["issue"]
        gate = (
            "G4"
            if "params_schema" in path
            else "G2"
            if "feature" in issue
            else (
                "G3"
                if any(term in issue for term in ["dsl", "adjust", "expression", "symbol"])
                else "G1"
            )
        )
        categories[gate].append(error)
    needed = {key for r in spec.get("rules", []) for key in r.get("required_features", [])}
    for key in sorted(needed):
        if registry.get(key, {}).get("status") not in {"verified_doc", "verified_live"}:
            categories["G2"].append({"path": key, "issue": "feature_not_verified_doc_or_live"})
    fixtures = validation.get("fixtures", [])
    runs = (
        run_fixtures(fields, spec, fixtures, settings.business.market_rules, set(registry))
        if not errors
        else []
    )
    fixture_ok = len(runs) >= 6 and all(r.passed for r in runs)
    mapping = [
        {
            "rule_id": r["id"],
            "expr": r["expr"],
            "source": "strategy-spec.rules[" + str(i) + "]",
            "source_hash": cv.fields.get("source_hash"),
            "required_features": r.get("required_features", []),
        }
        for i, r in enumerate(spec.get("rules", []))
    ]
    results: list[dict[str, Any]] = [
        {
            "gate": gate,
            "result": "fail" if issues else "pass",
            "detail": {"issues": issues, "rule_source_map": mapping if gate == "G1" else []},
        }
        for gate, issues in categories.items()
    ]
    clamp = settings.business.risk_controls.rc1_stop_take.clamp_to_price_limit
    now = dt.datetime.now(dt.UTC)
    probe = evaluate_risk(
        settings.business.risk_controls,
        RiskContext(
            observations={
                key: Evidence.model_validate(
                    {
                        "id": "synthetic_g5_" + key,
                        "key": key,
                        "value": value,
                        "unit": "元",
                        "provider": "system",
                        "endpoint": None,
                        "data_as_of": now,
                        "fetched_at": now,
                        "epistemic_type": "hypothesis",
                    }
                )
                for key, value in [("limit_down_price", "8"), ("limit_up_price", "12")]
            },
            regime=None,
            trade_action=None,
            plan_action=None,
            invalidated=None,
            plan_stop_loss=None,
        ),
        action=Action.SELL,
        horizon=Horizon.SWING,
        stops=Stops(stop_loss=Decimal("1"), take_profit=Decimal("20"), time_stop_days=None),
    )
    clamp_checked = (probe.stops.stop_loss, probe.stops.take_profit) == (
        Decimal("8"),
        Decimal("12"),
    )
    results.append(
        {
            "gate": "G5",
            "result": "pass" if fixture_ok and clamp and clamp_checked else "fail",
            "detail": {
                "fixture_ashare_checks": fixture_ok,
                "runtime_gate": "gate_tradability",
                "price_limit_clamp_enabled": clamp,
                "synthetic_clamp_probe_passed": clamp_checked,
                "runtime_producer": "daily_analysis→write_candidate",
            },
        }
    )
    overlap = compare(None, set(), [])
    results.append(missing_history_gate(fixture_ok, overlap))
    results.append(
        {
            "gate": "G7",
            "result": "skipped",
            "detail": {"issue": "human_review_pending", "actor": "本人管理员点击；代理不得批准"},
        }
    )
    stat = {"value": None, "n": 0, "window": "120 trading days", "small_sample": True}
    # Keep unknown internal data explicit. Public serialization must not turn it into "0".
    report = {
        "trigger_rate": stat,
        "coverage": stat,
        **overlap.model_dump(),
        "quota_delta_per_min": 0 if not validation.get("feature_requests") else None,
    }
    review_id = uuid.uuid4()
    conn.execute(
        insert(strategy_promotion_reviews).values(
            id=review_id,
            card_version_id=cv.id,
            target_strategy_version_id=version.id,
            gate_results=json.loads(json.dumps(results)),
            fixture_runs=[
                {"fixture_id": r.fixture_id, "passed": r.passed, "diff": r.mismatches} for r in runs
            ],
            g6_report=report,
            decision="pending",
            compliance_lint={"status": "pending_human_review"},
            note="Prepared only; no G7 or lifecycle approval",
        )
    )
    return review_id


def owned_review(conn: Connection, owner: uuid.UUID, review_id: uuid.UUID) -> Any:  # noqa: ANN401
    row = conn.execute(
        select(strategy_promotion_reviews)
        .join(
            strategy_card_versions,
            strategy_card_versions.c.id == strategy_promotion_reviews.c.card_version_id,
        )
        .join(strategy_cards, strategy_cards.c.id == strategy_card_versions.c.card_id)
        .where(
            strategy_promotion_reviews.c.id == review_id,
            (strategy_cards.c.owner_user_id.is_(None) | (strategy_cards.c.owner_user_id == owner)),
        )
    ).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return row


def public_review(row: Any) -> dict[str, Any]:  # noqa: ANN401
    report = dict(row.g6_report or {})
    # A pre-T-A17 stored report remains immutable. Explicitly labelled unexamined
    # history is the only legacy case for which its already-known reason is recoverable.
    if report.get("contract_gaps"):
        legacy_unexamined = any(
            g.get("issue")
            == "contract_requires_nonnull_decimal_but_unexamined_history_has_no_value"
            for g in report.pop("contract_gaps")
        )
        if (
            legacy_unexamined
            and report.get("max_jaccard") is None
            and (report.get("trigger_rate") or {}).get("n") == 0
        ):
            report["max_jaccard_null_reason"] = "no_history"
    overlap = Overlap.model_validate(
        {key: report.get(key) for key in ["max_jaccard", "max_jaccard_null_reason"]}
    )
    report.update(overlap.model_dump())
    result = {k: getattr(row, k) for k in ["decision", "gate_results", "fixture_runs"]}
    result["gate_results"] = [
        {**g, "detail": {**g["detail"], "max_jaccard_null_reason": overlap.max_jaccard_null_reason}}
        if g["gate"] == "G6"
        else g
        for g in result["gate_results"]
    ]
    result["g6_report"] = report
    return result
