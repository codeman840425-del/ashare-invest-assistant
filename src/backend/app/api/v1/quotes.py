"""S3-9 empty quote view: public identities and own licence metadata, never collection.

An owner-scoped HTTP quote cache is not wired yet. Global quote tables are not a
substitute for provenance; this route exposes the resulting gap without prices.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid

from fastapi import APIRouter, Header, Request, Response
from sqlalchemy import Connection, or_, select

from app.api.v1.imports import etag_response
from app.auth.deps import AuthDep, EngineDep
from app.common.errors import AppError, ErrorCode
from app.db.tables.licences import user_data_licence_holds as holds
from app.db.tables.licences import user_data_licence_status as licences
from app.db.tables.market import securities
from app.marketdata.subresource_read import DecimalText, Gap, Shape, one
from app.master.search import invalid
from app.schemas.enums import DataStatus, GapReason

router = APIRouter(tags=["quotes"])


class QuoteItem(Shape):
    security_code: str
    name: str
    price: DecimalText | None = None
    change_pct: DecimalText | None = None
    volume: DecimalText | None = None
    amount: DecimalText | None = None
    t: str | None = None
    data_status: DataStatus
    data_as_of: str | None = None
    gaps: list[Gap]


class QuotesResponse(Shape):
    items: list[QuoteItem]


def parse_codes(request: Request) -> tuple[str, ...]:
    raw = one(request.query_params, "codes")
    values = raw.split(",") if raw is not None else []
    if not 1 <= len(values) <= 200:
        raise invalid("codes", "must contain between 1 and 200 security codes")
    canonical = tuple(value.strip().upper() for value in values)
    if any(re.fullmatch(r"[0-9]{6}\.(?:SH|SZ|BJ)", code) is None for code in canonical):
        raise invalid("codes", "must contain canonical security codes")
    return tuple(dict.fromkeys(canonical))


def empty_quotes(conn: Connection, owner: uuid.UUID, codes: tuple[str, ...]) -> QuotesResponse:
    rows = conn.execute(
        select(securities.c.code, securities.c.name).where(securities.c.code.in_(codes))
    ).all()
    names = {row.code: row.name for row in rows}
    if set(names) != set(codes):
        raise AppError(ErrorCode.NOT_FOUND)
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
    message = "本人行情缓存尚无可用读取源" if licence is not None else "本人数据证书不可用"
    return QuotesResponse(
        items=[
            QuoteItem(
                security_code=code,
                name=names[code],
                data_status=DataStatus.UNAVAILABLE,
                gaps=[Gap(key="quotes", reason=reason, message=message)],
            )
            for code in codes
        ]
    )


@router.get("/quotes", response_model=QuotesResponse)
def quotes(
    request: Request,
    auth: AuthDep,
    engine: EngineDep,
    if_none_match: str | None = Header(default=None),
) -> Response:
    codes = parse_codes(request)
    with engine.connect() as conn:
        content = empty_quotes(conn, auth.user_id, codes)
    return etag_response(content.model_dump(mode="json"), if_none_match)
