"""In-app facts only. Caller owns transaction; transport happens after commit."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Row, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.db.tables.market import securities
from app.db.tables.notify import notification_refs, notifications

TZ = ZoneInfo("Asia/Shanghai")
LEVELS = {"info": 0, "attention": 1, "important": 2}


def project(conn: Connection, row: Row[Any]) -> dict[str, Any]:
    refs = conn.execute(
        select(notification_refs)
        .where(notification_refs.c.notification_id == row.id)
        .order_by(
            notification_refs.c.at.desc(), notification_refs.c.ref_type, notification_refs.c.ref_id
        )
        .limit(20)
    ).all()
    name = (
        conn.execute(
            select(securities.c.name).where(securities.c.code == row.security_code)
        ).scalar_one_or_none()
        if row.security_code
        else None
    )
    return {
        "id": str(row.id),
        "kind": row.kind,
        "severity": row.severity,
        "title": row.title,
        "body": row.body,
        "created_at": row.created_at.isoformat(),
        "updated_at": (row.updated_at or row.created_at).isoformat(),
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "security_code": row.security_code,
        "name": name,
        "merged_count": row.merged_count or 1,
        "version": row.version or 1,
        "refs": [
            {
                "type": r.ref_type,
                "id": r.ref_id,
                "at": r.at.isoformat(),
                "route": ref_route(conn, row.user_id, r.ref_type, r.ref_id),
            }
            for r in refs
        ],
        "target": {"type": row.target_type, "id": row.target_id, "route": row.target_route},
    }


def append(
    conn: Connection,
    *,
    owner: uuid.UUID,
    kind: str,
    severity: str,
    title: str,
    body: str | None,
    code: str | None,
    target_type: str,
    target_id: str | None,
    ref_type: str,
    ref_id: str,
    at: dt.datetime,
) -> tuple[uuid.UUID, bool]:
    if ref_type not in {"signal", "plan_condition"} or str(uuid.UUID(ref_id)) != ref_id:
        raise ValueError("invalid_notification_ref")
    if ref_type == "plan_condition" and ref_route(conn, owner, ref_type, ref_id) is None:
        raise ValueError("invalid_owned_plan_condition_ref")
    if at.tzinfo is None or severity not in LEVELS:
        raise ValueError("invalid_notification_clock_or_severity")
    local = at.astimezone(TZ)
    bucket = local.replace(minute=local.minute // 10 * 10, second=0, microsecond=0)
    key = f"{code}|{kind}|{bucket.isoformat()}" if code else f"{kind}|{ref_type}|{ref_id}"
    # A DB advisory lock serializes cross-process upsert + unique ref + read reset.
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 706))"),
        {"key": str(owner) + "|" + key},
    )
    identifier = conn.execute(
        select(notifications.c.id).where(
            notifications.c.user_id == owner, notifications.c.dedup_key == key
        )
    ).scalar_one_or_none()
    if identifier is None:
        identifier = uuid.uuid4()
        conn.execute(
            insert(notifications).values(
                id=identifier,
                user_id=owner,
                kind=kind,
                severity=severity,
                title=title,
                body=body,
                security_code=code,
                dedup_key=key,
                created_at=at,
                updated_at=at,
                merged_count=1,
                target_type=target_type,
                target_id=target_id,
                target_route=route(target_type, target_id),
            )
        )
        fresh = True
    else:
        fresh = False
    new = conn.execute(
        insert(notification_refs)
        .values(notification_id=identifier, ref_type=ref_type, ref_id=ref_id, at=at)
        .on_conflict_do_nothing()
        .returning(notification_refs.c.ref_id)
    ).first()
    if new is None:
        return identifier, False
    row = conn.execute(
        select(notifications).where(notifications.c.id == identifier).with_for_update()
    ).one()
    values: dict[str, Any] = {
        "read_at": None,
        "version": row.version if fresh else row.version + 1,
        "merged_count": row.merged_count if fresh else row.merged_count + 1,
    }
    if at >= (row.updated_at or row.created_at):
        values.update(
            updated_at=at,
            title=title,
            body=body,
            target_type=target_type,
            target_id=target_id,
            target_route=route(target_type, target_id),
        )
    values["severity"] = max((row.severity, severity), key=LEVELS.__getitem__)
    refs = conn.execute(
        select(notification_refs)
        .where(notification_refs.c.notification_id == identifier)
        .order_by(
            notification_refs.c.at.desc(), notification_refs.c.ref_type, notification_refs.c.ref_id
        )
        .limit(20)
    ).all()
    values["refs"] = [
        {
            "type": r.ref_type,
            "id": r.ref_id,
            "at": r.at.isoformat(),
            "route": ref_route(conn, row.user_id, r.ref_type, r.ref_id),
        }
        for r in refs
    ]
    conn.execute(update(notifications).where(notifications.c.id == identifier).values(**values))
    return identifier, True


def route(kind: str, identifier: str | None) -> str | None:
    prefixes = {
        "suggestion": "/suggestions/",
        "candidate_signal": "/candidate-signals/",
        "plan": "/plans/",
        "plan_draft": "/plan-drafts/",
        "daily_report": "/daily-reports/",
    }
    if kind == "none":
        if identifier is not None:
            raise ValueError("none_target_has_identifier")
        return None
    if kind not in prefixes or identifier is None:
        raise ValueError("unsupported_internal_target")
    if kind == "daily_report":
        dt.date.fromisoformat(identifier)
    else:
        uuid.UUID(identifier)
    return prefixes[kind] + identifier


def ref_route(conn: Connection, owner: uuid.UUID, kind: str, identifier: str) -> str | None:
    if kind == "signal":
        return None
    from app.db.tables.research import action_plans, plan_conditions, plan_versions

    plan = conn.execute(
        select(action_plans.c.id)
        .join(plan_versions, plan_versions.c.plan_id == action_plans.c.id)
        .join(plan_conditions, plan_conditions.c.plan_version_id == plan_versions.c.id)
        .where(plan_conditions.c.id == uuid.UUID(identifier), action_plans.c.user_id == owner)
    ).scalar_one_or_none()
    return "/plans/" + str(plan) if plan else None
