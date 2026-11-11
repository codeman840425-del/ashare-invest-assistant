"""B-05 fund flows read path; no collection and no cross-licence fallback."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import Engine, select
from starlette.datastructures import QueryParams

from app.api.v1.imports import etag_response
from app.auth.deps import AuthDep, EngineDep
from app.common.errors import AppError, ErrorCode
from app.db.tables.market import trading_calendar
from app.marketdata.subresource_read import (
    DecimalText,
    NamedResponse,
    ResourceReader,
    Shape,
    day,
    identity,
    integer,
    one,
    unavailable,
)
from app.master.search import invalid

router = APIRouter(prefix="/securities", tags=["securities"])


class FundFlowDay(Shape):
    trade_date: str
    amount: DecimalText | None
    main_net: DecimalText | None
    super_large_net: DecimalText | None
    large_net: DecimalText | None
    medium_net: DecimalText | None
    small_net: DecimalText | None
    main_net_pct: DecimalText | None
    is_final: bool


class FlowsResponse(NamedResponse):
    items: list[FundFlowDay]


@dataclass(frozen=True)
class FlowsQuery:
    days: int | None
    start: dt.date | None
    end: dt.date | None

    @classmethod
    def parse(cls, params: QueryParams) -> FlowsQuery:
        raw_days, start, end = one(params, "days"), one(params, "from"), one(params, "to")
        if start is not None or end is not None:
            if raw_days is not None:
                raise invalid("days", "must not be combined with from/to")
            if start is None or end is None:
                raise invalid("from", "from and to are required together")
            first, last = day(start, "from"), day(end, "to")
            if first > last:
                raise invalid("to", "must not precede from")
            return cls(None, first, last)
        return cls(integer(raw_days if raw_days is not None else "60", "days", 250), None, None)


def validate_range(engine: Engine, query: FlowsQuery) -> None:
    """Count actual reviewed open days, requiring coverage of every civil date in range."""
    if query.start is None or query.end is None:
        return
    with engine.connect() as conn:
        rows = conn.execute(
            select(trading_calendar.c.date, trading_calendar.c.is_open).where(
                trading_calendar.c.date.between(query.start, query.end)
            )
        ).all()
    if len(rows) != (query.end - query.start).days + 1:
        raise AppError(ErrorCode.CALENDAR_NOT_COVERED)
    if sum(bool(row.is_open) for row in rows) > 250:
        raise invalid("to", "range exceeds 250 trading days")


class PlaceholderFlowsReader:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def read(self, owner: uuid.UUID, code: str, query: FlowsQuery) -> dict[str, Any]:
        security = identity(self.engine, code)
        validate_range(self.engine, query)
        return unavailable(security, "fund_flows")


def get_flows_reader(engine: EngineDep) -> ResourceReader[FlowsQuery]:
    return PlaceholderFlowsReader(engine)


ReaderDep = Annotated[ResourceReader[FlowsQuery], Depends(get_flows_reader)]


@router.get("/{code}/fund-flows", response_model=FlowsResponse)
def fund_flows(
    code: str,
    request: Request,
    auth: AuthDep,
    reader: ReaderDep,
    if_none_match: str | None = Header(default=None),
) -> Response:
    query = FlowsQuery.parse(request.query_params)
    value = FlowsResponse.model_validate(reader.read(auth.user_id, code, query))
    return etag_response(value.model_dump(mode="json"), if_none_match)
