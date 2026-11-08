"""确认测试进程内麦蕊域名被拦截（tests/conftest.py），且 licence 环境变量为空。不产生任何网络流量。"""

from __future__ import annotations

import os
import socket
import urllib.request

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("host", ["api.mairuiapi.com", "pro.mairuiapi.com", "MAIRUIAPI.COM."])
def test_mairui_dns_is_blocked(host: str) -> None:
    with pytest.raises(RuntimeError, match="禁止访问麦蕊"):
        socket.getaddrinfo(host, 443)


def test_urllib_to_mairui_fails_before_network() -> None:
    with pytest.raises(Exception) as excinfo:
        urllib.request.urlopen("https://api.mairuiapi.com/hslt/list/placeholder", timeout=1)
    assert "禁止访问麦蕊" in str(excinfo.value)


def test_replay_mode_and_empty_licence() -> None:
    assert os.environ["MAIRUI_MODE"] == "replay"
    assert os.environ["MAIRUI_LICENCE"] == ""
