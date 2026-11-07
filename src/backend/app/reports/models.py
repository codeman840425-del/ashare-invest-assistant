"""Contract section 5.3 shape, locally checked; rejected external draft not adopted."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import Field, JsonValue

from app.schemas.enums import DataStatus, MarketRegime, ReconciliationStatus, RiskLevel
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
    total_assets: Money | None
    cash: Money | None
    position_pct: Money | None
    pnl_day: Money | None
    position_vs_regime: Literal["below", "within", "above"] | None


class Reconciliation(Model):
    status: ReconciliationStatus
    as_of: dt.datetime | None
    diff_count: int = Field(ge=0)
    important_count: int = Field(ge=0)


class Stock(Model):
    security_code: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ|BJ)$")
    name: str
    close: Money | None
    change_pct: Money | None
    data_status: DataStatus
    max_risk_level: RiskLevel | None
    suggestion_id: uuid.UUID | None
    suggestion: dict[str, JsonValue] | None
    change_from_previous: Literal["new", "changed", "unchanged", "removed"]
    highlights: list[TextEvidence]
    invalidation: list[TextEvidence]
    next_watch: list[TextEvidence]


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
