"""后端应用（T-B01，src/backend/app）进程内测试的共享 fixture（T-T01a）。

- 后端位置：环境变量 ``AIA_BACKEND_DIR``（默认 ``<repo>/src/backend``）。
- 契约/计划文档位置：``AIA_DOCS_DIR``（默认 ``<repo>/docs``）；只有文档为 v0.2（契约含
  “### v0.2” 变更记录）时才运行与文档逐项比对的用例，否则 skip 并写明原因。
- 不启动服务、不连外网、不连真实数据库：依赖检查一律打桩或指向本机关闭的端口。
- 只读：``sys.dont_write_bytecode = True``，避免在共享工作区（或导出目录）里生成 ``__pycache__``。
- 依赖：``tests/requirements-app.txt``（fastapi / pydantic-settings / httpx 等）；缺失时整组 skip，
  原因写明缺哪个包。
"""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.dont_write_bytecode = True

TESTS_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = TESTS_DIR.parent
BACKEND_DIR = Path(os.environ.get("AIA_BACKEND_DIR", REPO_ROOT / "src" / "backend")).resolve()
DOCS_DIR = Path(os.environ.get("AIA_DOCS_DIR", REPO_ROOT / "docs")).resolve()

#: 与 Settings 字段同名、可能被开发者 shell 带进来的环境变量；每个用例前清空，保证可复现
SETTINGS_ENV_KEYS = (
    "APP_ENV", "SERVICE_NAME", "LOG_LEVEL", "API_PREFIX", "DATABASE_URL", "REDIS_URL",
    "HEALTH_CHECK_TIMEOUT_S", "INGEST_HEARTBEAT_KEY", "INGEST_PAUSED_KEY", "INGEST_STALE_AFTER_S",
    "APP_MASTER_KEY", "PAGE_LIMIT_DEFAULT", "PAGE_LIMIT_MAX", "CURSOR_TTL_S", "CONFIG_DIR", "BUSINESS",
)

#: 本机必定拒绝连接的地址（端口 1）：只用于“依赖不可用”场景，不含任何凭据
DEAD_DB_URL = "postgresql://127.0.0.1:1/aia_test"
DEAD_REDIS_URL = "redis://127.0.0.1:1/0"

#: 测试用主密钥：固定占位串（≥ 32 字符），不是任何环境的真实密钥
TEST_MASTER_KEY = "test-only-master-key-" + "x" * 16


def _backend_import_error() -> str | None:
    if not (BACKEND_DIR / "app" / "main.py").is_file():
        return f"未找到后端 {BACKEND_DIR}/app/main.py（依赖 T-B01；可用 AIA_BACKEND_DIR 指定）"
    for pkg in ("fastapi", "pydantic_settings", "httpx", "yaml", "psycopg", "redis"):
        try:
            importlib.import_module(pkg)
        except ImportError:
            return f"缺少依赖包 {pkg}（uv pip install -r tests/requirements-app.txt）"
    return None


BACKEND_SKIP_REASON = _backend_import_error()


def docs_v02_skip_reason() -> str | None:
    contract = DOCS_DIR / "api-contract.md"
    plan = DOCS_DIR / "plan.md"
    if not contract.is_file() or not plan.is_file():
        return f"未找到契约/计划文档（{DOCS_DIR}）；可用 AIA_DOCS_DIR 指定"
    if "### v0.2" not in contract.read_text(encoding="utf-8"):
        return "契约不是 v0.2（依赖 T-A01 v0.2 文档合入；可用 AIA_DOCS_DIR 指向 v0.2 导出目录）"
    return None


@pytest.fixture(scope="session")
def backend() -> SimpleNamespace:
    """导入后端模块；不可用时 skip（原因含任务号/缺失包）。"""
    if BACKEND_SKIP_REASON:
        pytest.skip(BACKEND_SKIP_REASON)
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    try:
        mods = {
            name.rsplit(".", 1)[-1]: importlib.import_module(name)
            for name in (
                "app.config",
                "app.main",
                "app.common.errors",
                "app.common.pagination",
                "app.common.request_id",
                "app.common.middleware",
                "app.common.logging",
                "app.api.v1.health",
                "app.api.v1.meta",
                "app.schemas.enums",
            )
        }
    except ImportError as exc:  # pragma: no cover - 环境问题
        pytest.skip(f"后端模块导入失败（T-B01）：{type(exc).__name__}: {exc.name}")
    return SimpleNamespace(**mods)


@pytest.fixture(scope="session")
def docs_dir() -> Path:
    reason = docs_v02_skip_reason()
    if reason:
        pytest.skip(reason)
    return DOCS_DIR


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """清空 Settings 相关环境变量，CONFIG_DIR 指向空临时目录；返回该目录。"""
    for key in SETTINGS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setenv("CONFIG_DIR", str(cfg))
    return cfg


@pytest.fixture
def make_settings(backend: SimpleNamespace, clean_env: Path) -> Callable[..., Any]:
    def _make(**overrides: Any) -> Any:
        params: dict[str, Any] = {
            "app_env": "test",
            "database_url": DEAD_DB_URL,
            "redis_url": DEAD_REDIS_URL,
            "app_master_key": TEST_MASTER_KEY,
            "config_dir": clean_env,
        }
        params.update(overrides)
        return backend.config.Settings(**params)

    return _make


@pytest.fixture
def make_client(backend: SimpleNamespace, make_settings: Callable[..., Any]) -> Iterator[Callable[..., Any]]:
    """``make_client(app=None, **settings)`` → starlette TestClient（不抛服务端异常，便于断言 500）。"""
    from fastapi.testclient import TestClient

    clients: list[Any] = []

    def _make(app: Any = None, **overrides: Any) -> Any:
        if app is None:
            app = backend.main.create_app(make_settings(**overrides))
        client = TestClient(app, raise_server_exceptions=False)
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.close()


@pytest.fixture
def stub_health(backend: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """把健康检查的依赖探测替换为固定结果（不连任何服务）。

    兼容 T-B01 现状（``check_db`` + ``check_redis_and_ingest``）与 v0.2 修订后的同名函数；
    v0.2 若改了函数名，本 fixture 会 skip 并提示更新。
    """
    health = backend.health

    def _stub(db: str = "ok", redis: str = "ok", ingest: str = "ok") -> None:
        if not (hasattr(health, "check_db") and hasattr(health, "check_redis_and_ingest")):
            pytest.skip("健康检查探测函数已改名（T-B01 v0.2 修订），请更新 stub_health")

        async def _db(settings: Any) -> str:
            return db

        async def _ri(settings: Any) -> tuple[str, str]:
            return redis, ingest

        monkeypatch.setattr(health, "check_db", _db)
        monkeypatch.setattr(health, "check_redis_and_ingest", _ri)

    return _stub
