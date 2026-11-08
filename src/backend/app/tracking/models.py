from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.enums import Action, DataStatus
from app.signals.models import Evidence, Gap, Model


class Result(Model):
    strategy_version_id: uuid.UUID
    instance_id: uuid.UUID | None
    action: Action
    horizon_days: Literal[1, 5, 20]
    state: Literal["pending", "complete", "untradable", "excluded", "unavailable"]
    entry_at: dt.datetime | None = None
    entry_price: Decimal | None = Field(default=None, gt=0)
    exit_at: dt.datetime | None = None
    exit_price: Decimal | None = Field(default=None, gt=0)
    benchmark_code: str = "000300.SH"
    benchmark_entry_price: Decimal | None = Field(default=None, gt=0)
    benchmark_exit_price: Decimal | None = Field(default=None, gt=0)
    return_pct: Decimal | None = None
    benchmark_return_pct: Decimal | None = None
    excess_pct: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    max_runup_pct: Decimal | None = None
    direction_correct: bool | None = None
    invalidation_triggered_at: dt.datetime | None = None
    exclusion_reason: str | None = None
    price_basis: Literal["qfq"] = "qfq"
    cost_applied: bool = False
    evidence: list[Evidence] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self) -> Result:
        ids = [e.id for e in self.evidence]
        if len(ids) != len(set(ids)) or not set(self.evidence_ids) <= set(ids):
            raise ValueError("tracking_evidence_unresolved")
        if self.state in {"excluded", "untradable"} and not self.exclusion_reason:
            raise ValueError("tracking_exclusion_reason_missing")
        if self.state != "complete" and self.direction_correct is not None:
            raise ValueError("excluded_direction_not_applicable")
        return self


class Stat(Model):
    value: Decimal | None
    n: int = Field(ge=0)
    window: str
    small_sample: bool


class SuggestionTracking(Model):
    t1: Stat
    t5: Stat
    t20: Stat
    results: list[Result]
    data_status: DataStatus
    data_as_of: dt.datetime | None
    gaps: list[Gap]
