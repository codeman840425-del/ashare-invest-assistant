"""每用户数据证书（契约 v0.2.6/v0.2.8 §7.1 ``/me/data-licence*``、§7.9 ``/admin/data-licences*``；
T-B45、T-B03d）。

安全口径（契约 §5 ``DataLicenceStatus``、§9 v0.2.6 验收）：
- 任何响应、错误体、日志都**不含证书值或其任何片段**（不回显、不给后四位、不给指纹）。
  格式错误只报 ``field: "licence"`` + 固定文案；请求体不写日志（中间件只记方法/路径/状态/耗时）。
- 证书在本进程只用于算去重 HMAC 和 HPKE 封装（ingest 公钥），随后丢弃；``api`` 没有私钥。
- SSE ``data_licence`` 事件：SSE 基础设施尚未实现（缺口，见 T-B45 报告）。
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Annotated, Any

import redis
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, SecretStr, StringConstraints, field_validator
from sqlalchemy import and_, select, tuple_
from sqlalchemy.exc import IntegrityError

from app.auth import service as auth_service
from app.auth.abuse import RateLimiter, Window
from app.auth.deps import (
    AdminDep,
    AuthContext,
    AuthDep,
    EngineDep,
    RedisDep,
    SettingsDep,
    client_ip,
    ip_hash,
)
from app.common.errors import AppError, ErrorCode
from app.common.pagination import Page, PageParams, build_page, decode_cursor, page_params
from app.config import Settings
from app.db.tables.licences import user_data_licence_holds as holds
from app.db.tables.licences import user_data_licence_status as v
from app.db.tables.users import users
from app.licences import service
from app.schemas.enums import DataLicenceStatus, DataLicenceTier

router = APIRouter(tags=["data-licence"])

# /admin/* 不进公开的 openapi.json（include_in_schema=False）：契约 §1.3 要求非管理员看不出
# 管理接口是否存在，公开文档列出它们等于泄露；契约文本（§7.9）才是管理接口的权威说明。

LICENCE_MIN_LEN = 16
LICENCE_MAX_LEN = 64
_LICENCE_RE = re.compile(r"^[A-Za-z0-9-]+$")
#: 契约 §7.1：PUT 10 次/小时；/test 用 ingest.yaml ``licences.verify_rate_limit_per_hour``
PUT_PER_HOUR = 10
ADMIN_SCOPE = "admin:data-licences"

S = DataLicenceStatus


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class LicenceIn(_Body):
    licence: SecretStr
    tier: DataLicenceTier
    has_quant_pro: bool
    expires_on: dt.date | None

    @field_validator("licence", mode="before")
    @classmethod
    def _shape(cls, value: object) -> str:
        # 文案固定，绝不包含输入（契约：消息不含输入值）
        if not isinstance(value, str):
            raise ValueError("must be a string")
        stripped = value.strip()
        if not LICENCE_MIN_LEN <= len(stripped) <= LICENCE_MAX_LEN:
            raise ValueError(f"length must be {LICENCE_MIN_LEN}-{LICENCE_MAX_LEN}")
        if _LICENCE_RE.fullmatch(stripped) is None:
            raise ValueError("only letters, digits and '-' are allowed")
        return stripped


class LicencePatch(_Body):
    tier: DataLicenceTier | None = None
    has_quant_pro: bool | None = None
    expires_on: dt.date | None = None

    @field_validator("tier", "has_quant_pro")
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("must not be null")
        return value


class ReasonIn(_Body):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class VerificationOut(BaseModel):
    verification_id: str


def _require_settings_enabled(settings: Settings) -> None:
    """review M4：调度层（T-B04a-x）完成前生产不开放证书设置入口。
    ``DATA_LICENCE_SETTINGS_ENABLED`` 未设时 production 关闭、其余环境开启；关闭时写操作
    （PUT / PATCH / test）→ ``503 MAINTENANCE``（与未配置封装公钥同一表现）；GET 与 DELETE
    始终可用（用户随时能删除自己的证书）。"""
    if not settings.licence_settings_enabled:
        raise AppError(ErrorCode.MAINTENANCE)


def _limiter(rds: redis.Redis, auth: AuthContext, scope: str, limit: int) -> None:
    RateLimiter(rds).enforce(f"user:{auth.user_id}", [Window(scope, limit, 3600)])


# ---------------------------------------------------------------- /me/data-licence


@router.get("/me/data-licence")
def get_licence(auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.connect() as conn:
        return service.user_view(conn, auth.user_id)


@router.put("/me/data-licence", status_code=202)
def put_licence(
    body: LicenceIn,
    auth: AuthDep,
    settings: SettingsDep,
    engine: EngineDep,
    rds: RedisDep,
) -> dict[str, Any]:
    _require_settings_enabled(settings)
    _limiter(rds, auth, "data_licence:put:1h", PUT_PER_HOUR)
    service.current_public_key(settings)  # 未配置公钥 → 503，先于任何写入
    try:
        with engine.begin() as conn:
            result = service.set_licence(
                conn,
                settings,
                user_id=auth.user_id,
                licence=body.licence.get_secret_value(),
                tier=body.tier.value,
                has_quant_pro=body.has_quant_pro,
                expires_on=body.expires_on,
            )
    except IntegrityError as exc:
        raise service.map_integrity(exc) from None
    if result.verification_id is not None:
        service.enqueue_verify_best_effort(
            rds, licence_id=result.row.id, verification_id=result.verification_id
        )
    return service.status_view(result.row)


@router.patch("/me/data-licence")
def patch_licence(
    body: LicencePatch, auth: AuthDep, settings: SettingsDep, engine: EngineDep
) -> dict[str, Any]:
    _require_settings_enabled(settings)
    changes: dict[str, Any] = {}
    for name in body.model_fields_set:
        value = getattr(body, name)
        changes[name] = value.value if isinstance(value, DataLicenceTier) else value
    with engine.begin() as conn:
        row = service.patch_licence(conn, user_id=auth.user_id, changes=changes)
    return service.status_view(row)


@router.delete("/me/data-licence", status_code=204)
def delete_licence(auth: AuthDep, settings: SettingsDep, engine: EngineDep) -> Response:
    with engine.begin() as conn:
        service.delete_licence(conn, user_id=auth.user_id, settings=settings)
    return Response(status_code=204)


@router.post("/me/data-licence/test", status_code=202)
def test_licence(
    auth: AuthDep, settings: SettingsDep, engine: EngineDep, rds: RedisDep
) -> VerificationOut:
    _require_settings_enabled(settings)
    with engine.connect() as conn:
        row = service.live_row(conn, auth.user_id)
        held = service.is_held(conn, auth.user_id)
    # 契约 v0.2.8 #14：暂停期间（含暂停后删除了证书，GET 显示 paused_by_admin）→ 409
    if held or (row is not None and row.status == S.PAUSED_BY_ADMIN):
        raise AppError(
            ErrorCode.DATA_LICENCE_UNAVAILABLE, details={"status": S.PAUSED_BY_ADMIN.value}
        )
    if row is None:
        raise AppError(ErrorCode.DATA_LICENCE_NOT_SET)
    limit = settings.business.ingest.licences.verify_rate_limit_per_hour
    try:
        _limiter(rds, auth, "data_licence:test:1h", limit)
        if rds.exists(settings.ingest_paused_key):
            raise AppError(ErrorCode.INGEST_PAUSED)
        verification_id = uuid.uuid4()
        service.enqueue_verify(rds, licence_id=row.id, verification_id=verification_id)
    except redis.RedisError:
        raise AppError(ErrorCode.UPSTREAM_UNAVAILABLE) from None
    return VerificationOut(verification_id=str(verification_id))


# ---------------------------------------------------------------- /admin/data-licences


def _admin_item(
    settings: Settings,
    row: Any,  # noqa: ANN401 - 多列 Row，泛型参数随列数变化
    counts: dict[uuid.UUID, tuple[int, int]],
    depths: dict[uuid.UUID, dict[str, int]],
) -> dict[str, Any]:
    lic = row if row.licence_id is not None else None
    item = service.status_view(lic, held=row.held)
    last_minute, today = counts.get(row.licence_id, (0, 0)) if lic else (0, 0)
    item.update(
        {
            # 契约 v0.2.8 #2：与 /admin/ingest/status licences[].licence_id 对应；未设置为 null
            "licence_id": None if lic is None else str(row.licence_id),
            "user_id": str(row.user_pk),
            "username": row.username,
            "display_name": row.display_name,
            "per_minute_limit": service.per_minute_limit(settings, lic),
            "calls_last_minute": last_minute,
            "calls_today": today,
            "queue_depth": depths.get(row.licence_id, {"p0": 0, "p1": 0, "p2": 0})
            if lic
            else {"p0": 0, "p1": 0, "p2": 0},
        }
    )
    return item


@router.get("/admin/data-licences", include_in_schema=False)
def list_licences(
    admin: AdminDep,
    settings: SettingsDep,
    engine: EngineDep,
    rds: RedisDep,
    params: Annotated[PageParams, Depends(page_params)],
) -> Page[dict[str, Any]]:
    u = users.c
    stmt = (
        select(
            u.id.label("user_pk"),
            u.username,
            u.display_name,
            u.created_at.label("user_created_at"),
            v.c.id.label("licence_id"),
            *(c for c in v.c if c.name not in {"id", "user_id", "created_at"}),
            v.c.created_at,
            holds.c.user_id.is_not(None).label("held"),
        )
        .select_from(
            users.outerjoin(v, and_(v.c.user_id == u.id, v.c.deleted_at.is_(None))).outerjoin(
                holds, holds.c.user_id == u.id
            )
        )
        .where(u.deleted_at.is_(None))
        .order_by(u.created_at.desc(), u.id.desc())
        .limit(params.limit + 1)
    )
    if params.cursor:
        keys = decode_cursor(params.cursor, scope=ADMIN_SCOPE, settings=settings)
        if len(keys) != 2:
            raise AppError(ErrorCode.INVALID_CURSOR)
        try:
            after_ts = dt.datetime.fromisoformat(str(keys[0]))
            after_id = uuid.UUID(str(keys[1]))
        except ValueError:
            raise AppError(ErrorCode.INVALID_CURSOR) from None
        stmt = stmt.where(tuple_(u.created_at, u.id) < tuple_(after_ts, after_id))
    with engine.connect() as conn:
        rows = list(conn.execute(stmt))
        page_rows = rows[: params.limit]
        ids = [r.licence_id for r in page_rows if r.licence_id is not None]
        counts = service.call_counts(conn, ids)
    depths = service.queue_depths(rds, ids)
    page = build_page(
        rows,
        limit=params.limit,
        key=lambda r: [r.user_created_at.isoformat(), str(r.user_pk)],
        scope=ADMIN_SCOPE,
        settings=settings,
    )
    return Page[dict[str, Any]](
        items=[_admin_item(settings, r, counts, depths) for r in page.items],
        next_cursor=page.next_cursor,
    )


def _admin_transition(
    *,
    admin: AuthContext,
    user_id: uuid.UUID,
    reason: str,
    pause: bool,
    request: Request,
    settings: Settings,
    engine: EngineDep,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """返回 ``(licence_id, verification_id)``；``verification_id`` 只在恢复成功时非空。

    暂停按用户记录（``app.user_data_licence_holds``，review M1）：pause 要求已设置证书
    （否则 409 NOT_SET，契约不变）；resume 先删暂停记录，用户已 DELETE 证书时只解除暂停
    （204，``licence_id`` 为 None），否则把 ``paused_by_admin`` 行转 ``pending_verification``。

    重复暂停幂等（契约 v0.2.8 #17⑤，T-B03e）：已处于管理员暂停（有暂停记录，或证书行已是
    ``paused_by_admin``）时再次 pause → 204，不论证书是否已删除；状态不变，**不写审计、不写事件**。
    只缺暂停记录的旧数据（0010 之前）顺手补上记录（状态本来就是暂停，不算变化）。
    """
    verification_id: uuid.UUID | None = None
    with engine.begin() as conn:
        row = service.live_row(conn, user_id, lock=True)
        if pause:
            held = service.is_held(conn, user_id)
            if held or (row is not None and row.status == S.PAUSED_BY_ADMIN):
                if not held:
                    service.hold(conn, user_id)
                return (None if row is None else row.id), None
        released = False if pause else service.release_hold(conn, user_id)
        if row is None:
            if not released:
                raise AppError(ErrorCode.DATA_LICENCE_NOT_SET)
            auth_service.audit(
                conn,
                action="data_licence.resumed",
                actor_id=admin.user_id,
                actor_role=admin.user.role,
                target_type="user",
                target_id=str(user_id),
                detail={
                    "user_id": str(user_id),
                    "reason": reason,
                    "from_status": S.NOT_SET.value,
                    "to_status": S.NOT_SET.value,
                    "hold_released": True,
                },
                ip_hash=ip_hash(settings, client_ip(request, settings)),
            )
            return None, None
        before = str(row.status)
        after = before
        if pause:
            service.hold(conn, user_id)
        if pause and before != S.PAUSED_BY_ADMIN:
            service.set_status(conn, row, to=S.PAUSED_BY_ADMIN, event="paused", actor="admin")
            after = S.PAUSED_BY_ADMIN.value
        elif not pause and before == S.PAUSED_BY_ADMIN:
            service.set_status(
                conn,
                row,
                to=S.PENDING_VERIFICATION,
                event="resumed",
                actor="admin",
                paused_until=None,
            )
            after = S.PENDING_VERIFICATION.value
            verification_id = uuid.uuid4()
        auth_service.audit(
            conn,
            action="data_licence.paused" if pause else "data_licence.resumed",
            actor_id=admin.user_id,
            actor_role=admin.user.role,
            target_type="user_data_licence",
            target_id=str(row.id),
            detail={
                "user_id": str(user_id),
                "reason": reason,
                "from_status": before,
                "to_status": after,
            },
            ip_hash=ip_hash(settings, client_ip(request, settings)),
        )
    return row.id, verification_id


@router.post("/admin/data-licences/{user_id}/pause", status_code=204, include_in_schema=False)
def pause_licence(
    user_id: uuid.UUID,
    body: ReasonIn,
    admin: AdminDep,
    request: Request,
    settings: SettingsDep,
    engine: EngineDep,
) -> Response:
    _admin_transition(
        admin=admin,
        user_id=user_id,
        reason=body.reason,
        pause=True,
        request=request,
        settings=settings,
        engine=engine,
    )
    return Response(status_code=204)


@router.post("/admin/data-licences/{user_id}/resume", status_code=204, include_in_schema=False)
def resume_licence(
    user_id: uuid.UUID,
    body: ReasonIn,
    admin: AdminDep,
    request: Request,
    settings: SettingsDep,
    engine: EngineDep,
    rds: RedisDep,
) -> Response:
    licence_id, verification_id = _admin_transition(
        admin=admin,
        user_id=user_id,
        reason=body.reason,
        pause=False,
        request=request,
        settings=settings,
        engine=engine,
    )
    if verification_id is not None and licence_id is not None:
        service.enqueue_verify_best_effort(
            rds, licence_id=licence_id, verification_id=verification_id
        )
    return Response(status_code=204)
