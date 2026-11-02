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

from app.common.errors import ErrorCode, PayloadTooLarge, error_response
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


class BodySizeLimitMiddleware:
    """框架层请求体上限（契约 §4 ``413 PAYLOAD_TOO_LARGE {max_bytes}``）。

    nginx 的 ``client_max_body_size`` 是第一道（同值 26m）；这里兜底直连 api
    或 nginx 配置漂移的情况：
    - ``Content-Length`` 超限：不进路由，直接回 413；
    - 分块/无长度：边读边计数，超限时抛 :class:`PayloadTooLarge`。路由读体时抛出的会经异常处理器
      渲染为 413；在处理器之外抛出且尚未开始响应的，在这里渲染。
    应用层的文件超限（单文件 5 MB 等）不在这里，按契约走 ``422 IMPORT_FILE_ERRORS``。
    放在 :class:`RequestIdMiddleware` 内层，413 照常带 ``X-Request-Id``。
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.max_bytes
        declared = Headers(scope=scope).get("content-length")
        if declared is not None:
            try:
                too_large = int(declared) > limit
            except ValueError:
                too_large = False  # 非法长度交给服务器/框架处理
            if too_large:
                await self._reject(scope, receive, send)
                return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise PayloadTooLarge(limit)
            return message

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, send_wrapper)
        except PayloadTooLarge:
            if started:
                raise
            await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = error_response(
            ErrorCode.PAYLOAD_TOO_LARGE,
            details={"max_bytes": self.max_bytes},
            request_id=scope.get("state", {}).get("request_id"),
            headers={"Connection": "close"},
        )
        await response(scope, receive, send)


class PathCacheControlMiddleware:
    """按路径前缀统一覆盖 ``Cache-Control``（契约 v0.2.9 #41，plan 1.3）。

    ``/securities`` 及其下全部路径的**所有**响应（含 ``304``、错误、413、兜底 500）一律
    ``private, no-store``；路由里写的值（如 search 原来的 ``private, max-age=60``）被覆盖。
    放在最外层，只在这里设置一次。
    """

    def __init__(self, app: ASGIApp, *, prefixes: tuple[str, ...], value: str) -> None:
        self.app = app
        self.prefixes = prefixes
        self.value = value

    def _match(self, path: str) -> bool:
        return any(path == p or path.startswith(p + "/") for p in self.prefixes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._match(str(scope.get("path", ""))):
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = self.value
            await send(message)

        await self.app(scope, receive, send_wrapper)
