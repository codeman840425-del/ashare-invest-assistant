"""``/meta/registration``、``/auth/*``（契约 §7.1、§1.3；plan §3.6；T-B03）。

同步 ``def`` 路由：数据库（psycopg 同步引擎）与 Redis 都是阻塞调用，FastAPI 放线程池执行。
限速、渐进锁定、蜜罐、``login_attempts``、pending 上限归 T-B03a；管理员与禁用即吊销归 T-B03b。
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
from app.auth.consents import REGISTER_AGREEMENT_TO_KIND, REGISTER_DOC_VERSION
from app.auth.deps import (
    AuthDep,
    EngineDep,
    SettingsDep,
    StoreDep,
    client_ip,
    ip_hash,
)
from app.auth.passwords import (
    hash_password,
    needs_rehash,
    password_issues,
    verify_password,
)
from app.auth.sessions import CSRF_COOKIE, SESSION_COOKIE, SESSION_IDLE_TTL_S
from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.db.tables.users import users
from app.schemas.enums import AccountStatus, RegistrationMode, Role

router = APIRouter(tags=["auth"])

#: plan §3.6 / users.username CHECK：4–32 位小写字母、数字、下划线（契约写 3–32，取更严的库约束）
USERNAME_RE = re.compile(r"^[a-z0-9_]{4,32}$")
RESERVED_USERNAMES = frozenset({"admin", "root", "system"})
DISPLAY_NAME_MAX = 64


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegistrationModeOut(BaseModel):
    mode: RegistrationMode


class RegisterIn(_Body):
    username: Annotated[str, Field(min_length=1, max_length=64)]
    password: Annotated[str, Field(min_length=1, max_length=1024)]
    display_name: Annotated[str, Field(min_length=1, max_length=DISPLAY_NAME_MAX)]
    invite_code: Annotated[str | None, Field(max_length=128)] = None
    agreements: Annotated[list[str], Field(max_length=16)]


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
    common: dict[str, Any] = {
        "max_age": SESSION_IDLE_TTL_S,
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
    body: RegisterIn, request: Request, settings: SettingsDep, engine: EngineDep
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
    fields += [
        {"field": "password", "issue": i} for i in password_issues(body.password, username=username)
    ]
    display_name = body.display_name.strip()
    if not display_name:
        fields.append({"field": "display_name", "issue": "must not be blank"})
    agreed = set(body.agreements)
    unknown = sorted(agreed - set(REGISTER_AGREEMENT_TO_KIND))
    missing = sorted(set(REGISTER_AGREEMENT_TO_KIND) - agreed)
    if unknown:
        fields.append({"field": "agreements", "issue": "unknown: " + ",".join(unknown)})
    if missing:
        fields.append({"field": "agreements", "issue": "required: " + ",".join(missing)})
    if fields:
        raise _validation(fields)

    ih = ip_hash(settings, client_ip(request))
    pw_hash = hash_password(body.password)
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
                    role=Role.USER,
                    status=AccountStatus.PENDING,
                    password_changed_at=service.now_utc(),
                )
                .returning(users.c.id, users.c.username, users.c.status)
            ).one()
            service.insert_consents(
                conn,
                row.id,
                [REGISTER_AGREEMENT_TO_KIND[a] for a in sorted(agreed)],
                doc_version=REGISTER_DOC_VERSION,
                ip_hash=ih,
            )
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
) -> dict[str, Any]:
    username = body.username.strip().lower()
    ih = ip_hash(settings, client_ip(request))
    with engine.connect() as conn:
        user = service.find_user_by_username(conn, username)

    now = service.now_utc()
    if user is not None and user.locked_until is not None and user.locked_until > now:
        retry = max(1, int((user.locked_until - now).total_seconds()))
        raise AppError(ErrorCode.ACCOUNT_LOCKED, details={"retry_after_s": retry})

    # 用户不存在也跑一次哈希校验（时间接近），错误一律 401，不区分“用户不存在 / 密码错”
    if not verify_password(None if user is None else user.password_hash, body.password):
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
    assert user is not None  # noqa: S101 - verify_password(None, ...) 恒为 False

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
        if needs_rehash(user.password_hash):
            service.set_password_hash(conn, user.id, hash_password(body.password), changed=False)
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
            ip_hash=ip_hash(settings, client_ip(request)),
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
) -> Response:
    if not verify_password(auth.user.password_hash, body.old_password):
        raise _validation([{"field": "old_password", "issue": "incorrect"}])
    fields = [
        {"field": "new_password", "issue": i}
        for i in password_issues(body.new_password, username=auth.user.username)
    ]
    if body.new_password == body.old_password:
        fields.append({"field": "new_password", "issue": "must differ from old_password"})
    if fields:
        raise _validation(fields)
    with engine.begin() as conn:
        new_hash = hash_password(body.new_password)
        service.set_password_hash(conn, auth.user_id, new_hash, changed=True)
        service.audit(
            conn,
            action="auth.password_changed",
            actor_id=auth.user_id,
            actor_role=auth.user.role,
            target_type="user",
            target_id=str(auth.user_id),
            ip_hash=ip_hash(settings, client_ip(request)),
        )
    store.revoke_user(str(auth.user_id), keep=auth.session)
    return Response(status_code=204)
