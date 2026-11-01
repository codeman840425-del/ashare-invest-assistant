"""schemathesis 契约测试——对真实后端（T-T01 脚手架）。

服务不可达时 skip。地址用 AIA_CONTRACT_BASE_URL / AIA_OPENAPI_PATH 配置（见 conftest.py）。
只读：默认只测 GET，避免对共享环境产生写入；写接口的契约测试等鉴权/CSRF fixture 落地后再开（T-T17）。

``/health/ready``（及 ``/health``）在 db/redis 不可用时按契约 §7.10 返回 ``503 {status: "down", …}``（已在 OpenAPI 中声明，
非错误外壳），因此这两个路径不做 ``not_a_server_error`` 检查；响应体仍按 OpenAPI 校验（T-T01b）。
"""

from __future__ import annotations

import pytest
import schemathesis
from schemathesis.checks import not_a_server_error

pytestmark = pytest.mark.contract

schema = schemathesis.pytest.from_fixture("live_schema")
HEALTH_503_PATHS = {"/api/v1/health/ready", "/api/v1/health"}


@schema.include(method="GET").parametrize()
def test_live_api_conforms_to_openapi(case) -> None:  # type: ignore[no-untyped-def]
    declared_503 = case.path in HEALTH_503_PATHS and "503" in case.operation.definition.raw.get("responses", {})
    case.call_and_validate(excluded_checks=[not_a_server_error] if declared_503 else None)
