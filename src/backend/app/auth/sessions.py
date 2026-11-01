"""服务端会话（Redis）与 CSRF 令牌（契约 §1.3；plan §2“服务端会话 + httpOnly Cookie + CSRF 头”）。

- Cookie ``sid``：32 字节随机令牌（URL 安全 base64）。Redis 里只存它的 SHA-256，泄露 Redis 内容
  也拿不到可用的 Cookie。
- 键：``auth:session:{sha256(sid)}`` → JSON ``{user_id, csrf_token, created_at}``，TTL = 空闲期限，
  每次使用续期；``auth:user_sessions:{user_id}`` → 该用户全部会话摘要（集合），用于改密/禁用时吊销。
- 空闲期限：契约 §1.3 “空闲 7 天过期（可配置）”。配置键名 plan 未给 → 常量，
  待架构师定（报告 TODO）。
- CSRF：每个会话一个随机令牌，登录时通过响应体与非 HttpOnly Cookie ``csrf_token`` 下发；
  写请求的 ``X-CSRF-Token`` 头与会话中保存的值做常量时间比较（不信任 Cookie 本身）。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Final

import redis

SESSION_IDLE_TTL_S: Final = 7 * 24 * 3600
SESSION_COOKIE: Final = "sid"
CSRF_COOKIE: Final = "csrf_token"
CSRF_HEADER: Final = "X-CSRF-Token"

_SESSION_PREFIX: Final = "auth:session:"
_USER_PREFIX: Final = "auth:user_sessions:"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Session:
    sid_digest: str
    user_id: str
    csrf_token: str
    created_at: str

    def csrf_ok(self, presented: str | None) -> bool:
        if not presented:
            return False
        return hmac.compare_digest(presented.encode("utf-8"), self.csrf_token.encode("utf-8"))


class SessionStore:
    def __init__(self, client: redis.Redis, *, idle_ttl_s: int = SESSION_IDLE_TTL_S) -> None:
        self._r = client
        self._ttl = idle_ttl_s

    def create(self, user_id: str) -> tuple[str, Session]:
        """新建会话，返回 ``(sid 明文, Session)``；明文只写进 Cookie，不落 Redis。"""
        sid = secrets.token_urlsafe(32)
        session = Session(
            sid_digest=_digest(sid),
            user_id=user_id,
            csrf_token=secrets.token_urlsafe(32),
            created_at=dt.datetime.now(dt.UTC).isoformat(),
        )
        payload = json.dumps(
            {
                "user_id": session.user_id,
                "csrf_token": session.csrf_token,
                "created_at": session.created_at,
            }
        )
        pipe = self._r.pipeline()
        pipe.set(_SESSION_PREFIX + session.sid_digest, payload, ex=self._ttl)
        pipe.sadd(_USER_PREFIX + user_id, session.sid_digest)
        pipe.expire(_USER_PREFIX + user_id, self._ttl)
        pipe.execute()
        return sid, session

    def get(self, sid: str | None) -> Session | None:
        """取会话并续期；不存在、过期或内容损坏返回 ``None``。"""
        if not sid or len(sid) > 256:
            return None
        digest = _digest(sid)
        raw = self._r.get(_SESSION_PREFIX + digest)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            session = Session(
                sid_digest=digest,
                user_id=str(data["user_id"]),
                csrf_token=str(data["csrf_token"]),
                created_at=str(data["created_at"]),
            )
        except (ValueError, KeyError, TypeError):
            self._r.delete(_SESSION_PREFIX + digest)
            return None
        pipe = self._r.pipeline()
        pipe.expire(_SESSION_PREFIX + digest, self._ttl)
        pipe.expire(_USER_PREFIX + session.user_id, self._ttl)
        pipe.execute()
        return session

    def delete(self, session: Session) -> None:
        pipe = self._r.pipeline()
        pipe.delete(_SESSION_PREFIX + session.sid_digest)
        pipe.srem(_USER_PREFIX + session.user_id, session.sid_digest)
        pipe.execute()

    def revoke_user(self, user_id: str, *, keep: Session | None = None) -> int:
        """吊销某用户全部会话（``keep`` 除外），返回吊销数。改密、禁用、重置时调用。"""
        key = _USER_PREFIX + user_id
        members = self._r.smembers(key)
        digests = {m.decode() if isinstance(m, bytes) else m for m in members}
        if keep is not None:
            digests.discard(keep.sid_digest)
        if not digests:
            return 0
        pipe = self._r.pipeline()
        for d in digests:
            pipe.delete(_SESSION_PREFIX + d)
            pipe.srem(key, d)
        pipe.execute()
        return len(digests)
