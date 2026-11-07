"""Batch owned-product reads: no provider reads, per-security queries or invented events."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any

from sqlalchemy import Connection, Row, func, select

from app.aggregates import models as m
from app.db.tables.realtime import suggestions
from app.db.tables.research import action_plans, alerts
from app.db.tables.signals import candidate_signals, non_executable_reasons, plan_drafts
from app.db.tables.strategy import risk_events, strategy_instances
from app.signals.models import Evidence


def encoded(value: Any) -> str:  # noqa: ANN401
    return json.dumps(value, default=str)


def owned_suggestions(
    conn: Connection, owner: uuid.UUID, account: uuid.UUID | None, at: dt.datetime
) -> dict[str, Row[Any]]:
    instances = (
        set(
            conn.execute(
                select(strategy_instances.c.id).where(
                    strategy_instances.c.user_id == owner,
                    strategy_instances.c.account_id == account,
                )
            ).scalars()
        )
        if account
        else set()
    )
    rows = conn.execute(
        select(suggestions)
        .where(
            suggestions.c.user_id == owner,
            suggestions.c.status == "active",
            suggestions.c.created_at <= at,
        )
        .order_by(suggestions.c.created_at.desc(), suggestions.c.id.desc())
    ).all()
    found: dict[str, Row[Any]] = {}
    for row in rows:
        conclusions = row.strategies or []
        ids = {uuid.UUID(c["instance_id"]) for c in conclusions if c.get("instance_id")}
        if not ids or not ids <= instances:
            continue
        expiry = [c.get("valid_until") for c in conclusions]
        if any(v is None or dt.datetime.fromisoformat(v) <= at for v in expiry):
            continue
        if row.valid_until is not None and row.valid_until <= at:
            continue
        found.setdefault(row.security_code, row)
    return found


def reasons(
    conn: Connection, owner: uuid.UUID, account: uuid.UUID | None, at: dt.datetime
) -> list[Row[Any]]:
    return (
        list(
            conn.execute(
                select(non_executable_reasons, candidate_signals.c.security_code)
                .join(
                    candidate_signals,
                    (candidate_signals.c.id == non_executable_reasons.c.signal_id)
                    & (candidate_signals.c.user_id == owner),
                )
                .join(
                    strategy_instances, strategy_instances.c.id == candidate_signals.c.instance_id
                )
                .where(
                    non_executable_reasons.c.user_id == owner,
                    strategy_instances.c.user_id == owner,
                    strategy_instances.c.account_id == account,
                    non_executable_reasons.c.detected_at <= at,
                )
                .order_by(non_executable_reasons.c.released_at.desc(), non_executable_reasons.c.id)
            ).all()
        )
        if account
        else []
    )


def blocks(
    conn: Connection,
    owner: uuid.UUID,
    account: uuid.UUID | None,
    at: dt.datetime,
    trade_date: dt.date,
    current: dict[str, Row[Any]],
    names: dict[str, str],
    reason_rows: list[Row[Any]],
) -> dict[str, Any]:
    output: dict[str, Any] = {"gaps": [], "evidence": []}

    def block(model: Any, rows: list[dict[str, Any]]) -> Any:  # noqa: ANN401
        return model.model_validate_json(encoded({"items": rows[:50], "more": len(rows) > 50}))

    known = (
        set(
            conn.execute(
                select(strategy_instances.c.id).where(
                    strategy_instances.c.user_id == owner,
                    strategy_instances.c.account_id == account,
                )
            ).scalars()
        )
        if account
        else set()
    )
    candidate_ids = (
        set(
            conn.execute(
                select(candidate_signals.c.id).where(
                    candidate_signals.c.user_id == owner, candidate_signals.c.instance_id.in_(known)
                )
            ).scalars()
        )
        if known
        else set()
    )
    drafts = conn.execute(
        select(plan_drafts)
        .where(plan_drafts.c.user_id == owner, plan_drafts.c.status.in_(["pending", "stale"]))
        .order_by(plan_drafts.c.created_at.desc(), plan_drafts.c.id)
    ).all()
    pending = [
        {
            "id": r.id,
            "security_code": r.security_code,
            "name": names.get(r.security_code, r.security_code),
            "action": r.action,
            "valid_until": r.expires_at,
            "status": r.status,
        }
        for r in drafts
        if (r.instance_id in known or (r.signal_ids and set(r.signal_ids) <= candidate_ids))
    ]
    output["pending_plan_drafts"] = block(m.ProductBlock[m.PendingDraft], pending)
    start = dt.datetime.combine(trade_date, dt.time(), dt.timezone(dt.timedelta(hours=8)))
    released = [
        {
            "reason_id": r.id,
            "signal_id": r.signal_id,
            "code": r.code,
            "security_code": r.security_code,
            "name": names.get(r.security_code, r.security_code),
            "released_at": r.released_at,
        }
        for r in reason_rows
        if r.status == "released" and r.released_at is not None and start <= r.released_at <= at
    ]
    output["released_reasons"] = block(m.ProductBlock[m.ReleasedReason], released)
    flags: list[dict[str, Any]] = []
    for code, row in current.items():
        prefix = code + ":"
        output["evidence"].extend(
            Evidence.model_validate({**e, "id": prefix + e["id"]}) for e in row.evidence or []
        )
        flags.extend(
            {
                **flag,
                "evidence_ids": [prefix + i for i in flag["evidence_ids"]],
                "security_code": code,
                "name": row.name,
                "risk_event_id": None,
            }
            for flag in row.risk_flags or []
        )
    output["risk_flags"] = block(m.ProductBlock[m.TodayRiskFlag], flags)
    output["invalidations_today"] = block(m.ProductBlock[m.Invalidation], [])
    # These older tables have no approved immutable event serializer/satisfaction timestamp.
    # Count actual records and disclose a gap; never infer an event from plan creation time.
    for table, key in [
        (alerts, "alerts"),
        (action_plans, "plan_triggers"),
        (risk_events, "risk_flags"),
    ]:
        count = conn.execute(
            select(func.count()).select_from(table).where(table.c.user_id == owner)
        ).scalar_one()
        if count:
            output["gaps"].append((key, "存在历史记录，但缺已接入的证据/事件映射；未伪造展示项。"))
    invalidated = conn.execute(
        select(func.count())
        .select_from(suggestions)
        .where(suggestions.c.user_id == owner, suggestions.c.status == "invalidated")
    ).scalar_one()
    if invalidated:
        output["gaps"].append(
            (
                "invalidations_today",
                "存在失效建议，但没有可信失效发生时刻，未以创建时刻冒充今日事件。",
            )
        )
    return output


def focus_rows(rows: list[m.TerminalRow]) -> tuple[list[m.TerminalRow], bool]:
    """Use the full sorted universe, never the already clipped public terminal rows."""
    selected = [row for row in rows if row.holding or row.focus]
    return selected[:50], len(selected) > 50
