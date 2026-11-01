"""按证券类型区分的接口口径（契约 v0.2.8 #4–#9，T-A09；ETF 纳入）。

纯常量与纯函数，供证券搜索（T-B06）、个股资料与个股数据接口（T-B07/T-B13）、导入（T-B02x 后续）
直接调用，保证各接口同一口径：

- 搜索默认 ``types=stock,cdr,etf``（不含指数），同层排序 ``stock > cdr > etf > index``；
- ETF 资料：``board``、``list_date_basis``、``risk_flag``、``total_shares``、``float_shares``、
  ``industry`` 为 null，``concepts`` 为 ``[]``，不计入缺失、不出 gap；
- ETF 的 financials / fund-flows / factors / announcements：200、空 ``items``、
  ``data_status="unavailable"``、``gaps[].reason="not_applicable"``；指数保持 ``no_source``
  （v0.2.8 U5 默认不改）；
- ETF 价格保留 3 位小数；导入整手按 100 份整数倍（``IMPORT_LOT_SIZE_IRREGULAR``，仅提示）；
- 可转债本版不收录（仍按 ``IMPORT_UNKNOWN_SECURITY``）；其持仓展示（plan 第 9 节问题 63）
  **未定，不实现**。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from app.schemas.enums import GapReason, SecurityType

T = SecurityType

#: 契约 v0.2.8 #4：``/securities/search`` 的 ``types`` 默认值（不含指数）
DEFAULT_SEARCH_TYPES: Final = (T.STOCK, T.CDR, T.ETF)
#: 同层排序：值越小越靠前
SEARCH_TYPE_RANK: Final[dict[SecurityType, int]] = {T.STOCK: 0, T.CDR: 1, T.ETF: 2, T.INDEX: 3}

#: 契约 v0.2.8 #5：ETF 资料中不适用、恒为 null 的字段（不计入 data_status 缺失、不出 gap）
ETF_NULL_PROFILE_FIELDS: Final = frozenset(
    {"board", "list_date_basis", "risk_flag", "total_shares", "float_shares", "industry"}
)
#: 同上，恒为 ``[]`` 的字段
ETF_EMPTY_PROFILE_FIELDS: Final = frozenset({"concepts"})

#: 契约 v0.2.8 #6：个股数据接口（数据集名同路由末段）
PER_SECURITY_DATASETS: Final = frozenset({"financials", "fund-flows", "factors", "announcements"})
#: ``gaps[].key``（契约 §7：fund-flows 的 key 为 ``fund_flows``）
GAP_KEYS: Final[dict[str, str]] = {d: d.replace("-", "_") for d in PER_SECURITY_DATASETS}

#: 契约 v0.2.8 #8：价格小数位
ETF_PRICE_DP: Final = 3
STOCK_PRICE_DP: Final = 2
#: 契约 v0.2.8 #9 / §4.1 #46：ETF 买入按 100 份整数倍
ETF_LOT: Final = 100


def search_sort_key(security_type: SecurityType | str) -> int:
    try:
        return SEARCH_TYPE_RANK[SecurityType(security_type)]
    except (KeyError, ValueError):
        return len(SEARCH_TYPE_RANK)


def dataset_gap_reason(security_type: SecurityType | str, dataset: str) -> GapReason | None:
    """该类型证券的个股数据集是否“结构上没有”：ETF → ``not_applicable``；指数的
    financials/fund-flows → ``no_source``（v0.2.7 口径不变，U5）；其余返回 None（按正常取数）。"""
    if dataset not in PER_SECURITY_DATASETS:
        raise ValueError(f"unknown per-security dataset: {dataset}")
    t = SecurityType(security_type)
    if t == T.ETF:
        return GapReason.NOT_APPLICABLE
    if t == T.INDEX and dataset in {"financials", "fund-flows"}:
        return GapReason.NO_SOURCE
    return None


def dataset_gap(security_type: SecurityType | str, dataset: str) -> dict[str, str] | None:
    """``gaps[]`` 元素的 ``{key, reason}``（``message`` 由接口层补文案）；无结构性缺口返回 None。"""
    reason = dataset_gap_reason(security_type, dataset)
    return None if reason is None else {"key": GAP_KEYS[dataset], "reason": reason.value}


def price_dp(security_type: SecurityType | str) -> int:
    return ETF_PRICE_DP if SecurityType(security_type) == T.ETF else STOCK_PRICE_DP


def etf_lot_irregular(quantity: Decimal | int) -> bool:
    """ETF 买入数量不是 100 份整数倍 → True（导入只出 warning，不阻断）。"""
    return Decimal(quantity) % ETF_LOT != 0
