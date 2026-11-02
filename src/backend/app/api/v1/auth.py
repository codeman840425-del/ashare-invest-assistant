"""``/meta/registration``、``/auth/*``（契约 §7.1、§1.3；plan §3.6；T-B03）。

同步 ``def`` 路由：数据库（psycopg 同步引擎）与 Redis 都是阻塞调用，FastAPI 放线程池执行。
防滥用（T-B03a，``app.auth.abuse``）：登录/注册按 IP 限速、改密按用户限速、渐进锁定、pending 上限、
``login_attempts``；蜜罐 + 最短填写时间（契约 v0.2.8 §7.1，T-B03d）。邀请码归 T-B03c。
会话期限、argon2 参数、口令长度取 ``config/auth.yaml``（T-B03b）。
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from app.api.v1.me import build_me
from app.auth import abuse, invites, service
from app.auth.deps import (
    AuthDep,
    EngineDep,
    PasswordsDep,
    RedisDep,
    SettingsDep,
    StoreDep,
    client_ip,
    ip_hash,
)
from app.auth.sessions import CSRF_COOKIE, SESSION_COOKIE
from app.common.errors import AppError, ErrorCode
from app.config import Settings, get_settings
from app.db.tables.users import users
from app.schemas.enums import AccountStatus, RegistrationMode, Role

router = APIRouter(tags=["auth"])


def require_registration_open(settings: SettingsDep) -> None:
    """架构师裁定（T-T23 #1）：``closed`` 时 ``/auth/register`` 一律 ``503 REGISTRATION_CLOSED``，
    先于请求体校验（任何请求体，包括畸形的）。作为依赖挂在路由上，在请求体模型之前求值。

    注意（review-f72b8c7 m2）：真正先生效的是 :class:`_RegistrationGateRoute`（解析请求体之前），
    本依赖保留给 OpenAPI 与非 JSON 路径；改判定时只改本函数，两处共用。"""
    if settings.registration_mode == RegistrationMode.CLOSED:
        raise AppError(ErrorCode.REGISTRATION_CLOSED)


class _RegistrationGateRoute(APIRoute):
    """FastAPI 在求值依赖之前就解析 JSON：无法解析的请求体会先得到 400。本路由类在解析请求体
    之前调用同一个判定，保证 ``closed`` 时畸形 JSON 也是 503。"""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def gated(request: Request) -> Response:
            # T-B03f（review-f72b8c7 m1）：读 create_app 写入的 app.state.settings，不直接调用
            # get_settings 的 override（带依赖参数的 override 会 TypeError → 500）
            settings = getattr(request.app.state, "settings", None)
            require_registration_open(settings if settings is not None else get_settings())
            return await handler(request)

        return gated


#: 只放 ``POST /auth/register``（见 :class:`_RegistrationGateRoute`）
register_router = APIRouter(tags=["auth"], route_class=_RegistrationGateRoute)

#: plan §3.6 / users.username CHECK：4–32 位小写字母、数字、下划线（契约写 3–32，取更严的库约束）
USERNAME_RE = re.compile(r"^[a-z0-9_]{4,32}$")
RESERVED_USERNAMES = frozenset({"admin", "root", "system"})
#: 契约 v0.2.4 #2：display_name 1–32、apply_note ≤ 200
DISPLAY_NAME_MAX = 32
APPLY_NOTE_MAX = 200
#: 蜜罐（契约 v0.2.8 §7.1）：最短填写时间，固定规则、不进配置
HONEYPOT_MIN_FILL_MS = 3000


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegistrationModeOut(BaseModel):
    mode: RegistrationMode


class RegisterIn(_Body):
    username: Annotated[str, Field(min_length=1, max_length=64)]
    password: Annotated[str, Field(min_length=1, max_length=1024)]
    display_name: Annotated[str, Field(min_length=1, max_length=DISPLAY_NAME_MAX)]
    invite_code: Annotated[str | None, Field(max_length=128)] = None
    apply_note: Annotated[str | None, Field(max_length=APPLY_NOTE_MAX)] = None
    #: 契约 v0.2.8 §7.1 蜜罐：隐藏输入框，正常为空串或不传；不校验内容与长度
    website: str | None = None
    #: 契约 v0.2.8：表单首次渲染的毫秒 epoch（前端按服务端时钟校正）；提交距此 < 3 秒视为
    #: 机器；缺失不检查；不是整数 → 400（StrictInt：不接受字符串、小数、布尔）
    form_started_at: StrictInt | None = None
    #: 契约 v0.2.5（T-A06）：不做同意流程；旧客户端仍发 ``agreements`` 时忽略
    #: （不校验、不报错、不记录）
    agreements: Annotated[Any, Field(exclude=True)] = None


class RegisterOut(BaseModel):
    id: str
    username: str
    status: AccountStatus


class LoginIn(_Body):
    username: Annotated[str, Field(min_length=1, max_length=256)]
    password: Annotated[str, Field(min_length=1, max_length=1024)]


class PasswordIn(_Body):
    old_password: Annotated[str, Field(min_length=1, max_length=1024)]
    new_password: Annotated[str, Field(min_length=1, max_length=1024)]


def _validation(fields: list[dict[str, str]]) -> AppError:
    return AppError(ErrorCode.VALIDATION_ERROR, details={"fields": fields})


def _set_auth_cookies(response: Response, settings: Settings, sid: str, csrf: str) -> None:
    # T-A05 / review-T-B03 M4：Max-Age = 绝对期限；空闲过期由服务端 Redis TTL 控制
    common: dict[str, Any] = {
        "max_age": settings.business.auth.session.absolute_ttl_s,
        "path": "/",
        "secure": settings.session_cookie_secure,
        "samesite": "lax",
    }
    response.set_cookie(SESSION_COOKIE, sid, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **common)


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    for name, http_only in ((SESSION_COOKIE, True), (CSRF_COOKIE, False)):
        response.delete_cookie(
            name,
            path="/",
            secure=settings.session_cookie_secure,
            httponly=http_only,
            samesite="lax",
        )


@router.get("/meta/registration", tags=["meta"])
def registration_mode(settings: SettingsDep) -> RegistrationModeOut:
    return RegistrationModeOut(mode=settings.registration_mode)


def honeypot_trigger(body: RegisterIn, *, now_ms: int) -> str | None:
    """契约 v0.2.8 §7.1：``website`` 去首尾空白后非空；或 ``form_started_at`` 存在且
    ``now_ms - form_started_at < 3000``（含未来时间）。两者都中 → ``"both"``。"""
    by_field = bool((body.website or "").strip())
    too_fast = (
        body.form_started_at is not None and now_ms - body.form_started_at < HONEYPOT_MIN_FILL_MS
    )
    if by_field and too_fast:
        return "both"
    if by_field:
        return "website"
    if too_fast:
        return "too_fast"
    return None


@register_router.post(
    "/auth/register", status_code=201, dependencies=[Depends(require_registration_open)]
)
def register(
    body: RegisterIn,
    request: Request,
    settings: SettingsDep,
    engine: EngineDep,
    passwords: PasswordsDep,
    rds: RedisDep,
) -> RegisterOut:
    # 契约 v0.2.8 §7.1 判定顺序：注册模式（closed → 503，见 require_registration_open，先于
    # 请求体校验）→ IP 限速（蜜罐命中同样计数）→ 字段与邀请码校验（400）→ 用户名冲突（409）→
    # 待审核数上限（503）→ 蜜罐。
    mode = settings.registration_mode

    # 防滥用（plan §3.6）：同一 IP 每小时/每日上限（每次尝试都计，含校验失败）→ 429
    policy = settings.auth_abuse
    ip = client_ip(request, settings)
    abuse.RateLimiter(rds).enforce(abuse.ip_key(settings, ip), abuse.register_windows(policy))

    username = body.username.strip().lower()
    fields: list[dict[str, str]] = []
    if not USERNAME_RE.fullmatch(username):
        fields.append({"field": "username", "issue": "must match ^[a-z0-9_]{4,32}$"})
    elif username in RESERVED_USERNAMES:
        fields.append({"field": "username", "issue": "reserved"})
    pw_issues = passwords.issues(body.password, username=username)
    fields += [{"field": "password", "issue": i} for i in pw_issues]
    display_name = body.display_name.strip()
    if not display_name:
        fields.append({"field": "display_name", "issue": "must not be blank"})
    apply_note = (body.apply_note or "").strip() or None
    if mode == RegistrationMode.INVITE:
        # 邀请码缺失与无效同一种错误（不区分原因）；格式错误不查库
        if (
            body.invite_code is None
            or invites.normalize(body.invite_code, settings.business.auth.invite.code_bytes) is None
        ):
            fields.append({"field": "invite_code", "issue": "invalid"})
        if apply_note is None:
            fields.append({"field": "apply_note", "issue": "required"})
    if fields:
        raise _validation(fields)

    ih = ip_hash(settings, ip)
    pw_hash = passwords.hash(body.password)  # 蜜罐命中也照样哈希，耗时与正常注册一致
    trap = honeypot_trigger(body, now_ms=int(service.now_utc().timestamp() * 1000))
    try:
        with engine.begin() as conn:
            # 邀请码、重名、pending 上限放进保存点：蜜罐命中时回滚保存点（不消耗邀请码），
            # 外层事务只提交审计。先占用邀请码再查重名：没有有效邀请码的人探测不到用户名
            # 是否已存在；之后任何失败（含 409/503）整个事务回滚，占用随之撤销
            checks = conn.begin_nested()
            invite_id = (
                invites.redeem(
                    conn,
                    settings,
                    raw_code=body.invite_code,
                    username=username,
                    now=service.now_utc(),
                )
                if mode == RegistrationMode.INVITE
                else None
            )
            if service.username_taken(conn, username):
                raise AppError(ErrorCode.CONFLICT, details={"field": "username"})
            abuse.enforce_pending_cap(conn, policy)
            if trap is not None:
                # 契约 v0.2.8：与正常注册相同的 201 与响应体，但不建用户、不消耗邀请码、
                # 不进待审核列表；审计只记 trigger，不记任何表单内容
                checks.rollback()
                service.audit(
                    conn,
                    action="auth.register_honeypot",
                    actor_id=None,
                    actor_role=None,
                    target_type="registration",
                    target_id=None,
                    detail={"trigger": trap},
                    ip_hash=ih,
                )
                return RegisterOut(
                    id=str(uuid.uuid4()), username=username, status=AccountStatus.PENDING
                )
            checks.commit()
            row = conn.execute(
                insert(users)
                .values(
                    username=username,
                    password_hash=pw_hash,
                    display_name=display_name,
                    apply_note=apply_note,
                    role=Role.USER,
                    status=AccountStatus.PENDING,
                    password_changed_at=service.now_utc(),
                )
                .returning(users.c.id, users.c.username, users.c.status)
            ).one()
            service.audit(
                conn,
                action="auth.register",
                actor_id=row.id,
                actor_role=Role.USER,
                target_type="user",
                target_id=str(row.id),
                detail=None if invite_id is None else {"invite_id": str(invite_id)},
                ip_hash=ih,
            )
            if invite_id is not None:
                invites.mark_used_by(conn, invite_id, row.id)
                service.audit(
                    conn,
                    action="invite.redeemed",
                    actor_id=row.id,
                    actor_role=Role.USER,
                    target_type="invite",
                    target_id=str(invite_id),
                    ip_hash=ih,
                )
    except IntegrityError as exc:
        # 并发注册同名：唯一约束兜底
        raise AppError(ErrorCode.CONFLICT, details={"field": "username"}) from exc
    return RegisterOut(id=str(row.id), username=row.username, status=AccountStatus(row.status))


@router.post("/auth/login")
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    settings: SettingsDep,
    engine: EngineDep,
    store: StoreDep,
    passwords: PasswordsDep,
    rds: RedisDep,
) -> dict[str, Any]:
    policy = settings.auth_abuse
    ip = client_ip(request, settings)
    # 同一 IP 每分钟上限 → 429（不落 login_attempts，防刷表）
    abuse.RateLimiter(rds).enforce(abuse.ip_key(settings, ip), abuse.login_windows(policy))

    username = body.username.strip().lower()
    tried = username[: abuse.USERNAME_TRIED_MAX]
    ih = ip_hash(settings, ip)
    with engine.connect() as conn:
        user = service.find_user_by_username(conn, username)
    user_id = None if user is None else user.id

    # 锁定期内不校验密码（密码正确也拒绝）；不存在的用户名同规则锁定，不泄露存在性
    retry = abuse.locked_retry_after(user, tried, rds, service.now_utc())
    if retry is not None:
        with engine.begin() as conn:
            abuse.record_attempt(
                conn,
                username=tried,
                user_id=user_id,
                ip_hash=ih,
                success=False,
                failure_reason="locked",
            )
        raise AppError(ErrorCode.ACCOUNT_LOCKED, details={"retry_after_s": retry})

    # 用户不存在也跑一次哈希校验（时间接近），错误一律 401，不区分“用户不存在 / 密码错”
    if not passwords.verify(None if user is None else user.password_hash, body.password):
        with engine.begin() as conn:
            locked_s = abuse.record_failure(conn, policy, user_id=user_id, username=tried, rds=rds)
            abuse.record_attempt(
                conn,
                username=tried,
                user_id=user_id,
                ip_hash=ih,
                success=False,
                failure_reason="invalid_credentials",
            )
            if user is not None:
                service.audit(
                    conn,
                    action="auth.login_failed",
                    actor_id=user.id,
                    actor_role=user.role,
                    target_type="user",
                    target_id=str(user.id),
                    detail=None if locked_s is None else {"locked_s": locked_s},
                    ip_hash=ih,
                )
        raise AppError(ErrorCode.INVALID_CREDENTIALS)
    assert user is not None  # noqa: S101 - verify(None, ...) 恒为 False

    # 密码正确即打断“连续失败”（含未批准账号）
    with engine.begin() as conn:
        abuse.reset_failures(conn, user=user, username=tried, rds=rds)
        abuse.record_attempt(
            conn,
            username=tried,
            user_id=user_id,
            ip_hash=ih,
            success=user.status == AccountStatus.APPROVED,
            failure_reason=None if user.status == AccountStatus.APPROVED else "not_approved",
        )

    # 密码正确但未批准：403 + status（+ 驳回原因），不建会话（plan §3.6）
    if user.status != AccountStatus.APPROVED:
        details: dict[str, Any] = {"status": user.status}
        with engine.connect() as conn:
            reason = (
                service.latest_reject_reason(conn, user.id)
                if user.status == AccountStatus.REJECTED
                else None
            )
        if reason:
            details["reason"] = reason
        raise AppError(ErrorCode.ACCOUNT_NOT_APPROVED, details=details)

    # 会话固定防护：带着旧会话登录时先作废旧会话
    old = store.get(request.cookies.get(SESSION_COOKIE))
    if old is not None:
        store.delete(old)
    sid, session = store.create(str(user.id))

    with engine.begin() as conn:
        # argon2 参数改了（auth.yaml password_hash）→ 旧哈希透明升级
        if passwords.needs_rehash(user.password_hash):
            service.set_password_hash(conn, user.id, passwords.hash(body.password), changed=False)
        service.audit(
            conn,
            action="auth.login",
            actor_id=user.id,
            actor_role=user.role,
            target_type="user",
            target_id=str(user.id),
            ip_hash=ih,
        )
        me = build_me(conn, user)
    _set_auth_cookies(response, settings, sid, session.csrf_token)
    return {"user": me, "csrf_token": session.csrf_token}


@router.post("/auth/logout", status_code=204)
def logout(
    auth: AuthDep, request: Request, settings: SettingsDep, engine: EngineDep, store: StoreDep
) -> Response:
    store.delete(auth.session)
    with engine.begin() as conn:
        service.audit(
            conn,
            action="auth.logout",
            actor_id=auth.user_id,
            actor_role=auth.user.role,
            target_type="user",
            target_id=str(auth.user_id),
            ip_hash=ip_hash(settings, client_ip(request, settings)),
        )
    response = Response(status_code=204)
    _clear_auth_cookies(response, settings)
    return response


@router.post("/auth/password", status_code=204)
def change_password(
    body: PasswordIn,
    auth: AuthDep,
    request: Request,
    settings: SettingsDep,
    engine: EngineDep,
    store: StoreDep,
    passwords: PasswordsDep,
    rds: RedisDep,
) -> Response:
    # review M5：先查限速（已超限直接 429，不跑 argon2、不校验旧密码，猜对也不行），
    # 再校验，失败才记数——与登录一致
    limiter = abuse.RateLimiter(rds)
    windows = abuse.password_change_windows(settings.auth_abuse)
    limiter.ensure_not_limited(str(auth.user_id), windows)
    if not passwords.verify(auth.user.password_hash, body.old_password):
        # 契约 §7.1：旧密码错误计入 T-B03a 限速——按用户计数，超限 429 + Retry-After
        limiter.enforce(str(auth.user_id), windows)
        raise _validation([{"field": "old_password", "issue": "incorrect"}])
    fields = [
        {"field": "new_password", "issue": i}
        for i in passwords.issues(body.new_password, username=auth.user.username)
    ]
    if body.new_password == body.old_password:
        fields.append({"field": "new_password", "issue": "must differ from old_password"})
    if fields:
        raise _validation(fields)
    with engine.begin() as conn:
        new_hash = passwords.hash(body.new_password)
        service.set_password_hash(conn, auth.user_id, new_hash, changed=True)
        service.audit(
            conn,
            action="auth.password_changed",
            actor_id=auth.user_id,
            actor_role=auth.user.role,
            target_type="user",
            target_id=str(auth.user_id),
            ip_hash=ip_hash(settings, client_ip(request, settings)),
        )
    # review-T-B03 S3 / 契约 v0.2.3 #25：吊销全部会话（含当前），新建会话并下发新 sid / csrf_token
    store.revoke_user(str(auth.user_id))
    sid, session = store.create(str(auth.user_id))
    response = Response(status_code=204)
    _set_auth_cookies(response, settings, sid, session.csrf_token)
    return response
