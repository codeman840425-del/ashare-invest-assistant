"""Read only proven caller-owned mairui daily bars; never enqueue or fetch."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, or_, select

from app.db.tables.licences import user_data_licence_holds as holds
from app.db.tables.licences import user_data_licence_status as licences
from app.db.tables.market import daily_bars, trading_calendar
from app.marketdata.bars_read import BarsQuery, PlaceholderBarsReader
from app.marketdata.daily_snapshot import FINAL_AFTER

BEIJING = ZoneInfo("Asia/Shanghai")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _licence(conn: Connection, owner: uuid.UUID, now: dt.datetime) -> uuid.UUID | None:
    v = licences.c
    return conn.execute(
        select(v.id)
        .select_from(licences.outerjoin(holds, holds.c.user_id == v.user_id))
        .where(
            v.user_id == owner,
            v.deleted_at.is_(None),
            v.status == "active",
            holds.c.user_id.is_(None),
            or_(v.paused_until.is_(None), v.paused_until <= now),
            or_(v.expires_on.is_(None), v.expires_on >= now.astimezone(BEIJING).date()),
        )
    ).scalar_one_or_none()


def _expected_day(conn: Connection, now: dt.datetime) -> dt.date | None:
    local = now.astimezone(BEIJING)
    today = conn.execute(
        select(trading_calendar.c.is_open).where(trading_calendar.c.date == local.date())
    ).scalar_one_or_none()
    if today is None:
        return None
    cutoff = local.date()
    if today and local.time() < dt.time(17):
        cutoff -= dt.timedelta(days=1)
    return conn.execute(
        select(trading_calendar.c.date)
        .where(trading_calendar.c.is_open.is_(True), trading_calendar.c.date <= cutoff)
        .order_by(trading_calendar.c.date.desc())
        .limit(1)
    ).scalar_one_or_none()


class OwnedDailyBarsReader(PlaceholderBarsReader):
    def read(self, owner: uuid.UUID, code: str, query: BarsQuery) -> dict[str, Any]:
        content = super().read(owner, code, query)
        if query.freq != "d" or query.adjust != "none":
            return content
        now = _now()
        with self.engine.connect() as conn:
            lid = _licence(conn, owner, now)
            if lid is None:
                content["gaps"] = [
                    {
                        "key": "bars",
                        "reason": "data_licence_unavailable",
                        "message": "本人数据证书不可用",
                    }
                ]
                return content
            stmt = select(daily_bars).where(
                daily_bars.c.code == code,
                daily_bars.c.adj_type == "none",
                daily_bars.c.source == "mairui",
                daily_bars.c.source_licence_id == lid,
                daily_bars.c.fetched_at <= now,
                daily_bars.c.trade_date <= now.astimezone(BEIJING).date(),
            )
            if query.start is not None:
                stmt = stmt.where(daily_bars.c.trade_date >= query.start)
            if query.end is not None:
                stmt = stmt.where(daily_bars.c.trade_date <= query.end)
            if query.before is not None:
                stmt = stmt.where(daily_bars.c.trade_date < dt.date.fromisoformat(query.before))
            rows = conn.execute(
                stmt.order_by(daily_bars.c.trade_date.desc()).limit(query.limit + 1)
            ).all()
            if not rows:
                return content
            more = len(rows) > query.limit
            page = list(reversed(rows[: query.limit]))
            content["next_before"] = page[0].trade_date.isoformat() if more else None
            expected = _expected_day(conn, now)
        items, gaps = [], []
        returned_stamps: list[dt.datetime] = []
        for row in page:
            day = row.trade_date.isoformat()
            if row.is_suspended or any(
                getattr(row, field) is None
                for field in ("open", "high", "low", "close", "volume", "amount")
            ):
                gaps.append(
                    {
                        "key": "bars." + day,
                        "reason": "suspended" if row.is_suspended else "no_source",
                        "message": "当日停牌" if row.is_suspended else "日线缓存字段不完整",
                    }
                )
                continue
            stamp = row.fetched_at
            if stamp.tzinfo is None:
                raise ValueError("daily bar fetched_at must include timezone")
            items.append(
                {
                    "t": day,
                    **{
                        key: format(getattr(row, key), "f")
                        for key in ("open", "high", "low", "close", "volume", "amount")
                    },
                    "pre_close": None if row.pre_close is None else format(row.pre_close, "f"),
                    "avg_price": None,
                    "is_final": stamp >= dt.datetime.combine(row.trade_date, FINAL_AFTER, BEIJING),
                }
            )
            returned_stamps.append(stamp)
        if not items:
            content["gaps"] = gaps
            return content
        latest = page[-1].trade_date
        content.update(
            items=items,
            gaps=gaps,
            data_as_of=min(returned_stamps).astimezone(BEIJING).isoformat(),
            data_status="partial" if gaps else ("fresh" if expected == latest else "stale"),
        )
        return content
