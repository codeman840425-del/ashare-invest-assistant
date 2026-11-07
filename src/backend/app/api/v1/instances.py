"""T-B73 owned instances and explicit user creation; no automatic formal-card selection."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Connection, Row, and_, func, or_, select

from app.api.v1.accounts import owned_account
from app.api.v1.trades import normalize_code
from app.auth.deps import AuthDep, EngineDep, SettingsDep
from app.common.errors import AppError, ErrorCode
from app.common.pagination import PageParams, build_page, decode_cursor, page_params
from app.db.tables.market import securities
from app.db.tables.strategy import strategies, strategy_card_versions
from app.db.tables.strategy import strategy_instance_events as events
from app.db.tables.strategy import strategy_instances as instances
from app.db.tables.strategy import strategy_versions as versions
from app.schemas.enums import CardRiskLevel, Horizon, InstanceOrigin, InstanceSort, InstanceStatus
from app.strategy.instances.creation import create, patch
from app.strategy.instances.service import operate, owned
from app.strategy.instances.state import InstanceOp

router = APIRouter(tags=["strategy-instances"])


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    note: str | None = Field(default=None, max_length=200)


def instance_out(conn: Connection, row: Row[Any]) -> dict[str, Any]:
    actual = row.derived_strategy_version_id or row.strategy_version_id
    version = conn.execute(select(versions).where(versions.c.id == actual)).one()
    strategy = conn.execute(select(strategies).where(strategies.c.id == version.strategy_id)).one()
    name = None
    if row.security_code:
        name = (
            conn.execute(
                select(securities.c.name).where(
                    securities.c.code == row.security_code,
                )
            ).scalar_one_or_none()
            or row.security_code
        )
    card = None
    if version.card_version_id:
        card = conn.execute(
            select(strategy_card_versions.c.fields).where(
                strategy_card_versions.c.id == version.card_version_id,
            )
        ).scalar_one_or_none()
    fields = (
        "id",
        "derived_strategy_version_id",
        "status",
        "origin",
        "scope",
        "account_id",
        "security_code",
        "horizon",
        "param_overrides",
        "auto_downweight",
        "paused_by",
        "pause_reason_code",
        "created_at",
        "confirmed_at",
        "updated_at",
        "archived_at",
        "paused_until",
    )
    return {key: row._mapping[key] for key in fields} | {
        "strategy_id": strategy.id,
        "strategy_key": strategy.key,
        "strategy_name": strategy.name,
        "strategy_version_id": actual,
        "version_no": version.version_no,
        "lifecycle": version.lifecycle,
        "risk_level": (card or {}).get("risk_level", "normal"),
        "name": name,
        "budget_amount": str(row.budget_amount) if row.budget_amount is not None else None,
    }


@router.get("/strategy-instances/{instance_id}")
def detail(instance_id: uuid.UUID, auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.connect() as conn:
        return instance_out(conn, owned(conn, auth.user_id, instance_id))


@router.post("/strategy-instances/{instance_id}/{op}")
def change(
    instance_id: uuid.UUID,
    op: InstanceOp,
    auth: AuthDep,
    engine: EngineDep,
    body: Note | None = None,
) -> dict[str, Any]:
    with engine.begin() as conn:
        return instance_out(
            conn, operate(conn, auth.user_id, instance_id, op, note=body.note if body else None)
        )


@router.get("/strategy-instances")
def list_instances(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    params: PageParams = Depends(page_params),  # noqa: B008  # noqa: B008
    status: list[InstanceStatus] = Query(default=[]),  # noqa: B008
    strategy_id: uuid.UUID | None = None,
    strategy_version_id: uuid.UUID | None = None,
    horizon: Horizon | None = None,
    scope: str | None = None,
    account_id: uuid.UUID | None = None,
    security_code: str | None = None,
    origin: InstanceOrigin | None = None,
    risk_level: CardRiskLevel | None = None,
    order: InstanceSort = InstanceSort.CREATED_AT_DESC,
) -> Any:  # noqa: ANN401
    statuses = sorted(
        set(status or [InstanceStatus.PROPOSED, InstanceStatus.ACTIVE, InstanceStatus.PAUSED])
    )
    if scope not in {None, "account", "security", "watch_group"}:
        raise AppError(ErrorCode.VALIDATION_ERROR)
    with engine.connect() as conn:
        if account_id is not None:
            owned_account(conn, auth, account_id)
        if security_code is not None:
            security_code = normalize_code(conn, security_code)
        filters = {
            "status": statuses,
            "strategy_id": strategy_id,
            "strategy_version_id": strategy_version_id,
            "horizon": horizon,
            "scope": scope,
            "account_id": account_id,
            "security_code": security_code,
            "origin": origin,
            "risk_level": risk_level,
            "order": order,
            "user": auth.user_id,
        }
        cursor_scope = (
            "instances:"
            + hashlib.sha256(json.dumps(filters, sort_keys=True, default=str).encode()).hexdigest()
        )
        effective = func.coalesce(
            instances.c.derived_strategy_version_id, instances.c.strategy_version_id
        )
        query = (
            select(instances)
            .join(versions, versions.c.id == effective)
            .join(strategies, strategies.c.id == versions.c.strategy_id)
            .outerjoin(
                strategy_card_versions, strategy_card_versions.c.id == versions.c.card_version_id
            )
        )
        query = query.where(instances.c.user_id == auth.user_id, instances.c.status.in_(statuses))
        for column, value in (
            (versions.c.strategy_id, strategy_id),
            (versions.c.id, strategy_version_id),
            (instances.c.horizon, horizon),
            (instances.c.scope, scope),
            (instances.c.account_id, account_id),
            (instances.c.security_code, security_code),
            (instances.c.origin, origin),
        ):
            if value is not None:
                query = query.where(column == value)
        if risk_level is not None:
            query = query.where(
                func.coalesce(strategy_card_versions.c.fields["risk_level"].astext, "normal")
                == risk_level
            )
        ascending = order.value == "strategy_name_asc"
        column = (
            strategies.c.name
            if ascending
            else instances.c.updated_at
            if order.value == "updated_at_desc"
            else instances.c.created_at
        )
        if params.cursor:
            keys = decode_cursor(params.cursor, scope=cursor_scope, settings=settings)
            try:
                if len(keys) != 2 or not all(isinstance(key, str) for key in keys):
                    raise ValueError
                first = str(keys[0]) if ascending else dt.datetime.fromisoformat(str(keys[0]))
                last_id = uuid.UUID(str(keys[1]))
            except ValueError:
                raise AppError(ErrorCode.INVALID_CURSOR) from None
            query = query.where(
                or_(
                    column > first if ascending else column < first,
                    and_(
                        column == first,
                        instances.c.id > last_id if ascending else instances.c.id < last_id,
                    ),
                )
            )
        rows = conn.execute(
            query.order_by(
                column.asc() if ascending else column.desc(),
                instances.c.id.asc() if ascending else instances.c.id.desc(),
            ).limit(params.limit + 1)
        ).all()
        items = [instance_out(conn, row) for row in rows]
        return build_page(
            items,
            limit=params.limit,
            scope=cursor_scope,
            settings=settings,
            key=lambda item: [
                item["strategy_name"]
                if ascending
                else item[
                    "updated_at" if order.value == "updated_at_desc" else "created_at"
                ].isoformat(),
                str(item["id"]),
            ],
        )


@router.get("/strategy-instances/{instance_id}/events")
def list_events(
    instance_id: uuid.UUID,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    params: PageParams = Depends(page_params),  # noqa: B008
) -> Any:  # noqa: ANN401
    cursor_scope = f"instance-events:{auth.user_id}:{instance_id}"
    with engine.connect() as conn:
        owned(conn, auth.user_id, instance_id)
        query = select(events).where(events.c.instance_id == instance_id)
        if params.cursor:
            keys = decode_cursor(params.cursor, scope=cursor_scope, settings=settings)
            try:
                if len(keys) != 2:
                    raise ValueError
                at, identifier = dt.datetime.fromisoformat(str(keys[0])), uuid.UUID(str(keys[1]))
            except ValueError:
                raise AppError(ErrorCode.INVALID_CURSOR) from None
            query = query.where(
                or_(events.c.at < at, and_(events.c.at == at, events.c.id < identifier))
            )
        rows = conn.execute(
            query.order_by(events.c.at.desc(), events.c.id.desc()).limit(params.limit + 1)
        )
        items = []
        for row in rows:
            metadata = row.detail or {}
            detail = metadata.get("detail")
            items.append(
                {
                    "id": row.id,
                    "kind": row.kind,
                    "from_status": metadata.get("from_status"),
                    "to_status": metadata.get("to_status"),
                    "actor": metadata.get("actor", "user" if row.actor_id else "system"),
                    "reason_code": (detail or {}).get("reason_code"),
                    "note": metadata.get("note"),
                    "detail": detail,
                    "at": row.at,
                }
            )
        return build_page(
            items,
            limit=params.limit,
            scope=cursor_scope,
            settings=settings,
            key=lambda item: [item["at"].isoformat(), str(item["id"])],
        )


_Money = Annotated[str, Field(pattern=r"^\d{1,16}(?:\.\d{1,4})?$")]


class InstanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    strategy_version_id: uuid.UUID
    scope: Literal["account", "security", "watch_group"]
    account_id: uuid.UUID
    security_code: str | None = None
    horizon: Horizon
    param_overrides: dict[str, JsonValue] | None = None
    budget_amount: _Money | None = None


class InstancePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    param_overrides: dict[str, JsonValue] | None = None
    budget_amount: _Money | None = None


@router.post("/strategy-instances", status_code=201)
def create_user_instance(
    body: InstanceCreate, auth: AuthDep, engine: EngineDep, settings: SettingsDep
) -> dict[str, Any]:
    with engine.begin() as conn:
        code = normalize_code(conn, body.security_code) if body.security_code else None
        return create(
            conn,
            auth.user_id,
            is_admin=auth.user.role == "admin",
            version_id=body.strategy_version_id,
            account_id=body.account_id,
            security_code=code,
            scope=body.scope,
            horizon=body.horizon.value,
            overrides=body.param_overrides,
            budget=Decimal(body.budget_amount) if body.budget_amount is not None else None,
            risk_config=settings.business.risk_controls,
        )


@router.patch("/strategy-instances/{instance_id}")
def patch_instance(
    instance_id: uuid.UUID, body: InstancePatch, auth: AuthDep, engine: EngineDep
) -> dict[str, Any]:
    values = body.model_dump(exclude_unset=True)
    if values.get("budget_amount") is not None:
        values["budget_amount"] = Decimal(values["budget_amount"])
    with engine.begin() as conn:
        return instance_out(conn, patch(conn, auth.user_id, instance_id, values))
