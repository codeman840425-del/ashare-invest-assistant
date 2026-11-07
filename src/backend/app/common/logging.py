"""日志：每条记录带 ``request_id``（来自上下文，非请求内为 ``-``）。

不记录查询串、请求体与任何密钥；数据库 URL 等以 ``SecretStr`` 保存，不会被格式化输出。

兜底脱敏（评审 bbf58a0 m5，:class:`RedactFilter`）：输出前把消息（含参数）与异常文本中
独立的 6 位以上数字串、股东代码样式（字母 + 9 位数字、``0`` + 9 位数字）替换为 ``***``。
UUID 整体保留（批次号等需要可追查）。证券代码（6 位）也会被替换，这是有意的保守取舍。
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Final

from app.common.request_id import get_request_id

LOG_FORMAT: Final = "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s"

REDACTED: Final = "***"
_UUID: Final = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
)
_SENSITIVE: Final = re.compile(r"(?<![0-9A-Za-z])(?:[A-Za-z]\d{9}|\d{6,})(?![0-9A-Za-z])")


def redact(text: str) -> str:
    """把 UUID 以外的片段中的长数字串与股东代码样式替换为 ``***``。"""
    out: list[str] = []
    pos = 0
    for m in _UUID.finditer(text):
        out.append(_SENSITIVE.sub(REDACTED, text[pos : m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_SENSITIVE.sub(REDACTED, text[pos:]))
    return "".join(out)


class RedactFilter(logging.Filter):
    """输出前脱敏：消息先按参数格式化再脱敏（之后 ``args`` 置空）；异常文本预先格式化并脱敏。"""

    _fmt: Final = logging.Formatter()

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001  格式化失败：保留原样交给 logging 自己报错
            return True
        record.msg = redact(msg)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = self._fmt.formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


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
        handler.addFilter(RedactFilter())
        setattr(handler, marker, True)
        root.addHandler(handler)
    # uvicorn 自带的 access 日志不含 request_id，由 RequestIdMiddleware 输出访问日志替代
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
