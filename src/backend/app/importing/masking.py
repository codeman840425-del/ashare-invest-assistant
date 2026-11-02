"""股东代码、席位代码与原始行掩码（plan §3.5A“隐私与敏感字段”，T-B46）。

- 股东代码：只存 ``HMAC-SHA256(派生密钥, 代码)`` 与掩码（首字符 + ``****``）；明文不入库、
  不进日志、不出现在响应、导出与错误报告中。
- 席位代码、资金账号：丢弃。
- ``raw_masked``：按列位置替换已识别的敏感列，再用正则兜底（``A``+9 位、``0``+9 位）。
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Final

from app.config import Settings
from app.importing.keys import HOLDER_LABEL, derive

MASK: Final = "****"
_HOLDER_FALLBACK: Final = re.compile(r"(?<![0-9A-Za-z])([A-Za-z]\d{9}|0\d{9})(?![0-9A-Za-z])")


def holder_hmac(settings: Settings, code: str) -> str:
    return hmac.new(
        derive(settings, HOLDER_LABEL), code.strip().upper().encode(), hashlib.sha256
    ).hexdigest()


def holder_masked(code: str) -> str:
    code = code.strip()
    return (code[:1].upper() + MASK) if code else MASK


def holder_market(code: str) -> str | None:
    """股东代码样式推断市场：沪 ``A``+9 位数字；深 ``0`` 开头 10 位数字。"""
    code = code.strip().upper()
    if re.fullmatch(r"[A-Z]\d{9}", code):
        return "SH"
    if re.fullmatch(r"0\d{9}", code):
        return "SZ"
    return None


def mask_line(text: str, spans: list[tuple[int, int, str]]) -> str:
    """按 ``(起始下标, 结束下标, 替换值)`` 替换（替换值右侧补空格保持原长），再做正则兜底。"""
    chars = list(text)
    for start, end, repl in sorted(spans, reverse=True):
        width = end - start
        chars[start:end] = list(repl.ljust(width)[: max(width, len(repl))])
    out = "".join(chars)
    return _HOLDER_FALLBACK.sub(lambda m: holder_masked(m.group(1)), out)
