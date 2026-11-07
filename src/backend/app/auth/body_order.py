"""契约 §1.3 判定顺序（v0.2.9 #30）：框架的请求体解析不得先于认证（③）与 CSRF（④）。

FastAPI 在解析依赖之前就读取并解码 JSON 请求体；JSON 非法时直接抛 ``RequestValidationError``，
认证依赖还没运行，于是“未登录发非法 JSON”得到 400。契约要求：未登录 → ``401``，已登录缺 CSRF
→ ``403 CSRF_FAILED``，``/admin/*`` 非管理员 → ``404``。

做法：替换 ``RequestValidationError`` 的处理器。只在错误里含 ``json_invalid``（请求体 JSON
解码失败——只有这一类发生在依赖之前；字段缺失 / 类型错误的校验本来就在依赖之后）时，查看
匹配到的路由是否依赖 :func:`current_auth` / :func:`current_admin`，若是则先按同样的逻辑判定
认证与 CSRF，失败就返回对应错误；通过了才返回 ``400 VALIDATION_ERROR``。不依赖鉴权的端点
（登录等）行为不变。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.dependencies.models import Dependant
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.auth.deps import current_admin, current_auth, get_engine, get_session_store
from app.common.errors import AppError, E, error_response, validation_details
from app.config import Settings

_AUTH_CALLS: tuple[Callable[..., Any], ...] = (current_admin, current_auth)


def _auth_call(dep: Dependant | None) -> Callable[..., Any] | None:
    """在依赖树里找鉴权依赖（管理员优先，与路由声明一致）。"""
    if dep is None:
        return None
    stack = [dep]
    found: set[Callable[..., Any]] = set()
    while stack:
        d = stack.pop()
        if d.call in _AUTH_CALLS:
            found.add(d.call)
        stack.extend(d.dependencies)
    for call in _AUTH_CALLS:
        if call in found:
            return call
    return None


def _is_json_invalid(exc: RequestValidationError) -> bool:
    return any(e.get("type") == "json_invalid" for e in exc.errors())


def auth_before_body(request: Request, exc: RequestValidationError) -> AppError | None:
    """返回应先于 400 报告的认证 / CSRF 错误；没有则 ``None``。"""
    if not _is_json_invalid(exc):
        return None
    route = request.scope.get("route")
    call = _auth_call(getattr(route, "dependant", None))
    if call is None or call in request.app.dependency_overrides:
        return None
    settings: Settings = request.app.state.settings
    try:
        call(request, get_engine(settings), get_session_store(settings))
    except AppError as err:
        return err
    return None


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101 - 由注册类型保证
    err = auth_before_body(request, exc)
    if err is not None:
        return error_response(err.code, err.message, err.details, headers=err.headers)
    return error_response(E.VALIDATION_ERROR, details=validation_details(exc))


def install(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation_handler)
