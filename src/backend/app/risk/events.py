"""Append transitions to existing risk_events; GET never creates or clears events."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any

from sqlalchemy import Connection, DateTime, Uuid, cast, insert, select, text

from app.db.tables.strategy import risk_events
from app.schemas.enums import RiskControl

SCHEMA = "p2n02-risk-event-v1"


def record(
    conn: Connection,
    *,
    owner: uuid.UUID,
    account_id: uuid.UUID | None,
    instance_id: uuid.UUID,
    code: str,
    name: str,
    controls: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    at: dt.datetime,
    suggestion_id: uuid.UUID | None = None,
) -> None:
    """Business transaction only. Unknown inputs never clear a prior known violation.

    One append-only episode has active/cleared projections, the existing public
    RiskEvent states. Repeating identical facts adds no event, even on a new day.
    """
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": "risk-events:" + str(owner)},
    )
    for control in controls:
        key = ":".join([str(owner), str(account_id), str(instance_id), code, control["control"]])
        previous = conn.execute(
            select(risk_events)
            .where(
                risk_events.c.user_id == owner,
                risk_events.c.detail["schema"].astext == SCHEMA,
                risk_events.c.detail["event_key"].astext == key,
            )
            .order_by(risk_events.c.created_at.desc(), risk_events.c.id.desc())
            .limit(1)
        ).first()
        prior = previous.detail["payload"] if previous is not None else None
        if previous is not None and dt.datetime.fromisoformat(previous.detail["evaluated_at"]) > at:
            continue
        stored_at = max(at, previous.created_at + dt.timedelta(microseconds=1)) if previous else at
        # RC1 disabled warning remains active, but never has gated actions.
        flags = control["flags"]
        if not flags:
            if (
                control["state"] not in {"ok", "disabled"}
                or prior is None
                or prior["status"] == "cleared"
            ):
                continue
            payload = {**prior, "status": "cleared", "cleared_at": at.isoformat()}
            if control["control"] == "stop_take":
                checked = [e for e in evidence if e["key"] in {"rc1.price_check", "rc1.time_check"}]
                if not checked:
                    continue
                checked += [e for e in evidence if e["key"].startswith("rc1.price_basis:")]
                combined = {e["id"]: e for e in [*prior["evidence"], *checked]}
                payload.update(evidence=list(combined.values()), evidence_ids=sorted(combined))
        else:
            ids = sorted({i for f in flags for i in f["evidence_ids"]})
            used = [e for e in evidence if e["id"] in ids]
            if set(ids) != {e["id"] for e in used}:
                raise ValueError("risk_event_evidence_unresolved")
            caps = [f["quantity_cap"] for f in flags if f["quantity_cap"] is not None]
            from decimal import Decimal

            cap = str(min(Decimal(str(v)) for v in caps)) if caps else None
            payload = {
                "control": control["control"],
                "level": max(
                    (f["level"] for f in flags),
                    key=lambda v: {"info": 0, "warning": 1, "critical": 2}[v],
                ),
                "message": "；".join(dict.fromkeys(f["message"] for f in flags)),
                "gated_actions": sorted({v for f in flags for v in f["gated_actions"]}),
                "quantity_cap": cap,
                "evidence_ids": ids,
                "security_code": code,
                "name": name,
                "status": "active",
                "cleared_at": None,
                "suggestion_id": str(suggestion_id) if suggestion_id else None,
                "evidence": used,
            }
            # Evidence timestamps/context changing without flag meaning changing
            # do not open duplicate episodes or append daily duplicates.
            semantic = ["control", "level", "message", "gated_actions", "quantity_cap"]
            if (
                prior is not None
                and prior["status"] == "active"
                and all(prior[k] == payload[k] for k in semantic)
            ):
                continue
            if prior is not None and prior["status"] == "active":
                payload.update(id=prior["id"], triggered_at=prior["triggered_at"])
            else:
                times = [
                    dt.datetime.fromisoformat(str(e["value"]))
                    for e in used
                    if e["key"].startswith("rc1.event_at:")
                ]
                point = min(times) if times else at
                if point.tzinfo is None or point > at:
                    raise ValueError("risk_event_time_invalid")
                payload.update(id=str(uuid.uuid4()), triggered_at=point.isoformat())
        conn.execute(
            insert(risk_events).values(
                id=uuid.uuid4(),
                user_id=owner,
                control=control["control"],
                level=payload["level"],
                subject="security",
                security_code=code,
                detail={
                    "schema": SCHEMA,
                    "event_key": key,
                    "payload": payload,
                    "evaluated_at": at.isoformat(),
                },
                suggestion_id=suggestion_id,
                created_at=stored_at,
            )
        )


def listing(
    conn: Connection,
    owner: uuid.UUID,
    status: str | None,
    control: RiskControl | None,
    code: str | None,
    since: dt.datetime | None,
) -> tuple[Any, Any, Any, str]:
    # DISTINCT by episode id (not subject), so cleared historical episodes remain
    # visible when a later episode of the same subject is opened.
    root = risk_events.c.detail["payload"]["id"].astext
    latest = (
        select(risk_events.c.detail["payload"].label("payload"))
        .where(
            risk_events.c.user_id == owner,
            risk_events.c.detail["schema"].astext == SCHEMA,
        )
        .distinct(root)
        .order_by(root, risk_events.c.created_at.desc(), risk_events.c.id.desc())
        .subquery()
    )
    table = select(
        latest.c.payload,
        cast(latest.c.payload["id"].astext, Uuid).label("id"),
        cast(latest.c.payload["triggered_at"].astext, DateTime(timezone=True)).label(
            "triggered_at"
        ),
    ).subquery()
    query = select(table)
    for key, value in [("status", status), ("control", control), ("security_code", code)]:
        if value is not None:
            query = query.where(table.c.payload[key].astext == value)
    if since is not None:
        query = query.where(table.c.triggered_at >= since)
    scope = json.dumps(
        ["risk-events", str(owner), status, control, code, since.isoformat() if since else None]
    )
    return query, table, table.c.triggered_at, scope
