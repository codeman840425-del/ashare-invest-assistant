# ruff: noqa: ANN401
"""Owned immutable archival and pointer changes, with no external or scheduling I/O."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import Connection, insert, select, text, update

from app.common.errors import AppError, ErrorCode
from app.db.tables.accounts import accounts
from app.db.tables.licences import user_data_licence_status
from app.db.tables.market import securities
from app.db.tables.realtime import suggestion_threads as threads
from app.db.tables.realtime import suggestions
from app.db.tables.reviews import data_snapshots
from app.db.tables.signals import candidate_signals, non_executable_reasons
from app.db.tables.strategy import strategies, strategy_instances, strategy_versions
from app.db.tables.users import users
from app.signals.service import TERMINAL
from app.suggestions.aggregate import assemble
from app.suggestions.models import Conclusion, SuggestionInput

SCHEMA = "tb75-suggestion-input-v1"


def snapshot_items(content: SuggestionInput) -> dict[str, Any]:
    return {"schema_version": SCHEMA, "input": content.model_dump(mode="json")}


def owned(conn: Connection, user_id: uuid.UUID, identifier: uuid.UUID) -> Any:
    row = conn.execute(
        select(suggestions).where(suggestions.c.id == identifier, suggestions.c.user_id == user_id)
    ).one_or_none()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return row


def view(row: Any) -> dict[str, Any]:
    body = (row.holding_context or {}).get("suggestion_view")
    if not isinstance(body, dict):
        raise AppError(ErrorCode.MAINTENANCE, details={"issue": "suggestion_view_not_available"})
    return {
        **body,
        "engine_policy": body.get("engine_policy"),
        "id": str(row.id),
        "status": row.status,
        "origin": row.origin,
        "name": row.name,
        "created_at": row.created_at.isoformat(),
        "supersedes_id": str(row.supersedes_id) if row.supersedes_id else None,
        "superseded_by_id": str(row.superseded_by_id) if row.superseded_by_id else None,
    }


def summary(row: Any) -> dict[str, Any]:
    body = view(row)
    scores = [s["score"] for s in body["strategies"] if s["score"] is not None]
    return {key: body[key] for key in ["id", "security_code", "name", "created_at", "status"]} | {
        "consensus": body["consensus"]["status"],
        "actions": [
            {
                key: s[key]
                for key in ["strategy_key", "strategy_name", "action", "t_leg", "lifecycle"]
            }
            for s in body["strategies"]
        ],
        "executability_status": body["executability"]["status"],
        "divergent_dimensions": [
            r["dimension"] for r in body["dimension_matrix"] if r["divergent"]
        ],
        "top_score": max(scores) if scores else None,
    }


def owned_snapshot(conn: Connection, user_id: uuid.UUID, identifier: uuid.UUID) -> Any:
    row = conn.execute(
        select(data_snapshots).where(
            data_snapshots.c.id == identifier, data_snapshots.c.user_id == user_id
        )
    ).one_or_none()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    if (
        row.licence_id is not None
        and not conn.execute(
            select(user_data_licence_status.c.id).where(
                user_data_licence_status.c.id == row.licence_id,
                user_data_licence_status.c.user_id == user_id,
            )
        ).first()
    ):
        raise AppError(ErrorCode.NOT_FOUND)
    return row


def verified_carried(
    conn: Connection, owner: uuid.UUID, code: str, snapshot: uuid.UUID | None, at: dt.datetime
) -> dict[uuid.UUID, dict[str, Any]]:
    """Only literal conclusions from the current owned immutable archive may carry.

    This is an evidence reference, not a caller-controlled exemption from validation.
    No current rule evaluation, mutable version/weight or lifecycle is substituted.
    """
    if snapshot is None:
        return {}
    previous = conn.execute(
        select(suggestions)
        .join(threads, threads.c.current_suggestion_id == suggestions.c.id)
        .where(
            threads.c.user_id == owner,
            threads.c.security_code == code,
            suggestions.c.user_id == owner,
            suggestions.c.security_code == code,
            suggestions.c.snapshot_id == snapshot,
            suggestions.c.created_at <= at,
        )
    ).one_or_none()
    if previous is None:
        raise ValueError("carried_archive_not_owned_current")
    source = owned_snapshot(conn, owner, snapshot)
    digest = hashlib.sha256(
        json.dumps(
            source.items, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")
        ).encode()
    ).hexdigest()
    if (
        source.hash != digest
        or source.items.get("schema_version") != SCHEMA
        or source.created_at > at
    ):
        raise ValueError("carried_archive_integrity")
    prior = SuggestionInput.model_validate(source.items["input"])
    if prior.security_code != code:
        raise ValueError("carried_archive_security")
    return {c.instance_id: c.model_dump(mode="json") for c in prior.conclusions}


def carried_candidate(
    conn: Connection, owner: uuid.UUID, item: Conclusion, instance: Any
) -> dict[str, Any] | None:
    """Keep the historical conclusion; current execution gates remain conservative."""
    if item.candidate_signal_id is None:
        return None
    row = conn.execute(
        select(candidate_signals).where(
            candidate_signals.c.id == item.candidate_signal_id, candidate_signals.c.user_id == owner
        )
    ).one_or_none()
    if row is None or (
        row.instance_id,
        row.strategy_version_id,
        row.snapshot_id,
        row.security_code,
    ) != (
        item.instance_id,
        item.strategy_version_id,
        item.signal.snapshot_id,
        item.signal.security_code,
    ):
        raise ValueError("carried_candidate_binding")
    reasons = list(
        conn.execute(
            select(non_executable_reasons.c.id).where(
                non_executable_reasons.c.signal_id == row.id,
                non_executable_reasons.c.user_id == owner,
                non_executable_reasons.c.status == "active",
            )
        ).scalars()
    )
    version = conn.execute(
        select(strategy_versions.c.lifecycle).where(
            strategy_versions.c.id == item.strategy_version_id
        )
    ).scalar_one()
    from app.strategy.runtime import runnable

    role = conn.execute(select(users.c.role).where(users.c.id == owner)).scalar_one()
    return {
        "blocked": bool(reasons)
        or row.state in TERMINAL
        or row.state == "blocked"
        or instance.status != "active"
        or (instance.derived_strategy_version_id or instance.strategy_version_id)
        != item.strategy_version_id
        or not runnable(version, role),
        "reason_ids": [str(r) for r in reasons],
    }


def archive(
    conn: Connection,
    *,
    user_id: uuid.UUID,
    content: SuggestionInput,
    origin: str = "daily_batch",
    carry_from_snapshot_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,74))"), {"owner": str(user_id)}
    )
    user = conn.execute(select(users).where(users.c.id == user_id).with_for_update()).one_or_none()
    if user is None or user.status != "approved":
        raise AppError(ErrorCode.ACCOUNT_NOT_APPROVED)
    # Same lock order as T-B74: owner first, then instance/version/account.
    joint = owned_snapshot(conn, user_id, content.snapshot_id)
    expected = snapshot_items(content)
    if carry_from_snapshot_id is not None:
        expected["carried_from_snapshot_id"] = str(carry_from_snapshot_id)
    if joint.items != expected or joint.created_at > content.created_at:
        raise ValueError("suggestion_snapshot_input_mismatch")
    market = conn.execute(
        select(securities).where(securities.c.code == content.security_code).with_for_update()
    ).one_or_none()
    if market is None or market.type != "stock" or market.listing_status != "listed":
        raise ValueError("suggestion_security_not_supported")
    carried = verified_carried(
        conn, user_id, content.security_code, carry_from_snapshot_id, content.created_at
    )
    retained = set()
    candidates: dict[str, dict[str, Any]] = {}
    for conclusion in sorted(
        content.conclusions, key=lambda c: (str(c.strategy_version_id), str(c.instance_id))
    ):
        instance = conn.execute(
            select(strategy_instances)
            .where(
                strategy_instances.c.id == conclusion.instance_id,
                strategy_instances.c.user_id == user_id,
            )
            .with_for_update()
        ).one_or_none()
        if instance is None:
            raise AppError(ErrorCode.NOT_FOUND)
        if carried.get(conclusion.instance_id) == conclusion.model_dump(mode="json"):
            retained.add(conclusion.instance_id)
            state = carried_candidate(conn, user_id, conclusion, instance)
            if state is not None:
                candidates[str(conclusion.candidate_signal_id)] = state
            continue
        if (
            instance.status != "active"
            or (instance.derived_strategy_version_id or instance.strategy_version_id)
            != conclusion.strategy_version_id
        ):
            raise ValueError("suggestion_instance_not_active_or_version_mismatch")
        account = conn.execute(
            select(accounts)
            .where(
                accounts.c.id == instance.account_id,
                accounts.c.user_id == user_id,
                accounts.c.archived_at.is_(None),
            )
            .with_for_update()
        ).one_or_none()
        if account is None:
            raise AppError(ErrorCode.NOT_FOUND)
        if instance.scope != "account" and not (
            instance.scope == "security" and instance.security_code == content.security_code
        ):
            raise ValueError("suggestion_scope_mismatch")
        version = conn.execute(
            select(strategy_versions)
            .where(strategy_versions.c.id == conclusion.strategy_version_id)
            .with_for_update()
        ).one()
        strategy = conn.execute(
            select(strategies).where(strategies.c.id == version.strategy_id)
        ).one()
        from app.strategy.runtime import runnable

        if not runnable(version.lifecycle, user.role):
            raise AppError(
                ErrorCode.STRATEGY_VERSION_NOT_RUNNABLE, details={"lifecycle": version.lifecycle}
            )
        if strategy.owner_user_id not in {None, user_id} or (
            conclusion.strategy_key,
            conclusion.strategy_name,
            conclusion.version_no,
            conclusion.horizon,
            conclusion.lifecycle,
        ) != (strategy.key, strategy.name, version.version_no, instance.horizon, version.lifecycle):
            raise ValueError("suggestion_version_metadata_mismatch")
        if (
            conclusion.signal.valid_until is not None
            and conclusion.signal.valid_until <= content.created_at
        ):
            raise ValueError("suggestion_source_expired")
        source = owned_snapshot(conn, user_id, conclusion.signal.snapshot_id)
        if (source.items or {}).get("signal_input") != conclusion.signal.model_dump(mode="json"):
            raise ValueError("suggestion_source_input_mismatch")
        rules = version.config.get("spec", version.config).get("rules", [])
        known = {r["id"]: r for r in rules}
        if not known or any(
            r.rule_id not in known
            or (known[r.rule_id]["role"], known[r.rule_id]["dimension"], known[r.rule_id]["expr"])
            != (r.role, r.dimension, r.threshold)
            for r in conclusion.signal.rule_refs
        ):
            raise ValueError("suggestion_version_rules_mismatch")
        exit_only = all(
            r.role in {"weakening", "exit", "counter", "invalidation"}
            for r in conclusion.signal.rule_refs
        )
        if exit_only:
            from app.api.v1.portfolio import _account

            position = _account(
                conn,
                account.id,
                content.created_at.astimezone(dt.timezone(dt.timedelta(hours=8))).date(),
            ).positions.get(content.security_code)
            if position is None or position.qty <= 0:
                raise ValueError("exit_only_without_holding")
            if (
                conclusion.signal.proposed_action not in {"hold", "reduce", "sell"}
                or conclusion.signal.score is not None
            ):
                raise ValueError("exit_only_conclusion_invalid")
        identifier = conclusion.candidate_signal_id
        if identifier is not None:
            candidate = conn.execute(
                select(candidate_signals)
                .where(candidate_signals.c.id == identifier, candidate_signals.c.user_id == user_id)
                .with_for_update()
            ).one_or_none()
            if candidate is None:
                raise AppError(ErrorCode.NOT_FOUND)
            if (
                candidate.instance_id,
                candidate.strategy_version_id,
                candidate.snapshot_id,
                candidate.security_code,
            ) != (
                instance.id,
                version.id,
                conclusion.signal.snapshot_id,
                content.security_code,
            ) or candidate.state in TERMINAL:
                raise ValueError("suggestion_candidate_mismatch_or_terminal")
            for field in [
                "proposed_action",
                "t_leg",
                "score",
                "stops",
                "rule_refs",
                "evidence",
                "counter_evidence",
                "invalidation",
                "model_refs",
                "risk_flags",
            ]:
                expected = conclusion.signal.model_dump(mode="json")[field]
                if getattr(candidate, field) != expected:
                    raise ValueError("suggestion_candidate_body_mismatch")
            active = [
                str(v)
                for v in conn.execute(
                    select(non_executable_reasons.c.id).where(
                        non_executable_reasons.c.signal_id == identifier,
                        non_executable_reasons.c.user_id == user_id,
                        non_executable_reasons.c.status == "active",
                    )
                ).scalars()
            ]
            candidates[str(identifier)] = {
                "blocked": bool(active) or candidate.state == "blocked",
                "reason_ids": active,
            }
    body = assemble(content, candidates)
    body["engine_policy"] = None
    if content.engine_policy_id is not None:
        from app.db.tables.strategy import engine_policies
        from app.suggestions.confidence import ConfidenceComponents

        policy = conn.execute(
            select(engine_policies).where(engine_policies.c.id == content.engine_policy_id)
        ).one()
        for conclusion in content.conclusions:
            if conclusion.instance_id in retained:
                continue
            ConfidenceComponents.model_validate(conclusion.confidence_components)
            source = owned_snapshot(conn, user_id, conclusion.signal.snapshot_id)
            if (
                source.items.get("engine_policy_version_no"),
                source.items.get("content_sha256"),
            ) != (policy.version_no, policy.config["content_sha256"]):
                raise ValueError("candidate_policy_snapshot_mismatch")
        body["engine_policy"] = {
            "version_no": policy.version_no,
            "content_sha256": policy.config["content_sha256"],
        }
    if any(c.lifecycle == "simulating" for c in content.conclusions):
        body["explanation"]["text"] = "模拟中；不生成计划草案。" + body["explanation"]["text"]
    fingerprint = hashlib.sha256(
        json.dumps(
            {k: v for k, v in body.items() if k != "snapshot_id"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    thread = conn.execute(
        select(threads)
        .where(threads.c.user_id == user_id, threads.c.security_code == content.security_code)
        .with_for_update()
    ).one_or_none()
    prior = (
        owned(conn, user_id, thread.current_suggestion_id)
        if thread and thread.current_suggestion_id
        else None
    )
    if (
        prior
        and prior.status == "active"
        and (prior.holding_context or {}).get("input_hash") == fingerprint
    ):
        return {
            "suggestion": view(prior),
            "changed": False,
            "superseded_id": None,
            "data_as_of": body["data_as_of"],
        }
    thread_id = thread.id if thread else uuid.uuid4()
    identifier = uuid.uuid4()
    if thread is None:
        conn.execute(
            insert(threads).values(
                id=thread_id, user_id=user_id, security_code=content.security_code
            )
        )
    if prior and prior.status == "active":
        conn.execute(
            update(suggestions).where(suggestions.c.id == prior.id).values(status="superseded")
        )
    values = {
        k: body[k]
        for k in [
            "evidence",
            "strategies",
            "executability",
            "consensus",
            "dimension_matrix",
            "divergence",
            "risk_flags",
            "feature_set_version",
            "data_status",
        ]
    }
    values.update(
        {k: [uuid.UUID(v) for v in body[k]] for k in ["candidate_signal_ids", "plan_draft_ids"]}
    )
    # No automatic plan creation, inference, model call or template promotion.
    conn.execute(
        insert(suggestions).values(
            id=identifier,
            thread_id=thread_id,
            user_id=user_id,
            security_code=content.security_code,
            name=market.name,
            seq_no=prior.seq_no + 1 if prior else 1,
            status="active",
            origin=origin,
            snapshot_id=content.snapshot_id,
            engine_policy_id=content.engine_policy_id,
            strategy_version_ids=[c.strategy_version_id for c in content.conclusions],
            holding_context={"input_hash": fingerprint, "suggestion_view": body},
            explanation_text=body["explanation"]["text"],
            explanation_source="template",
            generated_by="rules_engine@tb75-v1",
            supersedes_id=prior.id if prior else None,
            created_at=content.created_at,
            **values,
        )
    )
    if prior:
        conn.execute(
            update(suggestions)
            .where(suggestions.c.id == prior.id)
            .values(superseded_by_id=identifier)
        )
    conn.execute(
        update(threads)
        .where(threads.c.id == thread_id)
        .values(current_suggestion_id=identifier, status="active", updated_at=content.created_at)
    )
    return {
        "suggestion": view(owned(conn, user_id, identifier)),
        "changed": True,
        "superseded_id": str(prior.id) if prior else None,
        "data_as_of": body["data_as_of"],
    }
