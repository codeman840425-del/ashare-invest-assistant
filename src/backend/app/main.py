"""FastAPI 入口：``uvicorn app.main:app``（运行目录 ``src/backend``）。"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.v1 import router as v1_router
from app.common.errors import ErrorResponse, install_exception_handlers
from app.common.logging import configure_logging
from app.common.middleware import RequestIdMiddleware
from app.config import Settings, get_settings

logger = logging.getLogger("app")

#: 写进 OpenAPI 的统一错误响应（所有路由都可能返回）
_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    "4XX": {"model": ErrorResponse, "description": "统一错误格式（契约 §2）"},
    "5XX": {"model": ErrorResponse, "description": "统一错误格式（契约 §2）"},
}


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(cfg.log_level)

    app = FastAPI(
        title="ashare-invest-assistant API",
        version="0.1.0",
        openapi_url=f"{cfg.api_prefix}/openapi.json",
        docs_url=f"{cfg.api_prefix}/docs" if cfg.app_env in {"local", "test"} else None,
        redoc_url=None,
        responses=_ERROR_RESPONSES,
    )
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings

    install_exception_handlers(app)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(v1_router, prefix=cfg.api_prefix)

    logger.info(
        "app created env=%s prefix=%s business_config=%s",
        cfg.app_env,
        cfg.api_prefix or "/",
        sorted(cfg.business),
    )
    return app


app = create_app()
