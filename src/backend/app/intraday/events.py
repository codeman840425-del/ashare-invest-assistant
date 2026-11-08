"""Owner-filtered rule event projection, never investment actions."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Connection, Row, Select, and_, or_, select

from app.db.tables.licences import user_data_licences
from app.db.tables.market import securities
from app.db.tables.realtime import signal_event_projections, signal_events
from app.schemas.enums import SignalKind
from app.strategy.reviews import lint


def owned(owner: uuid.UUID) -> Select[Any]:
    return (
        select(signal_events)
        .join(user_data_licences, user_data_licences.c.id == signal_events.c.source_licence_id)
        .where(
            user_data_licences.c.user_id == owner,
            select(signal_event_projections.c.event_id)
            .where(
                signal_event_projections.c.event_id == signal_events.c.id,
                signal_event_projections.c.user_id == owner,
            )
            .exists(),
            or_(
                signal_events.c.scope == "shared",
                and_(signal_events.c.scope == "user", signal_events.c.user_id == owner),
            ),
        )
    )


def project(conn: Connection, row: Row[Any]) -> dict[str, Any]:
    frozen = conn.execute(
        select(signal_event_projections)
        .join(
            user_data_licences, user_data_licences.c.user_id == signal_event_projections.c.user_id
        )
        .where(
            signal_event_projections.c.event_id == row.id,
            user_data_licences.c.id == row.source_licence_id,
        )
    ).one()
    d = row.detail
    kind = SignalKind(d["kind"])
    messages = {k.value: "规则状态已变化，请查看证据。" for k in SignalKind}
    messages["data_stale"] = "行情数据状态已变化，请查看证据。"
    messages["suspended"] = "证券交易状态已变化，请查看证据。"
    message = messages[kind.value]
    lint(message)
    return {
        "signal_event_id": str(row.id),
        "security_code": row.security_code,
        "name": conn.execute(
            select(securities.c.name).where(securities.c.code == row.security_code)
        ).scalar_one(),
        "kind": d["kind"],
        "at": row.created_at.isoformat(),
        "message": message,
        "strategy_key": d.get("strategy_key"),
        "instance_id": str(frozen.instance_id) if frozen.instance_id else None,
        "instance_ids": [str(i) for i in frozen.instance_ids],
        "rule_id": d.get("rule_id"),
        "price": d.get("price"),
        "candidate_signal_id": str(frozen.candidate_signal_id)
        if frozen.candidate_signal_id
        else None,
    }


def instance_ref(conn: Connection, event: Row[Any]) -> str | None:
    row = conn.execute(
        select(signal_event_projections.c.instance_id).where(
            signal_event_projections.c.event_id == event.id
        )
    ).scalar_one_or_none()
    return str(row) if row else None
