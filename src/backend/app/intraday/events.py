"""Owner-filtered rule event projection, never investment actions."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import Connection, Row, Select, and_, or_, select

from app.db.tables.licences import user_data_licences
from app.db.tables.market import securities
from app.db.tables.realtime import signal_events
from app.db.tables.strategy import strategy_instances, strategy_versions
from app.schemas.enums import SignalKind
from app.strategy.reviews import lint


def owned(owner: uuid.UUID) -> Select:
    return (
        select(signal_events)
        .join(user_data_licences, user_data_licences.c.id == signal_events.c.source_licence_id)
        .where(
            user_data_licences.c.user_id == owner,
            or_(
                signal_events.c.scope == "shared",
                and_(signal_events.c.scope == "user", signal_events.c.user_id == owner),
            ),
        )
    )


def project(conn: Connection, row: Row[Any]) -> dict[str, Any]:
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
        "instance_id": instance_ref(conn, row),
        "rule_id": d.get("rule_id"),
        "price": d.get("price"),
        "candidate_signal_id": d.get("candidate_signal_id"),
    }


def instance_ref(conn: Connection, event: Row[Any]) -> str | None:
    """Only unambiguous current owned binding; never guess among multiple instances."""
    owner = conn.execute(
        select(user_data_licences.c.user_id).where(
            user_data_licences.c.id == event.source_licence_id
        )
    ).scalar_one_or_none()
    ver = conn.execute(
        select(strategy_versions).where(strategy_versions.c.id == event.strategy_version_id)
    ).one_or_none()
    if owner is None or ver is None:
        return None
    q = select(strategy_instances).where(
        strategy_instances.c.user_id == owner,
        or_(
            strategy_instances.c.derived_strategy_version_id == ver.id,
            and_(
                strategy_instances.c.derived_strategy_version_id.is_(None),
                strategy_instances.c.strategy_version_id == ver.id,
            ),
        ),
        or_(
            strategy_instances.c.scope == "account",
            and_(
                strategy_instances.c.scope == "security",
                strategy_instances.c.security_code == event.security_code,
            ),
        ),
    )
    matches = []
    for inst in conn.execute(q):
        params = {
            k: v["default"] for k, v in ver.config.get("spec", ver.config)["params_schema"].items()
        }
        params.update(inst.param_overrides or {})
        body = json.dumps(
            params, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")
        )
        if hashlib.sha256(body.encode()).hexdigest() == event.params_hash:
            matches.append(inst.id)
    return str(matches[0]) if len(matches) == 1 else None
