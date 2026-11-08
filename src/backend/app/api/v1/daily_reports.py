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
                "stock_count": sum(
                    s.get("change_from_previous") != "removed" for s in row.body["stocks"]
                ),
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
        body = dict(row.body)
        body.setdefault("data_as_of", None)
        # Read-only legacy projection, never overwrite archived report snapshots.
        account = body.get("account")
        if account is not None and any(account.get(k) is None for k in ("total_assets", "cash")):
            body["account"] = None
            body["gaps"] = [
                *body.get("gaps", []),
                {"key": "account", "reason": "no_source", "message": "旧快照账户估值不可计算。"},
            ]
        if body["data_as_of"] is None:
            # Legacy bug repair is a read projection only: use frozen component
            # clocks, never generated_at, current quotes, or mutable live inputs.
            times = []
            components = [body.get("market"), body.get("account")]
            for stock in body.get("stocks", []):
                if stock.get("change_from_previous") == "removed":
                    continue
                components.append(stock)
                components.extend(d for d in stock.get("dimensions") or [] if d.get("facts"))
            for component in components:
                value = component.get("data_as_of") if component else None
                if not isinstance(value, str):
                    continue
                try:
                    stamp = dt.datetime.fromisoformat(value)
                except ValueError:
                    continue
                if stamp.tzinfo is not None and stamp <= row.generated_at:
                    times.append(stamp)
            body["data_as_of"] = min(times) if times else None
            body["data_status"] = "partial" if times else "unavailable"
            if times:
                body["gaps"] = [
                    *body.get("gaps", []),
                    {
                        "key": "legacy_aggregate_timestamp",
                        "reason": "no_source",
                        "message": "旧快照顶层时点缺失；仅从已冻结的已知组件时点投影，未重写存档。",
                    },
                ]
        return body
