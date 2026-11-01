"""``/meta/registration``、``/auth/*``（契约 §7.1、§1.3；plan §3.6；T-B03）。

同步 ``def`` 路由：数据库（psycopg 同步引擎）与 Redis 都是阻塞调用，FastAPI 放线程池执行。
限速、渐进锁定、蜜罐、``login_attempts``、pending 上限归 T-B03a；邀请码归 T-B03c。
会话期限、argon2 参数、口令长度取 ``config/auth.yaml``（T-B03b）。
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from app.api.v1.me import build_me
from app.auth import service
from app.auth.deps import (
    AuthDep,
    EngineDep,
    PasswordsDep,
    SettingsDep,
    StoreDep,
    client_ip,
    ip_hash,
)
from app.auth.sessions import CSRF_COOKIE, SESSION_COOKIE
from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.db.tables.users import users
from app.schemas.enums import AccountStatus, RegistrationMode, Role

router = APIRouter(tags=["auth"])

#: plan §3.6 / users.username CHECK：4–32 位小写字母、数字、下划线（契约写 3–32，取更严的库约束）
USERNAME_RE = re.compile(r"^[a-z0-9_]{4,32}$")
RESERVED_USERNAMES = frozenset({"admin", "root", "system"})
#: 契约 v0.2.4 #2：display_name 1–32、apply_note ≤ 200
DISPLAY_NAME_MAX = 32
APPLY_NOTE_MAX = 200


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


@router.post("/auth/register", status_code=201)
def register(
    body: RegisterIn,
    request: Request,
    settings: SettingsDep,
    engine: EngineDep,
    passwords: PasswordsDep,
) -> RegisterOut:
    # closed：一律 503（先于参数业务校验）。invite：邀请码的存储与核验未定义（无表、无发放接口），
    # 不能核验就不能放行 → 按最保守理解同 closed（报告 TODO）。open：契约“保留，V1 不用”，照实现。
    if settings.registration_mode != RegistrationMode.OPEN:
        raise AppError(ErrorCode.REGISTRATION_CLOSED)

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
    if fields:
        raise _validation(fields)

    ih = ip_hash(settings, client_ip(request, settings))
    pw_hash = passwords.hash(body.password)
    try:
        with engine.begin() as conn:
            if service.username_taken(conn, username):
                raise AppError(ErrorCode.CONFLICT, details={"field": "username"})
            row = conn.execute(
                insert(users)
                .values(
                    username=username,
                    password_hash=pw_hash,
                    display_name=display_name,
                    apply_note=(body.apply_note or "").strip() or None,
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
) -> dict[str, Any]:
    username = body.username.strip().lower()
    ih = ip_hash(settings, client_ip(request, settings))
    with engine.connect() as conn:
        user = service.find_user_by_username(conn, username)

    now = service.now_utc()
    if user is not None and user.locked_until is not None and user.locked_until > now:
        retry = max(1, int((user.locked_until - now).total_seconds()))
        raise AppError(ErrorCode.ACCOUNT_LOCKED, details={"retry_after_s": retry})

    # 用户不存在也跑一次哈希校验（时间接近），错误一律 401，不区分“用户不存在 / 密码错”
    if not passwords.verify(None if user is None else user.password_hash, body.password):
        if user is not None:
            with engine.begin() as conn:
                service.audit(
                    conn,
                    action="auth.login_failed",
                    actor_id=user.id,
                    actor_role=user.role,
                    target_type="user",
                    target_id=str(user.id),
                    ip_hash=ih,
                )
        raise AppError(ErrorCode.INVALID_CREDENTIALS)
    assert user is not None  # noqa: S101 - verify(None, ...) 恒为 False

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
) -> Response:
    if not passwords.verify(auth.user.password_hash, body.old_password):
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
