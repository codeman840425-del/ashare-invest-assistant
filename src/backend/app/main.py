"""FastAPI 入口：``uvicorn app.main:app``（运行目录 ``src/backend``）。"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.v1 import router as v1_router
from app.auth import body_order
from app.common.errors import (
    ErrorResponse,
    UriTooLongResponse,
    Utf8JSONResponse,
    install_exception_handlers,
)
from app.common.logging import configure_logging
from app.common.middleware import (
    BodySizeLimitMiddleware,
    PathCacheControlMiddleware,
    RequestIdMiddleware,
)
from app.config import ConfigError, Settings, get_settings
from app.config_files import BUSINESS_FILES
from app.licences.keys import PRIVATE_KEYS_NAME, private_keys_present
from app.version import APP_VERSION

logger = logging.getLogger("app")

#: 写进 OpenAPI 的统一错误响应（所有路由都可能返回）
_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    "4XX": {"model": ErrorResponse, "description": "统一错误格式（契约 §2）"},
    # T-B49：请求行过长由 nginx 直接返回 414（JSON 信封，形状同 413，code=URI_TOO_LONG）
    414: {"model": UriTooLongResponse, "description": "请求地址过长（nginx 产生，信封同 413）"},
    "5XX": {"model": ErrorResponse, "description": "统一错误格式（契约 §2）"},
}


#: 契约 v0.2.9 #41
SECURITIES_CACHE_CONTROL = "private, no-store"


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
    #: 生效的 Settings（T-B03f / review-f72b8c7 m1：路由类在依赖注入之外读取，不调用 override）
    app.state.settings = cfg
    install_exception_handlers(app)
    # 契约 §1.3 #30：非法 JSON 不得先于认证 / CSRF（覆盖上面的 RequestValidationError 处理器）
    body_order.install(app)
    # add_middleware 后加的在外层：RequestId 在最外，413 也带 X-Request-Id
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=cfg.business.imports.max_request_bytes)
    app.add_middleware(RequestIdMiddleware)
    # 契约 v0.2.9 #41：/securities/* 全部响应（含 304、错误）private, no-store；最外层统一设置
    app.add_middleware(
        PathCacheControlMiddleware,
        prefixes=(f"{cfg.api_prefix}/securities",),
        value=SECURITIES_CACHE_CONTROL,
    )
    app.include_router(v1_router, prefix=cfg.api_prefix)

    logger.info(
        "app created env=%s prefix=%s business_config=%s",
        cfg.app_env,
        cfg.api_prefix or "/",
        list(BUSINESS_FILES),
    )
    return app


app = create_app()
