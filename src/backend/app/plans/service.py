"""Plan transactions. JSON completeness stores immutable contract version fields."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, NoReturn

from sqlalchemy import Connection, Row, func, insert, select, text, update

from app.common.errors import AppError
from app.common.errors import ErrorCode as E
from app.db.tables.accounts import accounts
from app.db.tables.market import securities
from app.db.tables.research import action_plans, alerts, plan_conditions, plan_versions
from app.db.tables.users import audit_logs, users
from app.plans.models import PlanInput, VersionInput

OPEN = ("active", "triggered")


def invalid(field: str, issue: str = "invalid") -> NoReturn:
    raise AppError(E.VALIDATION_ERROR, details={"fields": [{"field": field, "issue": issue}]})


def transition(source: str, target: str, allowed: list[str]) -> NoReturn:
    raise AppError(
        E.INVALID_STATE_TRANSITION, details={"from": source, "to": target, "allowed": allowed}
    )


def audit(
    conn: Connection,
    owner: uuid.UUID,
    action: str,
    identifier: uuid.UUID,
    detail: dict[str, Any] | None = None,
    *,
    system: bool = False,
) -> None:
    conn.execute(
        insert(audit_logs).values(
            actor_id=None if system else owner,
            actor_role="system"
            if system
            else conn.execute(select(users.c.role).where(users.c.id == owner)).scalar_one(),
            action=action,
            target_type="action_plan",
            target_id=str(identifier),
            detail=detail or {},
        )
    )


def owner_lock(conn: Connection, owner: uuid.UUID) -> None:
    # Same first lock as candidate/suggestion assembly; then this module's lock.
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,74))"), {"owner": str(owner)}
    )
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,7707))"), {"owner": str(owner)}
    )


def owned(
    conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, lock: bool = False
) -> Row[Any]:
    q = select(action_plans).where(action_plans.c.id == identifier, action_plans.c.user_id == owner)
    row = conn.execute(q.with_for_update() if lock else q).first()
    if row is None:
        raise AppError(E.NOT_FOUND)
    return row


def validate(conn: Connection, owner: uuid.UUID, body: PlanInput) -> Row[Any]:
    from zoneinfo import ZoneInfo

    today = dt.datetime.now(ZoneInfo("Asia/Shanghai")).date()
    for condition in body.conditions:
        if condition.type == "date" and dt.date.fromisoformat(condition.params["on"]) < today:
            invalid("conditions.params.on")
    sec = conn.execute(select(securities).where(securities.c.code == body.security_code)).first()
    if sec is None:
        invalid("security_code", "unknown_security")
    if sec.type == "index":
        invalid("security_code", "not_allowed")
    if (
        body.account_id is not None
        and conn.execute(
            select(accounts.c.id).where(
                accounts.c.id == body.account_id, accounts.c.user_id == owner
            )
        ).first()
        is None
    ):
        invalid("account_id", "not_found")
    return sec


def duplicate(
    conn: Connection, owner: uuid.UUID, code: str, action: str, exclude: uuid.UUID | None = None
) -> None:
    q = (
        select(action_plans.c.id)
        .join(plan_versions, action_plans.c.current_version_id == plan_versions.c.id)
        .where(
            action_plans.c.user_id == owner,
            action_plans.c.security_code == code,
            action_plans.c.status.in_(OPEN),
            plan_versions.c.action == action,
        )
    )
    if exclude is not None:
        q = q.where(action_plans.c.id != exclude)
    found = conn.execute(q.order_by(action_plans.c.id)).first()
    if found:
        raise AppError(E.CONFLICT, details={"field": "security_code", "existing_id": str(found.id)})


def version(
    conn: Connection,
    head: Row[Any],
    body: PlanInput,
    n: int,
    *,
    answers: list[Any] | None = None,
    snapshot: uuid.UUID | None = None,
    market_rule: uuid.UUID | None = None,
) -> uuid.UUID:
    identifier = uuid.uuid4()
    payload = body.model_dump(mode="json", exclude={"base_version_no", "origin"})
    payload["checklist_answers"] = answers or []
    if n == 1:
        payload["candidate_signal_ids"] = [str(i) for i in (head.candidate_signal_ids or [])]
    payload["name"] = conn.execute(
        select(securities.c.name).where(securities.c.code == head.security_code)
    ).scalar_one()
    conn.execute(
        insert(plan_versions).values(
            id=identifier,
            plan_id=head.id,
            version_no=n,
            action=body.action.value,
            rationale=body.rationale,
            size_pct_of_assets=body.size_pct_of_assets,
            max_loss_amount=body.max_loss_amount,
            risks=body.risks,
            review_date=body.review_date,
            change_reason=getattr(body, "change_reason", None) if n > 1 else None,
            completeness=payload,
            snapshot_id=snapshot,
            market_rule_version_id=market_rule,
        )
    )
    for c in body.conditions:
        conn.execute(
            insert(plan_conditions).values(
                plan_version_id=identifier,
                kind=c.kind,
                type=c.type,
                params=c.params,
                description=c.description,
                epistemic_type="hypothesis",
            )
        )
    conn.execute(
        update(action_plans)
        .where(action_plans.c.id == head.id)
        .values(
            current_version_id=identifier, status="active", updated_at=func.now(), triggered_at=None
        )
    )
    return identifier


def project_version(conn: Connection, row: Row[Any]) -> dict[str, Any]:
    p = row.completeness or {}
    conditions = [
        {
            "id": str(c.id),
            "kind": c.kind,
            "type": c.type,
            "params": c.params,
            "description": c.description,
            "epistemic_type": "hypothesis",
        }
        for c in conn.execute(
            select(plan_conditions)
            .where(plan_conditions.c.plan_version_id == row.id)
            .order_by(plan_conditions.c.id)
        )
    ]
    return {
        "plan_id": str(row.plan_id),
        "version_no": row.version_no,
        "action": row.action,
        "qty": p.get("qty"),
        "price": p.get("price"),
        "size_pct_of_assets": str(row.size_pct_of_assets)
        if row.size_pct_of_assets is not None
        else None,
        "max_loss_amount": str(row.max_loss_amount) if row.max_loss_amount is not None else None,
        "stops": p.get("stops"),
        "rationale": row.rationale or "",
        "risks": row.risks,
        "review_date": row.review_date,
        "conditions": conditions,
        "change_reason": row.change_reason,
        "checklist_answers": p.get("checklist_answers", []),
        "snapshot_id": str(row.snapshot_id) if row.snapshot_id else None,
        "created_at": row.created_at,
    }


def alert_body(row: Row[Any]) -> dict[str, Any]:
    d = row.what_happened or {}
    return {
        "id": str(row.id),
        "rule_id": str(row.rule_id),
        "origin": d.get("origin", "plan_condition"),
        "severity": row.severity,
        "status": row.status,
        "security_code": row.security_code,
        "name": d.get("name", row.security_code),
        "title": d.get("title", ""),
        "triggered_at": row.triggered_at,
        "data_as_of": row.data_as_of,
        "affected_plans": row.affected or [],
        "evidence_ids": d.get("evidence_ids", []),
        "checklist": row.checklist or [],
        "snapshot_id": str(row.snapshot_id) if row.snapshot_id else None,
        "handled_at": row.handled_at,
        "evidence": d.get("evidence", []),
    }


def project(
    conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, summary: bool = False
) -> dict[str, Any]:
    head = owned(conn, owner, identifier)
    row = conn.execute(
        select(plan_versions).where(plan_versions.c.id == head.current_version_id)
    ).one()
    value = {
        "id": str(head.id),
        "security_code": head.security_code,
        "name": (row.completeness or {}).get("name", head.security_code),
        "account_id": str(head.account_id) if head.account_id else None,
        "origin": head.origin,
        "status": head.status,
        "action": row.action,
        "current_version_no": row.version_no,
        "plan_draft_id": str(head.plan_draft_id) if head.plan_draft_id else None,
        "candidate_id": None,
        "triggered_at": head.triggered_at,
        "created_at": head.created_at,
        "updated_at": head.updated_at,
    }
    if summary:
        return value
    pending, evidence = [], []
    if head.status in OPEN:
        for a in conn.execute(
            select(alerts)
            .where(
                alerts.c.user_id == owner,
                alerts.c.what_happened["plan_version_id"].astext == str(row.id),
            )
            .order_by(alerts.c.triggered_at, alerts.c.id)
        ):
            d = a.what_happened
            evidence.extend(d["evidence"])
            pending.append(
                {
                    "condition_id": d["condition_id"],
                    "condition_kind": d["condition_kind"],
                    "condition_text": d["condition_text"],
                    "triggered_at": a.triggered_at,
                    "alert_id": str(a.id),
                    "evidence_ids": d["evidence_ids"],
                }
            )
    value.update(
        current_version=project_version(conn, row),
        version_count=conn.execute(
            select(func.count())
            .select_from(plan_versions)
            .where(plan_versions.c.plan_id == head.id)
        ).scalar_one(),
        pending_triggers=pending,
        evidence=evidence,
    )
    return value


def create(
    conn: Connection,
    owner: uuid.UUID,
    body: PlanInput,
    *,
    draft: Row[Any] | None = None,
    answers: list[Any] | None = None,
) -> dict[str, Any]:
    validate(conn, owner, body)
    owner_lock(conn, owner)
    duplicate(conn, owner, body.security_code, body.action.value)
    identifier = uuid.uuid4()
    conn.execute(
        insert(action_plans).values(
            id=identifier,
            user_id=owner,
            security_code=body.security_code,
            account_id=body.account_id,
            origin="plan_draft" if draft else "manual",
            plan_draft_id=draft.id if draft else None,
            candidate_signal_ids=draft.signal_ids if draft else None,
            status="active",
        )
    )
    head = owned(conn, owner, identifier)
    version(
        conn,
        head,
        body,
        1,
        answers=answers,
        snapshot=draft.snapshot_id if draft else None,
        market_rule=draft.market_rule_version_id if draft else None,
    )
    audit(conn, owner, "plan.created", identifier)
    return project(conn, owner, identifier)


def revise(
    conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, body: VersionInput
) -> dict[str, Any]:
    owner_lock(conn, owner)
    head = owned(conn, owner, identifier, True)
    for key in ["security_code", "account_id", "origin"]:
        if key in body.model_fields_set and getattr(body, key) != getattr(head, key):
            invalid(key, "not_allowed")
    data = body.model_copy(
        update={"security_code": head.security_code, "account_id": head.account_id}
    )
    validate(conn, owner, data)
    if head.status not in OPEN:
        transition(head.status, head.status, [])
    current = conn.execute(
        select(plan_versions.c.version_no).where(plan_versions.c.id == head.current_version_id)
    ).scalar_one()
    if current != body.base_version_no:
        raise AppError(E.VERSION_CONFLICT, details={"current_version_no": current})
    duplicate(conn, owner, head.security_code, body.action.value, identifier)
    version(conn, head, data, current + 1)
    audit(conn, owner, "plan.revised", identifier, {"version_no": current + 1})
    return project(conn, owner, identifier)


def release_closed_plan_reasons(
    conn: Connection, owner: uuid.UUID, code: str, closed: uuid.UUID
) -> list[str]:
    """Exact machine-checkable plan.closed predicate, not a price/gate re-evaluation."""
    from app.db.tables.signals import (
        candidate_signal_events,
        candidate_signals,
        non_executable_reasons,
        reason_status_events,
    )

    remaining = (
        conn.execute(
            select(plan_versions.c.action)
            .join(action_plans, action_plans.c.current_version_id == plan_versions.c.id)
            .where(
                action_plans.c.user_id == owner,
                action_plans.c.security_code == code,
                action_plans.c.status.in_(OPEN),
            )
        )
        .scalars()
        .all()
    )
    released = []
    for reason in conn.execute(
        select(non_executable_reasons)
        .where(
            non_executable_reasons.c.user_id == owner,
            non_executable_reasons.c.code == "SAME_DIRECTION_PLAN_EXISTS",
            non_executable_reasons.c.status == "active",
            non_executable_reasons.c.machine_checkable.is_(True),
        )
        .order_by(non_executable_reasons.c.signal_id, non_executable_reasons.c.id)
        .with_for_update()
    ):
        if (reason.release_condition or {}).get("event") != "plan.closed":
            continue
        signal = conn.execute(
            select(candidate_signals)
            .where(
                candidate_signals.c.id == reason.signal_id,
                candidate_signals.c.user_id == owner,
                candidate_signals.c.security_code == code,
            )
            .with_for_update()
        ).first()
        if signal is None or any(
            (a in {"buy", "add"}) == (signal.proposed_action in {"buy", "add"}) for a in remaining
        ):
            continue
        value = {
            "event": "plan.closed",
            "plan_id": str(closed),
            "remaining_same_direction_plans": 0,
        }
        conn.execute(
            update(non_executable_reasons)
            .where(non_executable_reasons.c.id == reason.id)
            .values(
                status="released",
                released_at=func.now(),
                released_by="system",
                release_evidence=value,
            )
        )
        conn.execute(
            insert(reason_status_events).values(
                reason_id=reason.id,
                from_status="active",
                to_status="released",
                evaluated_value=value,
            )
        )
        if (
            signal.state == "blocked"
            and (signal.valid_until is None or signal.valid_until > dt.datetime.now(dt.UTC))
            and not conn.execute(
                select(non_executable_reasons.c.id).where(
                    non_executable_reasons.c.signal_id == signal.id,
                    non_executable_reasons.c.status == "active",
                )
            ).first()
        ):
            conn.execute(
                update(candidate_signals)
                .where(candidate_signals.c.id == signal.id, candidate_signals.c.user_id == owner)
                .values(state="released", state_changed_at=func.now())
            )
            conn.execute(
                insert(candidate_signal_events).values(
                    signal_id=signal.id,
                    from_state="blocked",
                    to_state="released",
                    cause="reason_released",
                    detail=value,
                )
            )
        released.append(str(reason.id))
    return released
