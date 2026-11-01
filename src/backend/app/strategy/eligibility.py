"""策略适用的证券类型（契约 v0.2.8 #10，编排者 2026-11-02；plan 第 9 节问题 53）。

ETF 纳入 ``security_type``、搜索与持仓（交割单可能含 ETF 成交），但**策略不对 ETF 运行**；
指数本来就不运行策略。凡是“选出给策略/信号用的证券”的地方都必须经过这里：

- :func:`is_strategy_eligible`：单只判定；类型未知（主数据里查不到）一律视为不可用（失败即关闭）。
- :func:`ensure_strategy_eligible`：创建/修改策略实例（``scope="security"``）前调用，不合格抛
  ``422 INSTANCE_SCOPE_INVALID{scope, security_code, security_type, issue:
  "security_type_not_supported"}``（契约 v0.2.8 §4、§6.0A 第 8 条；ETF 时
  ``security_type="etf"``）；主数据里查不到的代码 → 同一错误码，``issue: "unknown_security"``、
  不带 ``security_type``。
- :func:`split_strategy_universe`：从候选池（自选组、全市场、持仓）里剔除 ETF、指数与未知类型，
  返回保留与剔除两部分（剔除原因供日志/调试，不对外）。``account``/``watch_group`` 范围的实例
  运行时、生成候选信号、H-01 挂载持仓时都用它（契约 v0.2.8：运行时跳过 ETF，不报错）。

数据库层同口径兜底：迁移 0009 的 ``app.reject_non_strategy_security()`` 触发器挂在
``app.strategy_instances``（``security_code`` 非空时）与 ``app.candidate_signals`` 的写入上。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final

from app.common.errors import AppError, ErrorCode
from app.schemas.enums import STRATEGY_ELIGIBLE_SECURITY_TYPES, SecurityType

NOT_ELIGIBLE: Final = "not_strategy_eligible"
UNKNOWN_TYPE: Final = "unknown_security_type"
#: 契约 v0.2.8 ``INSTANCE_SCOPE_INVALID.details.issue``
ISSUE_TYPE_NOT_SUPPORTED: Final = "security_type_not_supported"
ISSUE_UNKNOWN_SECURITY: Final = "unknown_security"


def _as_type(security_type: SecurityType | str | None) -> SecurityType | None:
    if security_type is None:
        return None
    try:
        return SecurityType(security_type)
    except ValueError:
        return None


def is_strategy_eligible(security_type: SecurityType | str | None) -> bool:
    """只有 ``stock``/``cdr`` 运行策略；``etf``、``index``、未知值、``None`` 都返回 False。"""
    t = _as_type(security_type)
    return t is not None and t in STRATEGY_ELIGIBLE_SECURITY_TYPES


def ensure_strategy_eligible(
    security_code: str,
    security_type: SecurityType | str | None,
    *,
    scope: str = "security",
) -> None:
    if is_strategy_eligible(security_type):
        return
    t = _as_type(security_type)
    details: dict[str, str] = {"scope": scope, "security_code": security_code}
    if t is None:
        details["issue"] = ISSUE_UNKNOWN_SECURITY
    else:
        details["security_type"] = t.value
        details["issue"] = ISSUE_TYPE_NOT_SUPPORTED
    raise AppError(
        ErrorCode.INSTANCE_SCOPE_INVALID, "该证券类型不运行策略（ETF、指数不运行策略）", details
    )


def split_strategy_universe(
    codes: Iterable[str], types: Mapping[str, SecurityType | str | None]
) -> tuple[list[str], dict[str, str]]:
    """``codes`` 按原顺序去重后分为（可运行策略的代码, {被剔除代码: 原因}）。

    ``types`` 是代码 → ``market.securities.type``；不在其中的代码按未知类型剔除。
    """
    kept: list[str] = []
    dropped: dict[str, str] = {}
    seen: set[str] = set()
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        t = _as_type(types.get(code))
        if t is None:
            dropped[code] = UNKNOWN_TYPE
        elif t in STRATEGY_ELIGIBLE_SECURITY_TYPES:
            kept.append(code)
        else:
            dropped[code] = f"{NOT_ELIGIBLE}:{t.value}"
    return kept, dropped
