"""管理端 ``/admin/*``（契约 §7.9）。目前只有邀请码（T-B03c，契约 v0.2.3 #27）。

非管理员（含未登录）访问一律 ``404 NOT_FOUND``（:func:`app.auth.deps.current_admin`）。
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select, tuple_

from app.api.v1.auth import RESERVED_USERNAMES, USERNAME_RE
from app.auth import invites, service
from app.auth.deps import AdminDep, EngineDep, SettingsDep, client_ip, current_admin, ip_hash
from app.common.errors import AppError, ErrorCode
from app.common.pagination import Page, PageParams, build_page, decode_cursor, page_params
from app.db.tables.users import invite_codes

# include_in_schema=False：/admin/* 不进公开 openapi.json（契约 §1.3，见 T-B04a 报告）
router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(current_admin)],
    include_in_schema=False,
)

NOTE_MAX = 200
_SCOPE = "admin:invites"


class InviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ttl_h: Annotated[int, Field(strict=True)] | None = None
    bound_username: Annotated[str, Field(max_length=64)] | None = None
    note: Annotated[str, Field(max_length=NOTE_MAX)] | None = None


class InviteCreatedOut(BaseModel):
    id: str
    code: str
    expires_at: str
    bound_username: str | None
    note: str | None


class InviteOut(BaseModel):
    id: str
    status: invites.InviteStatus
    created_by: str
    created_at: str
    expires_at: str
    used_at: str | None
    used_by: str | None
    bound_username: str | None
    note: str | None


def _bj(value: dt.datetime) -> str:
    out = service.bj(value)
    assert out is not None  # noqa: S101 - 非空列
    return out


def _view(row: Any, now: dt.datetime) -> InviteOut:  # noqa: ANN401 - sqlalchemy Row
    return InviteOut(
        id=str(row.id),
        status=invites.status_of(row, now),
        created_by=str(row.created_by),
        created_at=_bj(row.created_at),
        expires_at=_bj(row.expires_at),
        used_at=service.bj(row.used_at),
        used_by=None if row.used_by is None else str(row.used_by),
        bound_username=row.bound_username,
        note=row.note,
    )


@router.post("/invites", status_code=201)
def create_invite(
    body: InviteIn,
    request: Request,
    admin: AdminDep,
    settings: SettingsDep,
    engine: EngineDep,
) -> InviteCreatedOut:
    cfg = settings.business.auth.invite
    fields: list[dict[str, str]] = []
    ttl_h = cfg.default_ttl_h if body.ttl_h is None else body.ttl_h
    if not 1 <= ttl_h <= cfg.max_ttl_h:
        fields.append({"field": "ttl_h", "issue": f"must be between 1 and {cfg.max_ttl_h}"})
    bound = None
    if body.bound_username is not None:
        bound = body.bound_username.strip().lower()
        if not USERNAME_RE.fullmatch(bound):
            fields.append({"field": "bound_username", "issue": "must match ^[a-z0-9_]{4,32}$"})
        elif bound in RESERVED_USERNAMES:
            fields.append({"field": "bound_username", "issue": "reserved"})
    note = None if body.note is None else (body.note.strip() or None)
    if fields:
        raise AppError(ErrorCode.VALIDATION_ERROR, details={"fields": fields})

    now = service.now_utc()
    with engine.begin() as conn:
        row, code = invites.create(
            conn,
            settings,
            created_by=admin.user_id,
            now=now,
            ttl_h=ttl_h,
            bound_username=bound,
            note=note,
        )
        service.audit(
            conn,
            action="invite.created",
            actor_id=admin.user_id,
            actor_role=admin.user.role,
            target_type="invite",
            target_id=str(row.id),
            detail={"ttl_h": ttl_h, "bound": bound is not None},
            ip_hash=ip_hash(settings, client_ip(request, settings)),
        )
    return InviteCreatedOut(
        id=str(row.id),
        code=code,
        expires_at=_bj(row.expires_at),
        bound_username=row.bound_username,
        note=row.note,
    )


@router.get("/invites")
def list_invites(
    admin: AdminDep,
    settings: SettingsDep,
    engine: EngineDep,
    page: Annotated[PageParams, Depends(page_params)],
) -> Page[InviteOut]:
    del admin
    c = invite_codes.c
    stmt = select(invite_codes)
    if page.cursor is not None:
        keys = decode_cursor(page.cursor, scope=_SCOPE, settings=settings)
        try:
            at = dt.datetime.fromisoformat(str(keys[0]))
            last_id = uuid.UUID(str(keys[1]))
        except (IndexError, ValueError):
            raise AppError(ErrorCode.INVALID_CURSOR) from None
        stmt = stmt.where(or_(c.created_at < at, tuple_(c.created_at, c.id) < tuple_(at, last_id)))
    stmt = stmt.order_by(c.created_at.desc(), c.id.desc()).limit(page.limit + 1)
    with engine.connect() as conn:
        rows = conn.execute(stmt).all()
    now = service.now_utc()
    raw = build_page(
        rows,
        limit=page.limit,
        key=lambda r: [r.created_at.isoformat(), str(r.id)],
        scope=_SCOPE,
        settings=settings,
    )
    return Page[InviteOut](items=[_view(r, now) for r in raw.items], next_cursor=raw.next_cursor)


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(
    invite_id: str,
    request: Request,
    admin: AdminDep,
    settings: SettingsDep,
    engine: EngineDep,
) -> Response:
    try:
        iid = uuid.UUID(invite_id)
    except ValueError:
        raise AppError(ErrorCode.NOT_FOUND) from None
    now = service.now_utc()
    with engine.begin() as conn:
        row = conn.execute(
            select(invite_codes).where(invite_codes.c.id == iid).with_for_update()
        ).first()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND)
        if not invites.revoke(conn, invite_id=iid, admin_id=admin.user_id, now=now):
            raise AppError(
                ErrorCode.INVALID_STATE_TRANSITION,
                details={"from": invites.status_of(row, now), "to": "revoked", "allowed": []},
            )
        service.audit(
            conn,
            action="invite.revoked",
            actor_id=admin.user_id,
            actor_role=admin.user.role,
            target_type="invite",
            target_id=str(iid),
            detail={"from": invites.status_of(row, now)},
            ip_hash=ip_hash(settings, client_ip(request, settings)),
        )
    return Response(status_code=204)
