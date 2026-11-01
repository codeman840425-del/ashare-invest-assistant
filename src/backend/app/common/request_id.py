"""request_id 上下文（契约 §1：响应头 ``X-Request-Id``，客户端可传入同名头）。"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar
from typing import Final

REQUEST_ID_HEADER: Final = "X-Request-Id"

#: 允许透传的外部 request_id：只含安全字符、长度 1–128，避免日志注入与超长头
_SAFE_ID: Final = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_request_id() -> str:
    """生成新的 request_id，格式与契约示例一致：``req_`` + 32 位十六进制。"""
    return f"req_{uuid.uuid4().hex}"


def accept_or_generate(incoming: str | None) -> str:
    """传入值合法则原样透传，否则（缺失/非法字符/超长）生成新的。"""
    if incoming is not None:
        candidate = incoming.strip()
        if _SAFE_ID.fullmatch(candidate):
            return candidate
    return new_request_id()


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None) -> object:
    return _request_id.set(value)


def reset_request_id(token: object) -> None:
    _request_id.reset(token)  # type: ignore[arg-type]
