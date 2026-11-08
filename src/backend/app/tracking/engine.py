"""Known simulation rules only; calendar is explicit, raw/qfq evidence separate."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, localcontext
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.features.pipeline import prepare
from app.schemas.enums import DataProvider, EpistemicType, GapReason
from app.signals.models import Evidence, Gap
from app.tracking.models import Result

BEIJING = ZoneInfo("Asia/Shanghai")
HOLD_THRESHOLDS = {1: Decimal(1), 5: Decimal(2), 20: Decimal(5)}


def gap(key: str) -> Gap:
    return Gap(key=key, reason=GapReason.NO_SOURCE, message="模拟跟踪缺少已核实依据：" + key)


def close_at(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(15), BEIJING)


def intraday(created: dt.datetime, opened: set[dt.date]) -> bool:
    local = created.astimezone(BEIJING)
    return local.date() in opened and dt.time(9, 30) <= local.time().replace(tzinfo=None) < dt.time(
        15
    )


def due_date(created: dt.datetime, period: int, calendar: dict[dt.date, bool]) -> dt.date | None:
    day = created.astimezone(BEIJING).date()
    if day not in calendar:
        return None
    opened = sorted(d for d, yes in calendar.items() if yes and d > day)
    if len(opened) < period:
        return None
    due = opened[period - 1]
    if any(day + dt.timedelta(days=i) not in calendar for i in range((due - day).days + 1)):
        return None
    return due


def interval_return(start: Decimal, end: Decimal) -> Decimal:
    if not start.is_finite() or not end.is_finite() or start <= 0 or end <= 0:
        raise ValueError("invalid_tracking_prices")
    with localcontext() as precision:
        precision.prec = 64
        return (end / start - 1) * 100


def direction(action: str, excess: Decimal | None, period: int) -> bool | None:
    if excess is None or action == "wait":
        return None
    if action in {"buy", "add"}:
        return excess > 0
    if action in {"sell", "reduce"}:
        return excess < 0
    return abs(excess) <= HOLD_THRESHOLDS[period]


def evaluate(
    *,
    conclusion: dict[str, Any],
    created: dt.datetime,
    period: Literal[1, 5, 20],
    calendar: dict[dt.date, bool],
    instrument: dict[str, Any],
    benchmark: dict[str, Any],
    factors: list[dict[str, Any]],
    facts: dict[str, dict[str, bool | None]],
    forced_hold: bool | None,
    now: dt.datetime,
    minutes: list[dict[str, Any]] | None = None,
    benchmark_minutes: list[dict[str, Any]] | None = None,
) -> Result:
    with localcontext() as precision:
        precision.prec = 64
        return _evaluate(
            conclusion=conclusion,
            created=created,
            period=period,
            calendar=calendar,
            instrument=instrument,
            benchmark=benchmark,
            factors=factors,
            facts=facts,
            forced_hold=forced_hold,
            now=now,
            minutes=minutes or [],
            benchmark_minutes=benchmark_minutes or [],
        )


def _evaluate(
    *,
    conclusion: dict[str, Any],
    created: dt.datetime,
    period: Literal[1, 5, 20],
    calendar: dict[dt.date, bool],
    instrument: dict[str, Any],
    benchmark: dict[str, Any],
    factors: list[dict[str, Any]],
    facts: dict[str, dict[str, bool | None]],
    forced_hold: bool | None,
    now: dt.datetime,
    minutes: list[dict[str, Any]],
    benchmark_minutes: list[dict[str, Any]],
) -> Result:
    result = Result(
        strategy_version_id=conclusion["strategy_version_id"],
        instance_id=conclusion.get("instance_id"),
        action=conclusion["action"],
        horizon_days=period,
        state="pending",
    )
    due = due_date(created, period, calendar)
    if due is None:
        # The service leaves this row absent with calendar+gap; unknown due is
        # neither "not yet due" nor proof it is already due.
        raise ValueError("tracking_calendar_not_covered")
    result.exit_at = close_at(due)
    opened = {d for d, yes in calendar.items() if yes}
    next_day = due_date(created, 1, calendar)
    if next_day is None:
        raise ValueError("tracking_calendar_inconsistent")
    during = intraday(created, opened)
    entry_day = created.astimezone(BEIJING).date() if during else next_day
    if not during:
        result.entry_at = dt.datetime.combine(entry_day, dt.time(9, 30), BEIJING)
    else:
        # END-stamped bars: use the immediate next session slot, never skip a
        # missing minute and silently enter at a later observed price.
        slot_start = created.astimezone(BEIJING).replace(second=0, microsecond=0)
        if created.second or created.microsecond:
            slot_start += dt.timedelta(minutes=1)
        if dt.time(11, 30) <= slot_start.time() < dt.time(13):
            slot_start = slot_start.replace(hour=13, minute=0)
        elif slot_start.time() >= dt.time(15):
            slot_start = dt.datetime.combine(next_day, dt.time(9, 30), BEIJING)
        entry_day = slot_start.date()
        if any(r["ts"] == slot_start + dt.timedelta(minutes=1) for r in minutes):
            result.entry_at = slot_start
    if now < result.exit_at:
        return result
    result.state = "unavailable"
    cutoff = min(
        now,
        dt.datetime.combine(due + dt.timedelta(days=1), dt.time.min, BEIJING)
        - dt.timedelta(microseconds=1),
    )
    evidence: list[Evidence] = []

    def proof(key: str, value: object, at: dt.datetime, unit: str | None = None) -> None:
        evidence.append(
            Evidence(
                id="tracking:" + key,
                key=key,
                value=None if value is None else str(value),
                unit=unit,
                provider=DataProvider.SYSTEM,
                endpoint="tracking:immutable-input:"
                + (
                    "000300.SH"
                    if key.startswith("benchmark_")
                    else str(conclusion.get("security_code", "unknown"))
                ),
                data_as_of=at,
                fetched_at=now,
                epistemic_type=EpistemicType.ESTIMATE,
            )
        )

    missing: list[str] = []
    entry_facts = facts.get(entry_day.isoformat(), {})
    t1_facts = facts.get(next_day.isoformat(), {})
    action = result.action
    excluded = None
    untradable = None
    if action == "wait":
        excluded = "wait"
    elif action == "hold" and forced_hold is True:
        excluded = "forced_hold"
    elif entry_facts.get("is_suspended") is True:
        untradable = "suspended"
    elif action in {"buy", "add"} and entry_facts.get("limit_locked_up") is True:
        untradable = "limit_locked_up"
    elif action in {"sell", "reduce"} and entry_facts.get("limit_locked_down") is True:
        untradable = "limit_locked_down"
    elif action == "hold" and (
        t1_facts.get("is_suspended") is True or t1_facts.get("limit_locked_down") is True
    ):
        excluded = "passive_hold_t1"
    needed = ["is_suspended"]
    if action in {"buy", "add"}:
        needed.append("limit_locked_up")
    if action in {"sell", "reduce"}:
        needed.append("limit_locked_down")
    for key in needed:
        proof("entry." + key, entry_facts.get(key), close_at(entry_day))
        if entry_facts.get(key) is None:
            missing.append("tradability." + key)
    if action == "hold":
        proof("forced_hold", forced_hold, created)
        if forced_hold is None:
            missing.append("forced_hold")
        for key in ["is_suspended", "limit_locked_down"]:
            proof("t1." + key, t1_facts.get(key), close_at(next_day))
            if t1_facts.get(key) is None:
                missing.append("t1." + key)
    if during:
        # No source in minute_bars identifies raw adjustment/anchor continuity.
        # Never silently borrow the daily factor or the reference price.
        missing.append("minute_qfq_bridge_unverified")
        if result.entry_at is None:
            missing.append("next_minute_bar")
    else:
        sessions = [d.isoformat() for d in sorted(opened) if entry_day <= d <= due]
        frame = prepare(instrument, sessions, as_of=cutoff, factors=factors, registry={})
        dates = frame["visible_dates"]
        opens, closes = frame["series"]["f.open_qfq"], frame["series"]["f.close_qfq"]
        lookup = {d: i for i, d in enumerate(dates)}
        left, right = lookup.get(entry_day.isoformat()), lookup.get(due.isoformat())
        result.entry_price = opens[left] if left is not None else None
        result.exit_price = closes[right] if right is not None else None
        if result.entry_price is None or result.exit_price is None:
            missing.append("qfq_prices_or_factors")
        else:
            result.return_pct = interval_return(result.entry_price, result.exit_price)
        raw = {
            r["trade_date"]: r
            for r in instrument["bars"]
            if dt.datetime.fromisoformat(r["first_seen_at"]) <= cutoff
        }
        for date, key, field in [(entry_day, "entry_raw", "open"), (due, "exit_raw", "close")]:
            proof(key, raw.get(date.isoformat(), {}).get(field), close_at(date), "CNY/share")
        for key, value in [("entry_qfq", result.entry_price), ("exit_qfq", result.exit_price)]:
            proof(key, value, result.exit_at, "CNY/share")
        for i, factor in enumerate(factors):
            observed = dt.datetime.fromisoformat(factor["available_at"])
            if observed <= cutoff and factor["date"] <= due.isoformat():
                proof("factor:" + str(i), factor["value"], observed)
        indices = {
            r["trade_date"]: r
            for r in benchmark["bars"]
            if r.get("is_final") is True
            and dt.datetime.fromisoformat(r["first_seen_at"]) <= cutoff
            and close_at(dt.date.fromisoformat(r["trade_date"])) <= cutoff
        }
        start, end = indices.get(entry_day.isoformat()), indices.get(due.isoformat())
        result.benchmark_entry_price = Decimal(str(start["open"])) if start else None
        result.benchmark_exit_price = Decimal(str(end["close"])) if end else None
        if result.benchmark_entry_price is not None and result.benchmark_exit_price is not None:
            result.benchmark_return_pct = interval_return(
                result.benchmark_entry_price, result.benchmark_exit_price
            )
            if result.return_pct is not None:
                result.excess_pct = result.return_pct - result.benchmark_return_pct
        else:
            missing.append("benchmark_prices")
        proof(
            "benchmark_entry",
            result.benchmark_entry_price,
            result.entry_at or close_at(entry_day),
            "index_points",
        )
        proof("benchmark_exit", result.benchmark_exit_price, result.exit_at, "index_points")
        # Schema does not resolve close-only vs intraday path, nor ratio conventions.
        missing.extend(["drawdown_runup_path_definition", "invalidation_monitor_not_connected"])
    if excluded is not None:
        result.state, result.exclusion_reason = "excluded", excluded
    elif untradable is not None:
        result.state, result.exclusion_reason = "untradable", untradable
    elif result.return_pct is not None and not any(
        k.startswith(("tradability.", "t1.", "forced_hold")) for k in missing
    ):
        result.state = "complete"
        result.direction_correct = direction(action, result.excess_pct, period)
    result.evidence = evidence
    result.evidence_ids = [e.id for e in evidence]
    result.gaps = [gap(k) for k in sorted(set(missing))]
    return Result.model_validate(result.model_dump())
