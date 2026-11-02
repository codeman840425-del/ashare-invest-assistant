"""服务端会话（Redis）与 CSRF 令牌（契约 §1.3；plan §2“服务端会话 + httpOnly Cookie + CSRF 头”）。

- Cookie ``sid``：32 字节随机令牌（URL 安全 base64）。Redis 里只存它的 SHA-256，泄露 Redis 内容
  也拿不到可用的 Cookie。
- 键：``auth:session:{sha256(sid)}`` → JSON ``{user_id, csrf_token, created_at}``，TTL = 空闲期限，
  每次使用续期（但不超过绝对期限的剩余时间）；``auth:user_sessions:{user_id}`` → 该用户全部会话摘要
  （集合），用于改密/禁用时吊销。
- 期限取 ``config/auth.yaml session``（review-T-B03 M4）：``idle_ttl_s`` 空闲过期（默认 7 天），
  ``absolute_ttl_s`` 自登录起绝对过期（默认 30 天，不续期）。每次取会话时检查
  ``now - created_at ≥ absolute_ttl_s`` 即作废。
- CSRF：每个会话一个随机令牌，登录时通过响应体与非 HttpOnly Cookie ``csrf_token`` 下发；
  写请求做**双提交**校验（契约 v0.2.4 #13 / §1.3，T-B47）：``X-CSRF-Token`` 头、``csrf_token``
  Cookie、会话中保存的值三者必须一致（常量时间比较）。只有头与 Cookie 一致不够（攻击者能写子域
  Cookie 时可伪造二者），只有头与会话一致也不够（Cookie 缺失或不符同样拒绝）。
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

    def csrf_ok(self, header: str | None, cookie: str | None) -> bool:
        """双提交：请求头、Cookie 与会话令牌三者一致才通过（两次比较都做，避免短路时序差）。"""
        if not header or not cookie:
            return False
        expected = self.csrf_token.encode("utf-8")
        header_ok = hmac.compare_digest(header.encode("utf-8"), expected)
        cookie_ok = hmac.compare_digest(cookie.encode("utf-8"), expected)
        return header_ok and cookie_ok


class SessionStore:
    def __init__(self, client: redis.Redis, *, idle_ttl_s: int, absolute_ttl_s: int) -> None:
        if idle_ttl_s <= 0 or absolute_ttl_s < idle_ttl_s:
            raise ValueError("要求 0 < idle_ttl_s ≤ absolute_ttl_s")
        self._r = client
        self._ttl = idle_ttl_s
        self._abs = absolute_ttl_s

    def _remaining_ttl(self, created_at: dt.datetime, now: dt.datetime) -> int:
        """本次续期的 TTL：空闲期限与绝对期限剩余时间取小；≤ 0 表示已绝对过期。"""
        left = self._abs - (now - created_at).total_seconds()
        return min(self._ttl, int(left))

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
        pipe.expire(_USER_PREFIX + user_id, self._abs)
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
            created = dt.datetime.fromisoformat(session.created_at)
            if created.tzinfo is None:
                raise ValueError("created_at 缺时区")
        except (ValueError, KeyError, TypeError):
            self._r.delete(_SESSION_PREFIX + digest)
            return None
        ttl = self._remaining_ttl(created, dt.datetime.now(dt.UTC))
        if ttl <= 0:
            # 绝对过期：作废，不续期（review-T-B03 M4）
            self.delete(session)
            return None
        pipe = self._r.pipeline()
        pipe.expire(_SESSION_PREFIX + digest, ttl)
        pipe.expire(_USER_PREFIX + session.user_id, self._abs)
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
