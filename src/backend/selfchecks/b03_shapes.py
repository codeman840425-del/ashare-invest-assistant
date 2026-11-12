"""B-03 fixture-only schemas and invariants; never registered as application responses."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, StringConstraints, create_model

from app.schemas.enums import (
    AnnouncementCategory,
    BarAdjust,
    BarFreq,
    DataProvider,
    DataStatus,
    GapReason,
    ReportPeriod,
)

DecimalText = Annotated[str, StringConstraints(pattern=r"^-?\d+(?:\.\d+)?$")]
DateText = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
# This is an explicit synthetic calendar, not a weekday-based production calendar.
SYNTHETIC_OPEN_DAYS = ("2026-10-30", "2026-11-02", "2026-11-03")
DISCLAIMER = "公告内容以交易所及上市公司披露原文为准，本系统仅提供标题与原文链接。"


class Shape(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Gap(Shape):
    key: str
    reason: GapReason
    message: str


class Source(Shape):
    provider: DataProvider
    endpoint: str | None
    fetched_at: str | None


class Status(Shape):
    data_status: DataStatus
    # Latest T-A53: no used data means null; frontend baseline is checked separately.
    data_as_of: str | None
    gaps: list[Gap]


class Sourced(Status):
    sources: list[Source]


class Named(Sourced):
    security_code: str
    name: str


class Bar(Shape):
    t: str
    open: DecimalText
    high: DecimalText
    low: DecimalText
    close: DecimalText
    pre_close: DecimalText | None
    volume: DecimalText
    amount: DecimalText
    avg_price: DecimalText | None
    is_final: bool


class Bars(Status):
    security_code: str
    name: str
    freq: BarFreq
    adjust: BarAdjust
    pre_close: DecimalText | None
    adjust_as_of: DateText | None
    next_before: str | None
    items: list[Bar]


FinancialPeriod = create_model(
    "FinancialPeriod",
    __base__=Shape,
    period_end=(DateText, ...),
    report_period=(ReportPeriod, ...),
    announce_date=(DateText | None, ...),
    available_from=(DateText | None, ...),
    is_restated=(bool, ...),
    **dict.fromkeys(
        (
            "revenue",
            "revenue_yoy_pct",
            "net_profit",
            "net_profit_yoy_pct",
            "deducted_net_profit",
            "eps",
            "bvps",
            "roe_pct",
            "gross_margin_pct",
            "debt_ratio_pct",
            "operating_cash_flow",
        ),
        (DecimalText | None, ...),
    ),
)


class Financials(Named):
    items: list[FinancialPeriod]


class Flow(Shape):
    trade_date: DateText
    amount: DecimalText | None
    main_net: DecimalText | None
    super_large_net: DecimalText | None
    large_net: DecimalText | None
    medium_net: DecimalText | None
    small_net: DecimalText | None
    main_net_pct: DecimalText | None
    is_final: bool


class Flows(Named):
    items: list[Flow]


class Factor(Shape):
    factor_id: str
    feature_key: str | None
    name: str
    category: str  # Contract leaves category keys unverified; synthetic placeholders only.
    value: DecimalText | None
    unit: str | None
    market_rank: int | None
    market_rank_pct: DecimalText | None


class Counts(Shape):
    total: int
    by_category: dict[str, int]


class Factors(Named):
    trade_date: DateText
    factor_set_version: str
    counts: Counts
    items: list[Factor]


class Announcement(Shape):
    id: str
    published_at: str
    title: str
    category: AnnouncementCategory
    category_raw: str | None
    level_raw: str | None
    url: str | None
    url_host: str | None
    file_format: Literal["pdf", "html", "other"] | None
    first_seen_at: str


class Announcements(Sourced):
    items: list[Announcement]
    next_cursor: str | None
    disclaimer: Literal[DISCLAIMER]


MODELS = {
    "bars": Bars,
    "financials": Financials,
    "fund-flows": Flows,
    "factors": Factors,
    "announcements": Announcements,
}


def validate(resource: str, body: dict[str, Any], allowlist: set[str]) -> None:
    """Reject malformed or misleading fixture data before writing or responding."""
    MODELS[resource].model_validate_json(json.dumps(body, allow_nan=False))
    items = body["items"]
    if body["data_as_of"] is not None and datetime.fromisoformat(body["data_as_of"]).tzinfo is None:
        raise ValueError("fixture timestamps must include a timezone")
    if (
        not items
        and body["data_status"] in {"pending", "unavailable"}
        and body["data_as_of"] is not None
    ):
        raise ValueError("no used data must not invent a data_as_of timestamp")
    if resource == "financials":
        periods = [row["period_end"] for row in items]
        if periods != sorted(set(periods), reverse=True):
            raise ValueError("financial periods must be unique and descending")
        for row in items:
            date.fromisoformat(row["period_end"])
            announced, available = row["announce_date"], row["available_from"]
            if announced is not None and available is not None:
                expected = next((d for d in SYNTHETIC_OPEN_DAYS if d > announced), None)
                if available != expected:
                    raise ValueError("available_from must use the explicit synthetic calendar")
    elif resource == "fund-flows":
        days = [row["trade_date"] for row in items]
        if days != sorted(set(days)):
            raise ValueError("fund-flow dates must be unique and ascending")
        for row in items:
            if all(
                row[key] is not None for key in ("main_net", "super_large_net", "large_net")
            ) and (
                Decimal(row["main_net"])
                != Decimal(row["super_large_net"]) + Decimal(row["large_net"])
            ):
                raise ValueError("main net must equal the two large-order buckets")
    elif resource == "factors":
        expected = {
            "total": len(items),
            "by_category": dict(Counter(row["category"] for row in items)),
        }
        if body["counts"] != expected:
            raise ValueError("factor counts disagree with the actual items")
    elif resource == "bars":
        times = [row["t"] for row in items]
        if times != sorted(set(times)):
            raise ValueError("bars must be unique and ascending")
        if body["freq"] == "1m" and body["adjust"] != "none":
            raise ValueError("minute bars cannot be adjusted")
        if body["adjust"] == "none" and body["adjust_as_of"] is not None:
            raise ValueError("unadjusted bars cannot have an adjustment date")
        for row in items:
            low, high = Decimal(row["low"]), Decimal(row["high"])
            if not low <= Decimal(row["open"]) <= high or not low <= Decimal(row["close"]) <= high:
                raise ValueError("invalid synthetic OHLC range")
            if Decimal(row["volume"]) < 0 or Decimal(row["amount"]) < 0:
                raise ValueError("negative bar quantity")
            if body["freq"] != "1m" and row["avg_price"] is not None:
                raise ValueError("daily/weekly average price must be null")
    elif resource == "announcements":
        keys = [(row["published_at"], row["id"]) for row in items]
        if keys != sorted(set(keys), reverse=True):
            raise ValueError("announcements must follow published_at/id descending")
        for row in items:
            if row["url"] is not None:
                parsed = urlsplit(row["url"])
                if parsed.scheme != "https" or parsed.hostname not in allowlist:
                    raise ValueError("announcement URL is outside the HTTPS allowlist")
                if row["url_host"] != parsed.hostname:
                    raise ValueError("announcement URL host metadata mismatch")
