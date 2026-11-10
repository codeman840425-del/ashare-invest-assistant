# ruff: noqa: S101
"""T-T61 / T-A95 B3：G6 warn 经 ack 只留审计，不挡审批/信号、不降权、不把结果改写成 pass。"""

from __future__ import annotations

import inspect
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.common.errors import AppError, ErrorCode
from app.feedback.core import priority_weight
from app.strategy import reviews as svc


def _row(*, g6: str = "warn", decision: str = "pending") -> SimpleNamespace:
    return SimpleNamespace(
        decision=decision,
        gate_results=[{"gate": f"G{i}", "result": g6 if i == 6 else "pass"} for i in range(1, 7)],
    )


def test_b3_g6_warn_ack_allows_approval_without_rewriting_result() -> None:
    """G6=warn + ack 可通过审批；未 ack 则 PROMOTION_WARN_UNACKNOWLEDGED；G6 仍为 warn。"""
    version = uuid.uuid4()
    binding = {"version_id": str(version), "content_sha256": "a" * 64}
    row = _row()
    with pytest.raises(AppError) as unacked:
        svc.validate_decision(row, binding, version, "a" * 64, "approved", [])
    assert unacked.value.code == ErrorCode.PROMOTION_WARN_UNACKNOWLEDGED
    svc.validate_decision(row, binding, version, "a" * 64, "approved", ["G6"])
    assert row.gate_results[5]["gate"] == "G6"
    assert row.gate_results[5]["result"] == "warn"  # 不改写为 pass
    # 与 G6=pass 一样不挡审批
    svc.validate_decision(_row(g6="pass"), binding, version, "a" * 64, "approved", [])


def test_b3_priority_weight_ignores_g6_warn() -> None:
    """降权只按 plan §2.5.7 的 n/wins/超额计算，签名不含 G6；同样统计得到同一权重。"""
    sig = inspect.signature(priority_weight)
    assert "g6" not in sig.parameters
    assert "gate" not in sig.parameters
    assert "warn" not in sig.parameters
    a = priority_weight(30, 12, Decimal("-2.1"), enabled=True)
    b = priority_weight(30, 12, Decimal("-2.1"), enabled=True)
    assert a.priority_weight == b.priority_weight
    assert a.n == 30
