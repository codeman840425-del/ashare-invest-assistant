"""Contract 7.7/7.7B. Writes require existing current-session/CSRF dependencies."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import Column, Connection, Row, Select, Table, func, select, tuple_, update

from app.auth.deps import AuthDep, EngineDep, RedisDep, SettingsDep
from app.common import idempotency
from app.common.errors import AppError
from app.common.errors import ErrorCode as E
from app.common.pagination import Page, PageParams, build_page, decode_cursor, page_params
from app.config import Settings
from app.db.tables.research import action_plans, alerts, plan_versions
from app.plans import service as s
from app.plans.models import (
    Alert,
    AlertPatch,
    Close,
    Plan,
    PlanInput,
    PlanSummary,
    PlanVersion,
    VersionInput,
)

router = APIRouter(tags=["plans"])
Paging = Annotated[PageParams, Depends(page_params)]


def statuses(raw: str, allowed: set[str]) -> list[str]:
    values = raw.split(",")
    if raw != "all" and (not values or not set(values) <= allowed):
        s.invalid("status")
    return [] if raw == "all" else values


def page(
    conn: Connection,
    table: Table,
    query: Select[Any],
    pp: PageParams,
    cfg: Settings,
    scope: str,
    stamp: Column[Any],
) -> Page[Any]:
    if pp.cursor:
        keys = decode_cursor(pp.cursor, scope=scope, settings=cfg)
        try:
            if len(keys) != 2:
                raise ValueError()
            at, identifier = dt.datetime.fromisoformat(str(keys[0])), uuid.UUID(str(keys[1]))
            if at.tzinfo is None:
                raise ValueError()
        except (ValueError, TypeError):
            raise AppError(E.INVALID_CURSOR) from None
        query = query.where(tuple_(stamp, table.c.id) < tuple_(at, identifier))
    rows = conn.execute(query.order_by(stamp.desc(), table.c.id.desc()).limit(pp.limit + 1)).all()
    return build_page(
        rows,
        limit=pp.limit,
        key=lambda r: [getattr(r, stamp.name).isoformat(), str(r.id)],
        scope=scope,
        settings=cfg,
    )


@router.post("/plans", status_code=201, response_model=Plan)
def create(
    body: PlanInput,
    auth: AuthDep,
    engine: EngineDep,
    rds: RedisDep,
    key: idempotency.KeyHeader = None,
) -> dict[str, Any]:
    def perform() -> tuple[int, Any]:
        with engine.begin() as conn:
            return 201, s.create(conn, auth.user_id, body)

    result: dict[str, Any] = idempotency.run(
        rds,
        user_id=auth.user_id,
        scope="plans:create",
        key=key,
        payload=body.model_dump(mode="json"),
        fn=perform,
    )[1]
    return result


@router.get("/plans", response_model=Page[PlanSummary])
def listing(
    auth: AuthDep,
    engine: EngineDep,
    cfg: SettingsDep,
    pp: Paging,
    status: str = "active,triggered",
    security_code: str | None = None,
    origin: str | None = None,
    account_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    wanted = statuses(status, {"active", "triggered", "done", "cancelled"})
    if origin not in {None, "manual", "plan_draft"}:
        s.invalid("origin")
    with engine.connect() as conn:
        q = select(action_plans).where(action_plans.c.user_id == auth.user_id)
        if wanted:
            q = q.where(action_plans.c.status.in_(wanted))
        for col, value in [
            (action_plans.c.security_code, security_code),
            (action_plans.c.origin, origin),
            (action_plans.c.account_id, account_id),
        ]:
            if value is not None:
                q = q.where(col == value)
        scope = f"plans:{auth.user_id}:{status}:{security_code}:{origin}:{account_id}"
        p = page(conn, action_plans, q, pp, cfg, scope, action_plans.c.created_at)
        return {
            "items": [s.project(conn, auth.user_id, r.id, True) for r in p.items],
            "next_cursor": p.next_cursor,
        }


@router.get("/plans/{identifier}", response_model=Plan)
def detail(identifier: uuid.UUID, auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.connect() as conn:
        return s.project(conn, auth.user_id, identifier)


@router.post("/plans/{identifier}/versions", status_code=201, response_model=Plan)
def revise(
    identifier: uuid.UUID,
    body: VersionInput,
    auth: AuthDep,
    engine: EngineDep,
    rds: RedisDep,
    key: idempotency.KeyHeader = None,
) -> dict[str, Any]:
    def perform() -> tuple[int, Any]:
        with engine.begin() as conn:
            return 201, s.revise(conn, auth.user_id, identifier, body)

    result: dict[str, Any] = idempotency.run(
        rds,
        user_id=auth.user_id,
        scope=f"plans:{identifier}:versions",
        key=key,
        payload=body.model_dump(mode="json"),
        fn=perform,
    )[1]
    return result


@router.get("/plans/{identifier}/versions", response_model=Page[PlanVersion])
def versions(
    identifier: uuid.UUID, auth: AuthDep, engine: EngineDep, cfg: SettingsDep, pp: Paging
) -> dict[str, Any]:
    with engine.connect() as conn:
        s.owned(conn, auth.user_id, identifier)
        scope = f"plans:{auth.user_id}:{identifier}:versions"
        q = select(plan_versions).where(plan_versions.c.plan_id == identifier)
        if pp.cursor:
            keys = decode_cursor(pp.cursor, scope=scope, settings=cfg)
            if len(keys) != 1 or type(keys[0]) is not int:
                raise AppError(E.INVALID_CURSOR)
            q = q.where(plan_versions.c.version_no < keys[0])
        rows = conn.execute(q.order_by(plan_versions.c.version_no.desc()).limit(pp.limit + 1)).all()
        p = build_page(
            rows, limit=pp.limit, key=lambda r: [r.version_no], scope=scope, settings=cfg
        )
        return {
            "items": [s.project_version(conn, r) for r in p.items],
            "next_cursor": p.next_cursor,
        }


@router.get("/plans/{identifier}/versions/{version_no}", response_model=PlanVersion)
def version_detail(
    identifier: uuid.UUID, version_no: int, auth: AuthDep, engine: EngineDep
) -> dict[str, Any]:
    with engine.connect() as conn:
        s.owned(conn, auth.user_id, identifier)
        row = conn.execute(
            select(plan_versions).where(
                plan_versions.c.plan_id == identifier, plan_versions.c.version_no == version_no
            )
        ).first()
        if row is None:
            raise AppError(E.NOT_FOUND)
        return s.project_version(conn, row)


@router.post("/plans/{identifier}/close", response_model=Plan)
def close(identifier: uuid.UUID, body: Close, auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.begin() as conn:
        s.owner_lock(conn, auth.user_id)
        row = s.owned(conn, auth.user_id, identifier, True)
        if row.status not in s.OPEN:
            s.transition(row.status, body.status, [])
        conn.execute(
            update(action_plans)
            .where(action_plans.c.id == identifier)
            .values(status=body.status, updated_at=func.now(), triggered_at=None)
        )
        released = s.release_closed_plan_reasons(conn, auth.user_id, row.security_code, identifier)
        s.audit(
            conn,
            auth.user_id,
            "plan.closed",
            identifier,
            {"status": body.status, "note": body.note, "released_reason_ids": released},
        )
        return s.project(conn, auth.user_id, identifier)


@router.get("/alerts", response_model=Page[Alert])
def alert_list(
    auth: AuthDep,
    engine: EngineDep,
    cfg: SettingsDep,
    pp: Paging,
    status: str = "new,read",
    origin: str | None = None,
    severity: str | None = None,
    security_code: str | None = None,
    plan_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    wanted = statuses(status, {"new", "read", "checked", "acted", "dismissed"})
    if origin not in {None, "plan_condition", "holding_event", "user_custom"}:
        s.invalid("origin")
    if severity not in {None, "info", "warning", "important"}:
        s.invalid("severity")
    with engine.connect() as conn:
        q = select(alerts).where(alerts.c.user_id == auth.user_id)
        if wanted:
            q = q.where(alerts.c.status.in_(wanted))
        for col, value in [
            (alerts.c.what_happened["origin"].astext, origin),
            (alerts.c.what_happened["plan_id"].astext, str(plan_id) if plan_id else None),
            (alerts.c.severity, severity),
            (alerts.c.security_code, security_code),
        ]:
            if value is not None:
                q = q.where(col == value)
        scope = f"alerts:{auth.user_id}:{status}:{origin}:{severity}:{security_code}:{plan_id}"
        p = page(conn, alerts, q, pp, cfg, scope, alerts.c.triggered_at)
        return {"items": [s.alert_body(a) for a in p.items], "next_cursor": p.next_cursor}


def own_alert(
    conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, lock: bool = False
) -> Row[Any]:
    q = select(alerts).where(alerts.c.user_id == owner, alerts.c.id == identifier)
    row = conn.execute(q.with_for_update() if lock else q).first()
    if row is None:
        raise AppError(E.NOT_FOUND)
    return row


@router.get("/alerts/{identifier}", response_model=Alert)
def alert_detail(identifier: uuid.UUID, auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.connect() as conn:
        return s.alert_body(own_alert(conn, auth.user_id, identifier))


@router.patch("/alerts/{identifier}", response_model=Alert)
def alert_patch(
    identifier: uuid.UUID, body: AlertPatch, auth: AuthDep, engine: EngineDep
) -> dict[str, Any]:
    allowed = {
        "new": ["read", "checked", "acted", "dismissed"],
        "read": ["checked", "acted", "dismissed"],
        "checked": ["acted", "dismissed"],
        "acted": [],
        "dismissed": [],
    }
    with engine.begin() as conn:
        row = own_alert(conn, auth.user_id, identifier, True)
        if row.status == body.status:
            return s.alert_body(row)
        if body.status not in allowed[row.status]:
            s.transition(row.status, body.status, allowed[row.status])
        conn.execute(
            update(alerts)
            .where(alerts.c.id == identifier)
            .values(status=body.status, handled_at=func.now())
        )
        s.audit(
            conn,
            auth.user_id,
            "alert.status_changed",
            identifier,
            {"from": row.status, "to": body.status},
        )
        return s.alert_body(own_alert(conn, auth.user_id, identifier))
