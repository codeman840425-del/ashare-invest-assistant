"""游标分页（契约 §1.2）。

- 请求：``?limit=``（默认 50，最大 200）``&cursor=``（不透明字符串）。
- 响应：``{"items": [...], "next_cursor": str | null}``；``null`` 表示最后一页。
- 游标内容：``{"v": 1, "s": scope, "k": [排序键...], "iat": 签发时间}``，
  base64url 编码后附 HMAC-SHA256 签名（密钥由 ``APP_MASTER_KEY`` 派生）。
  被篡改、跨接口复用（scope 不符）、格式错误或超过 ``CURSOR_TTL_S`` → ``400 INVALID_CURSOR``。
- 排序键（keyset）由调用方决定，默认 ``created_at desc, id desc``：调用方取 ``limit + 1``
  行，用 :func:`build_page` 生成下一页游标，再用 :func:`decode_cursor` 取回上一页最后一行的键。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict

from app.common.errors import AppError, ErrorCode
from app.config import Settings, get_settings, master_key_bytes

CURSOR_VERSION: Final = 1
_SIG_BYTES: Final = 16  # 截断到 128 bit，游标更短，仍足以防篡改

#: 游标里允许的排序键类型（datetime/UUID 由调用方先转成 ISO 字符串/str）
CursorKey = str | int

#: 进程内临时密钥：仅 local/test 环境且未设置 APP_MASTER_KEY 时使用（重启后旧游标失效）
_EPHEMERAL_KEY: Final = secrets.token_bytes(32)


def _signing_key(settings: Settings) -> bytes:
    # T-B49：非 local/test 无主密钥 → MasterKeyMissingError（不回退到临时密钥）
    master = master_key_bytes(settings)
    if master is None:
        return _EPHEMERAL_KEY
    return hmac.new(master, b"aia/cursor/v1", hashlib.sha256).digest()


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _invalid() -> AppError:
    return AppError(ErrorCode.INVALID_CURSOR)


def encode_cursor(
    keys: Sequence[CursorKey],
    *,
    scope: str,
    settings: Settings | None = None,
    now: float | None = None,
) -> str:
    """把排序键编码成不透明游标。``scope`` 建议用接口标识（如 ``"trades:list"``）。"""
    cfg = settings or get_settings()
    body = {
        "v": CURSOR_VERSION,
        "s": scope,
        "k": list(keys),
        "iat": int(now if now is not None else time.time()),
    }
    payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sig = hmac.new(_signing_key(cfg), payload, hashlib.sha256).digest()[:_SIG_BYTES]
    return f"{_b64e(payload)}.{_b64e(sig)}"


def decode_cursor(
    cursor: str,
    *,
    scope: str,
    settings: Settings | None = None,
    now: float | None = None,
) -> list[CursorKey]:
    """校验并解出排序键；任何问题都抛 ``AppError(INVALID_CURSOR)``，不区分原因。"""
    cfg = settings or get_settings()
    if not cursor or len(cursor) > 2048 or cursor.count(".") != 1:
        raise _invalid()
    payload_b64, sig_b64 = cursor.split(".")
    try:
        payload = _b64d(payload_b64)
        sig = _b64d(sig_b64)
    except (binascii.Error, ValueError):
        raise _invalid() from None
    expected = hmac.new(_signing_key(cfg), payload, hashlib.sha256).digest()[:_SIG_BYTES]
    if not hmac.compare_digest(sig, expected):
        raise _invalid()
    try:
        body = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _invalid() from None
    if not isinstance(body, dict) or body.get("v") != CURSOR_VERSION or body.get("s") != scope:
        raise _invalid()
    iat, keys = body.get("iat"), body.get("k")
    if not isinstance(iat, int) or not isinstance(keys, list):
        raise _invalid()
    current = now if now is not None else time.time()
    if current - iat > cfg.cursor_ttl_s or iat - current > 300:
        raise _invalid()
    if not all(isinstance(k, str | int) and not isinstance(k, bool) for k in keys):
        raise _invalid()
    return keys


class Page[T](BaseModel):
    """列表响应 ``{items, next_cursor}``。"""

    model_config = ConfigDict(extra="forbid")

    items: list[T]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class PageParams:
    limit: int
    cursor: str | None


#: 契约 §1.2 / T-T25 §7：OpenAPI 声明 ``limit`` 最大 200（配置 ``page_limit_max`` 只能更小）
PAGE_LIMIT_MAX: Final = 200


def page_params(
    limit: Annotated[int | None, Query(ge=1, le=PAGE_LIMIT_MAX)] = None,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    settings: Settings = Depends(get_settings),  # noqa: B008 - FastAPI 依赖注入写法
) -> PageParams:
    """FastAPI 依赖：解析 ``limit``/``cursor``。超过上限 → ``400 VALIDATION_ERROR``。"""
    if limit is None:
        limit = settings.page_limit_default
    elif limit > settings.page_limit_max:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            details={
                "fields": [{"field": "limit", "issue": f"must be <= {settings.page_limit_max}"}]
            },
        )
    return PageParams(limit=limit, cursor=cursor or None)


def build_page[T](
    rows: Sequence[T],
    *,
    limit: int,
    key: Callable[[T], Sequence[CursorKey]],
    scope: str,
    settings: Settings | None = None,
) -> Page[T]:
    """``rows`` 为按固定排序取出的至多 ``limit + 1`` 行；多出的一行只用于判断是否有下一页。"""
    has_more = len(rows) > limit
    items = list(rows[:limit])
    next_cursor = (
        encode_cursor(key(items[-1]), scope=scope, settings=settings)
        if has_more and items
        else None
    )
    return Page[T](items=items, next_cursor=next_cursor)
