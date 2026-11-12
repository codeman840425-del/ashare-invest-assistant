"""B-05 financials: real authenticated HTTP path, explicit empty default data source."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import Engine
from starlette.datastructures import QueryParams

from app.api.v1.imports import etag_response
from app.auth.deps import AuthDep, EngineDep
from app.marketdata.datasets import empty_dataset
from app.marketdata.subresource_read import (
    DecimalText,
    NamedResponse,
    ResourceReader,
    Shape,
    choices,
    day,
    integer,
    one,
)
from app.schemas.enums import ReportPeriod

router = APIRouter(prefix="/securities", tags=["securities"])


class FinancialPeriod(Shape):
    period_end: str
    report_period: ReportPeriod
    announce_date: str | None
    available_from: str | None
    is_restated: bool
    revenue: DecimalText | None
    revenue_yoy_pct: DecimalText | None
    net_profit: DecimalText | None
    net_profit_yoy_pct: DecimalText | None
    deducted_net_profit: DecimalText | None
    eps: DecimalText | None
    bvps: DecimalText | None
    roe_pct: DecimalText | None
    gross_margin_pct: DecimalText | None
    debt_ratio_pct: DecimalText | None
    operating_cash_flow: DecimalText | None


class FinancialsResponse(NamedResponse):
    items: list[FinancialPeriod]


@dataclass(frozen=True)
class FinancialsQuery:
    periods: tuple[str, ...]
    limit: int
    as_of: dt.date | None

    @classmethod
    def parse(cls, params: QueryParams) -> FinancialsQuery:
        raw_limit = one(params, "limit", "8")
        raw_date = one(params, "as_of")
        return cls(
            choices(params, "report_period", {item.value for item in ReportPeriod}),
            integer(raw_limit or "", "limit", 40),
            day(raw_date, "as_of") if raw_date is not None else None,
        )


class PlaceholderFinancialsReader:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def read(self, owner: uuid.UUID, code: str, query: FinancialsQuery) -> dict[str, Any]:
        with self.engine.connect() as conn:
            return empty_dataset(conn, owner, code, "financials")


def get_financials_reader(engine: EngineDep) -> ResourceReader[FinancialsQuery]:
    return PlaceholderFinancialsReader(engine)


ReaderDep = Annotated[ResourceReader[FinancialsQuery], Depends(get_financials_reader)]


@router.get("/{code}/financials", response_model=FinancialsResponse)
def financials(
    code: str,
    request: Request,
    auth: AuthDep,
    reader: ReaderDep,
    if_none_match: str | None = Header(default=None),
) -> Response:
    query = FinancialsQuery.parse(request.query_params)
    value = FinancialsResponse.model_validate(reader.read(auth.user_id, code, query))
    return etag_response(value.model_dump(mode="json"), if_none_match)
