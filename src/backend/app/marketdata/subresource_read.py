"""Shared read-only identity/status/query primitives for B-05 subresource placeholders."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import Engine, select
from starlette.datastructures import QueryParams

from app.common.errors import AppError, ErrorCode
from app.db.tables.market import securities, security_code_history
from app.master.search import invalid
from app.schemas.enums import DataProvider, DataStatus, GapReason

DecimalText = Annotated[str, StringConstraints(pattern=r"^-?\d+(?:\.\d+)?$")]


class Shape(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Gap(Shape):
    key: str
    reason: GapReason
    message: str


class Source(Shape):
    provider: DataProvider
    endpoint: str | None
    fetched_at: str | None


class SourcedResponse(Shape):
    sources: list[Source]
    data_status: DataStatus
    data_as_of: str | None
    gaps: list[Gap]


class NamedResponse(SourcedResponse):
    security_code: str
    name: str


@dataclass(frozen=True)
class SecurityIdentity:
    code: str
    name: str
    kind: str


def identity(engine: Engine, code: str) -> SecurityIdentity:
    with engine.connect() as conn:
        successor = conn.execute(
            select(security_code_history.c.code).where(security_code_history.c.old_code == code)
        ).scalar_one_or_none()
        if successor is not None:
            raise AppError(ErrorCode.NOT_FOUND, details={"superseded_by": successor})
        row = conn.execute(
            select(securities.c.code, securities.c.name, securities.c.type).where(
                securities.c.code == code
            )
        ).first()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return SecurityIdentity(row.code, row.name, row.type)


def unavailable(security: SecurityIdentity, key: str, *, named: bool = True) -> dict[str, Any]:
    reason = "not_applicable" if security.kind == "etf" else "no_source"
    result: dict[str, Any] = {
        "items": [],
        "sources": [],
        "data_status": "unavailable",
        "data_as_of": None,
        "gaps": [
            {
                "key": key,
                "reason": reason,
                "message": "该数据不适用" if reason == "not_applicable" else "读取源尚未接入",
            }
        ],
    }
    if named:
        result.update(security_code=security.code, name=security.name)
    return result


def one(params: QueryParams, field: str, default: str | None = None) -> str | None:
    if len(params.getlist(field)) > 1:
        raise invalid(field, "must not be repeated")
    return params.get(field, default)


def integer(value: str, field: str, maximum: int) -> int:
    if (
        not value.isascii()
        or not value.isdecimal()
        or len(value) > len(str(maximum))
        or not 1 <= int(value) <= maximum
    ):
        raise invalid(field, f"must be an integer between 1 and {maximum}")
    return int(value)


def day(value: str, field: str) -> dt.date:
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise invalid(field, "must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise invalid(field, "must be YYYY-MM-DD")
    return parsed


def choices(params: QueryParams, field: str, allowed: set[str]) -> tuple[str, ...]:
    values = tuple(sorted({part for raw in params.getlist(field) for part in raw.split(",")}))
    if not set(values) <= allowed:
        raise invalid(field, "contains an unknown value")
    return values


class ResourceReader[QueryT](Protocol):
    def read(self, owner: uuid.UUID, code: str, query: QueryT) -> dict[str, Any]:
        """Return only owner-scoped rows; no scheduling or upstream IO."""
