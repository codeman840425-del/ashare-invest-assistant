"""日 K 写入入口与测试假源（T-B127；契约 daily-bars-source §7）。"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import Protocol

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from app.aggregates.service import select_account
from app.api.v1.portfolio import _account
from app.common.errors import AppError
from app.config import Settings
from app.db.tables.market import daily_bars, securities, trading_calendar
from app.db.tables.realtime import pipeline_runs
from app.db.tables.users import users
from app.reports.service import covered
from app.schemas.enums import GapReason

DAILY_BARS_FETCH: str = "daily_bars_fetch"
_STEP: str = "daily_bars.fetch"
_KIND: str = "daily_batch"
_MONEY_Q = Decimal("0.0001")
_PRICE_Q = Decimal("0.01")
_VOLUME = Decimal("10000")
_ALLOWED_SOURCES = frozenset({"fake", "mairui"})


@dataclass(frozen=True)
class DailyBar:
    code: str
    trade_date: dt.date
    adj_type: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    pre_close: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    is_suspended: bool


@dataclass(frozen=True)
class BarGap:
    code: str
    trade_date: dt.date | None
    reason: str
    issue: str


@dataclass(frozen=True)
class DailyBarsResult:
    bars: Sequence[DailyBar] = ()
    gaps: Sequence[BarGap] = ()
    halted: str | None = None


FetchResult = DailyBarsResult


@dataclass(frozen=True)
class UpsertStats:
    inserted: int
    unchanged: int
    conflicts: int
    issues: tuple[str, ...]


class DailyBarsSource(Protocol):
    def fetch(
        self, codes: Sequence[str], start: dt.date, end: dt.date, adjust: str
    ) -> DailyBarsResult:
        """按闭区间拉取日 K。"""


def _u64(code: str, day: dt.date, salt: str = "") -> int:
    payload = f"{code}|{day.isoformat()}{salt}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _pre_close(code: str, day: dt.date) -> Decimal:
    # [5.00, 50.00]，步进 0.01（4501 档），用 sha256 前 8 字节，不用 hash()
    return (Decimal("5.00") + Decimal(_u64(code, day, "|pre") % 4501) / Decimal(100)).quantize(
        _PRICE_Q
    )


def _price_in_band(code: str, day: dt.date, salt: str, pre_close: Decimal) -> Decimal:
    lo = (pre_close * Decimal("0.8")).quantize(_PRICE_Q, rounding=ROUND_UP)
    hi = (pre_close * Decimal("1.2")).quantize(_PRICE_Q, rounding=ROUND_DOWN)
    if lo > hi:
        lo, hi = hi, lo
    steps = int((hi - lo) / _PRICE_Q)
    picked = lo + _PRICE_Q * (_u64(code, day, salt) % (steps + 1))
    return picked.quantize(_PRICE_Q)


def _high_low(open_: Decimal, close: Decimal, pre_close: Decimal) -> tuple[Decimal, Decimal]:
    """high/low 在可容纳时各扩 0.01 一档（保守「小量」），并夹在 20% 带内。"""
    mx, mn = max(open_, close), min(open_, close)
    hi_cap = (pre_close * Decimal("1.2")).quantize(_PRICE_Q, rounding=ROUND_DOWN)
    lo_cap = (pre_close * Decimal("0.8")).quantize(_PRICE_Q, rounding=ROUND_UP)
    high = mx + _PRICE_Q if mx + _PRICE_Q <= hi_cap else mx
    low = mn - _PRICE_Q if mn - _PRICE_Q >= lo_cap else mn
    return high.quantize(_PRICE_Q), low.quantize(_PRICE_Q)


def _days(start: dt.date, end: dt.date) -> list[dt.date]:
    out: list[dt.date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += dt.timedelta(days=1)
    return out


class FakeDailyBarsSource:
    """仅测试使用的确定日 K 假源。missing 优先于 suspended。"""

    def __init__(
        self, *, missing: Sequence[str] = (), suspended: Sequence[str] = ()
    ) -> None:
        self._missing = frozenset(missing)
        self._suspended = frozenset(suspended)

    def fetch(
        self, codes: Sequence[str], start: dt.date, end: dt.date, adjust: str
    ) -> DailyBarsResult:
        bars: list[DailyBar] = []
        gaps: list[BarGap] = []
        days = _days(start, end)
        for code in codes:
            if code in self._missing:
                gaps.append(
                    BarGap(
                        code=code,
                        trade_date=None,
                        reason=GapReason.NO_SOURCE,
                        issue=f"daily_bars_missing:{code}",
                    )
                )
                continue
            for day in days:
                if code in self._suspended:
                    bars.append(
                        DailyBar(
                            code=code,
                            trade_date=day,
                            adj_type="none",
                            open=None,
                            high=None,
                            low=None,
                            close=None,
                            pre_close=None,
                            volume=None,
                            amount=None,
                            is_suspended=True,
                        )
                    )
                    continue
                pre = _pre_close(code, day)
                open_ = _price_in_band(code, day, "|open", pre)
                close = _price_in_band(code, day, "|close", pre)
                high, low = _high_low(open_, close, pre)
                bars.append(
                    DailyBar(
                        code=code,
                        trade_date=day,
                        adj_type=adjust or "none",
                        open=open_,
                        high=high,
                        low=low,
                        close=close,
                        pre_close=pre,
                        volume=_VOLUME,
                        amount=(close * _VOLUME).quantize(_MONEY_Q),
                        is_suspended=False,
                    )
                )
        return DailyBarsResult(bars=tuple(bars), gaps=tuple(gaps), halted=None)


def _q(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value).quantize(_MONEY_Q)


def _field(row: object, name: str) -> object:
    mapping = getattr(row, "_mapping", row)
    return mapping[name]  # type: ignore[index]


def _q_field(row: object, name: str) -> Decimal | None:
    value = _field(row, name)
    return _q(value if isinstance(value, Decimal) or value is None else Decimal(str(value)))


def _value_key(row: object) -> tuple[object, ...]:
    suspended = _field(row, "is_suspended")
    return (
        _q_field(row, "open"),
        _q_field(row, "high"),
        _q_field(row, "low"),
        _q_field(row, "close"),
        _q_field(row, "pre_close"),
        _q_field(row, "volume"),
        _q_field(row, "amount"),
        bool(suspended) if suspended is not None else None,
    )


def _bar_key(bar: DailyBar) -> tuple[object, ...]:
    return (
        _q(bar.open),
        _q(bar.high),
        _q(bar.low),
        _q(bar.close),
        _q(bar.pre_close),
        _q(bar.volume),
        _q(bar.amount),
        bar.is_suspended,
    )


def upsert_daily_bars(
    conn: Connection,
    result: FetchResult,
    *,
    source: str | None,
    licence_id: uuid.UUID | None,
    fetched_at: dt.datetime,
) -> UpsertStats:
    if source is None or not str(source):
        raise ValueError("source is required")
    if not isinstance(source, str):
        raise TypeError("source must be a non-empty str")
    if licence_id is not None and not isinstance(licence_id, uuid.UUID):
        raise TypeError("licence_id must be uuid.UUID or None")

    inserted = unchanged = conflicts = 0
    issues: list[str] = []
    if not result.bars:
        return UpsertStats(inserted=0, unchanged=0, conflicts=0, issues=())

    values = [
        {
            "code": bar.code,
            "trade_date": bar.trade_date,
            "adj_type": bar.adj_type,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "pre_close": bar.pre_close,
            "volume": bar.volume,
            "amount": bar.amount,
            "is_suspended": bar.is_suspended,
            "source": source,
            "source_licence_id": licence_id,
            "fetched_at": fetched_at,
        }
        for bar in result.bars
    ]
    ret = conn.execute(
        pg_insert(daily_bars)
        .values(values)
        .on_conflict_do_nothing(index_elements=["code", "trade_date", "adj_type"])
        .returning(daily_bars.c.code, daily_bars.c.trade_date, daily_bars.c.adj_type)
    ).all()
    inserted_keys = {(r.code, r.trade_date, r.adj_type) for r in ret}
    inserted = len(inserted_keys)
    leftovers = [
        bar for bar in result.bars if (bar.code, bar.trade_date, bar.adj_type) not in inserted_keys
    ]
    if leftovers:
        existing = conn.execute(
            select(daily_bars).where(
                daily_bars.c.code.in_({b.code for b in leftovers}),
                daily_bars.c.trade_date.in_({b.trade_date for b in leftovers}),
                daily_bars.c.adj_type.in_({b.adj_type for b in leftovers}),
            )
        ).mappings()
        by_pk = {(r["code"], r["trade_date"], r["adj_type"]): r for r in existing}
        for bar in leftovers:
            row = by_pk.get((bar.code, bar.trade_date, bar.adj_type))
            if row is None:
                continue
            if _bar_key(bar) == _value_key(row):
                unchanged += 1
            else:
                conflicts += 1
                issues.append(f"daily_bar_conflict:{bar.code}:{bar.trade_date.isoformat()}")
    issues.sort()
    return UpsertStats(
        inserted=inserted, unchanged=unchanged, conflicts=conflicts, issues=tuple(issues)
    )


def daily_universe(
    conn: Connection, owner: uuid.UUID, trade_date: dt.date
) -> list[str]:
    """单用户宇宙：持仓中 type=stock 且 listing_status=listed 的代码，去重后升序。

    listing_status 为空视为不合格，不按 listed 推断。
    """
    raw: set[str] = set()
    account_id = select_account(conn, owner, None)
    if account_id is not None:
        for code in _account(conn, account_id, trade_date).positions:
            raw.add(code)
    if not raw:
        return []
    listed = (
        conn.execute(
            select(securities.c.code).where(
                securities.c.code.in_(sorted(raw)),
                securities.c.type == "stock",
                securities.c.listing_status == "listed",
            )
        )
        .scalars()
        .all()
    )
    return sorted(listed)


def _approved_owners(conn: Connection) -> list[uuid.UUID]:
    return list(
        conn.execute(select(users.c.id).where(users.c.status == "approved").order_by(users.c.id))
        .scalars()
        .all()
    )


def _union_universe(
    conn: Connection, owners: Sequence[uuid.UUID], trade_date: dt.date
) -> list[str]:
    codes: set[str] = set()
    for owner in owners:
        codes.update(daily_universe(conn, owner, trade_date))
    return sorted(codes)


def _empty_stats(
    user_id: uuid.UUID | None,
    window_trading_days: int | None,
    *,
    codes: int = 0,
    inserted: int = 0,
    unchanged: int = 0,
    conflicts: int = 0,
    missing: int = 0,
    suspended: int = 0,
    issues: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "user_id": str(user_id) if user_id is not None else None,
        "window_trading_days": window_trading_days,
        "codes": codes,
        "inserted": inserted,
        "unchanged": unchanged,
        "conflicts": conflicts,
        "missing": missing,
        "suspended": suspended,
        "issues": list(issues),
    }


def _record_run(
    conn: Connection,
    trade_date: dt.date,
    user_id: uuid.UUID | None,
    window_trading_days: int | None,
    *,
    status: str,
    stats: dict[str, object],
    error: str | None = None,
) -> None:
    conn.execute(
        insert(pipeline_runs).values(
            kind=_KIND,
            run_date=trade_date,
            step=_STEP,
            status=status,
            finished_at=dt.datetime.now(dt.UTC),
            stats=stats,
            error=error,
        )
    )


def _as_day(trade_date: dt.date | str) -> dt.date:
    return trade_date if isinstance(trade_date, dt.date) else dt.date.fromisoformat(trade_date)


def _as_user(user_id: uuid.UUID | str | None) -> uuid.UUID | None:
    if user_id is None:
        return None
    return user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))


def fetch_and_record(
    conn: Connection,
    source: DailyBarsSource,
    *,
    trade_date: dt.date | str,
    user_id: uuid.UUID | str | None,
    window_trading_days: int | None,
) -> int:
    day = _as_day(trade_date)
    uid = _as_user(user_id)
    if window_trading_days is not None and (
        type(window_trading_days) is not int or window_trading_days <= 0
    ):
        raise ValueError("window_trading_days must be a positive integer")
    # 事务由调用方负责，这里不 begin / commit。
    return _run_fetch(conn, source, day, uid, window_trading_days)


def _run_fetch(
    conn: Connection,
    source: DailyBarsSource,
    day: dt.date,
    uid: uuid.UUID | None,
    window_trading_days: int | None,
) -> int:
    try:
        is_open = covered(conn, day)
    except AppError as exc:
        if exc.details is not None and exc.details.get("issue") == "CALENDAR_NOT_COVERED":
            stats = _empty_stats(uid, window_trading_days, issues=["calendar_not_covered"])
            _record_run(conn, day, uid, window_trading_days, status="skipped", stats=stats)
            return 0
        raise
    if not is_open:
        return 0

    if window_trading_days is None:
        start, end = day, day
        open_days = {day}
    else:
        recent = (
            conn.execute(
                select(trading_calendar.c.date)
                .where(
                    trading_calendar.c.date <= day,
                    trading_calendar.c.is_open.is_(True),
                )
                .order_by(trading_calendar.c.date.desc())
                .limit(window_trading_days)
            )
            .scalars()
            .all()
        )
        if len(recent) < window_trading_days:
            stats = _empty_stats(uid, window_trading_days, issues=["calendar_not_covered"])
            _record_run(conn, day, uid, window_trading_days, status="skipped", stats=stats)
            return 0
        start, end = min(recent), day
        open_days = set(
            conn.execute(
                select(trading_calendar.c.date).where(
                    trading_calendar.c.date >= start,
                    trading_calendar.c.date <= end,
                    trading_calendar.c.is_open.is_(True),
                )
            )
            .scalars()
            .all()
        )

    owners = [uid] if uid is not None else _approved_owners(conn)
    codes = _union_universe(conn, owners, day)
    if not codes:
        stats = _empty_stats(uid, window_trading_days, codes=0)
        _record_run(conn, day, uid, window_trading_days, status="ok", stats=stats)
        return 0

    raw = source.fetch(codes, start, end, "none")
    kept = tuple(bar for bar in raw.bars if bar.trade_date in open_days)
    present = {(bar.code, bar.trade_date) for bar in kept}
    missing_codes: set[str] = {gap.code for gap in raw.gaps}
    missing_pairs = 0
    for code in codes:
        for open_day in open_days:
            if (code, open_day) not in present:
                missing_pairs += 1
                missing_codes.add(code)
    upsert = upsert_daily_bars(
        conn,
        DailyBarsResult(bars=kept, gaps=raw.gaps, halted=raw.halted),
        source="fake",
        licence_id=None,
        fetched_at=dt.datetime.now(dt.UTC),
    )
    missing_issues = [f"daily_bars_missing:{code}" for code in missing_codes]
    issues = sorted(set(missing_issues) | set(upsert.issues))
    suspended = sum(1 for bar in kept if bar.is_suspended)
    status = "partial" if upsert.conflicts or missing_pairs else "ok"
    stats = _empty_stats(
        uid,
        window_trading_days,
        codes=len(codes),
        inserted=upsert.inserted,
        unchanged=upsert.unchanged,
        conflicts=upsert.conflicts,
        missing=missing_pairs,
        suspended=suspended,
        issues=issues,
    )
    _record_run(conn, day, uid, window_trading_days, status=status, stats=stats)
    return upsert.inserted


def _validate_task_args(
    trade_date: str, user_id: str | None, window_trading_days: int | None
) -> tuple[dt.date, uuid.UUID | None]:
    day = dt.date.fromisoformat(trade_date)
    if user_id is not None:
        try:
            uid = uuid.UUID(user_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("user_id must be a UUID string") from exc
    else:
        uid = None
    if window_trading_days is not None and (
        type(window_trading_days) is not int or window_trading_days <= 0
    ):
        raise ValueError("window_trading_days must be a positive integer")
    return day, uid


def daily_bars_fetch_task(
    settings: Settings,
    trade_date: str,
    user_id: str | None = None,
    window_trading_days: int | None = None,
) -> int:
    from app.workers.jobs import _engine

    day, uid = _validate_task_args(trade_date, user_id, window_trading_days)
    engine = _engine(settings)
    try:
        with engine.begin() as conn:
            if settings.daily_bars_source == "off":
                stats = _empty_stats(uid, window_trading_days, issues=["daily_bars_source_off"])
                _record_run(conn, day, uid, window_trading_days, status="skipped", stats=stats)
                return 0
            if settings.daily_bars_source == "mairui":
                stats = _empty_stats(
                    uid, window_trading_days, issues=["daily_bars_http_budget_unset"]
                )
                _record_run(conn, day, uid, window_trading_days, status="skipped", stats=stats)
                return 0
            return fetch_and_record(
                conn,
                FakeDailyBarsSource(),
                trade_date=day,
                user_id=uid,
                window_trading_days=window_trading_days,
            )
    except Exception as exc:
        with engine.begin() as conn:
            _record_run(
                conn,
                day,
                uid,
                window_trading_days,
                status="failed",
                stats=_empty_stats(uid, window_trading_days),
                error=type(exc).__name__,
            )
        raise
