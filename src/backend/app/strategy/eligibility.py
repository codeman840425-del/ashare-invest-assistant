"""策略适用的证券类型（v0.2.7 Q3，编排者 2026-11-02；plan 第 9 节问题 53）。

ETF 纳入 ``security_type``、搜索与持仓（交割单可能含 ETF 成交），但**策略不对 ETF 运行**；
指数本来就不运行策略。凡是“选出给策略/信号用的证券”的地方都必须经过这里：

- :func:`is_strategy_eligible`：单只判定；类型未知（主数据里查不到）一律视为不可用（失败即关闭）。
- :func:`ensure_strategy_eligible`：创建/修改策略实例、生成候选信号前调用，不合格抛
  ``400 VALIDATION_ERROR``（``details.fields`` 含
  ``{field: "security_code", issue: "not_strategy_eligible"}``）。
- :func:`split_strategy_universe`：从候选池（自选组、全市场、持仓）里剔除 ETF、指数与未知类型，
  返回保留与剔除两部分（剔除原因供日志/调试，不对外）。

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


def ensure_strategy_eligible(security_code: str, security_type: SecurityType | str | None) -> None:
    if not is_strategy_eligible(security_type):
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "该证券类型不运行策略（ETF、指数不运行策略）",
            {"fields": [{"field": "security_code", "issue": NOT_ELIGIBLE}]},
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
