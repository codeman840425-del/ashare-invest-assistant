"""T-A158: factor placeholder has no invented date, category registration or set version."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import Engine
from starlette.datastructures import QueryParams

from app.api.v1.imports import etag_response
from app.auth.deps import AuthDep, EngineDep
from app.common.errors import AppError, ErrorCode
from app.marketdata.datasets import empty_dataset
from app.marketdata.subresource_read import (
    DecimalText,
    NamedResponse,
    ResourceReader,
    Shape,
    choices,
    day,
    one,
)
from app.schemas.enums import FactorCategory

router = APIRouter(prefix="/securities", tags=["securities"])


class FactorValue(Shape):
    factor_id: str
    feature_key: str | None
    name: str
    category: str  # Vocabulary is not registered until T003; this placeholder serves no rows.
    value: DecimalText | None
    unit: str | None
    market_rank: int | None
    market_rank_pct: DecimalText | None


class Counts(Shape):
    total: int
    by_category: dict[str, int]


class FactorsResponse(NamedResponse):
    trade_date: str | None
    factor_set_version: str | None
    counts: Counts
    items: list[FactorValue]


@dataclass(frozen=True)
class FactorsQuery:
    trade_date: str | None
    categories: tuple[str, ...]

    @classmethod
    def parse(cls, params: QueryParams) -> FactorsQuery:
        requested = one(params, "trade_date")
        if requested is not None:
            day(requested, "trade_date")  # Validate without replacing the requested view date.
        return cls(requested, choices(params, "category", {v.value for v in FactorCategory}))


class PlaceholderFactorsReader:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def read(self, owner: uuid.UUID, code: str, query: FactorsQuery) -> dict[str, Any]:
        with self.engine.connect() as conn:
            value = empty_dataset(conn, owner, code, "factors")
        value.update(
            trade_date=query.trade_date,
            factor_set_version=None,
            counts={"total": 0, "by_category": {}},
        )
        return value


def get_factors_reader(engine: EngineDep) -> ResourceReader[FactorsQuery]:
    return PlaceholderFactorsReader(engine)


ReaderDep = Annotated[ResourceReader[FactorsQuery], Depends(get_factors_reader)]


@router.get("/{code}/factors", response_model=FactorsResponse)
def factors(
    code: str,
    request: Request,
    auth: AuthDep,
    reader: ReaderDep,
    if_none_match: str | None = Header(default=None),
) -> Response:
    query = FactorsQuery.parse(request.query_params)
    value = FactorsResponse.model_validate(reader.read(auth.user_id, code, query))
    # B-05 is explicitly an empty placeholder. Even an explicitly installed fixture reader
    # cannot expose B-03 synthetic rows/versions via this real HTTP endpoint (T-A158 §2).
    if (
        value.items
        or value.factor_set_version is not None
        or value.counts.total != 0
        or value.counts.by_category
        or value.sources
        or value.data_as_of is not None
        or value.trade_date != query.trade_date
        or value.data_status not in {"pending", "unavailable"}
    ):
        raise AppError(ErrorCode.INTERNAL_ERROR)
    return etag_response(value.model_dump(mode="json"), if_none_match)
