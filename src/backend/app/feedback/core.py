"""P2N-08 slice 1. Pure, owned, PIT arithmetic; never writes or changes actions.

No implicit market calendars, account NAV, trade fees, strategy horizon or
internal-evaluation enablement. Callers must supply independently proven inputs.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Literal

from app.config_files import HealthFeedbackConfig, Rc5LossStreakDrawdown


@dataclass(frozen=True)
class Metric:
    value: Decimal | int | None
    triggered: bool | None
    evidence_ids: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()


def timestamp(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("feedback_timezone_required")
    return value


def finite(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("feedback_finite_decimal_required")
    return value


def refs(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


@dataclass(frozen=True)
class Observation:
    owner: uuid.UUID
    strategy_version: uuid.UUID
    suggestion_id: uuid.UUID
    instance_id: uuid.UUID | None
    instance_created_at: dt.datetime | None
    horizon: str | None
    horizon_days: int
    state: str
    direction_correct: bool | None
    exit_at: dt.datetime | None
    available_at: dt.datetime
    evidence_ids: tuple[str, ...]


def simulated_failures(
    owner: uuid.UUID,
    version: uuid.UUID,
    observations: Sequence[Observation],
    config: Rc5LossStreakDrawdown,
    *,
    version_horizon: str | None,
    at: dt.datetime,
) -> Metric:
    timestamp(at)
    mapping = config.sim_fail_horizon_by_horizon
    if mapping is None:
        return Metric(None, None, gaps=("sim_fail_horizon_config_missing",))
    groups: dict[tuple[uuid.UUID, int], list[Observation]] = defaultdict(list)
    for row in observations:
        if row.owner != owner or row.strategy_version != version:
            continue
        if timestamp(row.available_at) > at:
            continue
        groups[(row.suggestion_id, row.horizon_days)].append(row)
    selected: list[Observation] = []
    gaps: set[str] = set()
    for group in groups.values():
        if len(group) > 1 and any(
            r.instance_created_at is None or r.instance_id is None for r in group
        ):
            gaps.add("sim_fail_instance_order_unknown")
            continue
        row = min(
            group,
            key=lambda r: (
                timestamp(r.instance_created_at) if r.instance_created_at else at,
                str(r.instance_id),
            ),
        )
        same_instance = [
            r
            for r in group
            if (r.instance_created_at, r.instance_id) == (row.instance_created_at, row.instance_id)
        ]
        if any(r != row for r in same_instance):
            gaps.add("sim_fail_result_revision_unresolved")
            continue
        horizon = row.horizon if row.horizon is not None else version_horizon
        if horizon not in mapping:
            gaps.add("sim_fail_horizon_unknown")
            continue
        if type(row.horizon_days) is not int:
            gaps.add("sim_fail_horizon_unknown")
            continue
        if row.horizon_days != mapping[horizon]:
            continue
        if row.state != "complete":
            continue
        if row.exit_at is None or type(row.direction_correct) is not bool:
            gaps.add("sim_fail_result_unknown")
            continue
        if not row.evidence_ids:
            gaps.add("sim_fail_evidence_missing")
            continue
        if timestamp(row.exit_at) <= at:
            selected.append(row)
    selected.sort(key=lambda r: (r.exit_at, str(r.suggestion_id)))
    failures = 0
    for row in selected:
        failures = failures + 1 if row.direction_correct is False else 0
    if not groups:
        gaps.add("sim_fail_observations_missing")
    return Metric(
        failures,
        failures >= config.strategy_sim_fail_streak,
        refs([e for row in selected for e in row.evidence_ids]),
        tuple(sorted(gaps)),
    )


@dataclass(frozen=True)
class Fill:
    owner: uuid.UUID
    account: uuid.UUID
    security: str
    id: uuid.UUID
    executed_at: dt.datetime
    available_at: dt.datetime
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal | None
    fees: Decimal | None
    evidence_ids: tuple[str, ...]
    active: bool = True


@dataclass(frozen=True)
class ClosedSegment:
    security: str
    closed_at: dt.datetime
    closing_trade_id: uuid.UUID
    pnl: Decimal | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ClosedLosses:
    segments: tuple[ClosedSegment, ...]
    metric: Metric


def closed_losses(
    owner: uuid.UUID,
    account: uuid.UUID,
    fills: Sequence[Fill],
    config: Rc5LossStreakDrawdown,
    *,
    at: dt.datetime,
) -> ClosedLosses:
    timestamp(at)
    groups: dict[str, list[Fill]] = defaultdict(list)
    visible: dict[uuid.UUID, Fill] = {}
    for row in fills:
        if (
            row.owner == owner
            and row.account == account
            and timestamp(row.executed_at) <= at
            and timestamp(row.available_at) <= at
        ):
            previous = visible.get(row.id)
            if previous is not None and previous != row:
                raise ValueError("feedback_trade_revision_unresolved")
            visible[row.id] = row
    for row in visible.values():
        if row.active:
            groups[row.security].append(row)
    closed: list[ClosedSegment] = []
    gaps: set[str] = set()
    for code, rows in groups.items():
        quantity = Decimal(0)
        pnl = Decimal(0)
        known = True
        evidence: list[str] = []
        for row in sorted(rows, key=lambda r: (r.executed_at, str(r.id))):
            if finite(row.quantity) <= 0:
                raise ValueError("feedback_trade_quantity_positive")
            if row.price is not None and finite(row.price) <= 0:
                raise ValueError("feedback_trade_price_positive")
            if row.fees is not None and finite(row.fees) < 0:
                raise ValueError("feedback_trade_fee_nonnegative")
            if row.side not in {"buy", "sell"}:
                raise ValueError("feedback_trade_direction_invalid")
            if row.side == "sell" and row.quantity > quantity:
                # A truncated opening segment is never counted as a closed loss.
                gaps.add("closed_segment_opening_missing")
                quantity, pnl, known, evidence = Decimal(0), Decimal(0), True, []
                continue
            evidence.extend(row.evidence_ids)
            known = (
                known and row.price is not None and row.fees is not None and bool(row.evidence_ids)
            )
            if row.price is not None and row.fees is not None:
                pnl += (row.quantity * row.price * (1 if row.side == "sell" else -1)) - row.fees
            quantity += row.quantity * (1 if row.side == "buy" else -1)
            if quantity == 0:
                closed.append(
                    ClosedSegment(
                        code, row.executed_at, row.id, pnl if known else None, refs(evidence)
                    )
                )
                if not known:
                    gaps.add("closed_segment_price_or_fees_missing")
                pnl, known, evidence = Decimal(0), True, []
    closed.sort(key=lambda r: (r.closed_at, str(r.closing_trade_id)))
    count = 0
    for segment in closed:
        if segment.pnl is not None and segment.pnl != 0:
            count = count + 1 if segment.pnl < 0 else 0
    if not closed:
        gaps.add("closed_segments_missing")
    return ClosedLosses(
        tuple(closed),
        Metric(
            count,
            count >= config.closed_loss_streak,
            refs([e for row in closed for e in row.evidence_ids]),
            tuple(sorted(gaps)),
        ),
    )


@dataclass(frozen=True)
class NavPoint:
    owner: uuid.UUID
    account: uuid.UUID
    at: dt.datetime
    available_at: dt.datetime
    value: Decimal | None
    evidence_ids: tuple[str, ...]


def account_drawdown(
    owner: uuid.UUID,
    account: uuid.UUID,
    points: Sequence[NavPoint],
    config: Rc5LossStreakDrawdown,
    *,
    at: dt.datetime,
    complete_history: bool,
) -> Metric:
    timestamp(at)
    rows = [
        r
        for r in points
        if r.owner == owner
        and r.account == account
        and timestamp(r.at) <= at
        and timestamp(r.available_at) <= at
    ]
    if not complete_history or not rows or any(r.value is None or not r.evidence_ids for r in rows):
        return Metric(None, None, gaps=("account_nav_history_missing",))
    rows.sort(key=lambda r: r.at)
    # Conflicting revisions at the same source instant require an as-of source
    # resolver, not an arbitrary list-order winner inside arithmetic.
    if len({r.at for r in rows}) != len(rows):
        return Metric(None, None, gaps=("account_nav_revision_unresolved",))
    values = [finite(r.value) for r in rows if r.value is not None]
    peak = max(values)
    if peak <= 0 or any(v < 0 for v in values):
        return Metric(None, None, gaps=("account_nav_denominator_unknown",))
    with localcontext() as ctx:
        ctx.prec = 40
        drawdown = (peak - values[-1]) / peak * 100
    return Metric(
        drawdown,
        drawdown >= config.drawdown_from_peak_pct,
        refs([e for row in rows for e in row.evidence_ids]),
    )


@dataclass(frozen=True)
class Weight:
    n: int
    raw: Decimal | None
    health_weight: Decimal | None
    priority_weight: Decimal | None
    gaps: tuple[str, ...] = ()


def priority_weight(n: int, wins: int, avg_excess_pct: Decimal | None, *, enabled: bool) -> Weight:
    if type(n) is not int or type(wins) is not int or n < 0 or not 0 <= wins <= n:
        raise ValueError("feedback_sample_count_invalid")
    if avg_excess_pct is None:
        weight = Decimal(1) if n < 20 else None
        return Weight(
            n, None, weight, weight if enabled else Decimal(1), ("health_excess_missing",)
        )
    finite(avg_excess_pct)
    with localcontext() as ctx:
        ctx.prec = 40
        smooth = (Decimal(wins) + Decimal(10) * Decimal(".5")) / (n + 10)
        x = avg_excess_pct / 5
        # Stable decimal tanh, including extreme valid positive/negative returns.
        tail = (-2 * abs(x)).exp()
        excess = ((1 - tail) / (1 + tail)) * (1 if x >= 0 else -1)
        raw = 1 + Decimal(".6") * (smooth - Decimal(".5")) * 2 + Decimal(".4") * excess
        weight = Decimal(1) if n < 20 else max(Decimal(".3"), min(Decimal("1.2"), raw))
    return Weight(n, raw, weight, weight if enabled else Decimal(1))


@dataclass(frozen=True)
class HealthDay:
    date: dt.date
    n: int
    weight: Decimal | None
    robustness: Decimal | None = None


@dataclass(frozen=True)
class Health:
    state: str
    low_streak: int
    high_streak: int
    review_streak: int
    proposed_action: Literal["none", "review"]
    gaps: tuple[str, ...]


def health(
    current_state: str,
    days: Sequence[dt.date] | None,
    records: Sequence[HealthDay],
    *,
    internal_enabled: bool,
    baseline: Decimal | None,
    config: HealthFeedbackConfig | None,
) -> Health:
    """days must come from the real calendar, never inferred weekdays.

    No DB transition occurs here; returned proposals require the later worker.
    A missing row resets streaks rather than quietly skipping a trading day.
    """
    if days is None or not days:
        return Health(current_state, 0, 0, 0, "none", ("health_calendar_missing",))
    if list(days) != sorted(set(days)):
        raise ValueError("feedback_trading_days_must_be_ordered_unique")
    if len({r.date for r in records}) != len(records):
        raise ValueError("feedback_daily_revision_unresolved")
    if current_state not in {"published", "observing"}:
        return Health(current_state, 0, 0, 0, "none", ())
    by_day = {r.date: r for r in records}
    low = high = review = internal_low = 0
    state = current_state
    gaps: set[str] = set()
    proposal: Literal["none", "review"] = "none"
    for day in days:
        row = by_day.get(day)
        if row is None or row.weight is None:
            low = high = review = internal_low = 0
            gaps.add("health_daily_missing")
            continue
        if type(row.n) is not int or row.n < 0:
            raise ValueError("feedback_health_n_invalid")
        weight = finite(row.weight)
        if not Decimal(".3") <= weight <= Decimal("1.2"):
            raise ValueError("feedback_health_weight_outside_clamp")
        if row.n < 20:
            low = high = review = internal_low = 0
            continue
        internal_ok, degraded, severe = True, False, False
        if internal_enabled:
            if baseline is None or finite(baseline) <= 0 or row.robustness is None:
                internal_ok = False
                gaps.add("health_internal_evidence_missing")
            else:
                robustness = finite(row.robustness)
                degraded, severe = (
                    robustness < baseline * Decimal(".7"),
                    robustness < baseline * Decimal(".5"),
                )
                if config is None:
                    internal_ok = False
                    gaps.add("health_internal_recover_ratio_missing")
                else:
                    internal_ok = robustness >= baseline * config.internal_recover_ratio
        low = low + 1 if weight < Decimal(".8") else 0
        high = high + 1 if weight >= Decimal(".9") and internal_ok else 0
        review = review + 1 if weight < Decimal(".6") else 0
        internal_low = internal_low + 1 if severe else 0
        if state == "published" and (low >= 5 or degraded):
            state = "observing"
        elif state == "observing" and high >= 10:
            state = "published"
    if state == "observing" and (review >= 20 or internal_low >= 20):
        proposal = "review"
    return Health(state, low, high, review, proposal, tuple(sorted(gaps)))


def rc5_state(
    config: Rc5LossStreakDrawdown, metrics: Sequence[Metric]
) -> Literal["disabled", "triggered", "unknown", "ok"]:
    """Threshold result only; never pause or change an action from a read."""
    if not config.enabled:
        return "disabled"
    if any(m.triggered is True for m in metrics):
        return "triggered"
    if len(metrics) != 3 or any(m.value is None or m.gaps for m in metrics):
        return "unknown"
    return "ok"
