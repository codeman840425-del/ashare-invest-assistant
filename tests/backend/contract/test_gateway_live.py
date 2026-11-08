"""网关/后端运行时契约（T-T01c，对应 T-O01b 与契约 v0.2.3；只读或被拒的请求，不产生写入）。

对 ``AIA_CONTRACT_BASE_URL``（默认 nginx 8080，也可指向直连后端）检查：
- 健康检查 ``/api/v1/health/live``（运维 compose 中 api 等服务的 healthcheck 端点）；网关自身 ``/healthz``；
- ``X-Request-Id``：客户端传入的合法值原样透传到响应头与错误信封 ``error.request_id``；非法值/缺失时生成
  ``req_`` + 32 位十六进制，且响应头与 ``error.request_id`` 一致（契约 §1、§2，nginx 与后端 _SAFE_ID 同规则）；
- 405：``DELETE /api/v1/health`` → ``METHOD_NOT_ALLOWED`` + ``Allow`` 头 + ``details.allowed``；``/admin/*`` 用错方法 → 404 且无 ``Allow``；
- 413：请求体超过网关上限 → ``PAYLOAD_TOO_LARGE`` JSON 信封，``request_id`` 与响应头一致（只对网关有意义：
  直连后端时 skip；是否为网关看 ``AIA_CONTRACT_GATEWAY``=1/0，未设时看响应头 ``Server`` 是否为 nginx）。
服务不可达时整体 skip。
"""

from __future__ import annotations

import http.client
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import pytest

pytestmark = pytest.mark.contract

BASE_URL = os.environ.get("AIA_CONTRACT_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
API = "/api/v1"
GENERATED = re.compile(r"^req_[0-9a-f]{32}$")
GATEWAY_MAX_BYTES = 26 * 1024 * 1024  # deploy/nginx/nginx.conf client_max_body_size 26m（= details.max_bytes）


def _req(method: str, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    r = urllib.request.Request(BASE_URL + path, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:  # noqa: S310 - 本地/CI 地址
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


@pytest.fixture(scope="module", autouse=True)
def _reachable() -> None:
    try:
        _req("GET", f"{API}/health/live")
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"服务不可达，跳过网关 live 用例：{BASE_URL}（{type(exc).__name__}）")


@pytest.fixture(scope="module")
def is_gateway() -> bool:
    flag = os.environ.get("AIA_CONTRACT_GATEWAY")
    if flag in ("0", "1"):
        return flag == "1"
    _, h, _ = _req("GET", f"{API}/health/live")
    return h.get("server", "").lower().startswith("nginx")


def _envelope(body: bytes) -> dict:
    data = json.loads(body)
    assert set(data) == {"error"}, data
    return data["error"]


def test_health_live():
    status, _, _ = _req("GET", f"{API}/health/live")
    assert status == 200


def test_gateway_healthz(is_gateway):
    """nginx 自身探针 /healthz（compose nginx healthcheck）；直连后端不适用。"""
    if not is_gateway:
        pytest.skip("/healthz 由 nginx 自答；直连后端不适用")
    status, _, body = _req("GET", "/healthz")
    assert status == 200 and body.strip() == b"ok"


def test_client_request_id_preserved_on_success():
    rid = "t-t01c.rid:0001"
    status, h, _ = _req("GET", f"{API}/meta/enums", {"X-Request-Id": rid})
    assert status == 200 and h.get("x-request-id") == rid


def test_client_request_id_preserved_in_error_envelope():
    rid = "t-t01c-err-0002"
    status, h, body = _req("GET", f"{API}/__no_such_path__", {"X-Request-Id": rid})
    assert status == 404 and h.get("x-request-id") == rid
    err = _envelope(body)
    assert err["code"] == "NOT_FOUND" and err["request_id"] == rid


@pytest.mark.parametrize("bad", ["has space", "x" * 129, "a/b"], ids=["space", "too-long", "slash"])
def test_invalid_client_request_id_replaced(bad):
    status, h, body = _req("GET", f"{API}/__no_such_path__", {"X-Request-Id": bad})
    assert status == 404
    rid = h.get("x-request-id", "")
    assert GENERATED.match(rid) and _envelope(body)["request_id"] == rid


def test_missing_request_id_generated_and_matches_envelope():
    status, h, body = _req("GET", f"{API}/__no_such_path__")
    assert status == 404
    rid = h.get("x-request-id", "")
    assert GENERATED.match(rid) and _envelope(body)["request_id"] == rid


def test_405_has_allow_header_and_envelope():
    rid = "t-t01c-405"
    status, h, body = _req("DELETE", f"{API}/health", {"X-Request-Id": rid})
    assert status == 405
    allow = {m.strip() for m in h.get("allow", "").split(",") if m.strip()}
    assert "GET" in allow
    err = _envelope(body)
    assert err["code"] == "METHOD_NOT_ALLOWED" and err["request_id"] == rid == h.get("x-request-id")
    assert set(err["details"]["allowed"]) == allow


def test_admin_wrong_method_is_404_without_allow():
    status, h, body = _req("DELETE", f"{API}/admin/users")
    assert status == 404 and "allow" not in h
    assert _envelope(body)["code"] == "NOT_FOUND"


@pytest.mark.parametrize("client_rid", [None, "t-t01c-413"])
def test_413_payload_too_large_json_envelope(is_gateway, client_rid):
    if not is_gateway:
        pytest.skip("413 PAYLOAD_TOO_LARGE 由网关（nginx client_max_body_size）产生；直连后端不适用")
    u = urllib.parse.urlsplit(BASE_URL)
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=10)
    try:
        # 只发请求头：nginx 按 Content-Length 立即拒绝，不必真的上传 26 MB
        conn.putrequest("POST", f"{API}/imports")
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Content-Length", str(GATEWAY_MAX_BYTES + 1))
        if client_rid:
            conn.putheader("X-Request-Id", client_rid)
        conn.endheaders()
        resp = conn.getresponse()
        status, h, body = resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
    finally:
        conn.close()
    assert status == 413
    assert h.get("content-type", "").startswith("application/json")
    rid = h.get("x-request-id", "")
    assert rid == client_rid if client_rid else GENERATED.match(rid)
    err = _envelope(body)
    assert err["code"] == "PAYLOAD_TOO_LARGE" and err["request_id"] == rid
    assert err.get("details", {}).get("max_bytes", GATEWAY_MAX_BYTES) == GATEWAY_MAX_BYTES
