"""全局 pytest 配置（T-T01）。

- 路径常量：REPO_ROOT / TESTS_DIR / FIXTURES_DIR。
- 麦蕊防护：测试进程内任何对麦蕊域名的 DNS 解析都会直接失败（plan §8.0：CI 永不访问真实麦蕊）。
  这是兜底；业务代码在测试中应走 MAIRUI_MODE=replay 读 tests/fixtures/mairui/。
- 环境变量：强制 MAIRUI_MODE=replay、MAIRUI_LICENCE 为空，防止开发者 shell 中的真实值被读到。
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
FIXTURES_DIR = TESTS_DIR / "fixtures"

# 麦蕊相关域名（含子域）。只做拦截，不包含任何凭据。
BLOCKED_HOST_SUFFIXES = ("mairuiapi.com", "mairui.com")


class MairuiNetworkBlocked(RuntimeError):
    """测试中试图解析/连接麦蕊域名。"""


def _is_blocked(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    if not isinstance(host, str):
        return False
    h = host.lower().rstrip(".")
    return any(h == s or h.endswith("." + s) for s in BLOCKED_HOST_SUFFIXES)


_real_getaddrinfo = socket.getaddrinfo


def _guarded_getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
    if _is_blocked(host):
        raise MairuiNetworkBlocked(f"测试中禁止访问麦蕊：{host}")
    return _real_getaddrinfo(host, *args, **kwargs)


# 在收集阶段之前就生效（模块导入时），覆盖整个测试进程。
socket.getaddrinfo = _guarded_getaddrinfo
os.environ["MAIRUI_MODE"] = "replay"
os.environ["MAIRUI_LICENCE"] = ""


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


# hypothesis 示例库放在 tests/.hypothesis（已 .gitignore），不污染仓库根目录
try:
    from hypothesis import settings as _hyp_settings

    _hyp_settings.register_profile("aia", derandomize=True, database=None)
    _hyp_settings.load_profile("aia")
except ImportError:  # pragma: no cover
    pass
