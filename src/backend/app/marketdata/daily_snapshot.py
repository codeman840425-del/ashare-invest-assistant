"""Build an owner-scoped daily snapshot from daily bars and open the analyze gate."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.tables.market import daily_bars, securities, trading_calendar
from app.db.tables.realtime import pipeline_runs
from app.db.tables.reviews import data_snapshots
from app.marketdata.daily_bars import daily_universe
from app.replay.baseline import manifest_hash
from app.reports.service import covered

OWNED_VERSION = "owned-daily-v1"
ANALYZE_AS_OF = dt.time(17, 30)
FINAL_AFTER = dt.time(17, 10)
BEIJING = ZoneInfo("Asia/Shanghai")
_CALENDAR_BASIS = "trading_calendar"
_STEP = "daily_bars.fetch"
_KIND = "daily_batch"
_READY_STATUSES = frozenset({"ok", "partial"})
_MISSING_PREFIX = "daily_bars_missing:"
_CONFLICT_PREFIX = "daily_bar_conflict:"


def _at(day: dt.date, clock: dt.time) -> dt.datetime:
    return dt.datetime.combine(day, clock, BEIJING)


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _iso(value: dt.datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")
    return value.astimezone(BEIJING).isoformat()


def _stats_user(stats: object) -> str | None:
    if not isinstance(stats, dict):
        return None
    value = stats.get("user_id")
    if value is None or value == "":
        return None
    return str(value)


def _issue_code(issue: str) -> str | None:
    if issue.startswith(_MISSING_PREFIX):
        return issue[len(_MISSING_PREFIX) :]
    if issue.startswith(_CONFLICT_PREFIX):
        rest = issue[len(_CONFLICT_PREFIX) :]
        code, sep, _date = rest.rpartition(":")
        return code if sep else rest
    return None


def daily_bars_ready(
    conn: Connection, owner: uuid.UUID, trade_date: dt.date
) -> tuple[bool, tuple[str, ...]]:
    rows = conn.execute(
        select(pipeline_runs)
        .where(
            pipeline_runs.c.kind == _KIND,
            pipeline_runs.c.step == _STEP,
            pipeline_runs.c.run_date == trade_date,
        )
        .order_by(pipeline_runs.c.started_at.desc(), pipeline_runs.c.finished_at.desc())
    ).all()
    chosen = None
    for row in rows:
        uid = _stats_user(row.stats)
        if uid is None or uid == str(owner):
            chosen = row
            break
    if chosen is None or chosen.status not in _READY_STATUSES:
        return False, ()
    universe = set(daily_universe(conn, owner, trade_date))
    raw = chosen.stats.get("issues") if isinstance(chosen.stats, dict) else None
    carried: list[str] = []
    for issue in raw or []:
        if not isinstance(issue, str):
            continue
        if not (issue.startswith(_MISSING_PREFIX) or issue.startswith(_CONFLICT_PREFIX)):
            continue
        code = _issue_code(issue)
        if code in universe:
            carried.append(issue)
    return True, tuple(sorted(set(carried)))


def _col(row: object, name: str) -> object:
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return mapping[name]
    return getattr(row, name)


def _today_row(rows: list[object], day: dt.date) -> object | None:
    sourced = [row for row in rows if _col(row, "source") and _col(row, "trade_date") == day]
    return sourced[0] if sourced else None


def _include_historical(row: object, as_of: dt.datetime) -> bool:
    fetched = _col(row, "fetched_at")
    if not isinstance(fetched, dt.datetime) or fetched.tzinfo is None:
        return False
    return fetched <= as_of


def _is_placeholder(row: object) -> bool:
    return bool(_col(row, "is_suspended"))


def _has_ohlc(row: object) -> bool:
    return all(_col(row, name) is not None for name in ("open", "high", "low", "close"))


def _bar_item(row: object) -> dict[str, Any]:
    fetched = _col(row, "fetched_at")
    if not isinstance(fetched, dt.datetime):
        raise TypeError("fetched_at")
    trade_date = _col(row, "trade_date")
    if not isinstance(trade_date, dt.date):
        raise TypeError("trade_date")
    return {
        "trade_date": trade_date.isoformat(),
        "open": _as_str(_col(row, "open")),
        "high": _as_str(_col(row, "high")),
        "low": _as_str(_col(row, "low")),
        "close": _as_str(_col(row, "close")),
        "pre_close": _as_str(_col(row, "pre_close")),
        "volume": _as_str(_col(row, "volume")),
        "amount": _as_str(_col(row, "amount")),
        "first_seen_at": _iso(fetched),
        "is_final": fetched >= _at(trade_date, FINAL_AFTER),
    }


def _gap_item(row: object) -> dict[str, str]:
    trade_date = _col(row, "trade_date")
    if not isinstance(trade_date, dt.date):
        raise TypeError("trade_date")
    return {"trade_date": trade_date.isoformat(), "reason": "suspended"}


def _instrument(
    code: str,
    board: str,
    bars: list[dict[str, Any]],
    gaps: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "security_code": code,
        "board": board,
        "adjust": "none",
        "currency": "CNY",
        "price_unit": "CNY/share",
        "volume_unit": "share",
        "amount_unit": "CNY",
        "bars": bars,
        "gaps": gaps,
    }


def _load_boards(conn: Connection, codes: list[str]) -> dict[str, str | None]:
    if not codes:
        return {}
    rows = conn.execute(
        select(securities.c.code, securities.c.board).where(securities.c.code.in_(codes))
    ).all()
    return {row.code: row.board for row in rows}


def _load_bars(conn: Connection, codes: list[str], trade_date: dt.date) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {code: [] for code in codes}
    if not codes:
        return grouped
    rows = conn.execute(
        select(daily_bars)
        .where(
            daily_bars.c.code.in_(codes),
            daily_bars.c.adj_type == "none",
            daily_bars.c.trade_date <= trade_date,
        )
        .order_by(daily_bars.c.code, daily_bars.c.trade_date)
    ).all()
    for row in rows:
        grouped.setdefault(row.code, []).append(row)
    return grouped


def _calendar_dates(conn: Connection, start: dt.date, end: dt.date) -> dict[dt.date, bool]:
    rows = conn.execute(
        select(trading_calendar.c.date, trading_calendar.c.is_open).where(
            trading_calendar.c.date >= start,
            trading_calendar.c.date <= end,
        )
    ).all()
    return {row.date: bool(row.is_open) for row in rows}


def _sessions(calendar: dict[dt.date, bool], start: dt.date, end: dt.date) -> list[str] | None:
    cursor = start
    open_days: list[str] = []
    while cursor <= end:
        if cursor not in calendar:
            return None
        if calendar[cursor]:
            open_days.append(cursor.isoformat())
        cursor += dt.timedelta(days=1)
    return open_days


def _snapshot_id(owner: uuid.UUID, trade_date: dt.date, digest: str) -> uuid.UUID:
    key = f"{OWNED_VERSION}:{owner}:{trade_date.isoformat()}:{digest}"
    return uuid.uuid5(uuid.NAMESPACE_URL, key)


def build_owned_snapshot(
    conn: Connection, owner: uuid.UUID, trade_date: dt.date
) -> tuple[uuid.UUID | None, tuple[str, ...]]:
    is_open = covered(conn, trade_date)
    if not is_open:
        return None, ()
    codes = daily_universe(conn, owner, trade_date)
    if not codes:
        return None, ()

    boards = _load_boards(conn, codes)
    grouped = _load_bars(conn, codes, trade_date)
    as_of = _at(trade_date, ANALYZE_AS_OF)
    final_after = _at(trade_date, FINAL_AFTER)
    instruments: list[dict[str, Any]] = []
    omitted: list[dict[str, str]] = []
    included_dates: list[dt.date] = []

    for code in codes:
        board = boards.get(code)
        if board is None or board == "":
            omitted.append({"security_code": code, "issue": f"security_board_missing:{code}"})
            continue
        rows = grouped.get(code, [])
        today = _today_row(rows, trade_date)
        if today is None:
            omitted.append({"security_code": code, "issue": f"daily_bars_missing:{code}"})
            continue
        if _col(today, "source") == "mairui" or any(
            _col(row, "source") == "mairui" and _include_historical(row, as_of) for row in rows
        ):
            omitted.append(
                {"security_code": code, "issue": f"owned_snapshot_licence_unbound:{code}"}
            )
            continue
        fetched = _col(today, "fetched_at")
        if (
            isinstance(fetched, dt.datetime)
            and fetched.tzinfo is not None
            and fetched < final_after
        ):
            omitted.append({"security_code": code, "issue": f"daily_bars_not_final:{code}"})
            continue
        if (
            isinstance(fetched, dt.datetime)
            and fetched.tzinfo is not None
            and fetched > as_of
        ):
            omitted.append({"security_code": code, "issue": f"daily_bars_after_asof:{code}"})
            continue
        bars: list[dict[str, Any]] = []
        gaps: list[dict[str, str]] = []
        for row in rows:
            if not _col(row, "source") or not _include_historical(row, as_of):
                continue
            if _is_placeholder(row):
                gaps.append(_gap_item(row))
                included_dates.append(row.trade_date)
            elif _has_ohlc(row):
                bars.append(_bar_item(row))
                included_dates.append(row.trade_date)
        instruments.append(_instrument(code, str(board), bars, gaps))

    omitted.sort(key=lambda row: row["security_code"])
    issues = tuple(sorted({row["issue"] for row in omitted}))
    if included_dates:
        start = min(included_dates)
        calendar = _calendar_dates(conn, start, trade_date)
        sessions = _sessions(calendar, start, trade_date)
        if sessions is None:
            return None, ("calendar_not_covered",)
    else:
        sessions = []

    items = {
        "schema_version": OWNED_VERSION,
        "trade_date": trade_date.isoformat(),
        "calendar_basis": _CALENDAR_BASIS,
        "sessions": sessions,
        "instruments": instruments,
        "omitted": omitted,
    }
    digest = manifest_hash(items)
    ident = _snapshot_id(owner, trade_date, digest)
    conn.execute(
        pg_insert(data_snapshots)
        .values(
            id=ident,
            user_id=owner,
            licence_id=None,
            purpose="report",
            items=items,
            hash=digest,
            created_at=dt.datetime.now(dt.UTC),
        )
        .on_conflict_do_nothing(index_elements=[data_snapshots.c.id])
    )
    existing = conn.execute(select(data_snapshots).where(data_snapshots.c.id == ident)).one()
    if existing.user_id != owner or existing.hash != digest:
        raise ValueError("owned_snapshot_hash_conflict")
    return ident, issues
