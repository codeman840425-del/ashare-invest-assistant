"""裁定 R11（/workspace/team/reports/T-B46-47-rulings.md）：带登录态 schemathesis 的 ST202 有限例外。

ST202 = ``RejectedPositiveData``，来自 ``positive_data_acceptance`` 检查：schemathesis 按 schema 生成的“合法”请求被
服务端拒绝。R11 的处理原则：schema 能表达的约束由后端收紧 schema；schema **无法表达**的业务校验由测试员加有限例外，
例外**必须写明错误码，不得按端点整体放行**。

本模块登记测试员负责的 7 项（第 1、3、4、5、8 项；T-T25 裁定（docs 46538a6，契约 #32，reports/T-T25-rulings.md 二.1）
追加第 9、10 项）。每一项同时限定：

- 方法 + 路径模板（OpenAPI 路径，含 ``/api/v1`` 前缀）；
- 响应状态码 + 错误外壳里的 ``error.code``；
- 第 1/3/4/5 项还要求请求确实带了 ``cursor`` 查询参数（游标不透明，有效性 schema 无法表达，契约 §1.2）；
- 第 9/10 项还要求 ``error.details.fields`` 非空且**每一项**的 ``field`` 都是登记的字段（只放行一个错误码 + field；
  同一响应里另有 qty / price / encoding_override 等字段的格式错误 → 不放行，由后端收紧 schema 解决）；
- 只排除 ``positive_data_acceptance`` 这一项检查——响应体仍按 OpenAPI 校验（status_code_conformance、
  response_schema_conformance、not_a_server_error 等照常执行）。

任一条件不满足（换错误码、换方法、换路径、不带 cursor、换状态码）→ 不放行，照常报 ST202。

不在本模块的 R11 项（谁做见裁定表）：#2 horizon pattern、#6 data-licence nullable、#7 snapshot_as_of 空串、
#9 的 qty/price/security_code pattern、#10 encoding_override 内联取值、#11 licence 长度、#12 max_single_position_pct
—— 后端 T-B46-x / T-B47-x 收紧 schema。

T-T25 裁定 #2：CI 用的 ``src/backend/schemathesis.toml`` 归后端维护；**例外的唯一清单是本模块**（测试员维护）。
toml 中的每条例外都必须能在本模块找到（``EXCEPTIONS`` 或 ``TOML_CONTRACT_EXCEPTIONS``），由
``test_r11_exceptions.py::test_schemathesis_toml_entries_are_registered`` 只读核对。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from schemathesis.specs.openapi.checks import positive_data_acceptance

API = "/api/v1"
#: 例外只排除这一项检查（ST202 的来源）
CHECK = positive_data_acceptance
CHECK_NAME = "positive_data_acceptance"


@dataclass(frozen=True)
class R11Exception:
    ruling: str
    method: str
    path: str
    status: int
    error_code: str
    #: 非 None 时，请求的查询参数里必须有它，例外才生效
    query_param: str | None
    check: str = CHECK_NAME
    #: 非 None 时，错误外壳 ``error.details.fields`` 必须非空且每项 ``field`` 都等于它，例外才生效
    field: str | None = None


EXCEPTIONS: tuple[R11Exception, ...] = (
    # R11 第 1 项：GET /accounts，cursor 任意串 → 400 INVALID_CURSOR（游标不透明，契约 §1.2 新增条目）
    R11Exception("R11-1", "GET", f"{API}/accounts", 400, "INVALID_CURSOR", "cursor"),
    # R11 第 3 项：GET /imports，同第 1 项
    R11Exception("R11-3", "GET", f"{API}/imports", 400, "INVALID_CURSOR", "cursor"),
    # R11 第 4 项：GET /imports/{batch_id}/rows，同第 1 项
    R11Exception("R11-4", "GET", f"{API}/imports/{{batch_id}}/rows", 400, "INVALID_CURSOR", "cursor"),
    # R11 第 5 项：GET /trades，同第 1 项
    R11Exception("R11-5", "GET", f"{API}/trades", 400, "INVALID_CURSOR", "cursor"),
    # R11 第 8 项：POST /imports，内容不是支持的表格 → 422 IMPORT_UNSUPPORTED_FILE_TYPE（文件类型 schema 无法表达；
    # 仅限该错误码，其它 422/400 照常报）
    R11Exception("R11-8", "POST", f"{API}/imports", 422, "IMPORT_UNSUPPORTED_FILE_TYPE", None),
    # R11 第 9 项（T-T25 裁定 #1）：POST /trades，security_code 格式合法但推断不出市场 → 400 VALIDATION_ERROR，
    # field=security_code（市场推断 schema 无法表达）；qty/price/security_code 的格式错误不是例外
    R11Exception("R11-9", "POST", f"{API}/trades", 400, "VALIDATION_ERROR", None, field="security_code"),
    # R11 第 10 项（T-T25 裁定 #1）：PUT /imports/{batch_id}/options，解析器与批次 kind 不符 → 400 VALIDATION_ERROR，
    # field=parser_id（与批次状态相关，schema 无法表达）；encoding_override 取值错误不是例外
    R11Exception("R11-10", "PUT", f"{API}/imports/{{batch_id}}/options", 400, "VALIDATION_ERROR", None,
                 field="parser_id"),
)


@dataclass(frozen=True)
class TomlContractException:
    """不是 R11 例外、但 ``schemathesis.toml`` 里已有的契约级放行（T-T25 裁定 #2：toml 每条都须在本模块登记）。"""

    basis: str
    method: str
    path: str
    check: str
    #: 该检查额外接受的状态码（toml ``expected-statuses`` 中 2XX/3XX/4XX 之外的部分）
    extra_statuses: tuple[str, ...] = ()


TOML_CONTRACT_EXCEPTIONS: tuple[TomlContractException, ...] = (
    # 契约 §4 / §7.1：V1 默认 registration_mode=closed，POST /auth/register 一律 503 REGISTRATION_CLOSED
    TomlContractException("契约 §4/§7.1 注册 closed → 503", "POST", f"{API}/auth/register", "not_a_server_error",
                          ("503",)),
)


def error_code(body: Any) -> str | None:
    """契约错误外壳 ``{"error": {"code": ...}}`` 里的错误码；不是该形状时返回 None。"""
    if isinstance(body, (bytes, bytearray)):
        try:
            body = json.loads(body)
        except ValueError:
            return None
    if isinstance(body, Mapping):
        err = body.get("error")
        if isinstance(err, Mapping) and isinstance(err.get("code"), str):
            return str(err["code"])
    return None


def error_fields(body: Any) -> list[Any]:
    """错误外壳 ``error.details.fields[].field``（契约 §1.4）；不是该形状时返回空列表。"""
    if isinstance(body, (bytes, bytearray)):
        try:
            body = json.loads(body)
        except ValueError:
            return []
    err = body.get("error") if isinstance(body, Mapping) else None
    details = err.get("details") if isinstance(err, Mapping) else None
    fields = details.get("fields") if isinstance(details, Mapping) else None
    if not isinstance(fields, list):
        return []
    return [f.get("field") if isinstance(f, Mapping) else None for f in fields]


def match(method: str, path: str, query: Mapping[str, Any] | None, status: int, body: Any) -> R11Exception | None:
    """命中的例外；不命中返回 None。所有条件都必须满足。"""
    code = error_code(body)
    for e in EXCEPTIONS:
        if method.upper() != e.method or path != e.path or status != e.status or code != e.error_code:
            continue
        if e.query_param is not None and e.query_param not in (query or {}):
            continue
        if e.field is not None:
            fields = error_fields(body)
            if not fields or any(f != e.field for f in fields):
                continue
        return e
    return None


def _response_body(response: Any) -> Any:
    for attr in ("content", "body"):
        raw = getattr(response, attr, None)
        if isinstance(raw, (bytes, bytearray)):
            return raw
    try:
        return response.json()
    except Exception:  # noqa: BLE001 - 不是 JSON 即不命中
        return None


def match_case(case: Any, response: Any) -> R11Exception | None:
    """schemathesis ``Case`` + 响应 → 命中的例外。``case.path`` 是 OpenAPI 路径模板（不是代入后的 URL）。"""
    return match(case.method, case.path, case.query, response.status_code, _response_body(response))


def excluded_checks(case: Any, response: Any) -> list[Any]:
    """给 ``case.validate_response(..., excluded_checks=...)`` 用：命中例外时只排除 positive_data_acceptance。"""
    return [CHECK] if match_case(case, response) is not None else []
