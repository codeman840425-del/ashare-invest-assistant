"""T-B74 internal producer boundary; no public create-signal endpoint."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.schemas.enums import (
    Action,
    ConfidenceLevel,
    DataProvider,
    DataStatus,
    Dimension,
    EpistemicType,
    GapReason,
    RiskControl,
    RiskLevel,
    RuleRole,
    TLeg,
)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class Evidence(Model):
    id: str = Field(min_length=1)
    key: str = Field(min_length=1)
    value: str | int | float | bool | None
    unit: str | None
    provider: DataProvider
    endpoint: str | None
    data_as_of: dt.datetime
    fetched_at: dt.datetime
    epistemic_type: EpistemicType


class RuleRef(Model):
    rule_id: str = Field(min_length=1)
    snippet_id: uuid.UUID | None
    snippet_version: int | None
    role: RuleRole
    dimension: Dimension
    passed: bool | None
    value: str | None
    threshold: str | None
    evidence_ids: list[str]


class TextEvidence(Model):
    text: str = Field(min_length=1)
    expr: str | None
    evidence_ids: list[str]


class Stops(Model):
    stop_loss: Decimal | None
    take_profit: Decimal | None
    time_stop_days: int | None


class Confidence(Model):
    level: ConfidenceLevel
    value: Decimal = Field(ge=0, le=1)


class Gap(Model):
    key: str
    reason: GapReason
    message: str


class ModelRef(Model):
    model_key: str
    version: str
    role: Literal["auxiliary"]
    output: dict[str, JsonValue]
    evidence_ids: list[str]


class RiskFlag(Model):
    control: RiskControl
    level: RiskLevel
    message: str
    gated_actions: list[Action]
    quantity_cap: Decimal | None
    evidence_ids: list[str]


class RiskGateDetail(Model):
    control: Literal["total_exposure", "sector_concentration"]
    code: Literal["REGIME_MISMATCH", "SECTOR_EXPOSURE_EXCEEDED"]
    detail: dict[str, str]
    evidence_ids: list[str]

    @model_validator(mode="after")
    def coherent(self) -> RiskGateDetail:
        if (self.control == "total_exposure") != (self.code == "REGIME_MISMATCH"):
            raise ValueError("risk_detail_code_mismatch")
        return self


class SignalInput(Model):
    security_code: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ|BJ)$")
    proposed_action: Action
    t_leg: TLeg | None
    score: int | None = Field(ge=0, le=100)
    confidence: Confidence
    stops: Stops
    rule_refs: list[RuleRef] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    counter_evidence: list[TextEvidence] = Field(min_length=1)
    invalidation: list[TextEvidence] = Field(min_length=1)
    # Auxiliary model metadata is retained, never treated as a rule.
    model_refs: list[ModelRef]
    risk_flags: list[RiskFlag]
    risk_details: list[RiskGateDetail] = Field(default_factory=list, exclude_if=lambda v: not v)
    valid_until: dt.datetime | None
    snapshot_id: uuid.UUID
    feature_set_version: str = Field(min_length=1)
    created_at: dt.datetime
    data_status: DataStatus
    data_as_of: dt.datetime
    gaps: list[Gap]

    @model_validator(mode="after")
    def explainable(self) -> SignalInput:
        ids = {item.id for item in self.evidence}
        if len(ids) != len(self.evidence):
            raise ValueError("duplicate_evidence_id")
        references = (
            [item.evidence_ids for item in self.rule_refs]
            + [item.evidence_ids for item in self.risk_details]
            + [item.evidence_ids for item in [*self.counter_evidence, *self.invalidation]]
        )
        for references_ids in references:
            if not set(references_ids) <= ids:
                raise ValueError("unresolved_evidence")
        for references_ids in [item.evidence_ids for item in self.model_refs] + [
            item.evidence_ids for item in self.risk_flags
        ]:
            if not set(references_ids) <= ids:
                raise ValueError("unresolved_evidence")
        for value in [
            self.created_at,
            self.data_as_of,
            self.valid_until,
            *[v for item in self.evidence for v in [item.data_as_of, item.fetched_at]],
        ]:
            if value is not None and value.tzinfo is None:
                raise ValueError("timestamp_requires_timezone")
        if self.data_as_of > self.created_at:
            raise ValueError("future_data_as_of")
        if any(
            item.data_as_of > self.created_at or item.fetched_at > self.created_at
            for item in self.evidence
        ):
            raise ValueError("future_evidence")
        if self.valid_until is not None and self.valid_until <= self.created_at:
            raise ValueError("expired_at_creation")
        return self


class MarketFacts(Model):
    """Explicit evaluated snapshot facts; missing never silently defaults to false/zero."""

    price: Decimal | None = Field(default=None, gt=0)
    required_cash: Decimal | None = Field(default=None, ge=0)
    is_suspended: bool | None = None
    list_days: int | None = Field(default=None, ge=0)
    limit_locked_up: bool | None = None
    limit_locked_down: bool | None = None
    confidence_min: Decimal = Field(default=Decimal("0.4"), ge=0, le=1)
