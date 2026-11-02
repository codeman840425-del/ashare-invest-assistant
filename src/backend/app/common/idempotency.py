"""``Idempotency-Key``（契约 §1.2：创建类 ``POST`` 24 小时内同键同体返回首次结果，
同键异体 → ``409 IDEMPOTENCY_CONFLICT``；T-B46）。

Redis 键 ``idem:{user_id}:{scope}:{sha256(key)}``，
值 ``{"h": 请求体指纹, "s": 状态码, "b": 响应体}``：

1. ``SET NX`` 占位（``s = 0`` = 处理中，TTL 24 小时）；
2. 成功后写入首次结果；**失败不缓存**（释放占位，客户端可用同一键重试）；
3. 同键同体：已完成 → 原样返回首次结果；仍在处理中 → ``409 IDEMPOTENCY_CONFLICT``
   （``details.in_progress = true``）；同键异体 → ``409 IDEMPOTENCY_CONFLICT``。

幂等键本身只存哈希，不落日志。Redis 不可用 → ``503 UPSTREAM_UNAVAILABLE``（不在无保护时写入）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Callable
from typing import Any, Final

import redis

from app.common.errors import AppError, ErrorCode

TTL_S: Final = 24 * 3600
KEY_MAX: Final = 255


def _k(user_id: object, scope: str, key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"idem:{user_id}:{scope}:{digest}"


def body_hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def run(
    rds: redis.Redis,
    *,
    user_id: object,
    scope: str,
    key: str | None,
    payload: object,
    fn: Callable[[], tuple[int, Any]],
) -> tuple[int, Any]:
    """执行 ``fn`` → ``(status_code, body)``；带 ``key`` 时按上文规则去重。"""
    if key is None:
        return fn()
    key = key.strip()
    if not key or len(key) > KEY_MAX:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            details={"fields": [{"field": "Idempotency-Key", "issue": "invalid"}]},
        )
    rk = _k(user_id, scope, key)
    h = body_hash(payload)
    try:
        placed = rds.set(rk, json.dumps({"h": h, "s": 0}), nx=True, ex=TTL_S)
        if not placed:
            raw = rds.get(rk)
            if raw is not None:
                rec = json.loads(raw)
                if rec.get("h") != h:
                    raise AppError(ErrorCode.IDEMPOTENCY_CONFLICT)
                if rec.get("s"):
                    return int(rec["s"]), rec.get("b")
                raise AppError(ErrorCode.IDEMPOTENCY_CONFLICT, details={"in_progress": True})
            # 竞态：刚好过期 → 重新占位
            if not rds.set(rk, json.dumps({"h": h, "s": 0}), nx=True, ex=TTL_S):
                raise AppError(ErrorCode.IDEMPOTENCY_CONFLICT, details={"in_progress": True})
    except redis.RedisError:
        raise AppError(ErrorCode.UPSTREAM_UNAVAILABLE) from None
    try:
        status, body = fn()
    except BaseException:
        with contextlib.suppress(redis.RedisError):
            rds.delete(rk)
        raise
    with contextlib.suppress(redis.RedisError):
        rds.set(rk, json.dumps({"h": h, "s": status, "b": body}, default=str), ex=TTL_S)
    return status, body
