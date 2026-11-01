"""业务配置文件 ``config/*.yaml`` 的结构校验（plan.md §6.1）。

- 每个文件对应一个 pydantic 模型，全部 ``extra="forbid"``、``frozen=True``：未知键、缺键、
  类型或取值不符 → :class:`pydantic.ValidationError`，进程启动即失败（plan §6.1 通用规则）。
- 默认值**只在 YAML 里**（plan §6.1 是唯一出处），这里不写默认值，只写类型与取值范围；
  因此五个文件缺一不可，``config/`` 顶层也不允许出现其他 yaml 文件（防止文件名拼错被忽略）。
- 范围约束只取 plan 明文给出的（如 ``quote_interval_s`` 下限 5、``per_minute_budget`` 热调上限
  5400、RC2 用户可调范围 5–50）以及“数值本身必须有意义”的约束（正数、上下界有序）。
- ``config/strategies/`` 不在本模块范围（由导入器处理，plan §2.5.14）。
"""

from __future__ import annotations

import datetime as dt
import itertools
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PosInt = Annotated[int, Field(gt=0)]
NonNegInt = Annotated[int, Field(ge=0)]
Ratio = Annotated[float, Field(ge=0, le=1)]
Pct = Annotated[Decimal, Field(ge=0, le=100)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _File(_Strict):
    schema_version: Literal[1]


def _ordered_pair(pair: tuple[Any, Any], what: str) -> None:
    if pair[0] > pair[1]:
        raise ValueError(f"{what}：下界不能大于上界")


# ---------------------------------------------------------------------------
# config/realtime.yaml
# ---------------------------------------------------------------------------


class RealtimeIntervals(_Strict):
    quote_interval_s: Annotated[int, Field(ge=5)]
    all_market_interval_s: PosInt
    pro_tier1_interval_s: PosInt
    pro_tier2_interval_s: PosInt
    #: ``null`` = 2 × ``quote_interval_s``（见 :attr:`effective_stale_threshold_s`）
    stale_threshold_s: PosInt | None

    @property
    def effective_stale_threshold_s(self) -> int:
        return self.stale_threshold_s or 2 * self.quote_interval_s


class RealtimeBoards(_Strict):
    main: bool
    chinext: bool
    star: bool
    bse: bool
    etf_cb_holdings_only: bool


Tier1Source = Literal["holding", "focus", "multi_user_watch", "single_user_watch"]


class RealtimeUniverse(_Strict):
    tier1_cap: PosInt
    universe_hard_cap: PosInt
    tier1_alert_ratio: Annotated[float, Field(gt=0, le=1)]
    tier1_priority: Annotated[list[Tier1Source], Field(min_length=1)]

    @model_validator(mode="after")
    def _check(self) -> RealtimeUniverse:
        if len(set(self.tier1_priority)) != len(self.tier1_priority):
            raise ValueError("tier1_priority 不能重复")
        if self.tier1_cap > self.universe_hard_cap:
            raise ValueError("tier1_cap 不能大于 universe_hard_cap")
        return self


class RealtimeWatchlist(_Strict):
    per_user_cap: PosInt
    focus_cap: PosInt
    holdings_import_warn: PosInt


class RealtimeFlipDetection(_Strict):
    debounce_rounds: PosInt
    invalidation_immediate: bool


class RealtimeAdaptive(_Strict):
    enabled: bool
    unchanged_ratio: Annotated[float, Field(gt=0, le=1)]
    unchanged_rounds: PosInt
    breaker_cooldown_s: NonNegInt


class RealtimeNotify(_Strict):
    cadence_default: Literal["realtime", "1min", "3min", "5min"]
    sse_heartbeat_s: PosInt
    sse_replay_window_s: PosInt
    poll_fallback_s: PosInt


class RealtimeDegradedProfile(_Strict):
    holdings_only: bool
    quote_interval_s: Annotated[int, Field(ge=5)]
    tier2_enabled: bool


class RealtimeConfig(_File):
    intervals: RealtimeIntervals
    boards: RealtimeBoards
    universe: RealtimeUniverse
    watchlist: RealtimeWatchlist
    flip_detection: RealtimeFlipDetection
    adaptive: RealtimeAdaptive
    notify: RealtimeNotify
    degraded_profile: RealtimeDegradedProfile


# ---------------------------------------------------------------------------
# config/ingest.yaml
# ---------------------------------------------------------------------------

#: plan §6.1：per_minute_budget “可热调，上调上限 5400”
PER_MINUTE_BUDGET_MAX = 5400


class IngestShares(_Strict):
    snapshot: NonNegInt
    minute_bars: NonNegInt
    other: NonNegInt


class IngestPriorityMinShare(_Strict):
    p0_intraday: Ratio
    p2_backfill_intraday: Ratio


class IngestBudget(_Strict):
    per_minute_budget: Annotated[int, Field(gt=0, le=PER_MINUTE_BUDGET_MAX)]
    max_concurrency: PosInt
    shares: IngestShares
    priority_min_share: IngestPriorityMinShare

    @model_validator(mode="after")
    def _check(self) -> IngestBudget:
        s = self.shares
        if s.snapshot + s.minute_bars + s.other > self.per_minute_budget:
            raise ValueError("shares 合计不能超过 per_minute_budget")
        return self


class IngestBackoff(_Strict):
    base_s: PosInt
    max_s: PosInt
    breaker_open_s: PosInt

    @model_validator(mode="after")
    def _check(self) -> IngestBackoff:
        _ordered_pair((self.base_s, self.max_s), "backoff base_s/max_s")
        return self


class IngestLeader(_Strict):
    lock_key: Annotated[str, Field(min_length=1)]
    lease_s: PosInt
    renew_every_s: PosInt

    @model_validator(mode="after")
    def _check(self) -> IngestLeader:
        if self.renew_every_s >= self.lease_s:
            raise ValueError("renew_every_s 必须小于 lease_s")
        return self


class IngestHeartbeat(_Strict):
    key: Annotated[str, Field(min_length=1)]
    paused_key: Annotated[str, Field(min_length=1)]
    interval_s: PosInt
    ttl_s: PosInt
    stale_after_s: PosInt

    @model_validator(mode="after")
    def _check(self) -> IngestHeartbeat:
        if not self.interval_s < self.stale_after_s <= self.ttl_s:
            raise ValueError("需满足 interval_s < stale_after_s <= ttl_s")
        if self.key == self.paused_key:
            raise ValueError("key 与 paused_key 不能相同")
        return self


class IngestEgress(_Strict):
    check_on_start: bool


class IngestOnDemand(_Strict):
    coalesce_window_s: NonNegInt
    priority: Annotated[str, Field(pattern=r"^p[0-2]_[a-z_]+$")]


class IngestConfig(_File):
    budget: IngestBudget
    backoff: IngestBackoff
    leader: IngestLeader
    heartbeat: IngestHeartbeat
    egress: IngestEgress
    on_demand: IngestOnDemand


# ---------------------------------------------------------------------------
# config/market_rules.yaml
# ---------------------------------------------------------------------------


class PriceLimitPct(_Strict):
    main_board: Annotated[Decimal, Field(gt=0, le=100)]
    main_board_st: Annotated[Decimal, Field(gt=0, le=100)]
    chinext: Annotated[Decimal, Field(gt=0, le=100)]
    star: Annotated[Decimal, Field(gt=0, le=100)]
    bse: Annotated[Decimal, Field(gt=0, le=100)]


class NoLimit(_Strict):
    registered_ipo_first_days: NonNegInt
    bse_ipo_first_days: NonNegInt
    delisting_period_first_day: bool


class Lot(_Strict):
    buy_lot: PosInt
    star_min_buy: PosInt
    star_step: PosInt
    bse_min_buy: PosInt
    bse_step: PosInt


Session = tuple[dt.time, dt.time]


class Sessions(_Strict):
    call_auction: Session
    morning: Session
    afternoon: Session
    closing_auction: Session

    @model_validator(mode="after")
    def _check(self) -> Sessions:
        order = [self.call_auction, self.morning, self.afternoon, self.closing_auction]
        for start, end in order:
            if start >= end:
                raise ValueError("交易时段开始时间必须早于结束时间")
        for prev, nxt in itertools.pairwise(order):
            if prev[1] > nxt[0]:
                raise ValueError("交易时段不能重叠且须按时间顺序")
        return self


class Fees(_Strict):
    stamp_duty_sell_pct: Pct
    transfer_fee_pct: Pct
    commission_rate_default_pct: Pct | None
    commission_min_yuan: Annotated[Decimal, Field(ge=0)]
    slippage_default_pct: Pct


class ImpactTier(_Strict):
    #: 参与率上界（%，含）；``null`` = 最后一档（无上界）
    max_participation_pct: Annotated[Decimal, Field(gt=0)] | None
    bp: NonNegInt


class ImpactCost(_Strict):
    adv_window_days: PosInt
    tiers: Annotated[list[ImpactTier], Field(min_length=1)]

    @model_validator(mode="after")
    def _check(self) -> ImpactCost:
        bounds = [t.max_participation_pct for t in self.tiers]
        if bounds[-1] is not None or any(b is None for b in bounds[:-1]):
            raise ValueError("impact_cost.tiers：只有最后一档的 max_participation_pct 为 null")
        finite = [b for b in bounds if b is not None]
        if finite != sorted(finite) or len(set(finite)) != len(finite):
            raise ValueError("impact_cost.tiers：参与率上界须严格递增")
        return self


class Unfillable(_Strict):
    one_price_limit_up_blocks_buy: bool
    one_price_limit_down_blocks_sell: bool
    skip_suspended: bool


class MarketRuleSegment(_Strict):
    effective_from: dt.date
    price_limit_pct: PriceLimitPct
    no_limit: NoLimit
    lot: Lot
    sessions: Sessions
    t_plus: NonNegInt
    fees: Fees
    impact_cost: ImpactCost
    unfillable: Unfillable


class MarketRulesConfig(_File):
    segments: Annotated[list[MarketRuleSegment], Field(min_length=1)]

    @model_validator(mode="after")
    def _check(self) -> MarketRulesConfig:
        dates = [s.effective_from for s in self.segments]
        if len(set(dates)) != len(dates):
            raise ValueError("segments.effective_from 不能重复")
        return self

    def segment_for(self, day: dt.date) -> MarketRuleSegment | None:
        """``day`` 当天有效的规则段（effective_from ≤ day 中最晚的一段）。"""
        eligible = [s for s in self.segments if s.effective_from <= day]
        return max(eligible, key=lambda s: s.effective_from) if eligible else None


# ---------------------------------------------------------------------------
# config/risk_controls.yaml
# ---------------------------------------------------------------------------


class Rc1StopTake(_Strict):
    enabled: bool
    long_horizon_default_stop_pct: Annotated[Decimal, Field(lt=0, ge=-100)]
    clamp_to_price_limit: bool


class Rc2PositionCap(_Strict):
    enabled: bool
    #: plan §6.1：用户可调范围 5–50，系统默认也须落在该范围内
    single_position_max_pct: Annotated[Decimal, Field(ge=5, le=50)]


PctRange = tuple[Annotated[int, Field(ge=0, le=100)], Annotated[int, Field(ge=0, le=100)]]


class RegimeRanges(_Strict):
    uptrend: PctRange
    range: PctRange
    downtrend: PctRange

    @model_validator(mode="after")
    def _check(self) -> RegimeRanges:
        for name in ("uptrend", "range", "downtrend"):
            _ordered_pair(getattr(self, name), f"regime_ranges.{name}")
        return self


class Rc3TotalExposure(_Strict):
    enabled: bool
    regime_ranges: RegimeRanges
    regime_confirm_days: PosInt


class Rc4SectorConcentration(_Strict):
    enabled: bool
    sw_l1_max_pct: Annotated[Decimal, Field(gt=0, le=100)]
    concept_max_pct: Annotated[Decimal, Field(gt=0, le=100)]


class Rc5LossStreakDrawdown(_Strict):
    enabled: bool
    closed_loss_streak: PosInt
    drawdown_from_peak_pct: Annotated[Decimal, Field(gt=0, le=100)]
    strategy_sim_fail_streak: PosInt
    pause_on_trigger: bool
    pause_days: PosInt


Rc6Check = Literal[
    "opposite_side",
    "qty_over_plan",
    "held_after_invalidation",
    "buy_without_stop",
    "buy_during_wait",
]


class Rc6PlanViolation(_Strict):
    enabled: bool
    checks: list[Rc6Check]

    @model_validator(mode="after")
    def _check(self) -> Rc6PlanViolation:
        if len(set(self.checks)) != len(self.checks):
            raise ValueError("rc6_plan_violation.checks 不能重复")
        return self


class CoolingOffAfterStop(_Strict):
    enabled: bool
    days: PosInt


class Executability(_Strict):
    low_confidence_threshold: Ratio
    new_listing_min_days: NonNegInt
    cooling_off_after_stop: CoolingOffAfterStop
    same_template_cooldown_days: NonNegInt


class RiskControlsConfig(_File):
    rc1_stop_take: Rc1StopTake
    rc2_position_cap: Rc2PositionCap
    rc3_total_exposure: Rc3TotalExposure
    rc4_sector_concentration: Rc4SectorConcentration
    rc5_loss_streak_drawdown: Rc5LossStreakDrawdown
    rc6_plan_violation: Rc6PlanViolation
    executability: Executability


# ---------------------------------------------------------------------------
# config/horizon_classifier.yaml
# ---------------------------------------------------------------------------

FeatureKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.]*$")]
Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class Recompute(_Strict):
    on: list[Literal["import_confirm", "watchlist_add", "weekly"]]
    weekly_day: Weekday


class HorizonClassifierConfig(_File):
    version_no: PosInt
    suitable_threshold: Annotated[int, Field(ge=0, le=100)]
    reasons_per_horizon: tuple[PosInt, PosInt]
    recompute: Recompute
    #: 必须都在 feature_catalog 中（plan §6.1）；该检查需要数据库，留给导入器（见报告 TODO）
    features: Annotated[list[FeatureKey], Field(min_length=1)]
    #: 规则正文由策略研究员给出后由导入器写入；结构未定，这里只要求是映射
    rules: dict[str, Any]

    @model_validator(mode="after")
    def _check(self) -> HorizonClassifierConfig:
        _ordered_pair(self.reasons_per_horizon, "reasons_per_horizon")
        if len(set(self.features)) != len(self.features):
            raise ValueError("features 不能重复")
        return self


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------


class BusinessConfig(_Strict):
    """``config/`` 顶层五个文件；键为文件名（不含扩展名）。"""

    realtime: RealtimeConfig
    ingest: IngestConfig
    market_rules: MarketRulesConfig
    risk_controls: RiskControlsConfig
    horizon_classifier: HorizonClassifierConfig


BUSINESS_FILES: tuple[str, ...] = tuple(BusinessConfig.model_fields)
