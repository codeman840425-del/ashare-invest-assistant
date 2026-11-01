"""业务配置文件 ``config/*.yaml`` 的结构校验（plan.md §6.1）。

- 每个文件对应一个 pydantic 模型，全部 ``extra="forbid"``、``frozen=True``：未知键、缺键、
  类型或取值不符 → :class:`pydantic.ValidationError`，进程启动即失败（plan §6.1 通用规则）。
- 默认值**只在 YAML 里**（plan §6.1 是唯一出处），这里不写默认值，只写类型与取值范围；
  因此六个文件缺一不可，``config/`` 顶层也不允许出现其他 yaml 文件（防止文件名拼错被忽略）。
- 范围约束只取 plan 明文给出的（如 ``quote_interval_s`` 下限 5、``per_minute_budget`` 热调上限
  5400、RC2 用户可调范围 5–50）以及“数值本身必须有意义”的约束（正数、上下界有序）。
- ``config/strategies/`` 不在本模块范围（由导入器处理，plan §2.5.14）。
"""

from __future__ import annotations

import datetime as dt
import itertools
from decimal import Decimal
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

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
    #: 参与率口径（T-A02 定）：只支持成交额口径 ``amount``
    adv_basis: Literal["amount"]
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


Board = Literal["main_board", "chinext", "star", "bse"]
#: 交易所（证券代码后缀 ``.SH`` / ``.SZ`` / ``.BJ``，契约 security_code）
Exchange = Literal["SH", "SZ", "BJ"]


class RiskWarning(_Strict):
    """风险警示股票（ST/*ST）额外约束（T-A02，market_rules_check.md M5/M6）。"""

    daily_buy_cap_shares: PosInt
    #: 50 万股上限（``daily_buy_cap_shares``）的适用板块（T006b §7：主板与创业板，科创板不适用）
    applies_to_boards: Annotated[list[Board], Field(min_length=1)]
    limit_order_only: bool
    #: ``limit_order_only`` 只作用于这些交易所的证券（T-A03：仅沪 4.4.9 → ``[SH]``）
    limit_order_only_exchanges: list[Exchange]

    @model_validator(mode="after")
    def _check(self) -> RiskWarning:
        if len(set(self.applies_to_boards)) != len(self.applies_to_boards):
            raise ValueError("risk_warning.applies_to_boards 不能重复")
        if len(set(self.limit_order_only_exchanges)) != len(self.limit_order_only_exchanges):
            raise ValueError("risk_warning.limit_order_only_exchanges 不能重复")
        if self.limit_order_only and not self.limit_order_only_exchanges:
            raise ValueError(
                "risk_warning.limit_order_only=true 时 limit_order_only_exchanges 不能为空"
            )
        return self

    def daily_buy_cap_for(self, board: Board) -> int | None:
        """该板块风险警示股票的单日累计买入上限（股）；不适用返回 ``None``。"""
        return self.daily_buy_cap_shares if board in self.applies_to_boards else None

    def limit_order_only_for(self, exchange: Exchange) -> bool:
        """该交易所风险警示股票是否只能限价申报。"""
        return self.limit_order_only and exchange in self.limit_order_only_exchanges


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
    risk_warning: RiskWarning


class MarketRulesConfig(_File):
    #: 规则只建模到此日（T-A02）；更早的日期 :meth:`segment_for` 返回 ``None``（“交易规则未建模”）
    modeled_from: dt.date
    segments: Annotated[list[MarketRuleSegment], Field(min_length=1)]

    @model_validator(mode="after")
    def _check(self) -> MarketRulesConfig:
        dates = [s.effective_from for s in self.segments]
        if len(set(dates)) != len(dates):
            raise ValueError("segments.effective_from 不能重复")
        if min(dates) != self.modeled_from:
            raise ValueError("modeled_from 必须等于最早一段的 effective_from（每段写全，不做继承）")
        return self

    def segment_for(self, day: dt.date) -> MarketRuleSegment | None:
        """``day`` 当天有效的规则段（effective_from ≤ day 中最晚的一段）。

        早于 ``modeled_from`` 返回 ``None``（交易规则未建模）。
        """
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

#: 分类器输入键（T-A02 统一前缀）：``f.*`` 须登记在 feature_catalog（导入器检查，需要数据库），
#: ``sec.*`` / ``user.*`` / ``profile.*`` 由系统提供
FeatureKey = Annotated[str, Field(pattern=r"^(f|sec|user|profile)\.[a-z][a-z0-9_]*$")]
Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
HorizonName = Literal["intraday_t", "short", "swing", "long"]
HORIZON_NAMES: tuple[HorizonName, ...] = ("intraday_t", "short", "swing", "long")
RecomputeTrigger = Literal["import_confirm", "watchlist_add", "weekly", "position_open_close"]
RuleId = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9]*$")]
Score = Annotated[int, Field(ge=0, le=100)]
#: 规则比较值：不做类型强转（``"true"`` 不会变成 ``True``；YAML 1.2 布尔见 app.config）
Scalar = StrictBool | StrictInt | StrictFloat | StrictStr
RuleOp = Literal["eq", "ne", "gt", "ge", "lt", "le", "in", "contains", "between", "not_null"]


class Recompute(_Strict):
    on: Annotated[list[RecomputeTrigger], Field(min_length=1)]
    weekly_day: Weekday

    @model_validator(mode="after")
    def _check(self) -> Recompute:
        if len(set(self.on)) != len(self.on):
            raise ValueError("recompute.on 不能重复")
        return self


def _check_op_value(op: RuleOp, value: object, has_value: bool) -> None:
    """horizon_classifier.md §4「边界与比较语义」：按 op 校验 value 的形状。

    ``value: null`` 与不写等价（深合并里 null 表示“未覆盖”，且 model_dump 会写出 None）。
    """
    if op == "not_null":
        if has_value:
            raise ValueError("op=not_null 不带 value")
        return
    if not has_value:
        raise ValueError(f"op={op} 必须给 value")
    if op == "between":
        if not (isinstance(value, list) and len(value) == 2):
            raise ValueError("op=between 的 value 必须是 [下界, 上界]")
        lo, hi = value
        if (
            isinstance(lo, bool)
            or isinstance(hi, bool)
            or not all(isinstance(x, int | float) for x in (lo, hi))
        ):
            raise ValueError("op=between 的上下界必须是数值")
        if lo > hi:
            raise ValueError("op=between：下界不能大于上界")
    elif op == "in":
        if not (isinstance(value, list) and value):
            raise ValueError("op=in 的 value 必须是非空列表")
    else:
        if isinstance(value, list):
            raise ValueError(f"op={op} 的 value 必须是标量")
        if op in {"gt", "ge", "lt", "le"} and (
            isinstance(value, bool) or not isinstance(value, int | float)
        ):
            raise ValueError(f"op={op} 的 value 必须是数值")


class _Cond(_Strict):
    id: RuleId
    input: FeatureKey
    op: RuleOp
    value: Scalar | list[Scalar] | None = None

    @model_validator(mode="after")
    def _check_cond(self) -> _Cond:
        _check_op_value(self.op, self.value, self.value is not None)
        return self


class ClassifierGate(_Cond):
    """闸门（HG*）：条件为真时 ``score: 0`` 或 ``cap``，二选一。"""

    horizons: Literal["all"] | Annotated[list[HorizonName], Field(min_length=1)]
    score: Literal[0] | None = None
    cap: Score | None = None
    reason: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def _check(self) -> ClassifierGate:
        if (self.score is None) == (self.cap is None):
            raise ValueError(f"闸门 {self.id}：score 与 cap 必须且只能给一个")
        return self


class ClassifierRequire(_Cond):
    """周期前提：条件为假（或输入为 null，not_null 除外）时 ``else_score: 0`` 或 ``else_cap``。"""

    else_score: Literal[0] | None = None
    else_cap: Score | None = None
    reason: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def _check(self) -> ClassifierRequire:
        if (self.else_score is None) == (self.else_cap is None):
            raise ValueError(f"前提 {self.id}：else_score 与 else_cap 必须且只能给一个")
        return self


class ClassifierBand(_Strict):
    op: RuleOp
    value: Scalar | list[Scalar] | None = None
    pts: Annotated[int, Field(gt=0, le=100)]

    @model_validator(mode="after")
    def _check(self) -> ClassifierBand:
        if self.op == "not_null":
            raise ValueError("分档不支持 op=not_null")
        _check_op_value(self.op, self.value, self.value is not None)
        return self


class ClassifierComponent(_Strict):
    id: RuleId
    input: FeatureKey
    transform: Literal["rank_pct"] | None = None
    #: 与 feature_catalog.unit 一致性由导入器检查（不一致拒绝导入，不静默换算）
    unit: Annotated[str, Field(min_length=1)] | None = None
    bands: Annotated[list[ClassifierBand], Field(min_length=1)]
    text: Annotated[str, Field(min_length=1)]

    @property
    def max_pts(self) -> int:
        return max(b.pts for b in self.bands)

    @model_validator(mode="after")
    def _check(self) -> ClassifierComponent:
        pts = [b.pts for b in self.bands]
        if pts != sorted(pts, reverse=True):
            raise ValueError(f"组件 {self.id}：分档须按 pts 从高到低排列（取第一个命中的分档）")
        if self.transform == "rank_pct":
            for b in self.bands:
                vals = b.value if isinstance(b.value, list) else [b.value]
                if any(
                    not isinstance(v, int | float) or isinstance(v, bool) or not 0 <= v <= 1
                    for v in vals
                ):
                    raise ValueError(f"组件 {self.id}：rank_pct 分档取值须在 [0, 1]")
        return self


class HorizonRuleSet(_Strict):
    requires: list[ClassifierRequire]
    components: Annotated[list[ClassifierComponent], Field(min_length=1)]


class HorizonRuleSets(_Strict):
    intraday_t: HorizonRuleSet
    short: HorizonRuleSet
    swing: HorizonRuleSet
    long: HorizonRuleSet


class DataMissingCap(_Strict):
    missing_points_ge: Annotated[int, Field(gt=0, le=100)]
    cap: Score


class HorizonRules(_Strict):
    """``rules`` 块，rule_schema 1（plan §6.1、horizon_classifier.md §3–§4，T-A02）。"""

    rule_schema: Literal[1]
    calibration: Annotated[str, Field(min_length=1)]
    rank_pct_universe: Annotated[str, Field(min_length=1)]
    data_missing_cap: DataMissingCap
    tie_order: list[HorizonName]
    gates: list[ClassifierGate]
    horizons: HorizonRuleSets

    @model_validator(mode="after")
    def _check(self) -> HorizonRules:
        if sorted(self.tie_order) != sorted(HORIZON_NAMES):
            raise ValueError("tie_order 必须恰好包含四个周期各一次")
        ids = [g.id for g in self.gates]
        for h in HORIZON_NAMES:
            rs: HorizonRuleSet = getattr(self.horizons, h)
            ids += [r.id for r in rs.requires] + [c.id for c in rs.components]
            total = sum(c.max_pts for c in rs.components)
            if total != 100:
                raise ValueError(f"周期 {h}：components 满分合计须为 100（当前 {total}）")
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ValueError(f"规则 id 重复：{dup}")
        return self

    def inputs(self) -> set[str]:
        used = {g.input for g in self.gates}
        for h in HORIZON_NAMES:
            rs: HorizonRuleSet = getattr(self.horizons, h)
            used |= {r.input for r in rs.requires} | {c.input for c in rs.components}
        return used


#: 语义化版本（plan §3.3 horizon_classifier_versions.semver 的同一正则）
SEMVER_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"


class HorizonClassifierConfig(_File):
    version_no: PosInt
    #: 对外的语义化版本（T-A03；契约 ``/horizon-assessments.classifier_version``）
    classifier_version: Annotated[str, Field(pattern=SEMVER_PATTERN)]
    suitable_threshold: Score
    reasons_per_horizon: tuple[PosInt, PosInt]
    recompute: Recompute
    #: ``f.*`` 必须都在 feature_catalog 中（plan §6.1）；该检查需要数据库，留给导入器（见报告 TODO）
    features: Annotated[list[FeatureKey], Field(min_length=1)]
    #: ``{}`` 表示规则未配置（分类器不输出“适合”，plan §6.1），解析为 ``None``
    rules: HorizonRules | None

    @field_validator("rules", mode="before")
    @classmethod
    def _empty_rules(cls, value: object) -> object:
        return None if value == {} else value

    @model_validator(mode="after")
    def _check(self) -> HorizonClassifierConfig:
        _ordered_pair(self.reasons_per_horizon, "reasons_per_horizon")
        if len(set(self.features)) != len(self.features):
            raise ValueError("features 不能重复")
        if self.rules is not None:
            undeclared = sorted(self.rules.inputs() - set(self.features))
            if undeclared:
                raise ValueError(f"rules 用到未在 features 中声明的输入：{undeclared}")
        return self


# ---------------------------------------------------------------------------
# config/llm.yaml（plan §6.1、2.7、2.7.1、2.7.2）
# ---------------------------------------------------------------------------

#: 只存**环境变量名**的键（``*_env``）的取值形状；密钥值本身永远不进 YAML
EnvVarName = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]
#: 价目等金额：YAML 里写字符串（plan 原样 "0.04"），按 Decimal 解析，不经过浮点
Price = Annotated[Decimal, Field(ge=0)]
#: plan §6.1 只给出的取值；新增取值须先改 plan
#: （TODO：其他适配器类型 / user_id_mode / jitter 的取值由 T-B25 定）
LlmProviderKind = Literal["openai_compatible"]
LlmUserIdMode = Literal["hmac"]
#: DeepSeek ``thinking.type`` 的两种取值（plan 2.7.2：解释任务显式 disabled，官方默认 enabled）
LlmThinking = Literal["disabled", "enabled"]
LlmWeekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_HHMM = r"([01][0-9]|2[0-3]):[0-5][0-9]"
TimeWindow = Annotated[str, Field(pattern=rf"^{_HHMM}-{_HHMM}$")]
HttpStatus = Annotated[int, Field(ge=100, le=599)]


class LlmProvider(_Strict):
    kind: LlmProviderKind
    #: 不可热调；必须 https 且主机在 ``allowed_hosts`` 内（plan 2.7：防止把 key 发往他处）
    base_url: StrictStr
    allowed_hosts: Annotated[list[StrictStr], Field(min_length=1)]
    #: 只写变量名（如 ``DEEPSEEK_API_KEY``）；值只在环境变量中，由网关读取并只校验非空
    api_key_env: EnvVarName
    user_id_mode: LlmUserIdMode

    @model_validator(mode="after")
    def _check(self) -> LlmProvider:
        url = urlsplit(self.base_url)
        if url.scheme != "https" or not url.hostname:
            raise ValueError("base_url 必须是 https:// 开头的完整地址")
        if url.username or url.password:
            raise ValueError("base_url 不能内嵌用户名或密码")
        if url.hostname.lower() not in {h.lower() for h in self.allowed_hosts}:
            raise ValueError(f"base_url 主机 {url.hostname!r} 不在 allowed_hosts 内")
        return self


class LlmPricePerMillion(_Strict):
    input_cache_hit: Price
    input_cache_miss: Price
    output: Price


class LlmModel(_Strict):
    provider: StrictStr
    context_window_tokens: PosInt
    max_output_tokens_cap: PosInt
    thinking: LlmThinking
    json_output: StrictBool
    currency: Literal["CNY"]
    price_per_1m_peak: LlmPricePerMillion
    offpeak_multiplier: Annotated[Decimal, Field(gt=0, le=1)]
    price_checked_at: dt.date

    @model_validator(mode="after")
    def _check(self) -> LlmModel:
        if self.max_output_tokens_cap > self.context_window_tokens:
            raise ValueError("max_output_tokens_cap 不能大于 context_window_tokens")
        return self


class LlmPricingCalendar(_Strict):
    timezone: Literal["Asia/Shanghai"]
    peak_weekdays: list[LlmWeekday]
    peak_windows: list[TimeWindow]

    @model_validator(mode="after")
    def _check(self) -> LlmPricingCalendar:
        if len(set(self.peak_weekdays)) != len(self.peak_weekdays):
            raise ValueError("pricing_calendar.peak_weekdays 不能重复")
        for w in self.peak_windows:
            start, end = w.split("-")
            if start >= end:
                raise ValueError(f"pricing_calendar.peak_windows {w!r}：开始须早于结束")
        return self


class LlmRetry(_Strict):
    max_retries: NonNegInt
    backoff_base_s: Annotated[float, Field(gt=0)]
    backoff_max_s: Annotated[float, Field(gt=0)]
    jitter: Literal["full"]
    retry_on_status: list[HttpStatus]
    retry_on_network_error: StrictBool
    retry_on_empty_json: NonNegInt
    no_retry_status: list[HttpStatus]

    @model_validator(mode="after")
    def _check(self) -> LlmRetry:
        _ordered_pair((self.backoff_base_s, self.backoff_max_s), "retry.backoff_base_s/max_s")
        both = sorted(set(self.retry_on_status) & set(self.no_retry_status))
        if both:
            raise ValueError(f"retry_on_status 与 no_retry_status 不能重叠：{both}")
        return self


class LlmCircuitBreaker(_Strict):
    consecutive_5xx: PosInt
    open_s: PosInt


class LlmGateway(_Strict):
    connect_timeout_s: Annotated[float, Field(gt=0)]
    call_deadline_s: Annotated[float, Field(gt=0)]
    max_concurrency: PosInt
    retry: LlmRetry
    circuit_breaker: LlmCircuitBreaker
    on_429_halve_concurrency_s: PosInt

    @model_validator(mode="after")
    def _check(self) -> LlmGateway:
        if self.connect_timeout_s > self.call_deadline_s:
            raise ValueError("connect_timeout_s 不能大于 call_deadline_s")
        return self


class LlmTaskRoute(_Strict):
    model: StrictStr
    fallback_models: list[StrictStr]
    timeout_s: Annotated[float, Field(gt=0)]
    max_output_tokens: PosInt
    temperature: Annotated[float, Field(ge=0, le=2)]


class LlmBudget(_Strict):
    #: ``null`` = 不限（仍记录成本）；由管理员在后台设定（plan 问题 16）
    daily_budget_cny: Annotated[Decimal, Field(gt=0)] | None
    prefer_offpeak_for_batch: StrictBool


class LlmConfig(_File):
    providers: Annotated[dict[StrictStr, LlmProvider], Field(min_length=1)]
    models: Annotated[dict[StrictStr, LlmModel], Field(min_length=1)]
    pricing_calendar: LlmPricingCalendar
    gateway: LlmGateway
    #: 任务键集合 plan §6.1 未封闭（TODO：T-B25 定是否限定为枚举），这里只校验路由引用
    tasks: Annotated[dict[StrictStr, LlmTaskRoute], Field(min_length=1)]
    budget: LlmBudget

    @model_validator(mode="after")
    def _check(self) -> LlmConfig:
        for name, m in self.models.items():
            if m.provider not in self.providers:
                raise ValueError(f"models.{name}.provider={m.provider!r} 未在 providers 中定义")
        for name, t in self.tasks.items():
            for ref in (t.model, *t.fallback_models):
                if ref not in self.models:
                    raise ValueError(f"tasks.{name} 引用了未定义的模型 {ref!r}")
            chain = [t.model, *t.fallback_models]
            if len(set(chain)) != len(chain):
                raise ValueError(f"tasks.{name}.fallback_models 不能重复或包含主模型")
            cap = self.models[t.model].max_output_tokens_cap
            if t.max_output_tokens > cap:
                raise ValueError(f"tasks.{name}.max_output_tokens 超过模型上限 {cap}")
        return self


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------


class BusinessConfig(_Strict):
    """``config/`` 顶层六个文件；键为文件名（不含扩展名）。"""

    realtime: RealtimeConfig
    ingest: IngestConfig
    market_rules: MarketRulesConfig
    risk_controls: RiskControlsConfig
    horizon_classifier: HorizonClassifierConfig
    llm: LlmConfig


BUSINESS_FILES: tuple[str, ...] = tuple(BusinessConfig.model_fields)
