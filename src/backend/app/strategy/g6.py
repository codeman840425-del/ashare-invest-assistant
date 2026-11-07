"""T-A17 overlap representation. No fabricated history, empty-union zero or returns."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Overlap(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_jaccard: str | None = Field(pattern=r"^(?:0(?:\.[0-9]+)?|1(?:\.0+)?)$")
    max_jaccard_null_reason: Literal["no_history", "no_comparable_set"] | None

    @model_validator(mode="after")
    def coherent(self) -> Overlap:
        if (self.max_jaccard is None) != (self.max_jaccard_null_reason is not None):
            raise ValueError("max_jaccard_reason_mismatch")
        return self

    @property
    def duplicate(self) -> bool | None:
        return Decimal(self.max_jaccard) > Decimal(".9") if self.max_jaccard is not None else None


def compare(history_days: int | None, own: set[str], others: list[set[str]]) -> Overlap:
    # Unexamined/short own history takes precedence even when collections are empty.
    if history_days is None or history_days < 120:
        return Overlap(max_jaccard=None, max_jaccard_null_reason="no_history")
    comparable = [hits for hits in others if hits]
    if not own or not comparable:
        return Overlap(max_jaccard=None, max_jaccard_null_reason="no_comparable_set")
    value = max(Decimal(len(own & hits)) / Decimal(len(own | hits)) for hits in comparable)
    return Overlap(max_jaccard=str(value), max_jaccard_null_reason=None)


def missing_history_gate(fixtures_pass: bool, overlap: Overlap) -> dict[str, Any]:
    """Partial report only: valid fixtures cannot substitute for unexamined G6 statistics."""
    return {
        "gate": "G6",
        "result": "warn" if fixtures_pass else "fail",
        "detail": {
            "fixtures_all_pass": fixtures_pass,
            "max_jaccard_null_reason": overlap.max_jaccard_null_reason,
            "history": "not_examined_no_real_120_day_owned_history",
            "warning": "未体检/覆盖不足；不使用合成golden冒充真实历史统计。",
        },
    }
