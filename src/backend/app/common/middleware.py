"""请求级中间件：request_id 透传/生成、响应头、访问日志、未捕获异常兜底。

实现为纯 ASGI 中间件（不用 BaseHTTPMiddleware），以便：
- SSE 等流式响应不被缓冲；
- 未捕获异常在这里统一渲染为 ``500 INTERNAL_ERROR``，响应头仍带 ``X-Request-Id``。
"""

from __future__ import annotations

import logging
import time

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.common.errors import ErrorCode, error_response
from app.common.request_id import (
    REQUEST_ID_HEADER,
    accept_or_generate,
    reset_request_id,
    set_request_id,
)

access_logger = logging.getLogger("app.access")
error_logger = logging.getLogger("app.errors")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = accept_or_generate(Headers(scope=scope).get(REQUEST_ID_HEADER))
        scope.setdefault("state", {})["request_id"] = rid
        token = set_request_id(rid)
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = rid
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            error_logger.exception("unhandled error")
            if response_started:
                raise
            response = error_response(ErrorCode.INTERNAL_ERROR, request_id=rid)
            await response(scope, receive, send_wrapper)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            # 只记录方法、路径（不含查询串）、状态码、耗时
            access_logger.info(
                "%s %s %s %.1fms",
                scope.get("method", "-"),
                scope.get("path", "-"),
                status_code,
                elapsed_ms,
            )
            reset_request_id(token)
