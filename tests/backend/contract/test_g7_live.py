"""G-7 live 复测（T-live-83a031c §8.4，/workspace/team/reports/G-7.md；契约 §7.5/§7.6 v0.2.9 #27 ⑦，T-B46 裁定）。

用户 B 以 ``?account_id=<他人账户>`` 调 ``GET /api/v1/imports`` 与 ``GET /api/v1/trades`` → ``404 NOT_FOUND``
（不是 200 + 空列表），错误体与 ``GET /api/v1/portfolio?account_id=<他人账户>`` 的 404 同形。

**默认 skip**：只有显式设置下列环境变量时才对部署发请求（只读 GET + 一次登录；不注册、不写数据）：

- ``AIA_LIVE_G7=1``：开关；
- ``AIA_CONTRACT_BASE_URL``：网关根地址（默认 ``http://127.0.0.1:8080``）；
- ``AIA_LIVE_G7_USERNAME`` / ``AIA_LIVE_G7_PASSWORD``：用户 B 的测试账号（只从环境读取，不打印、不写报告）；
- ``AIA_LIVE_G7_FOREIGN_ACCOUNT_ID``：另一个测试用户 A 名下的账户 id。

后端修复 ab84776 在本地 main、未推 origin、未部署，故 xfail(strict=False)，owner 后端（G-7）。
不对 aia-t01 运行（运维迁移中）；不调用任何行情接口。
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

import pytest

pytestmark = [pytest.mark.contract]

BASE_URL = os.environ.get("AIA_CONTRACT_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
O_G7 = "后端 G-7（ab84776：list_imports / list_trades 带 account_id 时先 owned_account；在本地 main，未推 origin、未部署）"
ENV = ("AIA_LIVE_G7_USERNAME", "AIA_LIVE_G7_PASSWORD", "AIA_LIVE_G7_FOREIGN_ACCOUNT_ID")


class _Client:
    def __init__(self) -> None:
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def req(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        data = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "application/json", "Origin": BASE_URL}
        if data is not None:
            headers["Content-Type"] = "application/json"
        r = urllib.request.Request(BASE_URL + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(r, timeout=10) as resp:  # noqa: S310 - 显式开关下的测试部署地址
                st, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            st, raw = e.code, e.read()
        try:
            return st, json.loads(raw or b"{}")
        except ValueError:
            return st, {}


@pytest.fixture(scope="module")
def g7() -> tuple[_Client, str]:
    if os.environ.get("AIA_LIVE_G7") != "1":
        pytest.skip("G-7 live 默认 skip：设置 AIA_LIVE_G7=1 及 AIA_LIVE_G7_* 后对测试部署复测")
    missing = [k for k in ENV if not os.environ.get(k)]
    if missing:
        pytest.skip(f"G-7 live 缺少环境变量 {missing}")
    c = _Client()
    try:
        st, _ = c.req("POST", "/api/v1/auth/login", {"username": os.environ[ENV[0]], "password": os.environ[ENV[1]]})
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"服务不可达：{BASE_URL}（{type(exc).__name__}）")
    if st != 200:
        pytest.skip(f"测试账号登录失败（HTTP {st}），不复测")
    return c, os.environ[ENV[2]]


def _q(path: str, account_id: str) -> str:
    return f"{path}?{urllib.parse.urlencode({'account_id': account_id})}"


@pytest.mark.xfail(strict=False, reason=O_G7)
@pytest.mark.parametrize("path", ["/api/v1/imports", "/api/v1/trades"])
@pytest.mark.parametrize("which", ["foreign", "nonexistent"])
def test_g7_list_with_unowned_account_id_is_404(g7: tuple[_Client, str], path: str, which: str) -> None:
    c, foreign = g7
    aid = foreign if which == "foreign" else str(uuid.uuid4())
    ref_st, ref = c.req("GET", _q("/api/v1/portfolio", foreign))
    st, body = c.req("GET", _q(path, aid))
    assert st == 404, f"{path} account_id={which} → {st}（契约要求 404，不得 200 + 空列表）"
    assert body.get("error", {}).get("code") == "NOT_FOUND"
    assert "items" not in body
    if ref_st == 404:
        assert set(body["error"]) == set(ref.get("error", {})), "错误体须与 /portfolio 的 404 同形"
