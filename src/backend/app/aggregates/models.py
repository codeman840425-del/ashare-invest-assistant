"""Public field boilerplate reviewed locally from DeepSeek T-B77 draft.

Enums/nullability/required fields verified against api-contract §5.1/7.3.
EmptyBlocks deliberately reject nonempty future products: no mock suggestions/evidence.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import (
    DataGapScope,
    DataStatus,
    GapReason,
    MarketRegime,
    MarketSession,
    ReconciliationStatus,
    RiskLevel,
    SecurityType,
)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Gap(Model):
    key: str
    reason: GapReason
    message: str


class DataBlock(Model):
    data_status: DataStatus
    data_as_of: dt.datetime | None
    gaps: list[Gap]


class MarketClock(Model):
    """Must come from a reviewed calendar adapter; never guessed from weekday/code."""

    trade_date: dt.date
    session: MarketSession


class Range(Model):
    min_pct: str
    max_pct: str


class TerminalHolding(Model):
    qty: str
    sellable_qty: str
    cost_price: str
    weight_pct: str
    pnl: str | None
    pnl_pct: str | None
    security_type: SecurityType | None
    estimated: bool


class TerminalQuote(Model):
    price: str
    change_pct: str
    amount: str
    t: dt.datetime


class TerminalRow(Model):
    security_code: str
    name: str
    in_watchlist: bool
    focus: bool
    quote: TerminalQuote | None
    holding: TerminalHolding | None
    suggestion: None
    active_reason_count: int = Field(ge=0)
    max_risk_level: RiskLevel | None
    data_status: DataStatus
    data_as_of: dt.datetime | None


class MarketIndex(Model):
    security_code: str
    name: str
    price: str | None
    change_pct: str | None
    amount: str | None
    t: dt.datetime | None


class Breadth(Model):
    up: int = Field(ge=0)
    down: int = Field(ge=0)
    flat: int = Field(ge=0)
    limit_up: int = Field(ge=0)
    limit_down: int = Field(ge=0)


class MarketOverview(DataBlock):
    trade_date: dt.date
    session: MarketSession
    indices: list[MarketIndex]
    breadth: Breadth | None
    regime: MarketRegime | None
    regime_position_range: Range | None
    turnover_total: str | None


class Account(Model):
    account_id: uuid.UUID
    total_assets: str
    cash_available: str
    position_pct: str | None
    pnl_day: str | None
    regime: MarketRegime | None
    regime_position_range: Range | None
    data_status: DataStatus


class Terminal(DataBlock):
    server_time: dt.datetime
    trade_date: dt.date
    session: MarketSession
    account: Account | None
    rows: list[TerminalRow] = Field(max_length=300)
    truncated: bool
    unread_notifications: int = Field(ge=0)


class EmptyBlock(Model):
    items: tuple[()]
    more: Literal[False]


class Focus(Model):
    items: list[TerminalRow] = Field(max_length=50)
    more: bool


class Reconciliation(Model):
    status: ReconciliationStatus
    as_of: dt.datetime | None
    diff_count: int = Field(ge=0)
    important_count: int = Field(ge=0)


class Report(Model):
    date: dt.date
    status: Literal["ready", "generating", "not_yet"]


class TodayMarket(Model):
    regime: MarketRegime | None
    regime_position_range: Range | None
    data_status: DataStatus


class GapSecurity(Model):
    security_code: str
    name: str


class TodayGap(Model):
    key: str
    reason: GapReason
    scope: DataGapScope
    dataset: str | None
    message: str
    security_count: int = Field(ge=0)
    securities: list[GapSecurity] = Field(max_length=10)
    since: dt.datetime | None
    route: str | None


class GapBlock(Model):
    items: list[TodayGap] = Field(max_length=50)
    more: Literal[False]


class Today(DataBlock):
    server_time: dt.datetime
    trade_date: dt.date
    session: MarketSession
    market: TodayMarket
    focus: Focus
    pending_plan_drafts: EmptyBlock
    released_reasons: EmptyBlock
    risk_flags: EmptyBlock
    invalidations_today: EmptyBlock
    daily_report: Report
    reconciliation: Reconciliation
    unread_notifications: int = Field(ge=0)
    alerts: EmptyBlock
    plan_triggers: EmptyBlock
    data_gaps: GapBlock
    evidence: tuple[()]
