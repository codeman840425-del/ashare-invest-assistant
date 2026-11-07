"""Completed own daily reports only; building revisions never hide a completed one."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.auth.deps import AuthDep, EngineDep, SettingsDep
from app.common.errors import AppError, ErrorCode
from app.common.pagination import PageParams, build_page, decode_cursor, page_params
from app.db.tables.realtime import daily_reports
from app.reports.models import DailyReport

router = APIRouter(tags=["daily-reports"])


@router.get("/daily-reports")
def listing(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
) -> dict[str, Any]:
    from app.reports.service import COMPLETE

    ranked = (
        select(
            daily_reports,
            func.row_number()
            .over(partition_by=daily_reports.c.trade_date, order_by=daily_reports.c.revision.desc())
            .label("rank"),
        )
        .where(daily_reports.c.user_id == auth.user_id, daily_reports.c.status.in_(COMPLETE))
        .subquery()
    )
    scope = "daily-reports:" + str(auth.user_id)
    query = select(ranked).where(ranked.c.rank == 1)
    if page.cursor:
        keys = decode_cursor(page.cursor, scope=scope, settings=settings)
        try:
            if len(keys) != 1:
                raise ValueError
            before = dt.date.fromisoformat(str(keys[0]))
        except ValueError:
            raise AppError(ErrorCode.INVALID_CURSOR) from None
        query = query.where(ranked.c.trade_date < before)
    with engine.connect() as conn:
        rows = conn.execute(query.order_by(ranked.c.trade_date.desc()).limit(page.limit + 1)).all()
    result = build_page(
        rows,
        limit=page.limit,
        scope=scope,
        settings=settings,
        key=lambda row: [str(row.trade_date)],
    )
    return {
        "items": [
            {
                "date": row.trade_date,
                "generated_at": row.generated_at,
                "regime": row.body["market"]["regime"],
                "reconciliation_status": row.body["reconciliation"]["status"],
                "stock_count": len(row.body["stocks"]),
            }
            for row in rows[: page.limit]
        ],
        "next_cursor": result.next_cursor,
    }


@router.get("/daily-reports/{date}", response_model=DailyReport)
def detail(date: dt.date, auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    from app.reports.service import latest

    with engine.connect() as conn:
        row = latest(conn, auth.user_id, date)
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return dict(row.body)
