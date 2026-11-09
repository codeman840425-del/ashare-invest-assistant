"""裁定 R11 的 schemathesis 例外（r11_exceptions.py）离线自检：进程内小 FastAPI 应用，不联网、不连任何服务。

正例：第 1/3/4/5 项（GET + cursor → 400 INVALID_CURSOR）、第 8 项（POST /imports → 422 IMPORT_UNSUPPORTED_FILE_TYPE）、
第 9 项（POST /trades → 400 VALIDATION_ERROR field=security_code）与第 10 项（PUT /imports/{batch_id}/options →
400 VALIDATION_ERROR field=parser_id；T-T25 裁定 #1）不加例外时 schemathesis 报 ST202（RejectedPositiveData），加例外后通过——证明例外必要且生效。
反例（例外必须足够窄）：换错误码、换方法、换路径、不带 cursor、换状态码 → 仍报 ST202；
命中例外时其它检查照常执行（响应体违约仍被发现）；第 9/10 项换 field（qty / price / encoding_override）或混入别的
field → 仍报 ST202。
T-T25 裁定 #2：只读核对 ``src/backend/schemathesis.toml`` 的每条例外都在登记表中（toml 归后端，登记表归测试员）。
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import hypothesis
import pytest

fastapi = pytest.importorskip("fastapi")
schemathesis = pytest.importorskip("schemathesis", reason="schemathesis 未安装，契约用例 skip（T-T35 收集容错）")
from hypothesis import HealthCheck  # noqa: E402
from schemathesis.core.failures import FailureGroup  # noqa: E402

import r11_exceptions as r11

pytestmark = [pytest.mark.contract, pytest.mark.unit]

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


def _json_body(**props: Any) -> dict[str, Any]:
    return {"required": True, "content": {"application/json": {"schema": {
        "type": "object", "required": sorted(props), "properties": props, "additionalProperties": False}}}}


TRADE_BODY = _json_body(security_code={"type": "string", "pattern": "^[0-9]{6}$"},
                        qty={"type": "string", "pattern": "^[1-9][0-9]{0,6}$"})
OPTIONS_BODY = _json_body(parser_id={"type": "string", "enum": ["generic_csv", "broker_x"]})


def _fields_err(fields: tuple[str, ...]) -> JSONResponse:
    return JSONResponse({"error": {"code": "VALIDATION_ERROR", "message": "示例",
                                   "details": {"fields": [{"field": f, "issue": "示例"} for f in fields]}}},
                        status_code=400)


def make_app(*, cursor_code: str = "INVALID_CURSOR", cursor_status: int = 400,
             import_code: str = "IMPORT_UNSUPPORTED_FILE_TYPE", bad_body: bool = False,
             trade_fields: tuple[str, ...] = ("security_code",),
             options_fields: tuple[str, ...] = ("parser_id",)) -> FastAPI:
    """cursor 非空即拒（模拟不透明游标）；POST 上传一律按“不是支持的表格”拒绝。bad_body=True 时错误外壳违约。
    POST /trades 一律 400 VALIDATION_ERROR（fields=trade_fields，模拟“推断不出市场”）；PUT /imports/{batch_id}/options
    一律 400 VALIDATION_ERROR（fields=options_fields，模拟“解析器与批次 kind 不符”）。
    /api/v1/alerts 与 /api/v1/other-upload 是不在登记表中的对照路径；POST /api/v1/other-trades 同理。"""
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

    def trade() -> Any:  # 请求体 schema 由 openapi_extra 声明，处理函数不读请求体
        return _fields_err(trade_fields)

    def options(batch_id: str) -> Any:
        return _fields_err(options_fields)

    for p in ("/api/v1/trades", "/api/v1/other-trades"):
        app.add_api_route(p, trade, methods=["POST"], status_code=201, responses={400: ERR, 422: ERR},
                          openapi_extra={"requestBody": TRADE_BODY})
    app.add_api_route("/api/v1/imports/{batch_id}/options", options, methods=["PUT"], responses={400: ERR, 422: ERR},
                      openapi_extra={"requestBody": OPTIONS_BODY})
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
def test_registry_is_exactly_rulings_1_3_4_5_8_9_10() -> None:
    got = {(e.ruling, e.method, e.path, e.status, e.error_code, e.query_param, e.check, e.field)
           for e in r11.EXCEPTIONS}
    assert got == {
        ("R11-1", "GET", "/api/v1/accounts", 400, "INVALID_CURSOR", "cursor", "positive_data_acceptance", None),
        ("R11-3", "GET", "/api/v1/imports", 400, "INVALID_CURSOR", "cursor", "positive_data_acceptance", None),
        ("R11-4", "GET", "/api/v1/imports/{batch_id}/rows", 400, "INVALID_CURSOR", "cursor", "positive_data_acceptance", None),
        ("R11-5", "GET", "/api/v1/trades", 400, "INVALID_CURSOR", "cursor", "positive_data_acceptance", None),
        ("R11-8", "POST", "/api/v1/imports", 422, "IMPORT_UNSUPPORTED_FILE_TYPE", None, "positive_data_acceptance", None),
        ("R11-9", "POST", "/api/v1/trades", 400, "VALIDATION_ERROR", None, "positive_data_acceptance", "security_code"),
        ("R11-10", "PUT", "/api/v1/imports/{batch_id}/options", 400, "VALIDATION_ERROR", None,
         "positive_data_acceptance", "parser_id"),
    }
    assert r11.CHECK.__name__ == "positive_data_acceptance"


def test_registry_every_entry_names_an_error_code() -> None:
    """R11 原则：例外必须写明错误码，不得按端点整体放行。"""
    for e in r11.EXCEPTIONS:
        assert e.error_code and e.error_code.isupper() and e.status in {400, 422}, e
    # VALIDATION_ERROR 是通用码：登记它的例外必须再限定 field（裁定 #1“只放行一个错误码 + field”）
    for e in r11.EXCEPTIONS:
        if e.error_code == "VALIDATION_ERROR":
            assert e.field, e


def _ve(*fields: Any) -> dict[str, Any]:
    return {"error": {"code": "VALIDATION_ERROR", "message": "m",
                      "details": {"fields": [{"field": f, "issue": "x"} for f in fields]}}}


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
    # 第 9 / 10 项（T-T25 裁定 #1）：错误码 + field 都要对上；field 只能是登记的那一个
    (("POST", "/api/v1/trades", {}, 400, _ve("security_code")), "R11-9"),
    (("post", "/api/v1/trades", None, 400, b'{"error":{"code":"VALIDATION_ERROR","details":{"fields":'
      b'[{"field":"security_code"},{"field":"security_code"}]}}}'), "R11-9"),
    (("PUT", "/api/v1/imports/{batch_id}/options", {}, 400, _ve("parser_id")), "R11-10"),
    (("POST", "/api/v1/trades", {}, 400, _ve("qty")), None),
    (("POST", "/api/v1/trades", {}, 400, _ve("price")), None),
    (("POST", "/api/v1/trades", {}, 400, _ve("security_code", "qty")), None),
    (("POST", "/api/v1/trades", {}, 400, _ve()), None),
    (("POST", "/api/v1/trades", {}, 400, {"error": {"code": "VALIDATION_ERROR"}}), None),
    (("POST", "/api/v1/trades", {}, 400, _ve("parser_id")), None),
    (("POST", "/api/v1/trades", {}, 422, _ve("security_code")), None),
    (("POST", "/api/v1/trades", {}, 400, {"error": {"code": "INVALID_SECURITY", "details": {"fields": [
        {"field": "security_code"}]}}}), None),
    (("PUT", "/api/v1/trades", {}, 400, _ve("security_code")), None),
    (("PUT", "/api/v1/imports/{batch_id}/options", {}, 400, _ve("encoding_override")), None),
    (("PUT", "/api/v1/imports/{batch_id}/options", {}, 400, _ve("parser_id", "encoding_override")), None),
    (("PUT", "/api/v1/imports/{batch_id}/options", {}, 400, _ve("security_code")), None),
    (("POST", "/api/v1/imports/{batch_id}/options", {}, 400, _ve("parser_id")), None),
    (("PUT", "/api/v1/imports/7/options", {}, 400, _ve("parser_id")), None),
    (("PUT", "/api/v1/imports/{batch_id}/options", {}, 400, {"error": {"code": "VALIDATION_ERROR", "details": {
        "fields": "parser_id"}}}), None),
], ids=["r1", "r5_bytes", "r8", "wrong_code", "no_cursor", "no_query", "wrong_status", "wrong_method", "other_path",
        "concrete_path_not_template", "r8_wrong_code", "r8_wrong_status", "r8_wrong_method", "r8_not_json",
        "r8_no_envelope",
        "r9", "r9_bytes_repeat", "r10", "r9_qty", "r9_price", "r9_mixed", "r9_empty_fields", "r9_no_details",
        "r9_other_rulings_field", "r9_422", "r9_other_code", "r9_wrong_method", "r10_encoding_override",
        "r10_mixed", "r10_wrong_field", "r10_wrong_method", "r10_concrete_path", "r10_fields_not_list"])
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


@pytest.mark.parametrize("path,method,ruling", [
    ("/api/v1/trades", "POST", "R11-9"), ("/api/v1/imports/{batch_id}/options", "PUT", "R11-10"),
])
def test_field_400_is_st202_without_and_passes_with_exception(path: str, method: str, ruling: str) -> None:
    """T-T25 裁定 #1：第 9/10 项“格式合法但业务校验失败 → 400 VALIDATION_ERROR + 登记 field”放行。"""
    op = _schema()[path][method]
    for case in _cases(op):
        exc = _validate(case, use_r11=False)
        assert exc is not None and _st202(exc), "对照：不加例外时必须报 ST202（证明例外必要）"
        assert r11.match_case(case, case.call()).ruling == ruling
        assert _validate(case, use_r11=True) is None


@pytest.mark.parametrize("kw,path,method", [
    ({"trade_fields": ("qty",)}, "/api/v1/trades", "POST"),
    ({"trade_fields": ("price",)}, "/api/v1/trades", "POST"),
    ({"trade_fields": ("security_code", "qty")}, "/api/v1/trades", "POST"),
    ({"trade_fields": ()}, "/api/v1/trades", "POST"),
    ({}, "/api/v1/other-trades", "POST"),
    ({"options_fields": ("encoding_override",)}, "/api/v1/imports/{batch_id}/options", "PUT"),
    ({"options_fields": ("parser_id", "encoding_override")}, "/api/v1/imports/{batch_id}/options", "PUT"),
], ids=["r9_qty", "r9_price", "r9_mixed", "r9_no_fields", "r9_other_path", "r10_encoding_override", "r10_mixed"])
def test_field_exception_does_not_cover_other_400(kw: dict[str, Any], path: str, method: str) -> None:
    """裁定 #1：qty/price/encoding_override 的格式错误不是例外（后端收紧 schema 前照常失败）；同接口其他 400 仍报 ST202。"""
    op = _schema(**kw)[path][method]
    for case in _cases(op):
        exc = _validate(case, use_r11=True)
        assert exc is not None and _st202(exc)


# ------------------------------ schemathesis.toml 与登记表一致（T-T25 裁定 #2，只读） ------------------------------
_REPO = Path(__file__).resolve().parents[3]


def _toml_path() -> Path:
    base = os.environ.get("AIA_BACKEND_DIR")
    return (Path(base) if base else _REPO / "src" / "backend") / "schemathesis.toml"


def _as_list(v: Any) -> list[Any]:
    return [] if v is None else list(v) if isinstance(v, (list, tuple)) else [v]


def toml_entries(doc: dict[str, Any]) -> list[tuple[str | None, str, str, dict[str, Any]]]:
    """``[[operations]]`` → [(method|None, path, check, 检查配置)]。只认 include-path + include-method；
    其他筛选方式（include-path-regex / include-operation-id / include-tag …）登记表无法对应，按“未登记”报出。"""
    out: list[tuple[str | None, str, str, dict[str, Any]]] = []
    for op in doc.get("operations", []):
        paths = _as_list(op.get("include-path"))
        methods = _as_list(op.get("include-method")) or [None]
        other = sorted(k for k in op if k.startswith(("include-", "exclude-"))
                       and k not in ("include-path", "include-method"))
        checks = op.get("checks", {})
        if other or not paths or not checks:
            out.append((None, f"<不支持的筛选 {other or '无 include-path'}>", "<?>", dict(op)))
            continue
        for p in paths:
            for m in methods:
                for name, cfg in checks.items():
                    out.append((m.upper() if m else None, p, name, cfg if isinstance(cfg, dict) else {"value": cfg}))
    return out


def unregistered(entries: list[tuple[str | None, str, str, dict[str, Any]]]) -> list[tuple[Any, ...]]:
    known = {(e.method, e.path, e.check) for e in r11.EXCEPTIONS}
    contract = {(c.method, c.path, c.check): c for c in r11.TOML_CONTRACT_EXCEPTIONS}
    bad: list[tuple[Any, ...]] = []
    for method, path, check, cfg in entries:
        keys = {k for (m, p, c) in known | set(contract) if p == path and c == check and (method is None or m == method)
                for k in [(m, p, c)]}
        if not keys:
            bad.append((method, path, check))
            continue
        for k in keys & set(contract):
            extra = {s for s in _as_list(cfg.get("expected-statuses")) if s not in {"2XX", "3XX", "4XX"}}
            if not extra <= set(contract[k].extra_statuses):
                bad.append((method, path, check, sorted(extra)))
    return bad


def test_toml_checker_self_test() -> None:
    """一致性检查器自身：登记过的放行通过；未登记路径、未登记检查、多放的状态码、不支持的筛选方式都被报出。"""
    ok = {"operations": [
        {"include-path": "/api/v1/auth/register",
         "checks": {"not_a_server_error": {"expected-statuses": ["2XX", "3XX", "4XX", "503"]}}},
        {"include-path": "/api/v1/trades", "include-method": "POST",
         "checks": {"positive_data_acceptance": {"enabled": False}}},
    ]}
    assert unregistered(toml_entries(ok)) == []
    bad = {"operations": [
        {"include-path": "/api/v1/alerts", "checks": {"positive_data_acceptance": {"enabled": False}}},
        {"include-path": "/api/v1/trades", "include-method": "POST",
         "checks": {"response_schema_conformance": {"enabled": False}}},
        {"include-path": "/api/v1/trades", "include-method": "GET",
         "checks": {"positive_data_acceptance": {"enabled": False}}},
        {"include-path": "/api/v1/auth/register",
         "checks": {"not_a_server_error": {"expected-statuses": ["500", "503"]}}},
        {"include-path-regex": ".*", "checks": {"positive_data_acceptance": {"enabled": False}}},
    ]}
    got = unregistered(toml_entries(bad))
    assert len(got) == 4, got  # GET /trades 命中 R11-5（cursor），不算未登记
    assert ("GET", "/api/v1/trades", "positive_data_acceptance") not in got


def test_schemathesis_toml_entries_are_registered() -> None:
    """只读：``src/backend/schemathesis.toml``（后端维护，CI 在 src/backend 下读取）里的每条例外都能在
    r11_exceptions.py（例外唯一清单，测试员维护）中找到。反方向（登记表有、toml 没有）不判失败：toml 只能按
    接口整体关检查，不能按错误码 + field 限定，是否写进 toml 由后端决定。"""
    p = _toml_path()
    if not p.is_file():
        pytest.skip(f"{p} 不存在（tests-only 检出）")
    doc = tomllib.loads(p.read_text(encoding="utf-8"))
    assert unregistered(toml_entries(doc)) == [], "schemathesis.toml 有登记表外的例外——先登记到 r11_exceptions.py"


def test_exception_keeps_other_checks() -> None:
    """命中例外只排除 positive_data_acceptance：错误响应体违约仍被 response_schema_conformance 发现。"""
    op = _schema(bad_body=True)["/api/v1/accounts"]["GET"]
    for case in _cases(op, query={"cursor": "zz"}):
        resp = case.call()
        assert r11.match_case(case, resp) is None  # 没有错误外壳 → 不命中
        exc = _validate(case, use_r11=True)
        assert exc is not None and not all(type(e).__name__ == "RejectedPositiveData" for e in exc.exceptions)
