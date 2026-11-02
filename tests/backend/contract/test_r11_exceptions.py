"""裁定 R11 的 schemathesis 例外（r11_exceptions.py）离线自检：进程内小 FastAPI 应用，不联网、不连任何服务。

正例：第 1/3/4/5 项（GET + cursor → 400 INVALID_CURSOR）与第 8 项（POST /imports → 422 IMPORT_UNSUPPORTED_FILE_TYPE）
不加例外时 schemathesis 报 ST202（RejectedPositiveData），加例外后通过——证明例外必要且生效。
反例（例外必须足够窄）：换错误码、换方法、换路径、不带 cursor、换状态码 → 仍报 ST202；
命中例外时其它检查照常执行（响应体违约仍被发现）。
"""

from __future__ import annotations

from typing import Any

import hypothesis
import pytest
import schemathesis
from hypothesis import HealthCheck
from schemathesis.core.failures import FailureGroup

import r11_exceptions as r11

pytestmark = [pytest.mark.contract, pytest.mark.unit]

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

ERR = {"description": "错误外壳", "content": {"application/json": {"schema": {
    "type": "object", "required": ["error"], "properties": {"error": {
        "type": "object", "required": ["code", "message"],
        "properties": {"code": {"type": "string"}, "message": {"type": "string"}}}}}}}}


class Page(BaseModel):
    items: list[str]
    next_cursor: str | None


def _err(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": "示例"}}, status_code=status)


UPLOAD_BODY = {"required": True, "content": {"multipart/form-data": {"schema": {
    "type": "object", "required": ["file", "kind"],
    "properties": {"file": {"type": "string", "format": "binary"}, "kind": {"type": "string"}}}}}}

LISTINGS = ("/api/v1/accounts", "/api/v1/imports", "/api/v1/trades", "/api/v1/alerts")


def make_app(*, cursor_code: str = "INVALID_CURSOR", cursor_status: int = 400,
             import_code: str = "IMPORT_UNSUPPORTED_FILE_TYPE", bad_body: bool = False) -> FastAPI:
    """cursor 非空即拒（模拟不透明游标）；POST 上传一律按“不是支持的表格”拒绝。bad_body=True 时错误外壳违约。
    /api/v1/alerts 与 /api/v1/other-upload 是不在登记表中的对照路径。"""
    app = FastAPI(openapi_url="/openapi.json")

    def page(cursor: str | None) -> Any:
        if cursor is None:
            return Page(items=[], next_cursor=None)
        return JSONResponse({"oops": True}, status_code=cursor_status) if bad_body else _err(cursor_status, cursor_code)

    def listing(cursor: str | None = None) -> Any:
        return page(cursor)

    def rows(batch_id: str, cursor: str | None = None) -> Any:
        return page(cursor)

    def upload() -> Any:
        # 不用 File/Form 参数：那会要求 python-multipart（origin 0cb78ad 的后端依赖里没有）；
        # 请求体 schema 由 UPLOAD_BODY 直接写进 OpenAPI，处理函数不读请求体
        return _err(422, import_code)

    for p in LISTINGS:
        app.add_api_route(p, listing, methods=["GET"], response_model=Page, responses={400: ERR, 422: ERR})
    app.add_api_route("/api/v1/imports/{batch_id}/rows", rows, methods=["GET"], response_model=Page,
                      responses={400: ERR, 422: ERR})
    for p in ("/api/v1/imports", "/api/v1/other-upload"):
        app.add_api_route(p, upload, methods=["POST"], status_code=202, responses={400: ERR, 422: ERR},
                          openapi_extra={"requestBody": UPLOAD_BODY})
    return app


def _schema(**kw: Any) -> Any:
    return schemathesis.openapi.from_asgi("/openapi.json", make_app(**kw))


def _cases(op: Any, n: int = 3, **fixed: Any) -> list[Any]:
    out: list[Any] = []

    @hypothesis.given(op.as_strategy(**fixed))
    @hypothesis.settings(max_examples=n, database=None, deadline=None, derandomize=True,
                         suppress_health_check=list(HealthCheck), phases=[hypothesis.Phase.generate])
    def run(case: Any) -> None:
        out.append(case)

    run()
    assert out
    return out


def _st202(exc: FailureGroup) -> bool:
    return any(type(e).__name__ == "RejectedPositiveData" for e in exc.exceptions)


def _validate(case: Any, use_r11: bool) -> FailureGroup | None:
    resp = case.call()
    excluded = r11.excluded_checks(case, resp) if use_r11 else []
    try:
        case.validate_response(resp, additional_checks=[r11.CHECK], excluded_checks=excluded or None)
    except FailureGroup as exc:
        return exc
    return None


# ------------------------------ 登记表本身 ------------------------------
def test_registry_is_exactly_rulings_1_3_4_5_8() -> None:
    got = {(e.ruling, e.method, e.path, e.status, e.error_code, e.query_param, e.check) for e in r11.EXCEPTIONS}
    assert got == {
        ("R11-1", "GET", "/api/v1/accounts", 400, "INVALID_CURSOR", "cursor", "positive_data_acceptance"),
        ("R11-3", "GET", "/api/v1/imports", 400, "INVALID_CURSOR", "cursor", "positive_data_acceptance"),
        ("R11-4", "GET", "/api/v1/imports/{batch_id}/rows", 400, "INVALID_CURSOR", "cursor", "positive_data_acceptance"),
        ("R11-5", "GET", "/api/v1/trades", 400, "INVALID_CURSOR", "cursor", "positive_data_acceptance"),
        ("R11-8", "POST", "/api/v1/imports", 422, "IMPORT_UNSUPPORTED_FILE_TYPE", None, "positive_data_acceptance"),
    }
    assert r11.CHECK.__name__ == "positive_data_acceptance"


def test_registry_every_entry_names_an_error_code() -> None:
    """R11 原则：例外必须写明错误码，不得按端点整体放行。"""
    for e in r11.EXCEPTIONS:
        assert e.error_code and e.error_code.isupper() and e.status in {400, 422}, e


@pytest.mark.parametrize("args,hit", [
    (("GET", "/api/v1/accounts", {"cursor": "x"}, 400, {"error": {"code": "INVALID_CURSOR"}}), "R11-1"),
    (("get", "/api/v1/trades", {"cursor": "", "limit": 5}, 400, b'{"error": {"code": "INVALID_CURSOR"}}'), "R11-5"),
    (("POST", "/api/v1/imports", {}, 422, {"error": {"code": "IMPORT_UNSUPPORTED_FILE_TYPE"}}), "R11-8"),
    (("GET", "/api/v1/accounts", {"cursor": "x"}, 400, {"error": {"code": "VALIDATION_ERROR"}}), None),
    (("GET", "/api/v1/accounts", {"limit": 1}, 400, {"error": {"code": "INVALID_CURSOR"}}), None),
    (("GET", "/api/v1/accounts", None, 400, {"error": {"code": "INVALID_CURSOR"}}), None),
    (("GET", "/api/v1/accounts", {"cursor": "x"}, 422, {"error": {"code": "INVALID_CURSOR"}}), None),
    (("POST", "/api/v1/accounts", {"cursor": "x"}, 400, {"error": {"code": "INVALID_CURSOR"}}), None),
    (("GET", "/api/v1/alerts", {"cursor": "x"}, 400, {"error": {"code": "INVALID_CURSOR"}}), None),
    (("GET", "/api/v1/imports/123/rows", {"cursor": "x"}, 400, {"error": {"code": "INVALID_CURSOR"}}), None),
    (("POST", "/api/v1/imports", {}, 422, {"error": {"code": "VALIDATION_ERROR"}}), None),
    (("POST", "/api/v1/imports", {}, 400, {"error": {"code": "IMPORT_UNSUPPORTED_FILE_TYPE"}}), None),
    (("PUT", "/api/v1/imports", {}, 422, {"error": {"code": "IMPORT_UNSUPPORTED_FILE_TYPE"}}), None),
    (("POST", "/api/v1/imports", {}, 422, b"not json"), None),
    (("POST", "/api/v1/imports", {}, 422, {"code": "IMPORT_UNSUPPORTED_FILE_TYPE"}), None),
], ids=["r1", "r5_bytes", "r8", "wrong_code", "no_cursor", "no_query", "wrong_status", "wrong_method", "other_path",
        "concrete_path_not_template", "r8_wrong_code", "r8_wrong_status", "r8_wrong_method", "r8_not_json",
        "r8_no_envelope"])
def test_match_is_narrow(args: tuple[Any, ...], hit: str | None) -> None:
    e = r11.match(*args)
    assert (e.ruling if e else None) == hit


# ------------------------------ schemathesis 端到端（进程内） ------------------------------
@pytest.mark.parametrize("path,ruling", [
    ("/api/v1/accounts", "R11-1"), ("/api/v1/imports", "R11-3"),
    ("/api/v1/imports/{batch_id}/rows", "R11-4"), ("/api/v1/trades", "R11-5"),
])
def test_cursor_400_is_st202_without_and_passes_with_exception(path: str, ruling: str) -> None:
    op = _schema()[path]["GET"]
    for case in _cases(op, query={"cursor": "zz-not-a-cursor"}):
        exc = _validate(case, use_r11=False)
        assert exc is not None and _st202(exc), "对照：不加例外时必须报 ST202（证明例外必要）"
        assert r11.match_case(case, case.call()).ruling == ruling
        assert _validate(case, use_r11=True) is None


def test_import_422_unsupported_is_st202_without_and_passes_with_exception() -> None:
    op = _schema()["/api/v1/imports"]["POST"]
    for case in _cases(op):
        exc = _validate(case, use_r11=False)
        assert exc is not None and _st202(exc)
        assert _validate(case, use_r11=True) is None


@pytest.mark.parametrize("kw,path,method,fixed", [
    ({"cursor_code": "VALIDATION_ERROR"}, "/api/v1/accounts", "GET", {"query": {"cursor": "zz"}}),
    ({"cursor_status": 422}, "/api/v1/trades", "GET", {"query": {"cursor": "zz"}}),
    ({}, "/api/v1/alerts", "GET", {"query": {"cursor": "zz"}}),
    ({"import_code": "IMPORT_EMPTY_FILE"}, "/api/v1/imports", "POST", {}),
    ({}, "/api/v1/other-upload", "POST", {}),
], ids=["wrong_code", "wrong_status", "path_not_listed", "r8_other_code", "r8_other_path"])
def test_exception_does_not_cover_neighbours(kw: dict[str, Any], path: str, method: str, fixed: dict[str, Any]) -> None:
    """例外不外溢：同一现象换错误码 / 状态码 / 路径，加了 R11 例外仍报 ST202。"""
    op = _schema(**kw)[path][method]
    for case in _cases(op, **fixed):
        exc = _validate(case, use_r11=True)
        assert exc is not None and _st202(exc)


def test_exception_keeps_other_checks() -> None:
    """命中例外只排除 positive_data_acceptance：错误响应体违约仍被 response_schema_conformance 发现。"""
    op = _schema(bad_body=True)["/api/v1/accounts"]["GET"]
    for case in _cases(op, query={"cursor": "zz"}):
        resp = case.call()
        assert r11.match_case(case, resp) is None  # 没有错误外壳 → 不命中
        exc = _validate(case, use_r11=True)
        assert exc is not None and not all(type(e).__name__ == "RejectedPositiveData" for e in exc.exceptions)
