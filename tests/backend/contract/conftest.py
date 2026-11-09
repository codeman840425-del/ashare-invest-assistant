"""契约测试共享配置（T-T01）。

- `AIA_CONTRACT_BASE_URL`：被测服务根地址，默认 `http://127.0.0.1:8080`（nginx，见 deploy/env/.env.example 的 NGINX_HTTP_PORT）。
- `AIA_OPENAPI_PATH`：OpenAPI 文档路径，默认 `/api/v1/openapi.json`（后端落地时按 FastAPI 实际挂载路径调整）。
- 服务不可达或文档不可取时，live 契约用例 skip。
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

try:
    import schemathesis
except ModuleNotFoundError:  # schemathesis 未安装时收集不被打断，用例统一 skip（T-T35）
    schemathesis = None

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mock_app import make_app  # noqa: E402

BASE_URL = os.environ.get("AIA_CONTRACT_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
OPENAPI_PATH = os.environ.get("AIA_OPENAPI_PATH", "/api/v1/openapi.json")


def _require_schemathesis() -> None:
    if schemathesis is None:
        pytest.skip("schemathesis 未安装（pip install schemathesis 后可用；T-T35 收集容错）")




@pytest.fixture(scope="session")
def stub_schema():  # type: ignore[no-untyped-def]
    _require_schemathesis()
    return schemathesis.openapi.from_wsgi("/openapi.json", make_app())


@pytest.fixture(scope="session")
def live_schema():  # type: ignore[no-untyped-def]
    _require_schemathesis()
    url = BASE_URL + OPENAPI_PATH
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310 - 本地/CI 地址，可配置
            if resp.status != 200:
                pytest.skip(f"契约服务未就绪：GET {url} → {resp.status}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        pytest.skip(f"契约服务不可达，跳过 live 契约测试：{url}（{type(exc).__name__}）")
    return schemathesis.openapi.from_url(url)
