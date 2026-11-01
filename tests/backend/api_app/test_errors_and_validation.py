"""T-B01 报告 §6 建议 1、2、4 + 契约 v0.2 的 405（§4、§9）。

- 错误外壳：任意 404/405/400/500 只有 ``error.{code,message,details,request_id}`` 四个键，
  body 的 request_id == 响应头 ``X-Request-Id``。
- 500 不泄露异常信息、堆栈、SQL、DSN。
- 校验错误的 ``details.fields`` 结构（契约 §2 原例）。
- 405：契约 v0.2 新增 ``405 METHOD_NOT_ALLOWED`` + ``Allow`` 头 + ``details.allowed``；
  T-B01 现状映射为 404 且去掉 Allow → 运行时检测后 ``pytest.xfail``（不用静态 xfail，避免修订后 XPASS 报错）。
"""

# 注意：本文件不用 `from __future__ import annotations`——测试路由里的局部 pydantic 模型
# 需要在定义时解析注解，否则 FastAPI 会把 body 参数当成查询参数。

from typing import Any

import pytest

pytestmark = [pytest.mark.unit]

ENVELOPE_KEYS = {"code", "message", "details", "request_id"}
#: 用于检测泄露的标记串（虚构，不是任何真实值）
LEAK_MARKERS = ("LEAK_MARKER_7f3a", "SELECT secret_col FROM t_hidden", "postgresql://", "Traceback")


def assert_envelope(resp: Any, status: int, code: str) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body) == {"error"}
    err = body["error"]
    assert set(err) == ENVELOPE_KEYS
    assert err["code"] == code
    assert isinstance(err["message"], str) and err["message"]
    assert err["details"] is None or isinstance(err["details"], dict)
    assert err["request_id"] == resp.headers["X-Request-Id"]
    assert resp.headers["content-type"].startswith("application/json")
    return err


@pytest.fixture
def test_app(backend, make_settings):
    """真实 create_app + 只用于测试的路由（挂在 API 前缀下）。"""
    from fastapi import APIRouter, Depends
    from pydantic import BaseModel, ConfigDict

    settings = make_settings()
    app = backend.main.create_app(settings)

    class Body(BaseModel):
        model_config = ConfigDict(extra="forbid")
        name: str
        qty: int

    r = APIRouter()

    @r.get("/_test/items")
    def items(p=Depends(backend.pagination.page_params)) -> dict[str, Any]:  # noqa: B008
        return {"limit": p.limit, "cursor": p.cursor}

    @r.post("/_test/body")
    def body(b: Body) -> dict[str, Any]:
        return b.model_dump()

    @r.get("/_test/boom")
    def boom() -> None:
        raise RuntimeError(f"{LEAK_MARKERS[0]} {LEAK_MARKERS[1]} postgresql://h/db")

    @r.get("/_test/app-error")
    def app_error() -> None:
        raise backend.errors.AppError(backend.errors.ErrorCode.VERSION_CONFLICT, details={"current_version_no": 3})

    app.include_router(r, prefix=settings.api_prefix)
    return app


@pytest.fixture
def client(make_client, test_app):
    return make_client(app=test_app)


# ---------------- 1. 错误外壳 ----------------
def test_404_unknown_path(client):
    assert_envelope(client.get("/api/v1/no-such-path"), 404, "NOT_FOUND")


def test_404_outside_prefix(client):
    assert_envelope(client.get("/health"), 404, "NOT_FOUND")


def test_app_error_status_and_details(client):
    err = assert_envelope(client.get("/api/v1/_test/app-error"), 409, "VERSION_CONFLICT")
    assert err["details"] == {"current_version_no": 3}


def test_row_scope_code_cannot_be_raised(backend):
    """scope=row 的码不能作为 HTTP 错误抛出（v0.2 起这些码迁到 import_codes；见 test_meta_enums）。"""
    row_codes = [c for c, s in backend.errors.ERROR_CODES.items() if s.scope == "row"]
    if not row_codes:
        pytest.skip("ERROR_CODES 已无 row 级码（T-B01 v0.2 修订后预期如此）")
    with pytest.raises(ValueError):
        backend.errors.AppError(row_codes[0])


# ---------------- 2. 500 不泄露 ----------------
def test_500_does_not_leak(client, caplog):
    caplog.set_level("ERROR", logger="app.errors")
    resp = client.get("/api/v1/_test/boom", headers={"X-Request-Id": "rid-boom-1"})
    err = assert_envelope(resp, 500, "INTERNAL_ERROR")
    assert err["details"] is None
    assert err["request_id"] == "rid-boom-1"
    for marker in LEAK_MARKERS:
        assert marker not in resp.text
    # 异常只进日志（便于排查），且带 request_id 上下文
    assert any(r.name == "app.errors" and r.exc_info for r in caplog.records)


# ---------------- 4. 校验错误 ----------------
def test_limit_over_max_contract_example(client):
    err = assert_envelope(client.get("/api/v1/_test/items?limit=201"), 400, "VALIDATION_ERROR")
    assert err["details"] == {"fields": [{"field": "limit", "issue": "must be <= 200"}]}


@pytest.mark.parametrize(
    ("query", "issue"),
    [("limit=0", "must be >= 1"), ("limit=-5", "must be >= 1"), ("limit=abc", "must be an integer")],
)
def test_limit_invalid(client, query, issue):
    err = assert_envelope(client.get(f"/api/v1/_test/items?{query}"), 400, "VALIDATION_ERROR")
    assert {"field": "limit", "issue": issue} in err["details"]["fields"]


def test_limit_default_and_max(client):
    assert client.get("/api/v1/_test/items").json() == {"limit": 50, "cursor": None}
    assert client.get("/api/v1/_test/items?limit=200").json()["limit"] == 200
    assert client.get("/api/v1/_test/items?cursor=").json()["cursor"] is None


def test_cursor_too_long(client):
    err = assert_envelope(client.get("/api/v1/_test/items?cursor=" + "a" * 2049), 400, "VALIDATION_ERROR")
    assert err["details"]["fields"][0]["field"] == "cursor"


def test_body_missing_and_extra_fields(client):
    err = assert_envelope(client.post("/api/v1/_test/body", json={"name": "x", "extra": 1}), 400, "VALIDATION_ERROR")
    fields = {(f["field"], f["issue"]) for f in err["details"]["fields"]}
    assert ("qty", "required") in fields
    assert ("extra", "unknown field") in fields


def test_body_not_json(client):
    resp = client.post("/api/v1/_test/body", content=b"{not json", headers={"content-type": "application/json"})
    assert_envelope(resp, 400, "VALIDATION_ERROR")


def test_validation_error_echoes_no_input(client):
    """校验错误只给字段名与问题，不回显输入值（避免把用户输入/敏感值写进响应）。"""
    resp = client.post("/api/v1/_test/body", json={"name": "x", "qty": "LEAK_MARKER_7f3a"})
    assert_envelope(resp, 400, "VALIDATION_ERROR")
    assert "LEAK_MARKER_7f3a" not in resp.text


# ---------------- 405（契约 v0.2 §4 / §9） ----------------
def _xfail_if_405_not_implemented(resp: Any) -> None:
    if resp.status_code == 404:
        pytest.xfail("T-B01 v0.2 修订未完成：405 仍映射为 404 NOT_FOUND 且去掉 Allow（契约 v0.2 §4 METHOD_NOT_ALLOWED）")


def test_405_delete_health(client):
    resp = client.delete("/api/v1/health")
    _xfail_if_405_not_implemented(resp)
    err = assert_envelope(resp, 405, "METHOD_NOT_ALLOWED")
    allow = {m.strip().upper() for m in resp.headers["Allow"].split(",")}
    assert "GET" in allow and "DELETE" not in allow
    assert {m.upper() for m in err["details"]["allowed"]} == allow


def test_405_post_meta_enums(client):
    resp = client.post("/api/v1/meta/enums")
    _xfail_if_405_not_implemented(resp)
    assert_envelope(resp, 405, "METHOD_NOT_ALLOWED")
    assert "GET" in resp.headers["Allow"].upper()


def test_405_code_registered(backend):
    if "METHOD_NOT_ALLOWED" not in backend.errors.ErrorCode.__members__:
        pytest.xfail("T-B01 v0.2 修订未完成：ErrorCode 缺 METHOD_NOT_ALLOWED（契约 v0.2 §4）")
    spec = backend.errors.ERROR_CODES[backend.errors.ErrorCode.METHOD_NOT_ALLOWED]
    assert spec.http_status == 405 and spec.scope == "http"


def test_admin_wrong_method_is_404():
    pytest.skip("非管理员对 /admin/* 用错方法 → 404（契约 v0.2 §9）：依赖鉴权与 /admin 路由（T-B 鉴权任务）")
