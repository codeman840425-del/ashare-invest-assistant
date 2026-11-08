"""T-A26 raw-price and exchange-calendar RC1; no actions/orders or collectors."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, select

from app.config import Settings
from app.db.tables.accounts import opening_positions, trades
from app.db.tables.market import daily_bars, realtime_quotes, trading_calendar
from app.schemas.enums import RiskControl, RiskLevel
from app.signals.models import Evidence, RiskFlag, Stops

SH = ZoneInfo("Asia/Shanghai")


@dataclass
class Facts:
    mode: Literal["intraday", "close"] = "intraday"
    observed_at: dt.datetime | None = None
    fetched_at: dt.datetime | None = None
    last: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    stale_seconds: int = 0
    ex_rights: bool | None = None
    held: bool | None = None
    start: dt.date | None = None
    calendar: dict[dt.date, bool] = field(default_factory=dict)
    endpoint: str = "rc1:missing-source"


def positive(value: Decimal | None) -> bool:
    return value is not None and value.is_finite() and value > 0


def segment(
    rows: list[dict[str, Any]], quantity: Decimal, initial_quantity: Decimal = Decimal(0)
) -> dt.date | None:
    """Known internal ledger segment only; unmatched snapshot/ambiguous order refuses."""
    if not initial_quantity.is_finite() or initial_quantity < 0:
        return None
    qty, start = initial_quantity, None
    seen: dict[tuple[dt.date, Any], set[str]] = {}
    for row in rows:
        key = row["trade_date"], row.get("traded_at")
        seen.setdefault(key, set()).add(row["side"])
        if len(seen[key]) > 1:
            return None
        amount = row["quantity"]
        if not positive(amount):
            return None
        if row["side"] == "buy":
            if qty == 0:
                start = row["trade_date"]
            qty += amount
        else:
            qty -= amount
            if qty < 0:
                return None
            if qty == 0:
                start = None
    return start if qty == quantity and quantity > 0 else None


def load(
    conn: Connection,
    owner: uuid.UUID,
    account: uuid.UUID | None,
    code: str,
    settings: Settings,
    at: dt.datetime,
    *,
    stops_at: dt.datetime,
    position_known: bool,
) -> Facts:
    from app.api.v1.portfolio import _account

    today = at.astimezone(SH).date()
    facts = Facts(
        stale_seconds=settings.business.realtime.intervals.effective_stale_threshold_s,
        calendar={r.date: r.is_open for r in conn.execute(select(trading_calendar))},
        ex_rights=False if stops_at == at else None,
    )
    if position_known and account is not None:
        # Caller already checked account ownership; recheck before ANY ledger query.
        from app.db.tables.accounts import accounts

        owned = conn.execute(
            select(accounts.c.id).where(accounts.c.id == account, accounts.c.user_id == owner)
        ).first()
        if owned is not None:
            book = _account(conn, account, today)
            position = book.positions.get(code)
            quantity = position.qty if position is not None else Decimal(0)
            facts.held = quantity > 0
            openings = conn.execute(
                select(opening_positions).where(
                    opening_positions.c.account_id == account,
                    opening_positions.c.security_code == code,
                    opening_positions.c.as_of_date <= today,
                )
            ).all()
            initial = sum((r.quantity for r in openings), Decimal(0))
            rows = conn.execute(
                select(trades)
                .where(
                    trades.c.user_id == owner,
                    trades.c.account_id == account,
                    trades.c.security_code == code,
                    trades.c.voided_at.is_(None),
                    trades.c.trade_date <= today,
                    trades.c.created_at <= at,
                    (trades.c.traded_at.is_(None) | (trades.c.traded_at <= at)),
                )
                .order_by(trades.c.trade_date, trades.c.traded_at, trades.c.id)
            ).all()
            if not facts.held:
                net = initial + sum(
                    (r.quantity if r.side == "buy" else -r.quantity for r in rows), Decimal(0)
                )
                if not net.is_finite() or net != 0:
                    # A positive ledger with no rebuilt position is unknown,
                    # not evidence of liquidation and never clears a stop.
                    facts.held = None
                else:
                    facts.start = stops_at.astimezone(SH).date()
            else:
                if not rows or all(o.as_of_date <= rows[0].trade_date for o in openings):
                    facts.start = segment([dict(r._mapping) for r in rows], quantity, initial)
                # An opening balance interleaved with older trades is not an
                # actual first-buy execution; leave the origin unknown.

    closing = dt.datetime.combine(today, dt.time(15), SH)
    if at >= closing:
        facts.mode = "close"
        facts.endpoint = "market.daily_bars:adj_type=none"
        bar = conn.execute(
            select(daily_bars).where(
                daily_bars.c.code == code,
                daily_bars.c.adj_type == "none",
                daily_bars.c.trade_date == today,
                daily_bars.c.fetched_at >= closing,
                daily_bars.c.fetched_at <= at,
            )
        ).first()
        if (
            bar is not None
            and all(positive(bar._mapping[k]) for k in ["open", "high", "low", "close"])
            and bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
        ):
            facts.low, facts.high, facts.observed_at = bar.low, bar.high, closing
            facts.fetched_at = bar.fetched_at
    else:
        facts.endpoint = "market.realtime_quotes:raw"
        quote = conn.execute(
            select(realtime_quotes)
            .where(
                realtime_quotes.c.code == code,
                realtime_quotes.c.ts <= at,
                realtime_quotes.c.fetched_at <= at,
            )
            .order_by(realtime_quotes.c.ts.desc())
            .limit(1)
        ).first()
        if quote is not None:
            facts.last, facts.observed_at = quote.price, quote.ts
            facts.fetched_at = quote.fetched_at
    return facts


def assess(
    stops: Stops, facts: Facts | None, at: dt.datetime
) -> tuple[list[RiskFlag], list[Evidence], set[str]]:
    from app.risk.evaluation import observation

    facts = facts or Facts()
    flags: list[RiskFlag] = []
    evidence: list[Evidence] = []
    gaps: set[str] = set()

    def flag(reason: str, point: dt.datetime, values: dict[str, Any]) -> None:
        check_key = "rc1.time_check" if reason == "time_stop" else "rc1.price_check"
        used = [e.id for e in evidence if e.key == check_key]
        for key, value in {**values, "event_at:" + reason: point.isoformat()}.items():
            item = observation(
                "rc1." + key,
                value,
                point,
                facts.endpoint if reason != "time_stop" else "app.trades+market.trading_calendar",
            )
            item = item.model_copy(
                update={"fetched_at": at if reason == "time_stop" else facts.fetched_at or at}
            )
            evidence.append(item)
            used.append(item.id)
        flags.append(
            RiskFlag(
                control=RiskControl.STOP_TAKE,
                level=RiskLevel.WARNING,
                message="RC1触发：" + reason,
                gated_actions=[],
                quantity_cap=None,
                evidence_ids=used,
            )
        )

    price_required = stops.stop_loss is not None or stops.take_profit is not None
    if price_required:
        if any(not positive(v) for v in [stops.stop_loss, stops.take_profit] if v is not None):
            gaps.add("rc1.invalid_stop_price")
        elif facts.ex_rights is not False:
            gaps.add("stops_ex_rights" if facts.ex_rights else "rc1.stops_basis_unknown")
        elif facts.observed_at is None or facts.calendar.get(at.astimezone(SH).date()) is not True:
            gaps.add("rc1.raw_price")
        elif facts.observed_at > at:
            gaps.add("rc1.future_price")
        else:
            fresh = (at - facts.observed_at).total_seconds() <= facts.stale_seconds
            if facts.mode == "intraday" and (not positive(facts.last) or not fresh):
                gaps.add("rc1.latest_price_missing_or_stale")
            elif facts.mode == "close" and (
                not positive(facts.low)
                or not positive(facts.high)
                or facts.observed_at
                != dt.datetime.combine(at.astimezone(SH).date(), dt.time(15), SH)
            ):
                gaps.add("rc1.closed_daily_raw")
            else:
                low = facts.last if facts.mode == "intraday" else facts.low
                high = facts.last if facts.mode == "intraday" else facts.high
                check = observation(
                    "rc1.price_check",
                    json.dumps(
                        {
                            "raw_low_or_last": str(low),
                            "raw_high_or_last": str(high),
                            "stop_loss": str(stops.stop_loss)
                            if stops.stop_loss is not None
                            else None,
                            "take_profit": str(stops.take_profit)
                            if stops.take_profit is not None
                            else None,
                            "ex_rights_since_stops": False,
                        },
                        sort_keys=True,
                    ),
                    facts.observed_at,
                    facts.endpoint,
                )
                evidence.append(check.model_copy(update={"fetched_at": facts.fetched_at or at}))
                if stops.stop_loss is not None and low is not None and low <= stops.stop_loss:
                    flag(
                        "stop_loss",
                        facts.observed_at,
                        {"raw_low_or_last": low, "stop_loss": stops.stop_loss},
                    )
                elif (
                    stops.take_profit is not None and high is not None and high >= stops.take_profit
                ):
                    flag(
                        "take_profit",
                        facts.observed_at,
                        {"raw_high_or_last": high, "take_profit": stops.take_profit},
                    )
    if stops.time_stop_days is not None:
        if stops.time_stop_days <= 0:
            gaps.add("rc1.invalid_time_stop_days")
        elif facts.held is None or facts.start is None:
            gaps.add("rc1.holding_segment_start")
        else:
            start = facts.start
            today = at.astimezone(SH).date()
            dates = (
                [start + dt.timedelta(days=i) for i in range((today - start).days + 1)]
                if start <= today
                else []
            )
            if (
                not dates
                or facts.calendar.get(start) is not True
                or any(d not in facts.calendar for d in dates)
            ):
                gaps.add("rc1.calendar_not_covered")
            else:
                opened = [d for d in dates if d > start and facts.calendar[d]]
                evidence.append(
                    observation(
                        "rc1.time_check",
                        json.dumps(
                            {
                                "start_day_zero": start.isoformat(),
                                "opened_after_start": [d.isoformat() for d in opened],
                                "held": facts.held,
                                "time_stop_days": stops.time_stop_days,
                                "evaluated_at": at.isoformat(),
                            },
                            sort_keys=True,
                        ),
                        at,
                        "app.trades+market.trading_calendar",
                    )
                )
                if len(opened) >= stops.time_stop_days and facts.held:
                    due = dt.datetime.combine(opened[stops.time_stop_days - 1], dt.time(15), SH)
                    if at >= due:
                        flag(
                            "time_stop",
                            due,
                            {
                                "start_day_zero": start.isoformat(),
                                "time_stop_days": stops.time_stop_days,
                                "held": True,
                            },
                        )
    # Multiple strategy conclusions share one GET response: same key but
    # differing thresholds/periods must NEVER overwrite each other's evidence.
    scoped = {}
    for item in evidence:
        signature = hashlib.sha256(
            json.dumps(item.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:32]
        scoped[item.id] = item.id + ":" + signature
    evidence = [e.model_copy(update={"id": scoped[e.id]}) for e in evidence]
    flags = [
        f.model_copy(update={"evidence_ids": [scoped[i] for i in f.evidence_ids]}) for f in flags
    ]
    return flags, evidence, gaps
