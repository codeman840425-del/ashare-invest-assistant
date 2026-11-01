"""无验证码的防滥用（plan §3.6，契约 §1.3 / §4；T-B03a）。

- **限速**：Redis 有序集合滑动窗口（Lua 原子执行，时间取 Redis ``TIME``）。超限不计入窗口，
  返回需等待的秒数；路由层转成 ``429 RATE_LIMITED`` + ``Retry-After`` 头
  + ``details.retry_after_s``。
  键：``auth:rl:{scope}:{ip_key}``；``ip_key`` 是 IP 的 HMAC（无主密钥时为 SHA-256），不存明文 IP。
- **渐进锁定**：同一用户名连续失败 ``lock_after_failures`` 次锁 ``lock_base_s``，之后每多失败一次
  时长翻倍（15→30→60 分钟…），上限 ``lock_max_s``；成功登录（含密码正确但未批准）清零。
  已存在的用户状态写 ``users.failed_login_count / locked_until``；**不存在的用户名**用 Redis 同规则
  计数，使两者对外表现一致（不借锁定泄露用户名是否存在）。
- **pending 上限**：全站 ``pending`` 账户数达到上限时注册返回 ``503 REGISTRATION_CLOSED``。
- ``login_attempts``：每次进入凭据判断的登录都记一行（含锁定拒绝）；被限速的请求不记（防刷表）。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

import redis
from sqlalchemy import Connection, Row, delete, func, insert, select, update

from app.auth.deps import ip_hash
from app.common.errors import AppError, ErrorCode
from app.config import AuthAbusePolicy, Settings
from app.db.tables.users import login_attempts, users
from app.schemas.enums import AccountStatus

RL_PREFIX: Final = "auth:rl:"
GHOST_PREFIX: Final = "auth:lockout:"
#: ``login_attempts`` 保留 180 天（plan §3.3）
LOGIN_ATTEMPTS_RETENTION: Final = dt.timedelta(days=180)
USERNAME_TRIED_MAX: Final = 64

# KEYS = 各窗口键；ARGV = member, 然后每个键一对 (limit, window_ms)。
# 先检查全部窗口，任一超限则都不记入并返回最长等待秒数；否则全部记入并返回 0。
_SLIDING_WINDOW_LUA: Final = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local member = ARGV[1]
local wait = 0
for i, key in ipairs(KEYS) do
  local limit = tonumber(ARGV[2 * i])
  local window = tonumber(ARGV[2 * i + 1])
  redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
  if redis.call('ZCARD', key) >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local w = math.ceil((tonumber(oldest[2]) + window - now) / 1000)
    if w < 1 then w = 1 end
    if w > wait then wait = w end
  end
end
if wait > 0 then return wait end
for i, key in ipairs(KEYS) do
  redis.call('ZADD', key, now, member)
  redis.call('PEXPIRE', key, tonumber(ARGV[2 * i + 1]))
end
return 0
"""


@dataclass(frozen=True)
class Window:
    scope: str
    limit: int
    window_s: int


def ip_key(settings: Settings, ip: str | None) -> str:
    """限速键里的 IP 标识：有主密钥用 HMAC（与 ``ip_hash`` 同一函数），否则 SHA-256。"""
    hashed = ip_hash(settings, ip)
    if hashed is not None:
        return hashed
    return hashlib.sha256(b"ip:" + (ip or "unknown").encode("utf-8")).hexdigest()


class RateLimiter:
    def __init__(self, client: redis.Redis) -> None:
        self._r = client
        self._script = client.register_script(_SLIDING_WINDOW_LUA)

    def hit(self, key_suffix: str, windows: Sequence[Window]) -> int:
        """记一次请求；返回 0 表示放行，否则为需等待的秒数（本次不计入窗口）。"""
        keys = [f"{RL_PREFIX}{w.scope}:{key_suffix}" for w in windows]
        args: list[Any] = [secrets.token_hex(8)]
        for w in windows:
            args += [w.limit, w.window_s * 1000]
        return int(cast(int, self._script(keys=keys, args=args)))

    def enforce(self, key_suffix: str, windows: Sequence[Window]) -> None:
        wait = self.hit(key_suffix, windows)
        if wait > 0:
            raise AppError(
                ErrorCode.RATE_LIMITED,
                details={"retry_after_s": wait},
                headers={"Retry-After": str(wait)},
            )


def login_windows(policy: AuthAbusePolicy) -> list[Window]:
    return [Window("login:ip:1m", policy.login_ip_per_minute, 60)]


def register_windows(policy: AuthAbusePolicy) -> list[Window]:
    return [
        Window("register:ip:1h", policy.register_ip_per_hour, 3600),
        Window("register:ip:1d", policy.register_ip_per_day, 86_400),
    ]


def password_change_windows(policy: AuthAbusePolicy) -> list[Window]:
    """改密旧密码错误：同一用户每 ``lock_base_s`` 秒最多 ``lock_after_failures`` 次（只计失败）。"""
    return [Window("password:user", policy.lock_after_failures, policy.lock_base_s)]


def lock_seconds(policy: AuthAbusePolicy, failures: int) -> int | None:
    """连续失败 ``failures`` 次后应锁定的秒数；未到阈值为 ``None``。"""
    if failures < policy.lock_after_failures:
        return None
    exp = min(failures - policy.lock_after_failures, 32)
    return int(min(policy.lock_base_s * (2**exp), policy.lock_max_s))


# ---------------------------------------------------------------------------
# 锁定状态：已存在用户 → users 表；不存在的用户名 → Redis（同规则）
# ---------------------------------------------------------------------------
def _ghost_key(username: str) -> str:
    return GHOST_PREFIX + hashlib.sha256(username.encode("utf-8")).hexdigest()


def locked_retry_after(
    user: Row[Any] | None, username: str, rds: redis.Redis, now: dt.datetime
) -> int | None:
    """处于锁定期则返回剩余秒数（≥1），否则 ``None``。"""
    if user is not None:
        until = user.locked_until
        if until is not None and until > now:
            return max(1, int((until - now).total_seconds()))
        return None
    ttl = int(rds.pttl(_ghost_key(username) + ":lock"))
    if ttl > 0:
        return max(1, -(-ttl // 1000))
    return None


def record_failure(
    conn: Connection,
    policy: AuthAbusePolicy,
    *,
    user_id: uuid.UUID | None,
    username: str,
    rds: redis.Redis,
) -> int | None:
    """记一次密码错误；返回本次触发的锁定秒数（未触发为 ``None``）。"""
    if user_id is not None:
        failures = int(
            conn.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(failed_login_count=users.c.failed_login_count + 1)
                .returning(users.c.failed_login_count)
            ).scalar_one()
        )
        secs = lock_seconds(policy, failures)
        if secs is not None:
            conn.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(locked_until=func.now() + dt.timedelta(seconds=secs))
            )
        return secs
    key = _ghost_key(username)
    pipe = rds.pipeline()
    pipe.incr(key + ":fails")
    # 计数保留到最长锁定期之后，避免无限积累键
    pipe.expire(key + ":fails", policy.lock_max_s * 2)
    failures = int(pipe.execute()[0])
    secs = lock_seconds(policy, failures)
    if secs is not None:
        rds.set(key + ":lock", "1", ex=secs)
    return secs


def reset_failures(
    conn: Connection, *, user: Row[Any] | None, username: str, rds: redis.Redis
) -> None:
    if user is not None:
        if user.failed_login_count or user.locked_until is not None:
            conn.execute(
                update(users)
                .where(users.c.id == user.id)
                .values(failed_login_count=0, locked_until=None)
            )
        return
    rds.delete(_ghost_key(username) + ":fails", _ghost_key(username) + ":lock")


def record_attempt(
    conn: Connection,
    *,
    username: str,
    user_id: uuid.UUID | None,
    ip_hash: str | None,
    success: bool,
    failure_reason: str | None = None,
) -> None:
    conn.execute(
        insert(login_attempts).values(
            username_tried=username[:USERNAME_TRIED_MAX],
            user_id=user_id,
            ip_hash=ip_hash,
            success=success,
            failure_reason=failure_reason,
        )
    )


def purge_login_attempts(conn: Connection, *, now: dt.datetime | None = None) -> int:
    """删除超过 180 天的 ``login_attempts``（供定时任务调用；调度接入归 beat 任务）。"""
    cutoff = (now or dt.datetime.now(dt.UTC)) - LOGIN_ATTEMPTS_RETENTION
    res = conn.execute(delete(login_attempts).where(login_attempts.c.at < cutoff))
    return int(res.rowcount or 0)


def enforce_pending_cap(conn: Connection, policy: AuthAbusePolicy) -> None:
    pending = conn.execute(
        select(func.count())
        .select_from(users)
        .where(users.c.status == AccountStatus.PENDING, users.c.deleted_at.is_(None))
    ).scalar_one()
    if int(pending) >= policy.pending_cap:
        raise AppError(ErrorCode.REGISTRATION_CLOSED)
