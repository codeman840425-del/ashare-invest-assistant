"""schemathesis 契约测试——对真实后端（T-T01 脚手架）。

服务不可达时 skip。地址用 AIA_CONTRACT_BASE_URL / AIA_OPENAPI_PATH 配置（见 conftest.py）。
只读：默认只测 GET，避免对共享环境产生写入；写接口的契约测试等鉴权/CSRF fixture 落地后再开（T-T17）。
"""

from __future__ import annotations

import pytest
import schemathesis

pytestmark = pytest.mark.contract

schema = schemathesis.pytest.from_fixture("live_schema")


@schema.include(method="GET").parametrize()
def test_live_api_conforms_to_openapi(case) -> None:  # type: ignore[no-untyped-def]
    case.call_and_validate()
