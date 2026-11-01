"""日志：每条记录带 ``request_id``（来自上下文，非请求内为 ``-``）。

不记录查询串、请求体与任何密钥；数据库 URL 等以 ``SecretStr`` 保存，不会被格式化输出。
"""

from __future__ import annotations

import logging
import sys
from typing import Final

from app.common.request_id import get_request_id

LOG_FORMAT: Final = "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s"


class RequestIdFilter(logging.Filter):
    """给每条日志注入 ``record.request_id``。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = get_request_id() or "-"
        return True


def configure_logging(level: str = "INFO") -> None:
    """配置根日志与 uvicorn 日志（幂等：重复调用不会重复添加 handler）。"""
    root = logging.getLogger()
    root.setLevel(level)
    marker = "_aia_handler"
    if not any(getattr(h, marker, False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        handler.addFilter(RequestIdFilter())
        setattr(handler, marker, True)
        root.addHandler(handler)
    # uvicorn 自带的 access 日志不含 request_id，由 RequestIdMiddleware 输出访问日志替代
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
