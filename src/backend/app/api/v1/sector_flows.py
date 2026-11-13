"""Authenticated sector-flow empty view; no owner-scoped source is wired yet."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Header, Request, Response
from sqlalchemy import Connection, or_, select

from app.api.v1.imports import etag_response
from app.auth.deps import AuthDep, EngineDep
from app.db.tables.licences import user_data_licence_holds as holds
from app.db.tables.licences import user_data_licence_status as licences
from app.marketdata.subresource_read import Gap, SourcedResponse, integer, one
from app.master.search import invalid
from app.schemas.enums import DataStatus, GapReason, IndustryTaxonomy, SectorKind, SectorSort

router = APIRouter(tags=["market"])


class SectorFlowsResponse(SourcedResponse):
    kind: SectorKind
    taxonomy: IndustryTaxonomy | None
    trade_date: dt.date | None
    items: list[dict[str, object]]


def parse_query(request: Request) -> SectorKind:
    params = request.query_params
    try:
        kind = SectorKind(one(params, "kind") or "")
    except ValueError as exc:
        raise invalid("kind", "must be industry or concept") from exc
    try:
        SectorSort(one(params, "sort", SectorSort.MAIN_NET_DESC) or "")
    except ValueError as exc:
        raise invalid("sort", "must be a sector_sort value") from exc
    integer(one(params, "limit", "20") or "", "limit", 100)
    return kind


def empty_sector_flows(conn: Connection, owner: uuid.UUID, kind: SectorKind) -> SectorFlowsResponse:
    now = dt.datetime.now(dt.UTC)
    v = licences.c
    licence = conn.execute(
        select(v.id)
        .select_from(licences.outerjoin(holds, holds.c.user_id == v.user_id))
        .where(
            v.user_id == owner,
            v.deleted_at.is_(None),
            v.status == "active",
            holds.c.user_id.is_(None),
            or_(v.paused_until.is_(None), v.paused_until <= now),
            or_(v.expires_on.is_(None), v.expires_on >= (now + dt.timedelta(hours=8)).date()),
        )
    ).scalar_one_or_none()
    reason = GapReason.NO_SOURCE if licence is not None else GapReason.DATA_LICENCE_UNAVAILABLE
    return SectorFlowsResponse(
        kind=kind,
        taxonomy=None,
        trade_date=None,
        items=[],
        sources=[],
        data_status=DataStatus.UNAVAILABLE,
        data_as_of=None,
        gaps=[
            Gap(
                key=f"sector_flows.{kind.value}",
                reason=reason,
                message="本人板块资金缓存尚无可用读取源"
                if licence is not None
                else "本人数据证书不可用",
            )
        ],
    )


@router.get("/market/sector-flows", response_model=SectorFlowsResponse)
def sector_flows(
    request: Request,
    auth: AuthDep,
    engine: EngineDep,
    if_none_match: str | None = Header(default=None),
) -> Response:
    kind = parse_query(request)
    with engine.connect() as conn:
        content = empty_sector_flows(conn, auth.user_id, kind)
    return etag_response(content.model_dump(mode="json"), if_none_match)
