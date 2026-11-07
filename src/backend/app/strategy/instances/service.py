"""Transactional instance state operations and explicit system-component attachment.

No strategy selection, entitlement defaults, vendor access or candidate production.
System attachment requires an explicitly supplied reviewed component version; callers
must not replace that input with a catalog example or draft card.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Connection, Row, insert, select, update

from app.common.errors import AppError, ErrorCode
from app.db.tables.accounts import accounts, holdings
from app.db.tables.market import securities
from app.db.tables.strategy import strategies
from app.db.tables.strategy import strategy_instance_events as events
from app.db.tables.strategy import strategy_instances as instances
from app.db.tables.strategy import strategy_versions as versions
from app.schemas.enums import (
    InstanceOrigin,
    InstancePausedBy,
    InstanceStatus,
    Lifecycle,
    ReasonCode,
    RiskControl,
)
from app.strategy.eligibility import ensure_strategy_eligible
from app.strategy.instances.state import InstanceOp, InstanceState, apply_user_op


def owned(
    conn: Connection, user_id: uuid.UUID, instance_id: uuid.UUID, *, lock: bool = False
) -> Row[Any]:
    query = select(instances).where(instances.c.id == instance_id, instances.c.user_id == user_id)
    if lock:
        query = query.with_for_update()
    row = conn.execute(query).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return row


def event(
    conn: Connection,
    instance_id: uuid.UUID,
    *,
    kind: str,
    actor_id: uuid.UUID | None,
    before: str | None,
    after: str | None,
    note: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        insert(events).values(
            id=uuid.uuid4(),
            instance_id=instance_id,
            kind=kind,
            actor_id=actor_id,
            detail={
                "from_status": before,
                "to_status": after,
                "note": note,
                "actor": "user" if actor_id else "system",
                "detail": detail,
            },
        )
    )


def operate(
    conn: Connection,
    user_id: uuid.UUID,
    instance_id: uuid.UUID,
    op: InstanceOp,
    *,
    note: str | None = None,
) -> Row[Any]:
    row = owned(conn, user_id, instance_id, lock=True)
    actual = row.derived_strategy_version_id or row.strategy_version_id
    lifecycle = conn.execute(
        select(versions.c.lifecycle).where(versions.c.id == actual)
    ).scalar_one()
    state = InstanceState(
        status=InstanceStatus(row.status),
        origin=InstanceOrigin(row.origin),
        paused_by=InstancePausedBy(row.paused_by) if row.paused_by else None,
        pause_reason_code=ReasonCode(row.pause_reason_code) if row.pause_reason_code else None,
        paused_until=row.paused_until,
        archived_at=row.archived_at,
        updated_at=row.updated_at,
    )
    transition = apply_user_op(
        state, op, now=dt.datetime.now(dt.UTC), lifecycle=Lifecycle(lifecycle), note=note
    )
    if transition.changed:
        target = transition.state
        conn.execute(
            update(instances)
            .where(instances.c.id == instance_id)
            .values(
                status=target.status.value,
                paused_by=target.paused_by.value if target.paused_by else None,
                pause_reason_code=(
                    target.pause_reason_code.value if target.pause_reason_code else None
                ),
                paused_until=target.paused_until,
                archived_at=target.archived_at,
                updated_at=target.updated_at,
                **({"confirmed_at": target.updated_at} if op is InstanceOp.CONFIRM else {}),
            )
        )
        if transition.event_kind is None:
            raise RuntimeError("changed transition has no event")
        event(
            conn,
            instance_id,
            kind=transition.event_kind.value,
            actor_id=user_id,
            before=row.status,
            after=target.status.value,
            note=note,
            detail=transition.event_detail,
        )
    return owned(conn, user_id, instance_id)


def attach_system(
    conn: Connection,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    security_code: str,
    version_id: uuid.UUID,
    *,
    horizon: str,
    risk_settings: dict[str, Any],
) -> uuid.UUID:
    """Idempotent attachment under account lock; never revives a paused system instance.

    Explicit orchestration hook only, not an HTTP route or automatic H-01 selection.
    No call sites until formal component/policy and I1–I7 resolver are released.
    """
    account = conn.execute(
        select(accounts.c.id)
        .where(
            accounts.c.id == account_id,
            accounts.c.user_id == user_id,
            accounts.c.archived_at.is_(None),
        )
        .with_for_update()
    ).first()
    if account is None:
        raise AppError(ErrorCode.NOT_FOUND)
    quantity = conn.execute(
        select(holdings.c.quantity).where(
            holdings.c.account_id == account_id,
            holdings.c.security_code == security_code,
        )
    ).scalar_one_or_none()
    security_type = conn.execute(
        select(securities.c.type).where(
            securities.c.code == security_code,
        )
    ).scalar_one_or_none()
    ensure_strategy_eligible(security_code, security_type)
    if quantity is None or quantity <= 0:
        raise AppError(ErrorCode.INSTANCE_SCOPE_INVALID)
    version = conn.execute(select(versions).where(versions.c.id == version_id)).first()
    if version is None:
        raise AppError(ErrorCode.NOT_FOUND)
    owner_id = conn.execute(
        select(strategies.c.owner_user_id).where(
            strategies.c.id == version.strategy_id,
        )
    ).scalar_one()
    if owner_id is not None:
        raise AppError(ErrorCode.NOT_FOUND)
    if set(risk_settings) != {control.value for control in RiskControl} or any(
        not isinstance(value, dict)
        or type(value.get("enabled")) is not bool
        or not isinstance(value.get("params"), dict)
        for value in risk_settings.values()
    ):
        raise AppError(ErrorCode.RISK_CONTROL_INVALID_PARAMS)
    config = version.config
    roles = {rule.get("role") for rule in config.get("rules", [])}
    if (
        version.lifecycle not in {"published", "observing"}
        or config.get("origin") != "system"
        or not roles
        or not roles <= {"weakening", "exit", "counter", "invalidation"}
        or not roles.intersection({"weakening", "exit"})
        or not {"counter", "invalidation"} <= roles
        or any(action in {"buy", "add"} for action in config.get("action_map", {}).values())
        or horizon not in config.get("horizons", [])
    ):
        raise AppError(ErrorCode.STRATEGY_VERSION_NOT_RUNNABLE)
    existing = conn.execute(
        select(instances.c.id).where(
            instances.c.user_id == user_id,
            instances.c.account_id == account_id,
            instances.c.security_code == security_code,
            instances.c.origin == "system",
        )
    ).scalar_one_or_none()
    if existing is not None:
        return uuid.UUID(str(existing))
    identifier = uuid.uuid4()
    conn.execute(
        insert(instances).values(
            id=identifier,
            user_id=user_id,
            strategy_version_id=version_id,
            scope="security",
            account_id=account_id,
            security_code=security_code,
            origin="system",
            status="active",
            horizon=horizon,
            risk_settings_snapshot={"controls": risk_settings, "data_coverage": "partial"},
        )
    )
    event(conn, identifier, kind="created", actor_id=None, before=None, after="active")
    return identifier
