"""Validate the concrete security-dataset query contract after authentication."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid

from sqlalchemy import Connection, func, select
from starlette.datastructures import QueryParams

from app.common.errors import AppError, ErrorCode
from app.common.pagination import decode_cursor
from app.config import Settings
from app.db.tables.market import trading_calendar
from app.marketdata.datasets import Dataset
from app.master.search import invalid
from app.schemas.enums import AnnouncementCategory, FactorCategory, ReportPeriod


def _date(params: QueryParams, field: str) -> dt.date | None:
    value = params.get(field)
    if value is None:
        return None
    try:
        parsed = dt.date.fromisoformat(value)
        if value != parsed.isoformat():
            raise ValueError
    except ValueError:
        raise invalid(field, "must be YYYY-MM-DD") from None
    return parsed


def _integer(params: QueryParams, field: str, default: int, maximum: int) -> int:
    try:
        value = int(params.get(field, str(default)))
    except ValueError:
        raise invalid(field, "must be an integer") from None
    if not 1 <= value <= maximum:
        raise invalid(field, "out of range")
    return value


def _values(params: QueryParams, field: str, allowed: set[str]) -> list[str]:
    values = [item for value in params.getlist(field) for item in value.split(",")]
    if any(item not in allowed for item in values):
        raise invalid(field, "unknown value")
    return sorted(set(values))


def _flow_range(conn: Connection, params: QueryParams) -> None:
    start, end = _date(params, "from"), _date(params, "to")
    if start is None and end is None:
        _integer(params, "days", 60, 250)
        return
    if start is None or end is None or "days" in params or start > end:
        raise invalid("from", "use days or a complete ordered from/to range")
    total, opened = conn.execute(
        select(func.count(), func.count().filter(trading_calendar.c.is_open.is_(True))).where(
            trading_calendar.c.date >= start, trading_calendar.c.date <= end
        )
    ).one()
    # Never substitute weekdays for an unknown exchange calendar.
    if total != (end - start).days + 1:
        raise invalid("from", "trading calendar does not cover the requested range")
    if opened > 250:
        raise invalid("to", "range exceeds 250 trading days")


def validate_dataset_query(
    conn: Connection,
    settings: Settings,
    owner: uuid.UUID,
    code: str,
    dataset: Dataset,
    params: QueryParams,
) -> str | None:
    """Return only an explicitly requested factor date, never a fabricated latest date."""
    if dataset == "financials":
        _integer(params, "limit", 8, 40)
        _values(params, "report_period", {item.value for item in ReportPeriod})
        _date(params, "as_of")
    elif dataset == "fund-flows":
        _flow_range(conn, params)
    elif dataset == "factors":
        chosen = _date(params, "trade_date")
        _values(params, "category", {item.value for item in FactorCategory})
        return chosen.isoformat() if chosen is not None else None
    else:
        _integer(params, "limit", settings.page_limit_default, settings.page_limit_max)
        start, end = _date(params, "from"), _date(params, "to")
        if start is not None and end is not None and start > end:
            raise invalid("to", "range must be ordered")
        categories = _values(params, "category", {item.value for item in AnnouncementCategory})
        if "cursor" in params:
            filters = [str(start), str(end), categories]
            digest = hashlib.sha256(json.dumps(filters).encode()).hexdigest()
            keys = decode_cursor(
                params["cursor"],
                scope=f"security-announcements:{owner}:{code}:{digest}",
                settings=settings,
            )
            try:
                if len(keys) != 2 or dt.datetime.fromisoformat(str(keys[0])).tzinfo is None:
                    raise ValueError
                uuid.UUID(str(keys[1]))
            except ValueError:
                raise AppError(ErrorCode.INVALID_CURSOR) from None
    return None
