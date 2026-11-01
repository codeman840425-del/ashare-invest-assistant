"""统一错误格式与错误码（契约 §2、§4）。

响应体固定为::

    {"error": {"code": str, "message": str, "details": object | null, "request_id": str}}

- 错误码表 :data:`ERROR_CODES` 与契约 §4（v0.2）逐行对应（HTTP 状态取契约原值）。
  §4.1 的 ``IMPORT_*`` 导入提示码不是 HTTP 错误码，见 :data:`app.schemas.enums.IMPORT_CODE_TABLE`。
- 业务代码抛 :class:`AppError`；框架层异常（路由不存在、参数校验失败、未捕获异常）
  由 :func:`install_exception_handlers` 统一转换，不向客户端泄露堆栈或内部信息。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common.request_id import get_request_id

logger = logging.getLogger("app.errors")


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_CURSOR = "INVALID_CURSOR"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    ACCOUNT_NOT_APPROVED = "ACCOUNT_NOT_APPROVED"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    CSRF_FAILED = "CSRF_FAILED"
    FORBIDDEN = "FORBIDDEN"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    ENTITLEMENT_LIMIT_REACHED = "ENTITLEMENT_LIMIT_REACHED"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    CONFLICT = "CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    IMMUTABLE_RESOURCE = "IMMUTABLE_RESOURCE"
    IMPORT_FILE_ERRORS = "IMPORT_FILE_ERRORS"
    IMPORT_ROW_ERRORS = "IMPORT_ROW_ERRORS"
    IMPORT_WARNINGS_UNACKNOWLEDGED = "IMPORT_WARNINGS_UNACKNOWLEDGED"
    IMPORT_NOTHING_TO_COMMIT = "IMPORT_NOTHING_TO_COMMIT"
    STRATEGY_INVALID_CONFIG = "STRATEGY_INVALID_CONFIG"
    STRATEGY_EXPR_FORBIDDEN = "STRATEGY_EXPR_FORBIDDEN"
    STRATEGY_VERSION_PUBLISHED = "STRATEGY_VERSION_PUBLISHED"
    STRATEGY_NOT_OWNED = "STRATEGY_NOT_OWNED"
    STRATEGY_HORIZON_MISMATCH = "STRATEGY_HORIZON_MISMATCH"
    RISK_CONTROL_INVALID_PARAMS = "RISK_CONTROL_INVALID_PARAMS"
    SUGGESTION_SUPERSEDED = "SUGGESTION_SUPERSEDED"
    SUGGESTION_REFRESH_TOO_FREQUENT = "SUGGESTION_REFRESH_TOO_FREQUENT"
    SUGGESTION_INSUFFICIENT_DATA = "SUGGESTION_INSUFFICIENT_DATA"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    STRATEGY_VERSION_NOT_RUNNABLE = "STRATEGY_VERSION_NOT_RUNNABLE"
    STRATEGY_FIT_ACK_REQUIRED = "STRATEGY_FIT_ACK_REQUIRED"
    STRATEGY_PARAM_OUT_OF_RANGE = "STRATEGY_PARAM_OUT_OF_RANGE"
    INSTANCE_SCOPE_INVALID = "INSTANCE_SCOPE_INVALID"
    PROMOTION_GATES_NOT_MET = "PROMOTION_GATES_NOT_MET"
    CARD_IMPORT_INVALID = "CARD_IMPORT_INVALID"
    COMPLIANCE_LINT_FAILED = "COMPLIANCE_LINT_FAILED"
    SIGNAL_NOT_EXPLAINABLE = "SIGNAL_NOT_EXPLAINABLE"
    PLAN_REQUIRES_EXPLAINABLE_SIGNAL = "PLAN_REQUIRES_EXPLAINABLE_SIGNAL"
    SIGNAL_NOT_EXECUTABLE = "SIGNAL_NOT_EXECUTABLE"
    PLAN_DRAFT_STALE = "PLAN_DRAFT_STALE"
    CHECKLIST_INCOMPLETE = "CHECKLIST_INCOMPLETE"
    RISK_ACK_REQUIRED = "RISK_ACK_REQUIRED"
    DEVIATION_ACK_REQUIRED = "DEVIATION_ACK_REQUIRED"
    REASON_NOT_MANUALLY_RELEASABLE = "REASON_NOT_MANUALLY_RELEASABLE"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    FRESH_DATA_REQUIRED = "FRESH_DATA_REQUIRED"
    INGEST_PAUSED = "INGEST_PAUSED"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_BUDGET_EXCEEDED = "LLM_BUDGET_EXCEEDED"
    LLM_PROVIDER_TEST_FAILED = "LLM_PROVIDER_TEST_FAILED"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    UPSTREAM_RATE_LIMITED = "UPSTREAM_RATE_LIMITED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    MAINTENANCE = "MAINTENANCE"


ErrorScope = Literal["http", "internal"]


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    http_status: int
    #: 默认中文信息（可变，客户端不得据此判断逻辑）
    message: str
    #: http = 作为 HTTP 错误返回；internal = 只出现在日志/管理端，不返回给普通用户
    #: （契约 §7.10 ``error_codes[].scope``）
    scope: ErrorScope = "http"


E = ErrorCode

#: 契约 §4 错误码表（顺序同契约）
ERROR_CODES: Final[dict[ErrorCode, ErrorSpec]] = {
    E.VALIDATION_ERROR: ErrorSpec(400, "参数校验失败"),
    E.INVALID_CURSOR: ErrorSpec(400, "分页游标无效或已过期"),
    E.AUTH_REQUIRED: ErrorSpec(401, "未登录或会话已过期"),
    E.INVALID_CREDENTIALS: ErrorSpec(401, "用户名或密码错误"),
    E.ACCOUNT_NOT_APPROVED: ErrorSpec(403, "账号尚未通过审核或不可用"),
    E.ACCOUNT_LOCKED: ErrorSpec(403, "登录失败次数过多，账号已临时锁定"),
    E.CSRF_FAILED: ErrorSpec(403, "CSRF 令牌缺失或不符"),
    E.FORBIDDEN: ErrorSpec(403, "权限不足"),
    E.CONSENT_REQUIRED: ErrorSpec(403, "请先完成风险测评并同意相关条款"),
    E.ENTITLEMENT_LIMIT_REACHED: ErrorSpec(403, "已达到套餐权益上限"),
    E.NOT_FOUND: ErrorSpec(404, "资源不存在"),
    E.METHOD_NOT_ALLOWED: ErrorSpec(405, "该路径不支持此请求方法"),
    #: 请求体超过网关/框架上限（契约 v0.2.3 §4）；应用层文件超限仍用 422 IMPORT_FILE_ERRORS
    E.PAYLOAD_TOO_LARGE: ErrorSpec(413, "请求体过大"),
    E.CONFLICT: ErrorSpec(409, "数据冲突"),
    E.IDEMPOTENCY_CONFLICT: ErrorSpec(409, "同一幂等键对应了不同的请求内容"),
    E.VERSION_CONFLICT: ErrorSpec(409, "版本号不一致，请刷新后重试"),
    E.IMMUTABLE_RESOURCE: ErrorSpec(409, "该对象不可修改"),
    E.IMPORT_FILE_ERRORS: ErrorSpec(422, "文件有错误，无法导入"),
    E.IMPORT_ROW_ERRORS: ErrorSpec(422, "仍有未处理的错误行"),
    E.IMPORT_WARNINGS_UNACKNOWLEDGED: ErrorSpec(422, "有需要处理的提示尚未确认"),
    E.IMPORT_NOTHING_TO_COMMIT: ErrorSpec(422, "没有可写入的行"),
    E.STRATEGY_INVALID_CONFIG: ErrorSpec(422, "策略配置校验失败"),
    E.STRATEGY_EXPR_FORBIDDEN: ErrorSpec(422, "规则表达式包含不允许的字段或运算"),
    E.STRATEGY_VERSION_PUBLISHED: ErrorSpec(409, "已发布的版本不可修改"),
    E.STRATEGY_NOT_OWNED: ErrorSpec(403, "不能修改内置策略或他人的策略，请先复制"),
    E.STRATEGY_HORIZON_MISMATCH: ErrorSpec(422, "该策略不支持所选周期"),
    E.RISK_CONTROL_INVALID_PARAMS: ErrorSpec(422, "风控阈值超出允许范围"),
    E.SUGGESTION_SUPERSEDED: ErrorSpec(409, "该条已被新的结果取代"),
    E.SUGGESTION_REFRESH_TOO_FREQUENT: ErrorSpec(409, "刷新过于频繁，请稍后再试"),
    E.SUGGESTION_INSUFFICIENT_DATA: ErrorSpec(422, "必备数据缺失，未生成结果"),
    E.INVALID_STATE_TRANSITION: ErrorSpec(409, "当前状态不允许该操作"),
    E.STRATEGY_VERSION_NOT_RUNNABLE: ErrorSpec(409, "该策略版本当前不可运行"),
    E.STRATEGY_FIT_ACK_REQUIRED: ErrorSpec(422, "该周期被判定为不适合，需要确认"),
    E.STRATEGY_PARAM_OUT_OF_RANGE: ErrorSpec(422, "参数超出允许范围"),
    E.INSTANCE_SCOPE_INVALID: ErrorSpec(422, "实例作用范围不合法"),
    E.PROMOTION_GATES_NOT_MET: ErrorSpec(422, "门禁未通过"),
    E.CARD_IMPORT_INVALID: ErrorSpec(422, "策略文档校验失败"),
    E.COMPLIANCE_LINT_FAILED: ErrorSpec(422, "文案包含禁用词"),
    E.SIGNAL_NOT_EXPLAINABLE: ErrorSpec(500, "信号缺少可解释字段，已拒绝写入", "internal"),
    E.PLAN_REQUIRES_EXPLAINABLE_SIGNAL: ErrorSpec(422, "草案引用的信号缺少通过的规则依据"),
    E.SIGNAL_NOT_EXECUTABLE: ErrorSpec(409, "信号仍有未解除的不可执行原因"),
    E.PLAN_DRAFT_STALE: ErrorSpec(409, "草案已过期或依据已变化"),
    E.CHECKLIST_INCOMPLETE: ErrorSpec(422, "判断清单有必答项未回答"),
    E.RISK_ACK_REQUIRED: ErrorSpec(422, "请先确认风险提示"),
    E.DEVIATION_ACK_REQUIRED: ErrorSpec(422, "数量或价格超出草案区间，请确认偏离"),
    E.REASON_NOT_MANUALLY_RELEASABLE: ErrorSpec(409, "该原因由系统判断，不能手动解除"),
    E.REGISTRATION_CLOSED: ErrorSpec(503, "注册已关闭"),
    E.FRESH_DATA_REQUIRED: ErrorSpec(503, "行情不是最新，本次操作未执行"),
    E.INGEST_PAUSED: ErrorSpec(503, "行情采集已暂停"),
    E.LLM_UNAVAILABLE: ErrorSpec(503, "解释服务暂不可用"),
    E.LLM_BUDGET_EXCEEDED: ErrorSpec(429, "解释服务今日额度已用完"),
    E.LLM_PROVIDER_TEST_FAILED: ErrorSpec(422, "供应商连接测试失败"),
    E.UPSTREAM_ERROR: ErrorSpec(502, "上游数据源返回错误"),
    E.UPSTREAM_RATE_LIMITED: ErrorSpec(503, "上游请求已排队，请稍后再试"),
    E.UPSTREAM_UNAVAILABLE: ErrorSpec(503, "上游数据源暂不可用"),
    E.RATE_LIMITED: ErrorSpec(429, "请求过于频繁，请稍后再试"),
    E.INTERNAL_ERROR: ErrorSpec(500, "服务器内部错误"),
    E.MAINTENANCE: ErrorSpec(503, "系统维护中"),
}


# ---------------------------------------------------------------------------
# 响应模型（用于 OpenAPI 文档）
# ---------------------------------------------------------------------------


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    details: dict[str, Any] | None
    request_id: str


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


# ---------------------------------------------------------------------------
# 异常与渲染
# ---------------------------------------------------------------------------


class AppError(Exception):
    """业务错误。``details`` 结构按契约 §4 对应行约定。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        spec = ERROR_CODES[code]
        self.code = code
        self.status_code = spec.http_status
        self.message = message or spec.message
        self.details = details
        self.headers = headers or {}
        super().__init__(f"{code}: {self.message}")


def error_payload(
    code: ErrorCode,
    message: str | None = None,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code.value,
            "message": message or ERROR_CODES[code].message,
            "details": details,
            "request_id": request_id or get_request_id() or "",
        }
    }


JSON_MEDIA_TYPE: Final = "application/json; charset=utf-8"


class Utf8JSONResponse(JSONResponse):
    """契约 §1：``Content-Type: application/json; charset=utf-8``。

    Starlette 只给 ``text/*`` 自动补 charset，``JSONResponse`` 默认是裸 ``application/json``；
    错误信封与默认响应类（``create_app`` 的 ``default_response_class``）都用这个类。
    """

    media_type = JSON_MEDIA_TYPE


class PayloadTooLarge(StarletteHTTPException):
    """请求体超过框架层上限（``ingest.imports.max_request_bytes``）→ ``413 PAYLOAD_TOO_LARGE``。"""

    def __init__(self, max_bytes: int) -> None:
        super().__init__(status_code=413)
        self.max_bytes = max_bytes


def error_response(
    code: ErrorCode,
    message: str | None = None,
    details: dict[str, Any] | None = None,
    *,
    status_code: int | None = None,
    headers: dict[str, str] | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    payload = error_payload(code, message, details, request_id)
    hdrs = dict(headers or {})
    rid = payload["error"]["request_id"]
    if rid:
        hdrs["X-Request-Id"] = rid
    return Utf8JSONResponse(
        payload,
        status_code=status_code or ERROR_CODES[code].http_status,
        headers=hdrs,
    )


# 框架层 HTTPException 的状态码 → 契约错误码（405 单独处理；415 等契约无专用码，见报告）
_HTTP_STATUS_TO_CODE: Final[dict[int, ErrorCode]] = {
    400: E.VALIDATION_ERROR,
    401: E.AUTH_REQUIRED,
    403: E.FORBIDDEN,
    404: E.NOT_FOUND,
    405: E.METHOD_NOT_ALLOWED,
    409: E.CONFLICT,
    413: E.PAYLOAD_TOO_LARGE,
    422: E.VALIDATION_ERROR,
    429: E.RATE_LIMITED,
    503: E.MAINTENANCE,
}

_LOC_SOURCES: Final[frozenset[str]] = frozenset({"query", "body", "path", "header", "cookie"})


def _field_name(loc: tuple[int | str, ...]) -> str:
    parts = list(loc)
    if parts and parts[0] in _LOC_SOURCES:
        parts = parts[1:]
    return ".".join(str(p) for p in parts) or "body"


def _issue(err: dict[str, Any]) -> str:
    ctx = err.get("ctx") or {}
    kind = err.get("type", "")
    simple = {
        "less_than_equal": ("<=", "le"),
        "less_than": ("<", "lt"),
        "greater_than_equal": (">=", "ge"),
        "greater_than": (">", "gt"),
    }
    if kind in simple:
        op, key = simple[kind]
        return f"must be {op} {ctx.get(key)}"
    if kind == "missing":
        return "required"
    if kind in {"int_parsing", "int_type"}:
        return "must be an integer"
    if kind == "extra_forbidden":
        return "unknown field"
    return str(err.get("msg", "invalid"))


def validation_details(exc: RequestValidationError) -> dict[str, Any]:
    fields = [
        {"field": _field_name(tuple(e.get("loc", ()))), "issue": _issue(e)} for e in exc.errors()
    ]
    return {"fields": fields}


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101 - 由注册类型保证
    return error_response(exc.code, exc.message, exc.details, headers=exc.headers)


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    return error_response(E.VALIDATION_ERROR, details=validation_details(exc))


def _is_admin_path(request: Request) -> bool:
    prefix: str = getattr(request.app.state, "api_prefix", "")
    path = request.url.path
    if prefix and path.startswith(prefix):
        path = path[len(prefix) :]
    return path == "/admin" or path.startswith("/admin/")


def _is_admin_user(request: Request) -> bool:
    """鉴权尚未实现（T-B03）：在此之前一律视为非管理员。"""
    return bool(getattr(request.state, "is_admin", False))


def _method_not_allowed(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """契约 §4：405 带 ``Allow`` 头与 ``details.allowed``；非管理员访问 ``/admin/*`` 一律 404。"""
    if _is_admin_path(request) and not _is_admin_user(request):
        return error_response(E.NOT_FOUND)
    headers = dict(exc.headers or {})
    allow_raw = next((v for k, v in headers.items() if k.lower() == "allow"), "")
    allowed = [m.strip().upper() for m in allow_raw.split(",") if m.strip()]
    other = {k: v for k, v in headers.items() if k.lower() != "allow"}
    other["Allow"] = ", ".join(allowed)
    return error_response(E.METHOD_NOT_ALLOWED, details={"allowed": allowed}, headers=other)


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    if exc.status_code == 405:
        return _method_not_allowed(request, exc)
    code = _HTTP_STATUS_TO_CODE.get(exc.status_code)
    if code is None:
        # 未映射的框架状态码（如 415）：按契约只能落到已定义的错误码，记录原状态便于排查
        logger.warning("unmapped http status %s", exc.status_code)
        code = E.VALIDATION_ERROR if 400 <= exc.status_code < 500 else E.INTERNAL_ERROR
    headers = {k: v for k, v in (exc.headers or {}).items() if k.lower() != "allow"}
    details = {"max_bytes": exc.max_bytes} if isinstance(exc, PayloadTooLarge) else None
    return error_response(code, details=details, headers=headers)


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
