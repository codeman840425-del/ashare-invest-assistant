"""Internal producer boundary; strategy conclusions are not public write inputs."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import Field, model_validator

from app.schemas.enums import (
    DataStatus,
    Dimension,
    DimensionView,
    Horizon,
    Lifecycle,
    StrategyEvalState,
)
from app.signals.models import Gap, Model, RuleRef, SignalInput, TextEvidence


class DimensionConclusion(Model):
    dimension: Dimension
    view: DimensionView
    score: int | None = Field(ge=0, le=100)
    rules: list[RuleRef]


class Conclusion(Model):
    strategy_version_id: uuid.UUID
    strategy_key: str
    strategy_name: str
    version_no: int = Field(ge=1)
    instance_id: uuid.UUID
    horizon: Horizon
    lifecycle: Lifecycle
    state: StrategyEvalState
    signal: SignalInput
    candidate_signal_id: uuid.UUID | None
    priority_weight: Decimal = Field(ge=0)
    priority_downweighted: bool
    dimension_views: list[DimensionConclusion]
    reasons: list[TextEvidence]

    @model_validator(mode="after")
    def coherent(self) -> Conclusion:
        if self.lifecycle not in {"published", "observing"}:
            raise ValueError("version_not_runnable")
        signal = self.signal
        if (signal.proposed_action in {"hold", "wait"}) != (self.candidate_signal_id is None):
            raise ValueError("action_candidate_mismatch")
        if len({v.dimension for v in self.dimension_views}) != len(self.dimension_views):
            raise ValueError("duplicate_dimension")
        refs = {r.rule_id: r for r in signal.rule_refs}
        for view in self.dimension_views:
            if view.view == "unknown" and view.score is not None:
                raise ValueError("unknown_dimension_score")
            for rule in view.rules:
                if rule.dimension != view.dimension or refs.get(rule.rule_id) != rule:
                    raise ValueError("dimension_rule_mismatch")
        evidence = {e.id for e in signal.evidence}
        if any(not set(r.evidence_ids) <= evidence for r in self.reasons):
            raise ValueError("unresolved_reason_evidence")
        return self


class SuggestionInput(Model):
    security_code: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ|BJ)$")
    snapshot_id: uuid.UUID
    feature_set_version: str = Field(min_length=1)
    conclusions: list[Conclusion]
    data_status: DataStatus
    data_as_of: dt.datetime
    gaps: list[Gap]
    suitable: list[Horizon]
    user_overridden: bool
    created_at: dt.datetime

    @model_validator(mode="after")
    def coherent(self) -> SuggestionInput:
        if self.created_at.tzinfo is None or self.data_as_of.tzinfo is None:
            raise ValueError("timestamp_requires_timezone")
        if self.data_as_of > self.created_at:
            raise ValueError("invalid_data_as_of")
        if len({c.instance_id for c in self.conclusions}) != len(self.conclusions):
            raise ValueError("duplicate_instance")
        if any(
            c.signal.security_code != self.security_code
            or c.signal.created_at > self.created_at
            or c.signal.feature_set_version != self.feature_set_version
            for c in self.conclusions
        ):
            raise ValueError("suggestion_input_mismatch")
        return self
