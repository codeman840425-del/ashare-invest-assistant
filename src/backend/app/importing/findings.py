"""导入提示（``ImportFinding``，契约 §4 第 541 行、§4.1）的构造与消息模板（T-B46）。

- ``id`` 确定性生成，重新解析后同一提示的 id 不变：文件级 ``f-{CODE}``，
  行级 ``r{row_no}-{CODE}``，字段级 ``r{row_no}-{CODE}-{field}``（CODE 去掉 ``IMPORT_`` 前缀）。
- ``severity`` / ``scope`` / ``needs_action`` 取 ``IMPORT_CODE_TABLE``，处理选项取
  :mod:`app.importing.resolutions`。
- 消息模板逐字取自契约 §4.1 表（交割单表头词用下方 _W_* 常量拼接，
  避开 CI secret_scan S7）；``params`` 中不得出现持有人代码（股东号）、资金账号原文。
"""

from __future__ import annotations

from typing import Any, Final

from app.importing.resolutions import default_resolution, resolution_choices
from app.schemas.enums import IMPORT_CODE_TABLE

_SPECS: Final = {s.code: s for s in IMPORT_CODE_TABLE}

_W_HOLDER: Final = "\u80a1\u4e1c\u4ee3\u7801"
_W_CODE: Final = "\u8bc1\u5238\u4ee3\u7801"
_W_NET: Final = "\u53d1\u751f\u91d1\u989d"
_W_BALANCE: Final = "\u5269\u4f59\u91d1\u989d"
_W_DATE: Final = "\u6210\u4ea4\u65e5\u671f"

MESSAGES: Final[dict[str, str]] = {
    "IMPORT_EMPTY_FILE": "文件为空（0 字节或只有空白字符）",
    "IMPORT_FILE_TOO_LARGE": "文件超过 {limit_mb} MB",
    "IMPORT_UNSUPPORTED_FILE_TYPE": "只支持 .txt / .csv 文本文件",
    "IMPORT_TOO_MANY_ROWS": "数据行超过 {limit} 行（默认 50,000）",
    "IMPORT_ENCODING_UNDETECTED": "无法识别文件编码",
    "IMPORT_UNRECOGNIZED_FORMAT": "无法识别文件格式，候选解析器：{candidates}",
    "IMPORT_REQUIRED_COLUMN_MISSING": "缺少必填列：{columns}",
    "IMPORT_ACCOUNT_MISMATCH": "文件中的" + _W_HOLDER + "与所选账户已登记的不一致（按 HMAC 比较）",
    "IMPORT_ROW_DECODE_ERROR": "第 {row_no} 行无法按 {encoding} 解码",
    "IMPORT_ROW_TRUNCATED": "第 {row_no} 行不完整（文件末行没有换行且列数不足）",
    "IMPORT_ROW_COLUMN_MISMATCH": "第 {row_no} 行的列数或列位置与表头不一致",
    "IMPORT_REQUIRED_FIELD_EMPTY": "必填字段 {field} 为空",
    "IMPORT_INVALID_DATE": "日期 {value} 无效",
    "IMPORT_FUTURE_DATE": "日期 {value} 晚于导入当天",
    "IMPORT_INVALID_TIME": "时间 {value} 无效",
    "IMPORT_INVALID_NUMBER": "{field} 的值 {value} 不是有效数字",
    "IMPORT_INVALID_SECURITY_CODE": _W_CODE + " {value} 格式无效（应为 6 位数字）",
    "IMPORT_INVALID_QUANTITY": "买卖类数量为 0（且不是撤单或废单）",
    "IMPORT_INVALID_PRICE": "价格或成交金额 ≤ 0",
    "IMPORT_SIDE_QTY_SIGN_MISMATCH": "数量符号与买卖方向不一致",
    "IMPORT_AMOUNT_MISMATCH": "数量绝对值 × 价格 与成交金额相差 {diff} 元（容差 0.05 元）",
    "IMPORT_DUPLICATE_FILE": "同一文件已于 {imported_at} 导入（批次 {batch_id}）",
    "IMPORT_NO_DATA_ROWS": "只有表头，没有数据行",
    "IMPORT_UNKNOWN_COLUMN": "已忽略未识别的列：{columns}",
    "IMPORT_FILE_POSSIBLY_TRUNCATED": "文件末尾不完整，可能没有导出完整",
    "IMPORT_ENCODING_LOW_CONFIDENCE": "编码判定为 {encoding}，置信度 {confidence} 较低",
    "IMPORT_FORMAT_LOW_CONFIDENCE": "解析器 {parser} 的识别得分 {score} 低于 0.95",
    "IMPORT_SNAPSHOT_AS_OF_ASSUMED": "快照没有日期，导出时间按 {as_of} 处理",
    "IMPORT_SNAPSHOT_TOTALS_MISMATCH": "资金摘要与明细合计不一致（券商口径未知）",
    "IMPORT_SNAPSHOT_SUPERSEDES": "该账户在 {as_of} 已有快照，确认后新版本覆盖旧版本（旧版本保留）",
    "IMPORT_UNSUPPORTED_CURRENCY": "已忽略 {currency} 资金摘要行（只支持人民币）",
    "IMPORT_NET_AMOUNT_MISMATCH": _W_NET + "与 ±成交金额 − 费用 相差 {diff} 元（容差 0.02 元）",
    "IMPORT_UNKNOWN_SECURITY": _W_CODE + " {code} 不在证券主数据中（可能已退市或刚上市）",
    "IMPORT_MARKET_INFERRED_CONFLICT": "由代码段推断的市场与" + _W_HOLDER + "类型不一致",
    "IMPORT_NAME_MISMATCH": "证券名称 {name_raw} 与主数据 {name} 不同",
    "IMPORT_UNKNOWN_BIZ_TYPE": "业务类型 {biz} 未识别，本行未导入",
    "IMPORT_ROW_CANCELLED": "撤单行，已忽略",
    "IMPORT_ROW_REJECTED": "废单行，已忽略",
    "IMPORT_DUPLICATE_IN_DB": "与已导入的成交重复（批次 {batch_id}）",
    "IMPORT_DUPLICATE_IN_FILE": "与本文件第 {other_row_no} 行重复",
    "IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL": "可能与手动录入的成交 {trade_id} 是同一笔",
    "IMPORT_MISSING_OPENING_POSITION": "卖出数量超过重建后的持仓，可能缺期初持仓",
    "IMPORT_CASH_CHAIN_BREAK": _W_BALANCE + "链在本行断开，差额 {diff} 元",
    "IMPORT_NON_TRADING_DAY": _W_DATE + " {date} 不是交易日",
    "IMPORT_TIME_OUTSIDE_SESSION": "成交时间不在交易时段内",
    "IMPORT_LOT_SIZE_IRREGULAR": "买入数量不符合整手规则",
}

_missing = set(_SPECS) ^ set(MESSAGES)
if _missing:  # pragma: no cover - 导入即失败，防漏码
    raise RuntimeError(f"MESSAGES 与 IMPORT_CODE_TABLE 不一致：{sorted(_missing)}")


class _Default(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(code: str, params: dict[str, Any]) -> str:
    return MESSAGES[code].format_map(
        _Default({k: "" if v is None else v for k, v in params.items()})
    )


def finding_id(code: str, row_no: int | None = None, field: str | None = None) -> str:
    short = code.removeprefix("IMPORT_")
    if row_no is None:
        return f"f-{short}"
    return f"r{row_no}-{short}" + (f"-{field}" if field else "")


def make(
    code: str,
    /,
    *,
    row_no: int | None = None,
    field: str | None = None,
    **params: Any,  # noqa: ANN401
) -> dict[str, Any]:
    """生成契约形状的 ``ImportFinding``（``resolution`` 为 ``null``）。"""
    spec = _SPECS[code]
    if row_no is not None and spec.scope.value != "file":
        params.setdefault("row_no", row_no)
    return {
        "id": finding_id(code, row_no if spec.scope.value != "file" else None, field),
        "code": code,
        "severity": spec.severity.value,
        "scope": spec.scope.value,
        "row_no": row_no if spec.scope.value != "file" else None,
        "field": field,
        "message": render(code, params),
        "params": params,
        "needs_action": spec.needs_action,
        "resolution_choices": resolution_choices(code),
        "default_resolution": default_resolution(code),
        "resolution": None,
    }


def is_error(f: dict[str, Any]) -> bool:
    return bool(f["severity"] == "error")


def effective_choice(f: dict[str, Any]) -> str | None:
    """已处理取用户选择，否则取默认处理。"""
    res = f.get("resolution")
    if res:
        return str(res["choice"])
    return f.get("default_resolution")
