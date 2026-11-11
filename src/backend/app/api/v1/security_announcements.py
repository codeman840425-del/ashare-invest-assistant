"""B-05 announcement read port, scoped signed pagination and allowlisted original links."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import Engine
from starlette.datastructures import QueryParams

from app.api.v1.imports import etag_response
from app.auth.deps import AuthDep, EngineDep, SettingsDep
from app.common.errors import AppError, ErrorCode
from app.common.pagination import decode_cursor, encode_cursor
from app.config import Settings
from app.marketdata.subresource_read import (
    ResourceReader,
    Shape,
    SourcedResponse,
    choices,
    day,
    identity,
    integer,
    one,
    unavailable,
)
from app.master.search import invalid
from app.schemas.enums import AnnouncementCategory

router = APIRouter(prefix="/securities", tags=["securities"])
DISCLAIMER = "公告内容以交易所及上市公司披露原文为准，本系统仅提供标题与原文链接。"
BEIJING = dt.timezone(dt.timedelta(hours=8))


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


class AnnouncementsResponse(SourcedResponse):
    items: list[Announcement]
    next_cursor: str | None
    disclaimer: Literal["公告内容以交易所及上市公司披露原文为准，本系统仅提供标题与原文链接。"]


@dataclass(frozen=True)
class AnnouncementsQuery:
    start: dt.date | None
    end: dt.date | None
    categories: tuple[str, ...]
    limit: int
    cursor: str | None
    boundary: tuple[str, str] | None = None

    @classmethod
    def parse(cls, params: QueryParams, settings: Settings) -> AnnouncementsQuery:
        raw_start, raw_end = one(params, "from"), one(params, "to")
        start = day(raw_start, "from") if raw_start is not None else None
        end = day(raw_end, "to") if raw_end is not None else None
        if start and end and start > end:
            raise invalid("to", "must not precede from")
        maximum = min(200, settings.page_limit_max)
        limit = integer(
            one(params, "limit", str(settings.page_limit_default)) or "", "limit", maximum
        )
        return cls(
            start,
            end,
            choices(params, "category", {v.value for v in AnnouncementCategory}),
            limit,
            one(params, "cursor"),
        )

    def scope(self, owner: uuid.UUID, code: str) -> str:
        filters = json.dumps(
            [str(self.start), str(self.end), self.categories, "published_at,id:desc"],
            separators=(",", ":"),
        )
        digest = hashlib.sha256(filters.encode()).hexdigest()
        return f"announcements:{owner}:{code}:{digest}"

    def decoded(self, owner: uuid.UUID, code: str, settings: Settings) -> AnnouncementsQuery:
        if self.cursor is None:
            return self
        keys = decode_cursor(self.cursor, scope=self.scope(owner, code), settings=settings)
        if len(keys) != 2 or not all(isinstance(k, str) and k for k in keys):
            raise AppError(ErrorCode.INVALID_CURSOR)
        stamp, ident = str(keys[0]), str(keys[1])
        try:
            aware_stamp(stamp)
        except ValueError as exc:
            raise AppError(ErrorCode.INVALID_CURSOR) from exc
        return replace(self, boundary=(stamp, ident))


def aware_stamp(value: str) -> dt.datetime:
    stamp = dt.datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("announcement timestamp needs a timezone")
    return stamp


class PlaceholderAnnouncementsReader:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def read(self, owner: uuid.UUID, code: str, query: AnnouncementsQuery) -> dict[str, Any]:
        result = unavailable(identity(self.engine, code), "announcements", named=False)
        result.update(next_cursor=None, disclaimer=DISCLAIMER)
        return result


def get_announcements_reader(engine: EngineDep) -> ResourceReader[AnnouncementsQuery]:
    return PlaceholderAnnouncementsReader(engine)


ReaderDep = Annotated[ResourceReader[AnnouncementsQuery], Depends(get_announcements_reader)]


def original_link(url: str, allowlist: tuple[str, ...]) -> tuple[str | None, str | None]:
    """Check and publish the same browser-compatible URL; a bad link stays item-local."""
    normalized = url.replace("\\", "/")
    # Browsers trim/drop ASCII whitespace and controls; reject ambiguous inputs outright.
    if any(ord(char) <= 32 or ord(char) == 127 for char in normalized):
        return None, None
    try:
        parsed = urlsplit(normalized)
        host = parsed.hostname
        _ = parsed.port  # Validate non-numeric and out-of-range ports as well as bracket syntax.
    except ValueError:
        return None, None
    if (
        parsed.scheme != "https"
        or host not in allowlist
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None, host
    return normalized, host


def window(
    original: dict[str, Any],
    query: AnnouncementsQuery,
    owner: uuid.UUID,
    code: str,
    settings: Settings,
) -> dict[str, Any]:
    body = deepcopy(original)
    boundary = (
        (aware_stamp(query.boundary[0]), query.boundary[1]) if query.boundary is not None else None
    )
    rows = []
    for row in body["items"]:
        stamp = aware_stamp(row["published_at"])
        local_day = stamp.astimezone(BEIJING).date()
        if (
            (query.start is not None and local_day < query.start)
            or (query.end is not None and local_day > query.end)
            or (query.categories and row["category"] not in query.categories)
            or (boundary is not None and (stamp, row["id"]) >= boundary)
        ):
            continue
        rows.append(row)
    rows.sort(key=lambda row: (aware_stamp(row["published_at"]), row["id"]), reverse=True)
    # Duplicate source rows must not create repeated items or ambiguous keyset boundaries.
    unique = {(aware_stamp(row["published_at"]), row["id"]) for row in rows}
    if len(unique) != len(rows):
        raise ValueError("duplicate announcement key")
    selected = rows[: query.limit]
    body["items"] = selected
    body["next_cursor"] = (
        encode_cursor(
            [selected[-1]["published_at"], selected[-1]["id"]],
            scope=query.scope(owner, code),
            settings=settings,
        )
        if len(rows) > query.limit
        else None
    )
    allowlist = settings.business.securities.announcements.url_host_allowlist
    for row in selected:
        if row["url"] is not None:
            row["url"], row["url_host"] = original_link(row["url"], allowlist)
    if not selected:
        body["data_as_of"] = None
        body["sources"] = []
        if body["data_status"] not in {"pending", "unavailable"}:
            body["data_status"] = "unavailable"
            body["gaps"] = [
                {"key": "announcements", "reason": "no_source", "message": "请求区间无公告数据"}
            ]
    return body


@router.get("/{code}/announcements", response_model=AnnouncementsResponse)
def announcements(
    code: str,
    request: Request,
    auth: AuthDep,
    reader: ReaderDep,
    settings: SettingsDep,
    if_none_match: str | None = Header(default=None),
) -> Response:
    query = AnnouncementsQuery.parse(request.query_params, settings).decoded(
        auth.user_id, code, settings
    )
    content = window(reader.read(auth.user_id, code, query), query, auth.user_id, code, settings)
    value = AnnouncementsResponse.model_validate(content)
    return etag_response(value.model_dump(mode="json"), if_none_match)
