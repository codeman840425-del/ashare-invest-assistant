"""RC6 quantity/opposite-side projection from explicit owned PIT facts only.

No DB reader, event writer, worker or orders. Caller must prove timeline and
trade coverage; an absent history is never an empty successful history.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from app.feedback.core import finite, timestamp
from app.schemas.enums import DataProvider, EpistemicType, RiskControl, RiskLevel
from app.signals.models import Evidence, RiskFlag

SH = ZoneInfo("Asia/Shanghai")
SIDES = {"buy", "sell"}
SUPPORTED = {"opposite_side", "qty_over_plan"}


@dataclass(frozen=True)
class Plan:
    id: str
    owner: uuid.UUID
    account: uuid.UUID
    code: str
    side: str
    quantity: Decimal | None
    start: dt.datetime
    end: dt.datetime | None
    available_at: dt.datetime
    end_known_at: dt.datetime | None = None


@dataclass(frozen=True)
class Trade:
    id: str
    owner: uuid.UUID
    account: uuid.UUID
    code: str
    side: str
    quantity: Decimal
    executed_at: dt.datetime | dt.date
    available_at: dt.datetime
    voided: bool = False


@dataclass(frozen=True)
class Facts:
    owner: uuid.UUID
    account: uuid.UUID
    code: str
    plans: tuple[Plan, ...]
    trades: tuple[Trade, ...]
    coverage_at: dt.datetime | None
    coverage_complete: bool = False


@dataclass(frozen=True)
class Selection:
    plan: Plan | None
    opposite: bool | None
    gaps: tuple[str, ...] = ()


@dataclass(frozen=True)
class Assessment:
    flags: tuple[RiskFlag, ...]
    evidence: tuple[Evidence, ...]
    gaps: tuple[str, ...]
    quantities: dict[str, Decimal]
    logical_keys: tuple[str, ...]


def execution(value: dt.datetime | dt.date) -> dt.datetime:
    return (
        timestamp(value)
        if isinstance(value, dt.datetime)
        else dt.datetime.combine(value, dt.time(15), SH)
    )


def select_plan(plans: tuple[Plan, ...], trade: Trade, *, at: dt.datetime) -> Selection:
    timestamp(at)
    point = execution(trade.executed_at)
    if timestamp(trade.available_at) > at or point > at:
        return Selection(None, None, ("plan_trade_not_yet_visible",))
    eligible = []
    for plan in plans:
        if (plan.owner, plan.account, plan.code) != (trade.owner, trade.account, trade.code):
            continue
        if timestamp(plan.available_at) > at:
            continue
        timestamp(plan.start)
        if plan.end is not None:
            timestamp(plan.end)
            if plan.end <= plan.start:
                raise ValueError("rc6_plan_interval_invalid")
            if plan.end_known_at is None:
                return Selection(None, None, ("plan_end_provenance_missing",))
            end = plan.end if timestamp(plan.end_known_at) <= at else None
        else:
            end = None
        if plan.side not in SIDES or trade.side not in SIDES:
            return Selection(None, None, ("plan_direction_unknown",))
        # A date-only trade cannot be allocated across any same-day boundary.
        if not isinstance(trade.executed_at, dt.datetime) and (
            plan.start.astimezone(SH).date() == point.astimezone(SH).date()
            or (end is not None and end.astimezone(SH).date() == point.astimezone(SH).date())
        ):
            return Selection(None, None, ("plan_date_precision_ambiguous",))
        if plan.start <= point and (end is None or point < end):
            eligible.append(plan)
    if not eligible:
        return Selection(None, None, ("plan_not_effective_at_trade",))
    same = [p for p in eligible if p.side == trade.side]
    pool = same or eligible
    latest = max(p.start for p in pool)
    chosen = min((p for p in pool if p.start == latest), key=lambda p: p.id)
    return Selection(chosen, chosen.side != trade.side)


def _evidence(key: str, value: str, point: dt.datetime, fetched: dt.datetime) -> Evidence:
    return Evidence(
        id="rc6:" + key,
        key="plan_" + key,
        value=value,
        unit=None,
        provider=DataProvider.SYSTEM,
        endpoint="owned_rc6_facts:" + key,
        data_as_of=point,
        fetched_at=fetched,
        epistemic_type=EpistemicType.ESTIMATE,
    )


def assess(facts: Facts, *, at: dt.datetime, checks: tuple[str, ...]) -> Assessment:
    with localcontext() as ctx:
        ctx.prec = max(
            64,
            sum(len(str(t.quantity)) for t in facts.trades)
            + sum(len(str(p.quantity)) for p in facts.plans)
            + 64,
        )
        return _assess(facts, at=at, checks=checks)


def _assess(facts: Facts, *, at: dt.datetime, checks: tuple[str, ...]) -> Assessment:
    timestamp(at)
    missing = {"plan_check_not_connected:" + c for c in checks if c not in SUPPORTED}
    if (
        not facts.coverage_complete
        or facts.coverage_at is None
        or timestamp(facts.coverage_at) > at
    ):
        return Assessment(
            (), (), tuple(sorted(missing | {"plan_history_coverage_missing"})), {}, ()
        )
    if facts.coverage_at != at:
        return Assessment((), (), ("plan_history_coverage_as_of_mismatch",), {}, ())
    plans: dict[str, Plan] = {}
    for p in facts.plans:
        if (p.owner, p.account, p.code) != (facts.owner, facts.account, facts.code) or timestamp(
            p.available_at
        ) > at:
            continue
        if p.id in plans and plans[p.id] != p:
            return Assessment((), (), ("plan_version_revision_unresolved",), {}, ())
        plans[p.id] = p
    trades: dict[str, Trade] = {}
    for t in facts.trades:
        if (t.owner, t.account, t.code) != (facts.owner, facts.account, facts.code):
            continue
        if timestamp(t.available_at) > at or execution(t.executed_at) > at:
            continue
        if t.id in trades and trades[t.id] != t:
            return Assessment((), (), ("plan_trade_revision_unresolved",), {}, ())
        if type(t.voided) is not bool:
            raise ValueError("rc6_void_state_requires_boolean")
        if not t.voided and finite(t.quantity) <= 0:
            raise ValueError("rc6_quantity_positive")
        trades[t.id] = t
    evidence = {
        _evidence("coverage", "complete", facts.coverage_at, facts.coverage_at).id: _evidence(
            "coverage", "complete", facts.coverage_at, facts.coverage_at
        )
    }
    quantities: dict[str, Decimal] = {}
    used: dict[str, list[str]] = {}
    flags: dict[str, RiskFlag] = {}
    for t in sorted(trades.values(), key=lambda t: (execution(t.executed_at), t.id)):
        if t.voided:
            continue
        selected = select_plan(tuple(plans.values()), t, at=at)
        missing.update(selected.gaps)
        if selected.plan is None:
            continue
        p = selected.plan
        pe = _evidence(
            "version:" + p.id,
            json.dumps(
                {
                    "side": p.side,
                    "quantity": str(p.quantity),
                    "from": p.start.isoformat(),
                    "until": p.end.isoformat()
                    if p.end is not None and p.end_known_at is not None and p.end_known_at <= at
                    else None,
                },
                sort_keys=True,
            ),
            p.start,
            p.available_at,
        )
        te = _evidence("trade:" + t.id, str(t.quantity), execution(t.executed_at), t.available_at)
        evidence[pe.id], evidence[te.id] = pe, te
        used.setdefault(p.id, []).extend([pe.id, te.id])
        check = None
        if selected.opposite:
            if "opposite_side" in checks:
                check = "opposite_side"
        else:
            quantities[p.id] = quantities.get(p.id, Decimal(0)) + t.quantity
            if "qty_over_plan" in checks:
                if p.quantity is None:
                    missing.add("planned_quantity_missing")
                elif finite(p.quantity) < 0:
                    raise ValueError("rc6_plan_quantity_nonnegative")
                elif quantities[p.id] > p.quantity:
                    check = "qty_over_plan"
        if check:
            key = p.id + ":" + check
            flags[key] = RiskFlag(
                control=RiskControl.PLAN_VIOLATION,
                level=RiskLevel.WARNING,
                message="成交违反有效计划：" + check,
                gated_actions=[],
                quantity_cap=None,
                evidence_ids=sorted(set(used[p.id])),
            )
    return Assessment(
        tuple(flags[k] for k in sorted(flags)),
        tuple(evidence.values()),
        tuple(sorted(missing)),
        quantities,
        tuple(sorted(flags)),
    )
