"""裁定 R11（/workspace/team/reports/T-B46-47-rulings.md）：带登录态 schemathesis 的 ST202 有限例外。

ST202 = ``RejectedPositiveData``，来自 ``positive_data_acceptance`` 检查：schemathesis 按 schema 生成的“合法”请求被
服务端拒绝。R11 的处理原则：schema 能表达的约束由后端收紧 schema；schema **无法表达**的业务校验由测试员加有限例外，
例外**必须写明错误码，不得按端点整体放行**。

本模块只登记测试员负责的 5 项（第 1、3、4、5、8 项）。每一项同时限定：

- 方法 + 路径模板（OpenAPI 路径，含 ``/api/v1`` 前缀）；
- 响应状态码 + 错误外壳里的 ``error.code``；
- 第 1/3/4/5 项还要求请求确实带了 ``cursor`` 查询参数（游标不透明，有效性 schema 无法表达，契约 §1.2）；
- 只排除 ``positive_data_acceptance`` 这一项检查——响应体仍按 OpenAPI 校验（status_code_conformance、
  response_schema_conformance、not_a_server_error 等照常执行）。

任一条件不满足（换错误码、换方法、换路径、不带 cursor、换状态码）→ 不放行，照常报 ST202。

不在本模块的 R11 项（谁做见裁定表）：#2 horizon pattern、#6 data-licence nullable、#7 snapshot_as_of 空串、
#9 decimal/security_code pattern、#10 encoding_override 枚举、#11 licence 长度、#12 max_single_position_pct
—— 后端 T-B46-x / T-B47-x 收紧 schema；#9 的“格式合法但推断不出市场 → 400”与 #10 的 kind_mismatch 也是测试员例外，
但本批未要求，待后端 pattern / enum 落地后再按同样方式登记（见 T-T25.md 待决问题）。

CI 用的 ``src/backend/schemathesis.toml`` 不在测试员可改范围（tests/ only）；本模块供 tests/ 内的 schemathesis
用例使用，toml 的同步由负责人决定（见报告）。
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


def match(method: str, path: str, query: Mapping[str, Any] | None, status: int, body: Any) -> R11Exception | None:
    """命中的例外；不命中返回 None。所有条件都必须满足。"""
    code = error_code(body)
    for e in EXCEPTIONS:
        if method.upper() != e.method or path != e.path or status != e.status or code != e.error_code:
            continue
        if e.query_param is not None and e.query_param not in (query or {}):
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
