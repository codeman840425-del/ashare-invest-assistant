"""schemathesis 契约测试——可运行示例（T-T01）：对本地 WSGI 桩跑 openapi_v1_stub.json。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

schemathesis = pytest.importorskip("schemathesis", reason="schemathesis 未安装，契约用例 skip（T-T35 收集容错）")
from schemathesis.core.failures import FailureGroup  # noqa: E402
from schemathesis.openapi.checks import JsonSchemaError  # noqa: E402

from mock_app import STUB, make_app

pytestmark = pytest.mark.contract

schema = schemathesis.pytest.from_fixture("stub_schema")


@schema.parametrize()
def test_stub_conforms_to_contract(case) -> None:  # type: ignore[no-untyped-def]
    case.call_and_validate()


def test_contract_checker_catches_violation() -> None:
    """违约桩（/health 返回非枚举 status）必须被 schemathesis 判定失败，证明校验真的生效。"""
    broken = schemathesis.openapi.from_wsgi("/openapi.json", make_app(health_status="bad"))
    op = broken["/health"]["GET"]
    case = op.Case()
    try:
        case.call_and_validate()
    except FailureGroup as exc:  # BaseExceptionGroup 子类，不是 Exception
        assert any(isinstance(e, JsonSchemaError) for e in exc.exceptions), exc
    else:
        pytest.fail("违约响应没有被契约校验发现")


def test_stub_paths_exist_in_api_contract_doc() -> None:
    """契约文档对照（plan §8.0）：桩里的每个路径都必须能在 docs/api-contract.md 中找到。"""
    doc = (Path(__file__).resolve().parents[3] / "docs" / "api-contract.md").read_text(encoding="utf-8")
    assert "`/api/v1`" in doc
    for path in STUB["paths"]:
        assert re.search(r"`" + re.escape(path) + r"`", doc), f"{path} 不在 api-contract.md"
    for code in ("AUTH_REQUIRED", "NOT_FOUND"):
        assert f"`{code}`" in doc
