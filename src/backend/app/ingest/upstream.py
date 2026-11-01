"""麦蕊响应归类（plan §2.1B 第 6 点、§0A 实测：业务错误多为 HTTP 200 + ``{"error": "..."}``，
103 为 HTTP 429 + 纯文本，无限流响应头）。

先看响应体里的 ``error``，再看 HTTP 状态码。返回 :class:`Signal`，由 :mod:`.state` 决定后果。
归类结果不含响应原文（原文可能回显证书，见 :mod:`.vault` 的脱敏）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum


class Signal(StrEnum):
    OK = "ok"
    INVALID = "invalid"  # 102 证书无效
    QUOTA = "quota"  # 101 当日额度用完
    IP_LIMITED = "ip_limited"  # 103 / HTTP 429
    RATE_LIMITED = "rate_limited"  # 频率 503
    DATA_MISSING = "data_missing"  # 数据缺失型 503：不熔断，只记缺失
    NOT_ENTITLED = "not_entitled"  # 403：接口未开通（如因子），不影响证书状态
    SERVER_ERROR = "server_error"  # 其他 5xx
    NETWORK = "network"  # 连接/超时
    CLIENT_ERROR = "client_error"  # 其他 4xx / 无法识别的业务错误：不重试、不改状态


#: 需要按证书退避（并计入连续失败）的信号
BACKOFF_SIGNALS = frozenset({Signal.RATE_LIMITED, Signal.SERVER_ERROR, Signal.NETWORK})

_CODE_RE = re.compile(r"(?<!\d)(10[123])(?!\d)")
_CODE_SIGNAL = {"101": Signal.QUOTA, "102": Signal.INVALID, "103": Signal.IP_LIMITED}
_RATE_HINTS = ("频繁", "频率", "线程", "too many", "rate")


def _error_text(body: object) -> str | None:
    if isinstance(body, Mapping):
        err = body.get("error")
        if err is None:
            return None
        return str(err)
    if isinstance(body, str):
        return body
    return None


def classify(
    http_status: int | None,
    body: object = None,
    *,
    data_missing_503: bool = False,
) -> Signal:
    """``http_status=None`` 表示网络错误/超时。

    ``data_missing_503``：调用方已知该接口在“数据不存在”时返回 503（如分钟线传前复权 ``f``，
    plan §0A），此时 503 归为 :attr:`Signal.DATA_MISSING`；否则 503 一律按频率类处理（保守）。
    """
    if http_status is None:
        return Signal.NETWORK
    text = _error_text(body) if (http_status != 200 or isinstance(body, Mapping)) else None
    if text is not None:
        m = _CODE_RE.search(text)
        if m:
            return {"101": Signal.QUOTA, "102": Signal.INVALID, "103": Signal.IP_LIMITED}[
                m.group(1)
            ]
    if http_status == 429:
        return Signal.IP_LIMITED
    if http_status == 503:
        if data_missing_503 and not (text and any(h in text.lower() for h in _RATE_HINTS)):
            return Signal.DATA_MISSING
        return Signal.RATE_LIMITED
    if http_status == 403:
        return Signal.NOT_ENTITLED
    if 500 <= http_status <= 599:
        return Signal.SERVER_ERROR
    if 400 <= http_status <= 499:
        return Signal.CLIENT_ERROR
    if isinstance(body, Mapping) and body.get("error") is not None:
        return Signal.CLIENT_ERROR
    return Signal.OK
