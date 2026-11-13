"""Bars read port: owned unadjusted daily cache; other modes remain unconnected.

No adjustment, aggregation, backfill or upstream IO is enabled here.
Synthetic readers are installed explicitly by local/test selfchecks only.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import Engine, select
from starlette.datastructures import QueryParams

from app.auth.deps import EngineDep
from app.common.errors import AppError, ErrorCode
from app.db.tables.market import securities, security_code_history
from app.master.search import invalid
from app.schemas.enums import BarAdjust, BarFreq, DataStatus, GapReason

DecimalText = Annotated[str, StringConstraints(pattern=r"^-?\d+(?:\.\d+)?$")]


class Bar(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

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


class BarsGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    reason: GapReason
    message: str


class BarsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    security_code: str
    name: str
    freq: BarFreq
    adjust: BarAdjust
    pre_close: DecimalText | None
    adjust_as_of: str | None
    next_before: str | None
    items: list[Bar]
    data_status: DataStatus
    data_as_of: str | None
    gaps: list[BarsGap]


def _day(value: str, field: str) -> dt.date:
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise invalid(field, "must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise invalid(field, "must be YYYY-MM-DD")
    return parsed


@dataclass(frozen=True)
class BarsQuery:
    freq: str
    adjust: str
    start: dt.date | None
    end: dt.date | None
    before: str | None
    limit: int

    @classmethod
    def parse(cls, params: QueryParams) -> BarsQuery:
        for field in ("freq", "adjust", "from", "to", "before", "limit"):
            if len(params.getlist(field)) > 1:
                raise invalid(field, "must not be repeated")
        freq = params.get("freq", "")
        if freq not in {item.value for item in BarFreq}:
            raise invalid("freq", "must be d, w or 1m")
        adjust = params.get("adjust", "none" if freq == "1m" else "qfq")
        if adjust not in {item.value for item in BarAdjust} or (freq == "1m" and adjust != "none"):
            raise invalid("adjust", "unsupported adjustment")
        raw_limit = params.get("limit", "500")
        if not raw_limit.isascii() or not raw_limit.isdecimal():
            raise invalid("limit", "must be an integer between 1 and 2000")
        # Reject oversized input before integer conversion (including Python's digit limit).
        if len(raw_limit) > 4 or not 1 <= int(raw_limit) <= 2000:
            raise invalid("limit", "must be an integer between 1 and 2000")
        start = _day(params["from"], "from") if "from" in params else None
        end = _day(params["to"], "to") if "to" in params else None
        if start and end and start > end:
            raise invalid("to", "must not precede from")
        before = params.get("before")
        if before is not None:
            if start is not None or end is not None:
                raise invalid("before", "must not be combined with from/to")
            if freq == "1m":
                try:
                    stamp = dt.datetime.fromisoformat(before)
                except ValueError as exc:
                    raise invalid("before", "must be an ISO timestamp") from exc
                if stamp.tzinfo is None:
                    raise invalid("before", "timestamp must include timezone")
            else:
                _day(before, "before")
        return cls(freq, adjust, start, end, before, int(raw_limit))


class BarsReader(Protocol):
    def read(self, owner: uuid.UUID, code: str, query: BarsQuery) -> dict[str, Any]:
        """Read only the caller's dataset; never schedule collection."""


def empty_bars(code: str, name: str, query: BarsQuery) -> dict[str, Any]:
    """A connected HTTP path does not imply a connected price source."""
    return {
        "security_code": code,
        "name": name,
        "freq": query.freq,
        "adjust": query.adjust,
        "pre_close": None,
        "adjust_as_of": None,
        "next_before": None,
        "items": [],
        "data_status": "unavailable",
        "data_as_of": None,
        "gaps": [{"key": "bars", "reason": "no_source", "message": "行情读取源尚未接入"}],
    }


class PlaceholderBarsReader:
    """Public identity only. No synthetic or other user's price data in the default app."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def read(self, owner: uuid.UUID, code: str, query: BarsQuery) -> dict[str, Any]:
        with self.engine.connect() as conn:
            successor = conn.execute(
                select(security_code_history.c.code).where(security_code_history.c.old_code == code)
            ).scalar_one_or_none()
            if successor is not None:
                raise AppError(ErrorCode.NOT_FOUND, details={"superseded_by": successor})
            row = conn.execute(
                select(securities.c.code, securities.c.name).where(securities.c.code == code)
            ).first()
            if row is None:
                raise AppError(ErrorCode.NOT_FOUND)
        return empty_bars(row.code, row.name, query)


def get_bars_reader(engine: EngineDep) -> BarsReader:
    from app.marketdata.owned_daily_read import OwnedDailyBarsReader

    return OwnedDailyBarsReader(engine)


BarsReaderDep = Annotated[BarsReader, Depends(get_bars_reader)]
