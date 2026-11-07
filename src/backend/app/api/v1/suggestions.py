"""Owned suggestion reads/actions and cache-only synchronous refresh."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, insert, or_, select, update

from app.api.v1.candidate_signals import scoped_page
from app.api.v1.trades import normalize_code
from app.auth.deps import AuthDep, EngineDep, RedisDep, SettingsDep
from app.common.errors import AppError, ErrorCode
from app.common.pagination import PageParams, page_params
from app.db.tables.accounts import trades
from app.db.tables.membership import entitlement_overrides, plan_entitlements, user_subscriptions
from app.db.tables.realtime import suggestion_threads, suggestion_user_actions, suggestions
from app.db.tables.reviews import data_snapshots
from app.licences.service import live_status
from app.schemas.enums import SuggestionStatus
from app.suggestions.models import SuggestionInput
from app.suggestions.service import SCHEMA, archive, owned, summary, view

router = APIRouter(tags=["suggestions"])


class Refresh(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    security_code: str


class ActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    kind: Literal["viewed", "dismissed", "acted_trade_linked"]
    trade_id: uuid.UUID | None
    note: str | None = Field(max_length=200)


@router.get("/suggestions")
def listing(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
    security_code: str | None = None,
    status: SuggestionStatus | None = None,
) -> dict[str, Any]:
    with engine.connect() as conn:
        code = normalize_code(conn, security_code) if security_code else None
        query = select(suggestions).where(suggestions.c.user_id == auth.user_id)
        if code:
            query = query.where(suggestions.c.security_code == code)
        if status:
            query = query.where(suggestions.c.status == status)
        scope = hashlib.sha256(json.dumps([str(auth.user_id), code, status]).encode()).hexdigest()
        rows, cursor = scoped_page(
            query,
            table=suggestions,
            time=suggestions.c.created_at,
            params=page,
            scope="suggestions:" + scope,
            settings=settings,
            conn=conn,
        )
        return {"items": [summary(row) for row in rows], "next_cursor": cursor}


def refresh_interval(conn: Connection, user_id: uuid.UUID, now: dt.datetime) -> int:
    key = "realtime.min_notify_interval_s"
    override = conn.execute(
        select(entitlement_overrides.c.value).where(
            entitlement_overrides.c.user_id == user_id,
            entitlement_overrides.c.key == key,
            or_(
                entitlement_overrides.c.expires_at.is_(None),
                entitlement_overrides.c.expires_at > now,
            ),
        )
    ).first()
    values = (
        [override.value]
        if override
        else conn.execute(
            select(plan_entitlements.c.value)
            .select_from(
                plan_entitlements.join(
                    user_subscriptions, plan_entitlements.c.plan_id == user_subscriptions.c.plan_id
                )
            )
            .where(
                user_subscriptions.c.user_id == user_id,
                user_subscriptions.c.status == "active",
                user_subscriptions.c.starts_at <= now,
                or_(user_subscriptions.c.ends_at.is_(None), user_subscriptions.c.ends_at > now),
                plan_entitlements.c.key == key,
            )
        )
        .scalars()
        .all()
    )
    if len(values) != 1 or type(values[0]) is not int or values[0] <= 0:
        raise AppError(ErrorCode.MAINTENANCE, details={"issue": "refresh_entitlement_not_defined"})
    return int(values[0])


@router.post("/suggestions/refresh")
def refresh(
    body: Refresh, auth: AuthDep, engine: EngineDep, settings: SettingsDep, redis: RedisDep
) -> dict[str, Any]:
    now = dt.datetime.now(dt.UTC)
    with engine.begin() as conn:
        code = normalize_code(conn, body.security_code)
        status = live_status(conn, auth.user_id)
        if status != "active":
            raise AppError(ErrorCode.DATA_LICENCE_UNAVAILABLE, details={"status": status})
        # No provider client, ingestion enqueue, or secret-bearing licence read here.
        snapshot = conn.execute(
            select(data_snapshots)
            .where(
                data_snapshots.c.user_id == auth.user_id,
                data_snapshots.c["items"]["schema_version"].astext == SCHEMA,
                data_snapshots.c["items"]["input"]["security_code"].astext == code,
                data_snapshots.c.created_at <= now,
            )
            .order_by(data_snapshots.c.created_at.desc(), data_snapshots.c.id.desc())
            .limit(1)
        ).one_or_none()
        if snapshot is None:
            raise AppError(ErrorCode.FRESH_DATA_REQUIRED, details={"data_as_of": None})
        content = SuggestionInput.model_validate(snapshot.items["input"])
        if content.snapshot_id != snapshot.id:
            raise AppError(ErrorCode.MAINTENANCE, details={"issue": "refresh_snapshot_id_mismatch"})
        threshold = settings.business.realtime.intervals.effective_stale_threshold_s
        if (
            content.data_status != "fresh"
            or content.gaps
            or (now - content.data_as_of).total_seconds() > threshold
        ):
            raise AppError(
                ErrorCode.FRESH_DATA_REQUIRED,
                details={"data_as_of": content.data_as_of.isoformat()},
            )
        interval = refresh_interval(conn, auth.user_id, now)
        key = "suggestion-refresh:" + str(auth.user_id) + ":" + code
        if not redis.set(key, "1", nx=True, ex=interval):
            raise AppError(
                ErrorCode.SUGGESTION_REFRESH_TOO_FREQUENT,
                details={"retry_after_s": max(1, redis.ttl(key))},
            )
        return archive(conn, user_id=auth.user_id, content=content, origin="manual_refresh")


@router.get("/suggestions/{identifier}")
def detail(identifier: uuid.UUID, auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.connect() as conn:
        return view(owned(conn, auth.user_id, identifier))


@router.get("/suggestions/{identifier}/chain")
def chain(identifier: uuid.UUID, auth: AuthDep, engine: EngineDep) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        current = owned(conn, auth.user_id, identifier)
        rows = conn.execute(
            select(suggestions)
            .where(
                suggestions.c.user_id == auth.user_id, suggestions.c.thread_id == current.thread_id
            )
            .order_by(suggestions.c.seq_no)
        ).all()
        return [view(row) for row in rows]


@router.post("/suggestions/{identifier}/actions", status_code=204)
def action(identifier: uuid.UUID, body: ActionBody, auth: AuthDep, engine: EngineDep) -> None:
    with engine.begin() as conn:
        # Same owner lock as the generator prevents racing replacement/user actions.
        from app.db.tables.users import users

        conn.execute(select(users.c.id).where(users.c.id == auth.user_id).with_for_update()).one()
        row = owned(conn, auth.user_id, identifier)
        if row.status == "superseded":
            pointer = conn.execute(
                select(suggestion_threads.c.current_suggestion_id).where(
                    suggestion_threads.c.id == row.thread_id,
                    suggestion_threads.c.user_id == auth.user_id,
                )
            ).scalar_one()
            raise AppError(ErrorCode.SUGGESTION_SUPERSEDED, details={"current_id": str(pointer)})
        if body.kind == "acted_trade_linked":
            trade = conn.execute(
                select(trades.c.id).where(
                    trades.c.id == body.trade_id,
                    trades.c.user_id == auth.user_id,
                    trades.c.security_code == row.security_code,
                    trades.c.voided_at.is_(None),
                )
            ).first()
            if trade is None:
                raise AppError(ErrorCode.VALIDATION_ERROR, details={"field": "trade_id"})
        elif body.trade_id is not None:
            raise AppError(ErrorCode.VALIDATION_ERROR, details={"field": "trade_id"})
        conn.execute(
            insert(suggestion_user_actions).values(
                suggestion_id=row.id,
                user_id=auth.user_id,
                kind=body.kind,
                trade_id=body.trade_id,
                note=body.note,
            )
        )
        if body.kind in {"dismissed", "acted_trade_linked"}:
            conn.execute(
                update(suggestion_threads)
                .where(
                    suggestion_threads.c.id == row.thread_id,
                    suggestion_threads.c.user_id == auth.user_id,
                )
                .values(
                    user_decision="dismissed" if body.kind == "dismissed" else "acted",
                    decided_at=dt.datetime.now(dt.UTC),
                )
            )
