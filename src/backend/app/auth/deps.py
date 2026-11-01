"""认证依赖：数据库 / Redis 资源、当前用户、CSRF（契约 §1.3）。

判定顺序（🔒 接口）：无会话或会话失效 → ``401 AUTH_REQUIRED``；用户不存在或已注销 → 吊销会话后
``401 AUTH_REQUIRED``；账号非 ``approved`` → ``403 ACCOUNT_NOT_APPROVED {status}``；写方法
（POST/PUT/PATCH/DELETE）的 ``X-CSRF-Token`` 缺失或不符 → ``403 CSRF_FAILED``。
``/admin/*`` 的 404 规则不在这里。
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import redis
from fastapi import Depends, Request
from sqlalchemy import Engine, Row, select

from app.auth.passwords import PasswordPolicy, policy_for
from app.auth.sessions import CSRF_HEADER, SESSION_COOKIE, Session, SessionStore
from app.common.errors import AppError, ErrorCode
from app.config import Settings, get_settings
from app.db.engine import engine_for
from app.db.tables.users import users
from app.schemas.enums import AccountStatus, Role

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def get_engine(settings: Annotated[Settings, Depends(get_settings)]) -> Engine:
    if settings.database_url is None:
        raise AppError(ErrorCode.INTERNAL_ERROR)
    return engine_for(settings.database_url.get_secret_value())


@lru_cache(maxsize=4)
def _redis_for(url: str) -> redis.Redis:
    return redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)


def get_session_store(settings: Annotated[Settings, Depends(get_settings)]) -> SessionStore:
    if not settings.redis_url:
        raise AppError(ErrorCode.INTERNAL_ERROR)
    ttl = settings.business.auth.session
    return SessionStore(
        _redis_for(settings.redis_url),
        idle_ttl_s=ttl.idle_ttl_s,
        absolute_ttl_s=ttl.absolute_ttl_s,
    )


def get_password_policy(settings: Annotated[Settings, Depends(get_settings)]) -> PasswordPolicy:
    return policy_for(settings.business.auth)


def get_redis(settings: Annotated[Settings, Depends(get_settings)]) -> redis.Redis:
    if not settings.redis_url:
        raise AppError(ErrorCode.INTERNAL_ERROR)
    return _redis_for(settings.redis_url)


EngineDep = Annotated[Engine, Depends(get_engine)]
StoreDep = Annotated[SessionStore, Depends(get_session_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
PasswordsDep = Annotated[PasswordPolicy, Depends(get_password_policy)]
RedisDep = Annotated[redis.Redis, Depends(get_redis)]


def _parse_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()[:64]))
    except ValueError:
        return None


def _trusted_peer(peer: str, nets: tuple[str, ...]) -> bool:
    addr = _parse_ip(peer)
    if addr is None:
        return False
    ip = ipaddress.ip_address(addr)
    return any(ip in ipaddress.ip_network(n, strict=False) for n in nets)


def client_ip(request: Request, settings: Settings) -> str | None:
    """来源 IP（审计 ``ip_hash``；T-B03a 的按 IP 限速也用它）。

    - 直连对端不在 ``TRUSTED_PROXIES`` 内：一律取直连地址，忽略所有转发头（防伪造）。
    - 直连对端是我方 nginx：``X-Forwarded-For`` 只取**最右一跳**（nginx 用
      ``$proxy_add_x_forwarded_for`` 追加的 ``$remote_addr``），左侧各跳是客户端可伪造的，绝不采信；
      没有 XFF 时用 nginx 覆盖写入的 ``X-Real-IP``（T-O03 M1）；都不合法时退回直连地址。
    """
    peer = request.client.host if request.client else None
    if peer is None or not _trusted_peer(peer, settings.trusted_proxies):
        return peer
    xff = request.headers.get("x-forwarded-for")
    if xff is not None:
        hops = [h for h in (p.strip() for p in xff.split(",")) if h]
        rightmost = _parse_ip(hops[-1]) if hops else None
        return rightmost or peer
    return _parse_ip(request.headers.get("x-real-ip")) or peer


def ip_hash(settings: Settings, ip: str | None) -> str | None:
    """``HMAC-SHA256(APP_MASTER_KEY, ip)``；未配置主密钥（仅 local/test 允许）时不记录。"""
    if ip is None or settings.app_master_key is None:
        return None
    key = settings.app_master_key.get_secret_value().encode("utf-8")
    return hmac.new(key, b"ip:" + ip.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class AuthContext:
    user: Row[Any]
    session: Session

    @property
    def user_id(self) -> uuid.UUID:
        return uuid.UUID(str(self.user.id))


def load_user(engine: Engine, user_id: str) -> Row[Any] | None:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return None
    with engine.connect() as conn:
        return conn.execute(
            select(users).where(users.c.id == uid, users.c.deleted_at.is_(None))
        ).first()


def current_auth(request: Request, engine: EngineDep, store: StoreDep) -> AuthContext:
    session = store.get(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise AppError(ErrorCode.AUTH_REQUIRED)
    user = load_user(engine, session.user_id)
    if user is None:
        store.delete(session)
        raise AppError(ErrorCode.AUTH_REQUIRED)
    if user.status != AccountStatus.APPROVED:
        # 禁用即吊销属于 T-B03b；这里兜底：非 approved 的会话直接作废
        store.revoke_user(str(user.id))
        raise AppError(ErrorCode.ACCOUNT_NOT_APPROVED, details={"status": user.status})
    if request.method.upper() in UNSAFE_METHODS and not session.csrf_ok(
        request.headers.get(CSRF_HEADER)
    ):
        raise AppError(ErrorCode.CSRF_FAILED)
    return AuthContext(user=user, session=session)


AuthDep = Annotated[AuthContext, Depends(current_auth)]


def current_admin(request: Request, engine: EngineDep, store: StoreDep) -> AuthContext:
    """契约 §1.3 / §7.9：``/admin/*`` 不是已登录、已批准的 ``role=admin`` 时（含未登录、
    会话失效、非 approved）一律 ``404 NOT_FOUND``，与不存在的路径无法区分。
    已确认是管理员之后，不安全方法的 CSRF 不符照常返回 ``403 CSRF_FAILED``。"""
    session = store.get(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise AppError(ErrorCode.NOT_FOUND)
    user = load_user(engine, session.user_id)
    if user is None or user.status != AccountStatus.APPROVED or user.role != Role.ADMIN:
        raise AppError(ErrorCode.NOT_FOUND)
    if request.method.upper() in UNSAFE_METHODS and not session.csrf_ok(
        request.headers.get(CSRF_HEADER)
    ):
        raise AppError(ErrorCode.CSRF_FAILED)
    return AuthContext(user=user, session=session)


AdminDep = Annotated[AuthContext, Depends(current_admin)]
