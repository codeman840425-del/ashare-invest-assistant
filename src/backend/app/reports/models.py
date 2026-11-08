"""Contract section 5.3 shape, locally checked; rejected external draft not adopted."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from app.schemas.enums import DataStatus, Dimension, MarketRegime, ReconciliationStatus, RiskLevel
from app.signals.models import Evidence, Gap, Model, TextEvidence

Money = Annotated[str, Field(pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")]


class PositionRange(Model):
    min_pct: Money
    max_pct: Money


class Breadth(Model):
    up: int = Field(ge=0)
    down: int = Field(ge=0)
    limit_up: int = Field(ge=0)
    limit_down: int = Field(ge=0)


class Market(Model):
    regime: MarketRegime | None
    regime_position_range: PositionRange | None
    breadth: Breadth | None
    summary: list[TextEvidence]


class Account(Model):
    total_assets: Money
    cash: Money
    position_pct: Money | None
    pnl_day: Money | None
    position_vs_regime: Literal["below", "within", "above"] | None


class Reconciliation(Model):
    status: ReconciliationStatus
    as_of: dt.datetime | None
    diff_count: int = Field(ge=0)
    important_count: int = Field(ge=0)


class FeatureRef(Model):
    feature_key: str
    status: Literal["declared", "verified_doc", "verified_live", "gap", "deprecated"] | None
    evidence_ids: list[str]


class DailyDimensionAnalysis(Model):
    dimension: Dimension
    facts: list[TextEvidence]
    feature_refs: list[FeatureRef]
    data_status: DataStatus
    data_as_of: dt.datetime | None
    gaps: list[Gap]


class Stock(Model):
    security_code: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ|BJ)$")
    name: str
    close: Money | None
    change_pct: Money | None
    data_status: DataStatus
    max_risk_level: RiskLevel | None
    suggestion_id: uuid.UUID | None
    suggestion: dict[str, JsonValue] | None
    change_from_previous: Literal["new", "changed", "unchanged", "removed"] | None
    change_fields: list[Literal["actions", "confidence_level", "executability", "max_risk_level"]]
    highlights: list[TextEvidence]
    invalidation: list[TextEvidence]
    next_watch: list[TextEvidence]
    analysis_snapshot_id: uuid.UUID | None = None
    dimensions: list[DailyDimensionAnalysis] | None = None

    @model_validator(mode="after")
    def dimensions_consistent(self) -> Stock:
        if self.change_from_previous == "removed":
            if self.dimensions is not None or self.analysis_snapshot_id is not None:
                raise ValueError("removed_stock_has_analysis")
        elif self.dimensions is not None:
            if [d.dimension for d in self.dimensions] != list(Dimension):
                raise ValueError("daily_dimensions_order_or_duplicates")
            if self.analysis_snapshot_id is None:
                raise ValueError("daily_analysis_snapshot_missing")
        return self


class Pending(Model):
    plan_drafts: int = Field(ge=0)
    active_reasons: int = Field(ge=0)


class Explanation(Model):
    source: Literal["template", "llm"]
    text: str
    llm_call_id: uuid.UUID | None


class DailyReport(Model):
    date: dt.date
    generated_at: dt.datetime
    account_id: uuid.UUID | None
    market: Market
    account: Account | None
    reconciliation: Reconciliation
    stocks: list[Stock]
    pending: Pending
    explanation: Explanation
    evidence: list[Evidence]
    data_status: DataStatus
    data_as_of: dt.datetime | None
    gaps: list[Gap]

    @model_validator(mode="after")
    def dimension_evidence_resolves(self) -> DailyReport:
        ids = {e.id for e in self.evidence}
        for stock in self.stocks:
            for dimension in stock.dimensions or []:
                refs = [i for f in dimension.facts for i in f.evidence_ids]
                refs += [i for f in dimension.feature_refs for i in f.evidence_ids]
                if not set(refs) <= ids or any(
                    not i.startswith(stock.security_code + ":") for i in refs
                ):
                    raise ValueError("daily_dimension_evidence_unresolved")
        return self
