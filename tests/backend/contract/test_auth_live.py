"""认证接口 live 冒烟（T-T01d；契约 v0.2.4 §1.3/§3 auth；只发未登录、被拒绝的请求，不登录、不注册、不产生写入）。

完整的注册/登录/会话/CSRF/改密/me 行为由 ``tests/backend/api_app/test_auth_t_b03.py`` 在一次性 PG+Redis 上覆盖；
这里只确认网关（默认 nginx 8080，``AIA_CONTRACT_BASE_URL`` 可改）后的真实应用：
- ``/meta/registration`` 只返回 ``{mode}``（v0.2.4），mode ∈ {open, invite, closed}；
- 未登录访问 ``/me`` 与未登录的非安全请求 → ``401 AUTH_REQUIRED``（不是 403 CSRF_FAILED），错误信封带 request_id；
- 伪造的 sid Cookie 同样 401，响应不回显 Cookie 值。
不发失败登录：避免在共享库写审计/触发锁定。服务不可达时整体 skip。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

import pytest

pytestmark = pytest.mark.contract

BASE_URL = os.environ.get("AIA_CONTRACT_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
API = "/api/v1"
RID = re.compile(r"^req_[0-9a-f]{32}$")


def _req(method: str, path: str, headers: dict[str, str] | None = None, body: bytes | None = None) -> tuple[int, dict[str, str], bytes]:
    r = urllib.request.Request(BASE_URL + path, method=method, headers=headers or {}, data=body)
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:  # noqa: S310 - 本地/CI 地址
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


@pytest.fixture(scope="module", autouse=True)
def _reachable() -> None:
    try:
        st, _, _ = _req("GET", f"{API}/meta/registration")
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"服务不可达，跳过认证 live 用例：{BASE_URL}（{type(exc).__name__}）")
    if st == 404:
        pytest.skip("目标服务没有认证路由（T-B03 未部署）")


def _assert_err(st: int, h: dict[str, str], body: bytes, status: int, code: str) -> dict:
    assert st == status, (st, body[:300])
    err = json.loads(body)["error"]
    assert err["code"] == code
    assert RID.match(err["request_id"]) and h.get("x-request-id") == err["request_id"]
    return err


def test_meta_registration_mode_only() -> None:
    st, _, body = _req("GET", f"{API}/meta/registration")
    assert st == 200
    data = json.loads(body)
    assert set(data) == {"mode"} and data["mode"] in {"open", "invite", "closed"}


def test_me_without_session_is_401() -> None:
    _assert_err(*_req("GET", f"{API}/me"), 401, "AUTH_REQUIRED")


@pytest.mark.parametrize("method,path", [("POST", "/auth/logout"), ("POST", "/auth/password")])
def test_unsafe_without_session_is_401_not_csrf(method: str, path: str) -> None:
    _assert_err(*_req(method, API + path, {"Content-Type": "application/json"}, b"{}"), 401, "AUTH_REQUIRED")


def test_forged_sid_is_401_and_not_echoed() -> None:
    forged = "tt01d-forged-" + "0" * 32
    st, h, body = _req("GET", f"{API}/me", {"Cookie": f"sid={forged}"})
    _assert_err(st, h, body, 401, "AUTH_REQUIRED")
    assert forged.encode() not in body and forged not in json.dumps(h)
