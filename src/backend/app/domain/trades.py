"""成交的作废与更正规则（契约 v0.2.4 #12 / §7.2 ``Trade``、``TradeCreate``、
``POST /trades/{id}/void``；T-F02 D5；T-B02x）。纯函数，不读库。

- 成交事实不可修改：作废只写 ``voided_at`` / ``void_reason``（库触发器只放行这几列）。
- 更正 = 同一事务中作废原记录 + 写新记录；
  新记录的 ``replaces_trade_id`` 对外叫 ``corrects_trade_id``。
- 导入批次回滚造成的作废：``void_reason = "batch_reverted:{batch_id}"``。
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Final
from zoneinfo import ZoneInfo

from app.common.errors import AppError, ErrorCode

REASON_MAX: Final = 200
BATCH_REVERTED_PREFIX: Final = "batch_reverted:"
BEIJING: Final = ZoneInfo("Asia/Shanghai")
_FEE_COLUMNS: Final = ("commission", "stamp_tax", "transfer_fee", "other_fee")


def _reason(raw: str | None, *, field: str = "reason") -> str:
    note = (raw or "").strip()
    if not note:
        raise AppError(
            ErrorCode.VALIDATION_ERROR, details={"fields": [{"field": field, "issue": "required"}]}
        )
    if len(note) > REASON_MAX:
        raise AppError(
            ErrorCode.VALIDATION_ERROR, details={"fields": [{"field": field, "issue": "too_long"}]}
        )
    return note


def validate_void_reason(reason: str | None) -> str:
    """``POST /trades/{id}/void`` 的 ``reason``：去掉首尾空白后 1–200 字。

    用户不能自己写 ``batch_reverted:`` 前缀（那是批次回滚专用）。
    """
    note = _reason(reason)
    if note.startswith(BATCH_REVERTED_PREFIX):
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            details={"fields": [{"field": "reason", "issue": "invalid"}]},
        )
    return note


def validate_correction_reason(
    corrects_trade_id: uuid.UUID | None, reason: str | None
) -> str | None:
    """``TradeCreate``：``corrects_trade_id`` 非空时 ``reason`` 必填（1–200）；否则可空、≤200。"""
    if corrects_trade_id is not None:
        return _reason(reason)
    note = (reason or "").strip() or None
    if note is not None and len(note) > REASON_MAX:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            details={"fields": [{"field": "reason", "issue": "too_long"}]},
        )
    return note


def batch_revert_void_reason(batch_id: uuid.UUID) -> str:
    return f"{BATCH_REVERTED_PREFIX}{batch_id}"


def ensure_voidable(voided_at: dt.datetime | None) -> None:
    """已作废的成交再作废（或被更正）→ ``409 INVALID_STATE_TRANSITION``。"""
    if voided_at is not None:
        raise AppError(ErrorCode.INVALID_STATE_TRANSITION)


def _dec(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def fee_total(row: Mapping[str, Any]) -> Decimal | None:
    """各项费用之和；全部为空时为 ``None``（契约 ``fee_total: string(decimal) | null``）。"""
    parts = [row.get(c) for c in _FEE_COLUMNS]
    present = [Decimal(p) for p in parts if p is not None]
    return sum(present, Decimal(0)) if present else None


def trade_out(row: Mapping[str, Any], *, name: str | None) -> dict[str, Any]:
    """``app.trades`` 一行 → 契约 ``Trade``。``name`` 由调用方从证券主数据取。

    库列与契约字段名的对应：``quantity→qty``、``import_batch_id→batch_id``、
    ``replaces_trade_id→corrects_trade_id``、``traded_at``（北京时间）→ ``trade_time``；
    ``source`` 的 ``csv_template`` 对外归为 ``import``。
    """
    traded_at: dt.datetime | None = row.get("traded_at")
    amount = row.get("amount")
    if amount is None:
        amount = Decimal(row["quantity"]) * Decimal(row["price"])
    voided_at = row.get("voided_at")
    return {
        "id": str(row["id"]),
        "account_id": str(row["account_id"]),
        "trade_date": row["trade_date"].isoformat(),
        "trade_time": None
        if traded_at is None
        else traded_at.astimezone(BEIJING).time().isoformat("seconds"),
        "security_code": row["security_code"],
        "name": name,
        "side": str(row["side"]),
        "qty": _dec(row["quantity"]),
        "price": _dec(row["price"]),
        "amount": _dec(amount),
        "fee_total": _dec(fee_total(row)),
        "net_amount": _dec(row.get("net_amount")),
        "source": "manual" if row["source"] == "manual" else "import",
        "batch_id": None if row.get("import_batch_id") is None else str(row["import_batch_id"]),
        "voided": voided_at is not None,
        "void_reason": row.get("void_reason"),
        "voided_at": None if voided_at is None else voided_at.isoformat(),
        "corrects_trade_id": None
        if row.get("replaces_trade_id") is None
        else str(row["replaces_trade_id"]),
        "created_at": row["created_at"].isoformat(),
    }
