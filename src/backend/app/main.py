"""FastAPI 入口：``uvicorn app.main:app``（运行目录 ``src/backend``）。"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.v1 import router as v1_router
from app.common.errors import ErrorResponse, Utf8JSONResponse, install_exception_handlers
from app.common.logging import configure_logging
from app.common.middleware import BodySizeLimitMiddleware, RequestIdMiddleware
from app.config import ConfigError, Settings, get_settings
from app.config_files import BUSINESS_FILES
from app.licences.keys import PRIVATE_KEYS_NAME, private_keys_present
from app.version import APP_VERSION

logger = logging.getLogger("app")

#: 写进 OpenAPI 的统一错误响应（所有路由都可能返回）
_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    "4XX": {"model": ErrorResponse, "description": "统一错误格式（契约 §2）"},
    "5XX": {"model": ErrorResponse, "description": "统一错误格式（契约 §2）"},
}


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(cfg.log_level)
    if private_keys_present():
        # plan §2.1B（T-A07）：证书解密私钥只能注入 ingest；api 进程看到私钥即拒绝启动
        raise ConfigError(f"api 不得持有 {PRIVATE_KEYS_NAME}（只给 ingest）")

    app = FastAPI(
        title="ashare-invest-assistant API",
        version=APP_VERSION,
        openapi_url=f"{cfg.api_prefix}/openapi.json",
        docs_url=f"{cfg.api_prefix}/docs" if cfg.app_env in {"local", "test"} else None,
        redoc_url=None,
        responses=_ERROR_RESPONSES,
        default_response_class=Utf8JSONResponse,
    )
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings

    app.state.api_prefix = cfg.api_prefix
    install_exception_handlers(app)
    # add_middleware 后加的在外层：RequestId 在最外，413 也带 X-Request-Id
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=cfg.business.imports.max_request_bytes)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(v1_router, prefix=cfg.api_prefix)

    logger.info(
        "app created env=%s prefix=%s business_config=%s",
        cfg.app_env,
        cfg.api_prefix or "/",
        list(BUSINESS_FILES),
    )
    return app


app = create_app()
