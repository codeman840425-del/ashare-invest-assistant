"""管理端 ``/admin/*``（契约 §7.9）：邀请码（T-B03c，契约 v0.2.3 #27）与 ``/admin/ingest/status``
（契约 v0.2.8 #1，T-B47）。证书列表与暂停/恢复在 :mod:`app.api.v1.data_licence`。

非管理员（含未登录）访问一律 ``404 NOT_FOUND``（:func:`app.auth.deps.current_admin`）。
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select, tuple_

from app.api.v1.auth import RESERVED_USERNAMES, USERNAME_RE
from app.auth import invites, service
from app.auth.deps import (
    AdminDep,
    EngineDep,
    RedisDep,
    SettingsDep,
    client_ip,
    current_admin,
    ip_hash,
)
from app.common.errors import AppError, ErrorCode
from app.common.pagination import Page, PageParams, build_page, decode_cursor, page_params
from app.db.tables.users import account_reviews, audit_logs, invite_codes, login_attempts, users
from app.licences import ingest_status
from app.schemas.enums import AccountStatus

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


@router.get("/users")
def list_users(
    admin: AdminDep,
    settings: SettingsDep,
    engine: EngineDep,
    page: Annotated[PageParams, Depends(page_params)],
    status: AccountStatus | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """契约 §7.9：只读审核列表；仅投影公开管理字段，审计 IP 摘要不出库。"""
    del admin
    query = (q or "").strip()
    scope = f"admin:users:{status or ''}:{query}"
    c = users.c
    # 注册审计只用于同 IP 提示；没有地域事实时保持 null，不推断地域。
    registrations = (
        select(audit_logs.c.actor_id, audit_logs.c.ip_hash)
        .where(audit_logs.c.action == "auth.register", audit_logs.c.actor_id.is_not(None))
        .distinct(audit_logs.c.actor_id)
        .order_by(audit_logs.c.actor_id, audit_logs.c.at.asc(), audit_logs.c.id.asc())
        .subquery()
    )
    ip_counts = (
        select(registrations.c.ip_hash, func.count().label("registrations"))
        .where(registrations.c.ip_hash.is_not(None))
        .group_by(registrations.c.ip_hash)
        .subquery()
    )
    last_login = (
        select(func.max(login_attempts.c.at))
        .where(login_attempts.c.user_id == c.id, login_attempts.c.success)
        .correlate(users)
        .scalar_subquery()
    )
    review_reason = (
        select(account_reviews.c.reason)
        .where(
            account_reviews.c.user_id == c.id,
            account_reviews.c.action.in_(["approve", "reject", "disable", "enable"]),
        )
        .order_by(account_reviews.c.created_at.desc(), account_reviews.c.id.desc())
        .limit(1)
        .correlate(users)
        .scalar_subquery()
    )
    stmt = (
        select(
            c.id,
            c.username,
            c.display_name,
            c.status,
            c.role,
            c.apply_note,
            c.created_at,
            c.reviewed_at,
            last_login.label("last_login_at"),
            review_reason.label("review_reason"),
            func.coalesce(ip_counts.c.registrations, 0).label("same_ip_registrations"),
        )
        .select_from(
            users.outerjoin(registrations, registrations.c.actor_id == c.id).outerjoin(
                ip_counts, ip_counts.c.ip_hash == registrations.c.ip_hash
            )
        )
        .where(c.deleted_at.is_(None), c.status.in_([s.value for s in AccountStatus]))
    )
    if status is not None:
        stmt = stmt.where(c.status == status)
    if query:
        stmt = stmt.where(
            or_(
                c.username.icontains(query, autoescape=True),
                c.display_name.icontains(query, autoescape=True),
            )
        )
    if page.cursor:
        keys = decode_cursor(page.cursor, scope=scope, settings=settings)
        try:
            if len(keys) != 2:
                raise ValueError
            at, ident = dt.datetime.fromisoformat(str(keys[0])), uuid.UUID(str(keys[1]))
            if at.tzinfo is None:
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise AppError(ErrorCode.INVALID_CURSOR) from exc
        stmt = stmt.where(tuple_(c.created_at, c.id) < tuple_(at, ident))
    with engine.connect() as conn:
        rows = conn.execute(
            stmt.order_by(c.created_at.desc(), c.id.desc()).limit(page.limit + 1)
        ).all()
    raw = build_page(
        rows,
        limit=page.limit,
        key=lambda row: [row.created_at.isoformat(), str(row.id)],
        scope=scope,
        settings=settings,
    )
    items = []
    for row in raw.items:
        item = dict(row._mapping)
        item.update(
            id=str(row.id),
            created_at=_bj(row.created_at),
            reviewed_at=service.bj(row.reviewed_at),
            last_login_at=service.bj(row.last_login_at),
            register_ip_region=None,
            same_ip_flag=row.same_ip_registrations
            > settings.business.auth.admin.same_ip_highlight_threshold,
        )
        items.append(item)
    return {"items": items, "next_cursor": raw.next_cursor}


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


# ------------------------------------------------------------ /admin/ingest/status（T-B47）


@router.get("/ingest/status")
def get_ingest_status(
    admin: AdminDep,
    settings: SettingsDep,
    engine: EngineDep,
    rds: RedisDep,
) -> dict[str, Any]:
    """契约 v0.2.8 §7.9：只读的采集状态；``licences[]`` 按证书一行（§5.1 ``IngestLicenceStatus``），
    不含证书值、密文、HMAC 或其片段。"""
    del admin
    with engine.connect() as conn:
        return ingest_status.build(conn, rds, settings)


@router.get("/securities/reconciliation")
def get_master_reconciliation(
    admin: AdminDep,
    settings: SettingsDep,
    engine: EngineDep,
    page: Annotated[PageParams, Depends(page_params)],
    status: str = "open",
    kind: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    from app.db.tables.licences import user_data_licence_status as licences
    from app.db.tables.market import securities
    from app.db.tables.market import security_reconciliation_diffs as diffs
    from app.db.tables.users import users
    from app.schemas.enums import SecurityReconciliationKind, SecurityReconciliationSource

    del admin
    kinds = sorted(set(kind.split(","))) if kind is not None else []
    if (
        status not in {"open", "resolved", "all"}
        or any(x not in {k.value for k in SecurityReconciliationKind} for x in kinds)
        or (source is not None and source not in {s.value for s in SecurityReconciliationSource})
    ):
        raise AppError(ErrorCode.VALIDATION_ERROR)
    scope = f"admin:reconciliation:{status}:{','.join(kinds)}:{source or ''}"
    stmt = select(
        diffs, securities.c.name, licences.c.user_id.label("owner_id"), users.c.username
    ).select_from(
        diffs.outerjoin(securities, securities.c.code == diffs.c.security_code)
        .outerjoin(
            licences, (licences.c.id == diffs.c.source_licence_id) & licences.c.deleted_at.is_(None)
        )
        .outerjoin(users, users.c.id == licences.c.user_id)
    )
    if status != "all":
        stmt = stmt.where(diffs.c.status == status)
    if kinds:
        stmt = stmt.where(diffs.c.kind.in_(kinds))
    if source:
        stmt = stmt.where(diffs.c.source == source)
    if page.cursor:
        keys = decode_cursor(page.cursor, scope=scope, settings=settings)
        try:
            day, ident = dt.date.fromisoformat(str(keys[0])), int(keys[1])
            if len(keys) != 2 or ident < 1:
                raise ValueError
        except (ValueError, TypeError, IndexError) as exc:
            raise AppError(ErrorCode.VALIDATION_ERROR) from exc
        stmt = stmt.where(tuple_(diffs.c.last_seen_on, diffs.c.id) < tuple_(day, ident))
    with engine.connect() as conn:
        rows = (
            conn.execute(
                stmt.order_by(diffs.c.last_seen_on.desc(), diffs.c.id.desc()).limit(page.limit + 1)
            )
            .mappings()
            .all()
        )
    fields = (
        "id",
        "kind",
        "source",
        "security_code",
        "source_name",
        "field",
        "master_value",
        "source_value",
        "first_seen_on",
        "last_seen_on",
        "seen_days",
        "status",
        "resolved_on",
    )
    items = []
    for row in rows:
        item = {
            key: row[key].isoformat() if isinstance(row[key], dt.date) else row[key]
            for key in fields
        }
        item["name"] = None if row["kind"] == "vendor_unknown" else row["name"]
        item["licence_owner"] = (
            {"user_id": str(row["owner_id"]), "username": row["username"]}
            if row["owner_id"]
            else None
        )
        items.append(item)
    return build_page(
        items,
        limit=page.limit,
        key=lambda r: [r["last_seen_on"], r["id"]],
        scope=scope,
        settings=settings,
    ).model_dump()
