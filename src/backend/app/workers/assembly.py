"""Trusted daily P1 producer. Uses only frozen cached inputs and the existing DSL/archivers."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Connection, Row, insert, select

from app.config import Settings
from app.db.tables.market import trading_calendar
from app.db.tables.reviews import data_snapshots
from app.schemas.enums import Action, Dimension, GapReason, Horizon
from app.signals.models import Gap, MarketFacts, SignalInput, Stops
from app.signals.service import snapshot_items as signal_items
from app.signals.service import write_candidate
from app.strategy.cards.dsl import Interpreter, parse
from app.suggestions.confidence import components, numeric
from app.suggestions.models import Conclusion, SuggestionInput
from app.suggestions.risk import RiskContext, apply_risk, effective_config, evaluate_risk
from app.suggestions.service import archive
from app.suggestions.service import snapshot_items as suggestion_items


def canonical(value: Any) -> str:  # noqa: ANN401
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))


def persist(
    conn: Connection,
    owner: uuid.UUID,
    identifier: uuid.UUID,
    items: dict[str, Any],
    at: dt.datetime,
) -> None:
    prior = conn.execute(select(data_snapshots).where(data_snapshots.c.id == identifier)).first()
    encoded = json.loads(canonical(items))
    if prior:
        if prior.user_id != owner or prior.items != encoded:
            raise ValueError("engine_snapshot_identity_conflict")
        return
    conn.execute(
        insert(data_snapshots).values(
            id=identifier,
            user_id=owner,
            purpose="signal",
            hash=hashlib.sha256(canonical(items).encode()).hexdigest(),
            items=encoded,
            created_at=at,
        )
    )


def conclusion(
    conn: Connection,
    *,
    owner: uuid.UUID,
    instance: Row[Any],
    version: Row[Any],
    strategy: Row[Any],
    result: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    source: Row[Any],
    policy: Row[Any],
    settings: Settings,
) -> Conclusion:
    spec = version.config.get("spec", version.config)
    refs = result["rule_refs"]
    rules = {r["id"]: r for r in spec["rules"]}
    exit_only = all(r["role"] in {"weakening", "exit", "counter", "invalidation"} for r in refs)
    params = {key: value["default"] for key, value in spec["params_schema"].items()}
    params.update(instance.param_overrides or {})
    frame, at = result["frame"], result["as_of"]
    views = []

    def score(rows: list[dict[str, Any]]) -> int | None:
        positive = [
            r
            for r in rows
            if r["role"] in {"entry", "filter", "hold"}
            and Decimal(str(rules[r["rule_id"]].get("weight", 1))) > 0
        ]
        if not positive or any(r["passed"] is None for r in positive):
            return None
        weights = [Decimal(str(rules[r["rule_id"]].get("weight", 1))) for r in positive]
        value = sum((w for r, w in zip(positive, weights, strict=True) if r["passed"]), Decimal(0))
        return int((100 * value / sum(weights)).quantize(Decimal(1), rounding=ROUND_HALF_UP))

    for dimension in Dimension:
        rows = [r for r in refs if r["dimension"] == dimension]
        number = None if exit_only else score(rows)
        exits = [r for r in rows if r["role"] in {"weakening", "exit"}]
        if exit_only:
            view = (
                "bearish"
                if any(r["passed"] is True for r in exits)
                else "neutral"
                if exits and all(r["passed"] is not None for r in exits)
                else "unknown"
            )
        elif number is None:
            view = "unknown"
        else:
            limits = spec["dimension_view_thresholds"]
            view = (
                "bullish"
                if Decimal(number) / 100 >= Decimal(str(limits["bullish"]))
                else (
                    "bearish"
                    if Decimal(number) / 100 <= Decimal(str(limits["bearish"]))
                    else "neutral"
                )
            )
        views.append({"dimension": dimension, "view": view, "score": number, "rules": rows})
    confidence = components(
        refs=refs, views=views, rules=spec["rules"], frame=frame, params=params, registry=registry
    )
    stops: dict[str, Any] = {
        "stop_loss": None,
        "take_profit": None,
        "time_stop_days": spec.get("stops", {}).get("time_stop_days"),
    }
    stop_trace = {}
    missing = list(result["gaps"])
    for key in ["stop_loss", "take_profit"]:
        expr = spec.get("stops", {}).get(key)
        if expr is None:
            continue
        evaluator = Interpreter(frame["features"], frame["series"], frame["context"], params)
        node, _, _ = parse(expr, set(registry), set(params), "exit", "daily_close")
        stops[key] = numeric(evaluator.value(node))
        stop_trace[key] = {
            "expr": expr,
            "value": stops[key],
            "inputs": evaluator.inputs,
            "computed": evaluator.computed,
        }
        if stops[key] is None:
            missing.append("stops." + key)

    def texts(role: str) -> list[dict[str, Any]]:
        return [
            {
                "text": r["rule_id"]
                + (
                    "：满足"
                    if r["passed"] is True
                    else "：不满足"
                    if r["passed"] is False
                    else "：数据不足"
                ),
                "expr": rules[r["rule_id"]]["expr"],
                "evidence_ids": r["evidence_ids"],
            }
            for r in refs
            if r["role"] == role
        ]

    if not refs or not result["evidence"] or not texts("counter") or not texts("invalidation"):
        raise ValueError("p1_rule_evidence_counter_invalidation_missing")
    days = spec.get("valid_until", {}).get("trading_days")
    expiry = None
    if isinstance(days, int) and days > 0:
        future = (
            conn.execute(
                select(trading_calendar.c.date)
                .where(trading_calendar.c.date > at.date(), trading_calendar.c.is_open.is_(True))
                .order_by(trading_calendar.c.date)
                .limit(days)
            )
            .scalars()
            .all()
        )
        if len(future) == days:
            expiry = dt.datetime.combine(future[-1], dt.time(15), at.tzinfo)
    if expiry is None:
        missing.append("valid_until")
    gaps = [
        Gap(key=k, reason=GapReason.NO_SOURCE, message="未提供可验证输入，不作默认推断。")
        for k in sorted(set(missing))
    ]
    raw = {
        "security_code": result["security_code"],
        "proposed_action": result["action"],
        "t_leg": None,
        "score": None if exit_only else score(refs),
        "confidence": {k: confidence[k] for k in ["level", "value"]},
        "stops": stops,
        "rule_refs": refs,
        "evidence": result["evidence"],
        "counter_evidence": texts("counter"),
        "invalidation": texts("invalidation"),
        "model_refs": [],
        "risk_flags": [],
        "valid_until": expiry,
        "snapshot_id": uuid.UUID(int=0),
        "feature_set_version": result["feature_set_version"],
        "created_at": at,
        "data_status": "partial" if gaps else "fresh",
        "data_as_of": frame["data_as_of"] or at,
        "gaps": gaps,
    }
    signal = SignalInput.model_validate(raw)
    risk = evaluate_risk(
        effective_config(conn, owner, settings.business.risk_controls),
        RiskContext(
            observations={},
            regime=None,
            trade_action=None,
            plan_action=None,
            invalidated=None,
            plan_stop_loss=None,
        ),
        action=Action(result["action"]),
        horizon=Horizon(instance.horizon),
        stops=Stops.model_validate(stops),
    )
    signal = apply_risk(
        signal,
        risk,
        gaps=[
            Gap(key=k, reason=GapReason.NO_SOURCE, message="风控事实尚无证据。") for k in risk.gaps
        ],
    )
    signature = {
        "signal": signal.model_dump(mode="json"),
        "source_id": str(source.id),
        "version_id": str(version.id),
        "instance_id": str(instance.id),
        "policy_id": str(policy.id),
        "components": confidence["components"],
    }
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, canonical(signature))
    signal = signal.model_copy(update={"snapshot_id": identifier})
    features = frame["features"]
    price = frame["series"].get("f.close", [None])[-1] if frame["series"].get("f.close") else None
    facts = MarketFacts(
        price=price,
        is_suspended=features.get("f.is_suspended"),
        list_days=features.get("f.list_days"),
        limit_locked_up=features.get("f.limit_locked_up"),
        limit_locked_down=features.get("f.limit_locked_down"),
    )
    items = signal_items(signal, facts) | {
        "engine_policy_version_no": policy.version_no,
        "content_sha256": policy.config["content_sha256"],
        "source_snapshot_id": str(source.id),
        "source_hash": source.hash,
        "stop_evaluations": stop_trace,
        "confidence_components": confidence["components"],
    }
    persist(conn, owner, identifier, items, at)
    candidate = write_candidate(
        conn,
        user_id=owner,
        instance_id=instance.id,
        content=signal,
        facts=facts,
        market_rules=settings.business.market_rules,
    )
    if signal.proposed_action not in {"hold", "wait"} and candidate["id"] is None:
        raise ValueError("candidate_not_archivable:" + candidate["diagnostic"])
    return Conclusion.model_validate(
        {
            "strategy_version_id": version.id,
            "strategy_key": strategy.key,
            "strategy_name": strategy.name,
            "version_no": version.version_no,
            "instance_id": instance.id,
            "horizon": instance.horizon,
            "lifecycle": version.lifecycle,
            "state": result["state"],
            "signal": signal,
            "candidate_signal_id": candidate["id"],
            "priority_weight": "1",
            "priority_downweighted": False,
            "dimension_views": views,
            "confidence_components": confidence["components"],
            "reasons": [t for role in ["entry", "hold", "weakening", "exit"] for t in texts(role)],
        }
    )


def archive_conclusions(
    conn: Connection, owner: uuid.UUID, code: str, rows: list[Conclusion], policy: Row[Any]
) -> dict[str, Any]:
    at = max(r.signal.created_at for r in rows)
    raw = {
        "engine_policy_id": policy.id,
        "security_code": code,
        "snapshot_id": uuid.UUID(int=0),
        "feature_set_version": rows[0].signal.feature_set_version,
        "conclusions": rows,
        "data_status": "partial" if any(r.signal.gaps for r in rows) else "fresh",
        "data_as_of": max(r.signal.data_as_of for r in rows),
        "gaps": [g for r in rows for g in r.signal.gaps],
        "suitable": [],
        "user_overridden": False,
        "created_at": at,
    }
    content = SuggestionInput.model_validate(raw)
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, canonical(content.model_dump(mode="json")))
    content = content.model_copy(update={"snapshot_id": identifier})
    persist(conn, owner, identifier, suggestion_items(content), at)
    return archive(conn, user_id=owner, content=content)
