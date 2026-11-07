"""T-A16 report comparisons use the prior open day, never an earlier same-day revision."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Connection, select

from app.db.tables.market import trading_calendar
from app.db.tables.realtime import daily_reports, suggestions


def apply(conn: Connection, owner: uuid.UUID, date: dt.date, stocks: list[dict[str, Any]]) -> bool:
    day = conn.execute(
        select(trading_calendar.c.date)
        .where(trading_calendar.c.date < date, trading_calendar.c.is_open.is_(True))
        .order_by(trading_calendar.c.date.desc())
        .limit(1)
    ).scalar_one_or_none()
    prior = (
        conn.execute(
            select(daily_reports.c.body)
            .where(
                daily_reports.c.user_id == owner,
                daily_reports.c.trade_date == day,
                daily_reports.c.status.in_(["ready", "partial"]),
            )
            .order_by(daily_reports.c.revision.desc())
            .limit(1)
        ).scalar_one_or_none()
        if day
        else None
    )
    if prior is None:
        for stock in stocks:
            stock.update(change_from_previous=None, change_fields=[])
        return False
    before = {
        s["security_code"]: s
        for s in prior.get("stocks", [])
        if s.get("change_from_previous") != "removed"
    }
    ids = {
        uuid.UUID(str(s["suggestion_id"]))
        for s in [*stocks, *before.values()]
        if s.get("suggestion_id")
    }
    details = (
        {
            str(row.id): row
            for row in conn.execute(
                select(suggestions).where(suggestions.c.id.in_(ids), suggestions.c.user_id == owner)
            )
        }
        if ids
        else {}
    )

    def values(stock: dict[str, Any]) -> dict[str, Any]:
        suggestion = details.get(str(stock.get("suggestion_id")))
        strategies = suggestion.strategies if suggestion else []
        return {
            "actions": frozenset(
                (s["strategy_key"], s["action"], s.get("t_leg")) for s in strategies
            ),
            "confidence_level": frozenset(
                (s["strategy_key"], s["confidence"]["level"]) for s in strategies
            ),
            "executability": (suggestion.executability or {}).get("status") if suggestion else None,
            "max_risk_level": stock.get("max_risk_level"),
        }

    current = {s["security_code"] for s in stocks}
    for stock in stocks:
        old = before.get(stock["security_code"])
        fields = []
        if old:
            left, right = values(old), values(stock)
            fields = [key for key in left if left[key] != right[key]]
            # A formerly empty product and an available product differ even if actions=[] .
            if (
                bool(old.get("suggestion_id")) != bool(stock.get("suggestion_id"))
                and "actions" not in fields
            ):
                fields.insert(0, "actions")
        stock.update(
            change_from_previous="new" if old is None else "changed" if fields else "unchanged",
            change_fields=fields,
        )
    for code in sorted(set(before) - current):
        old = before[code]
        stocks.append(
            {
                **old,
                "close": None,
                "change_pct": None,
                "suggestion_id": None,
                "suggestion": None,
                "max_risk_level": None,
                "change_from_previous": "removed",
                "change_fields": [],
                "highlights": [],
                "invalidation": [],
                "next_watch": [],
            }
        )
    return True
