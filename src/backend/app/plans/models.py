from __future__ import annotations

import datetime as dt
import re
import uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.errors import AppError, ErrorCode
from app.schemas.enums import Action
from app.signals.models import Evidence, Stops


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def number(value: object, *, positive: bool = False) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"-?[0-9]+(?:\.[0-9]{1,4})?", value):
        raise ValueError("decimal_string_required")
    d = Decimal(value)
    if abs(d) >= Decimal("100000000000000") or (d <= 0 if positive else d < 0):
        raise ValueError("invalid_decimal")
    return value


class Condition(Body):
    kind: Literal["trigger", "invalidation"]
    type: Literal["price_above", "price_below", "pct_change", "date", "custom"]
    params: dict[str, Any]
    description: str = Field(min_length=1, max_length=200)

    @field_validator("type", mode="before")
    @classmethod
    def supported(cls, value: object) -> object:
        if value in ("indicator", "event"):
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                details={"fields": [{"field": "conditions.type", "issue": "not_supported"}]},
            )
        return value

    @model_validator(mode="after")
    def coherent(self) -> Condition:
        p = self.params
        if self.type in {"price_above", "price_below"}:
            if set(p) != {"price"}:
                raise ValueError("invalid_params")
            number(p["price"], positive=True)
        elif self.type == "pct_change":
            if (
                set(p) != {"pct"}
                or not isinstance(p["pct"], str)
                or not re.fullmatch(r"-?[0-9]+(?:\.[0-9]{1,4})?", p["pct"])
            ):
                raise ValueError("invalid_params")
            if Decimal(p["pct"]) == 0 or abs(Decimal(p["pct"])) >= Decimal("100000000000000"):
                raise ValueError("invalid_params")
        elif self.type == "date":
            if set(p) != {"on"} or not isinstance(p["on"], str):
                raise ValueError("invalid_params")
            if dt.date.fromisoformat(p["on"]).isoformat() != p["on"]:
                raise ValueError("invalid_params")
        elif p:
            raise ValueError("invalid_params")
        if not self.description.strip():
            raise ValueError("empty_text")
        return self


class PlanInput(Body):
    security_code: str
    account_id: uuid.UUID | None = None
    action: Action
    qty: str | None = None
    price: str | None = None
    size_pct_of_assets: str | None = None
    max_loss_amount: str | None = None
    stops: Stops | None = None
    rationale: str = Field(min_length=1, max_length=2000)
    risks: str | None = Field(default=None, max_length=2000)
    review_date: dt.date | None = None
    conditions: list[Condition] = Field(default_factory=list, max_length=20)
    candidate_id: None = None

    @field_validator("candidate_id", mode="before")
    @classmethod
    def no_candidate(cls, value: object) -> object:
        if value is not None:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                details={"fields": [{"field": "candidate_id", "issue": "not_supported"}]},
            )
        return value

    @field_validator("qty", "price", "max_loss_amount")
    @classmethod
    def decimals(cls, value: str | None) -> str | None:
        return number(value, positive=True) if value is not None else None

    @field_validator("size_pct_of_assets")
    @classmethod
    def percentage(cls, value: str | None) -> str | None:
        if value is not None:
            number(value)
            if Decimal(value) > 100:
                raise ValueError("invalid_percent")
        return value

    @field_validator("rationale")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty_text")
        return value


class VersionInput(PlanInput):
    security_code: str = ""
    base_version_no: int = Field(strict=True, ge=1)
    change_reason: str = Field(min_length=1, max_length=200)
    origin: Literal["manual", "plan_draft"] | None = None

    @field_validator("change_reason")
    @classmethod
    def reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty_text")
        return value


class Close(Body):
    status: Literal["done", "cancelled"]
    note: str | None = Field(default=None, max_length=200)


class DraftInput(Body):
    signal_ids: list[uuid.UUID] = Field(min_length=1)


class Answer(Body):
    id: str
    answer: Literal["yes", "no", "unsure"]
    note: str | None = None


class Confirm(Body):
    checklist_answers: list[Answer]
    risk_ack: bool = Field(strict=True)
    chosen_qty: str
    chosen_price: str
    deviation_ack: bool = Field(strict=True)

    @field_validator("chosen_qty", "chosen_price")
    @classmethod
    def positive(cls, value: str) -> str:
        return number(value, positive=True)


class AlertPatch(Body):
    status: Literal["read", "checked", "acted", "dismissed"]


class SavedCondition(Condition):
    id: uuid.UUID
    epistemic_type: Literal["hypothesis"]


class ChecklistAnswer(Answer):
    question: str


class PlanVersion(Body):
    plan_id: uuid.UUID
    version_no: int
    action: Action
    qty: str | None
    price: str | None
    size_pct_of_assets: str | None
    max_loss_amount: str | None
    stops: Stops | None
    rationale: str
    risks: str | None
    review_date: dt.date | None
    conditions: list[SavedCondition]
    change_reason: str | None
    checklist_answers: list[ChecklistAnswer]
    snapshot_id: str | None
    created_at: dt.datetime


class PlanSummary(Body):
    id: uuid.UUID
    security_code: str
    name: str
    account_id: uuid.UUID | None
    origin: Literal["manual", "plan_draft"]
    status: Literal["active", "triggered", "done", "cancelled"]
    action: Action
    current_version_no: int
    plan_draft_id: uuid.UUID | None
    candidate_id: None
    triggered_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime


class Pending(Body):
    condition_id: uuid.UUID
    condition_kind: Literal["trigger", "invalidation"]
    condition_text: str
    triggered_at: dt.datetime
    alert_id: uuid.UUID | None
    evidence_ids: list[str]


class Plan(PlanSummary):
    current_version: PlanVersion
    version_count: int
    pending_triggers: list[Pending]
    evidence: list[Evidence]

    @model_validator(mode="after")
    def resolves(self) -> Plan:
        if not {e for p in self.pending_triggers for e in p.evidence_ids} <= {
            e.id for e in self.evidence
        }:
            raise ValueError("unresolved_evidence")
        return self


class Affected(Body):
    plan_id: uuid.UUID
    plan_version_no: int
    condition_id: uuid.UUID | None


class Alert(Body):
    id: uuid.UUID
    rule_id: uuid.UUID
    origin: Literal["plan_condition", "holding_event", "user_custom"]
    severity: Literal["info", "warning", "important"]
    status: Literal["new", "read", "checked", "acted", "dismissed"]
    security_code: str | None
    name: str | None
    title: str
    triggered_at: dt.datetime
    data_as_of: dt.datetime | None
    affected_plans: list[Affected]
    evidence_ids: list[str]
    checklist: list[str]
    snapshot_id: str | None
    handled_at: dt.datetime | None
    evidence: list[Evidence]

    @model_validator(mode="after")
    def resolves(self) -> Alert:
        if not set(self.evidence_ids) <= {e.id for e in self.evidence}:
            raise ValueError("unresolved_evidence")
        return self


class QuantityRange(Body):
    min: str
    max: str
    lot: int = Field(gt=0)


class PriceRange(Body):
    low: str
    high: str


class Question(Body):
    id: str
    question: str
    required: bool


class FeeEstimate(Body):
    amount: str
    epistemic_type: Literal["fact", "estimate"]


class PlanDraft(Body):
    id: uuid.UUID
    status: Literal["pending", "confirmed", "discarded", "expired", "stale"]
    signal_ids: list[uuid.UUID]
    security_code: str
    name: str
    action: Action
    qty_range: QuantityRange
    price_range: PriceRange
    stops: Stops
    max_loss_amount: str
    max_loss_pct: str
    fee_estimate: FeeEstimate
    user_context_snapshot: dict[str, str | None]
    risk_flags: list[dict[str, Any]]
    judgment_checklist: list[Question]
    valid_until: dt.datetime
    market_rule_version_id: uuid.UUID
    created_at: dt.datetime


class Confirmed(Body):
    plan_id: uuid.UUID
    plan_version_no: Literal[1]
