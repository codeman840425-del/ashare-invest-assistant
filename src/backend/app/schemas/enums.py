"""契约 §3 枚举与 §6.1 不可执行原因码表 —— **全仓唯一来源**。

``GET /meta/enums`` 直接下发本模块内容；其他模块需要枚举时从这里导入，不要另行定义。

⚠ T-A01（架构师正在修订契约中的 Suggestion / CandidateSignal 结构）：
:data:`PENDING_T_A01` 中列出的枚举与这两个结构强相关，取值以契约当前版本为准，
T-A01 定稿后只改本文件。本任务刻意**不**定义 Suggestion / CandidateSignal 的模型。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

# ---------------------------------------------------------------------------
# 账号 / 用户
# ---------------------------------------------------------------------------


class AccountStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISABLED = "disabled"


class Role(StrEnum):
    USER = "user"
    ADMIN = "admin"


# ---------------------------------------------------------------------------
# 证据 / 策略 / 信号（★ = 与 Suggestion/CandidateSignal 相关，见 PENDING_T_A01）
# ---------------------------------------------------------------------------


class EpistemicType(StrEnum):  # ★
    FACT = "fact"
    ESTIMATE = "estimate"
    HYPOTHESIS = "hypothesis"
    EXECUTION = "execution"


class Horizon(StrEnum):  # ★
    INTRADAY_T = "intraday_t"
    SHORT = "short"
    SWING = "swing"
    LONG = "long"


class Dimension(StrEnum):  # ★
    TECHNICAL = "technical"
    CAPITAL = "capital"
    FUNDAMENTAL = "fundamental"
    SENTIMENT = "sentiment"
    SECTOR_MARKET = "sector_market"
    NEWS = "news"


class DimensionView(StrEnum):  # ★
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class RuleRole(StrEnum):  # ★
    ENTRY = "entry"
    HOLD = "hold"
    WEAKENING = "weakening"
    EXIT = "exit"
    FILTER = "filter"
    VETO = "veto"
    COUNTER = "counter"
    INVALIDATION = "invalidation"


class Action(StrEnum):  # ★
    BUY = "buy"
    ADD = "add"
    HOLD = "hold"
    REDUCE = "reduce"
    SELL = "sell"
    WAIT = "wait"


class TLeg(StrEnum):  # ★ 仅 intraday_t
    SELL_FIRST = "sell_first"
    BUY_FIRST = "buy_first"


class ConfidenceLevel(StrEnum):  # ★
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConsensusStatus(StrEnum):  # ★
    UNANIMOUS = "unanimous"
    DIVERGENT = "divergent"
    SINGLE = "single"
    NONE = "none"


class SuggestionOrigin(StrEnum):  # ★
    DAILY_BATCH = "daily_batch"
    INTRADAY_EVENT = "intraday_event"
    MANUAL_REFRESH = "manual_refresh"


class SuggestionStatus(StrEnum):  # ★
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


class RiskControl(StrEnum):  # ★（RiskFlag.control）
    STOP_TAKE = "stop_take"  # RC1
    POSITION_CAP = "position_cap"  # RC2
    TOTAL_EXPOSURE = "total_exposure"  # RC3
    SECTOR_CONCENTRATION = "sector_concentration"  # RC4
    LOSS_STREAK_DRAWDOWN = "loss_streak_drawdown"  # RC5
    PLAN_VIOLATION = "plan_violation"  # RC6


#: risk_control → 契约中的 RC 编号（随 /meta/enums 一并下发，便于前端展示）
RISK_CONTROL_LABELS: Final[dict[RiskControl, str]] = {
    RiskControl.STOP_TAKE: "RC1",
    RiskControl.POSITION_CAP: "RC2",
    RiskControl.TOTAL_EXPOSURE: "RC3",
    RiskControl.SECTOR_CONCENTRATION: "RC4",
    RiskControl.LOSS_STREAK_DRAWDOWN: "RC5",
    RiskControl.PLAN_VIOLATION: "RC6",
}


class RiskLevel(StrEnum):  # ★（RiskFlag.level）
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class MarketRegime(StrEnum):
    UPTREND = "uptrend"
    RANGE = "range"
    DOWNTREND = "downtrend"


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------


class NotificationKind(StrEnum):
    SUGGESTION_CHANGE = "suggestion_change"
    INVALIDATION = "invalidation"
    DAILY_REPORT = "daily_report"
    ALERT = "alert"
    IMPORT = "import"
    SYSTEM = "system"
    REASON_RELEASED = "reason_released"
    PLAN_DRAFT_READY = "plan_draft_ready"
    PLAN_TRIGGERED = "plan_triggered"
    STRATEGY_HEALTH = "strategy_health"


class Severity(StrEnum):
    INFO = "info"
    ATTENTION = "attention"
    IMPORTANT = "important"


class Channel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    WECOM_APP = "wecom_app"  # 预留


# ---------------------------------------------------------------------------
# 数据状态（契约 §1.1）
# ---------------------------------------------------------------------------


class DataStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    PENDING = "pending"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# 成交 / 导入
# ---------------------------------------------------------------------------


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class ImportStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PREVIEW_READY = "preview_ready"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    REVERTED = "reverted"


# ---------------------------------------------------------------------------
# 策略三层
# ---------------------------------------------------------------------------


class CardCompleteness(StrEnum):
    DRAFT = "draft"
    DOCUMENTED = "documented"
    RUNNABLE_CANDIDATE = "runnable_candidate"
    PROMOTED = "promoted"
    RETIRED = "retired"


class Lifecycle(StrEnum):  # ★（CandidateSignal.lifecycle）
    DRAFT = "draft"
    SIMULATING = "simulating"
    PUBLISHED = "published"
    OBSERVING = "observing"
    RETIRED = "retired"


class InstanceStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class CandidateSignalState(StrEnum):  # ★
    OPEN = "open"
    DRAFTED = "drafted"
    BLOCKED = "blocked"
    RELEASED = "released"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"


class ReasonCode(StrEnum):  # ★ 契约 §6.1（取值为大写，契约原文如此）
    DATA_STALE = "DATA_STALE"
    KEY_DATA_MISSING = "KEY_DATA_MISSING"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    NON_TRADING_TIME = "NON_TRADING_TIME"
    SUSPENDED = "SUSPENDED"
    LIMIT_LOCKED = "LIMIT_LOCKED"
    ST_OR_DELISTING = "ST_OR_DELISTING"
    NEW_LISTING = "NEW_LISTING"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    T1_NOT_SELLABLE = "T1_NOT_SELLABLE"
    NO_POSITION = "NO_POSITION"
    POSITION_CAP_REACHED = "POSITION_CAP_REACHED"
    STRATEGY_BUDGET_EXHAUSTED = "STRATEGY_BUDGET_EXHAUSTED"
    SECTOR_EXPOSURE_EXCEEDED = "SECTOR_EXPOSURE_EXCEEDED"
    REGIME_MISMATCH = "REGIME_MISMATCH"
    SAME_DIRECTION_PLAN_EXISTS = "SAME_DIRECTION_PLAN_EXISTS"
    CONFLICTS_CONFIRMED_PLAN = "CONFLICTS_CONFIRMED_PLAN"
    BLOCKLISTED = "BLOCKLISTED"
    COOLING_OFF = "COOLING_OFF"
    LOSS_STREAK_PAUSE = "LOSS_STREAK_PAUSE"
    STRATEGY_CONFLICT = "STRATEGY_CONFLICT"
    USER_MUTED = "USER_MUTED"
    PROFILE_OR_CONSENT_MISSING = "PROFILE_OR_CONSENT_MISSING"


class ReasonStatus(StrEnum):  # ★
    ACTIVE = "active"
    RELEASED = "released"
    OBSOLETE = "obsolete"


class CheckOn(StrEnum):  # ★
    TICK = "tick"
    DAILY_CLOSE = "daily_close"
    SCHEDULE = "schedule"
    HOLDING_CHANGE = "holding_change"
    CASH_UPDATE = "cash_update"
    IMPORT = "import"
    PLAN_CHANGE = "plan_change"
    USER_ACTION = "user_action"


class ReleaseKind(StrEnum):  # ★
    EXPR = "expr"
    TIME = "time"
    EVENT = "event"
    USER_ACTION = "user_action"


class PlanDraftStatus(StrEnum):  # ★
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISCARDED = "discarded"
    EXPIRED = "expired"
    STALE = "stale"


class PlanOrigin(StrEnum):
    MANUAL = "manual"
    PLAN_DRAFT = "plan_draft"


class RestrictionKind(StrEnum):
    BLOCKLIST = "blocklist"
    COOLING_OFF = "cooling_off"
    MUTE = "mute"


class SuggestionUserAction(StrEnum):  # ★（没有 converted_to_plan）
    VIEWED = "viewed"
    DISMISSED = "dismissed"
    DRAFT_REQUESTED = "draft_requested"
    DRAFT_CONFIRMED = "draft_confirmed"
    REASON_MANUALLY_RELEASED = "reason_manually_released"
    ACTED_TRADE_LINKED = "acted_trade_linked"


class FeatureStatus(StrEnum):
    DECLARED = "declared"
    VERIFIED_DOC = "verified_doc"
    VERIFIED_LIVE = "verified_live"
    GAP = "gap"
    DEPRECATED = "deprecated"


class Gate(StrEnum):  # 契约原文为大写 G1–G7
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"
    G4 = "G4"
    G5 = "G5"
    G6 = "G6"
    G7 = "G7"


class LlmTask(StrEnum):
    SUGGESTION_RATIONALE = "suggestion_rationale"
    DAILY_REPORT_STOCK = "daily_report_stock"
    DAILY_REPORT_SUMMARY = "daily_report_summary"
    STRATEGY_DIVERGENCE = "strategy_divergence"
    ANNOUNCEMENT_TITLE_DIGEST = "announcement_title_digest"


# ---------------------------------------------------------------------------
# /meta/enums 注册表：契约 §3 的枚举名 → 枚举类（顺序与契约表格一致）
# ---------------------------------------------------------------------------

CONTRACT_ENUMS: Final[dict[str, type[StrEnum]]] = {
    "account_status": AccountStatus,
    "role": Role,
    "epistemic_type": EpistemicType,
    "horizon": Horizon,
    "dimension": Dimension,
    "dimension_view": DimensionView,
    "rule_role": RuleRole,
    "action": Action,
    "t_leg": TLeg,
    "confidence_level": ConfidenceLevel,
    "consensus_status": ConsensusStatus,
    "suggestion_origin": SuggestionOrigin,
    "suggestion_status": SuggestionStatus,
    "risk_control": RiskControl,
    "risk_level": RiskLevel,
    "market_regime": MarketRegime,
    "notification_kind": NotificationKind,
    "severity": Severity,
    "channel": Channel,
    "data_status": DataStatus,
    "trade_side": TradeSide,
    "import_status": ImportStatus,
    "card_completeness": CardCompleteness,
    "lifecycle": Lifecycle,
    "instance_status": InstanceStatus,
    "candidate_signal_state": CandidateSignalState,
    "reason_code": ReasonCode,
    "reason_status": ReasonStatus,
    "check_on": CheckOn,
    "release_kind": ReleaseKind,
    "plan_draft_status": PlanDraftStatus,
    "plan_origin": PlanOrigin,
    "restriction_kind": RestrictionKind,
    "suggestion_user_action": SuggestionUserAction,
    "feature_status": FeatureStatus,
    "gate": Gate,
    "llm_task": LlmTask,
}

#: 与 Suggestion / CandidateSignal 结构强相关、T-A01 可能调整的枚举（报告中已标注）
PENDING_T_A01: Final[frozenset[str]] = frozenset(
    {
        "epistemic_type",
        "horizon",
        "dimension",
        "dimension_view",
        "rule_role",
        "action",
        "t_leg",
        "confidence_level",
        "consensus_status",
        "suggestion_origin",
        "suggestion_status",
        "risk_control",
        "risk_level",
        "lifecycle",
        "candidate_signal_state",
        "reason_code",
        "reason_status",
        "check_on",
        "release_kind",
        "plan_draft_status",
        "suggestion_user_action",
    }
)


# ---------------------------------------------------------------------------
# 契约 §6.1 不可执行原因码表（含默认解除条件）
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReasonCodeSpec:
    code: ReasonCode
    #: 默认 release_condition.kind；契约写成 "time / expr" 的保留为多个候选，顺序同原文
    release_kinds: tuple[ReleaseKind, ...]
    check_on: tuple[CheckOn, ...]
    manually_releasable: bool
    #: 契约"可手动解除"列的括注（如"通过 /restrictions"），无则为 None
    note: str | None = None


_K = ReleaseKind
_C = CheckOn

REASON_CODE_TABLE: Final[tuple[ReasonCodeSpec, ...]] = (
    ReasonCodeSpec(ReasonCode.DATA_STALE, (_K.EXPR,), (_C.TICK,), False),
    ReasonCodeSpec(ReasonCode.KEY_DATA_MISSING, (_K.EXPR,), (_C.TICK, _C.DAILY_CLOSE), False),
    ReasonCodeSpec(ReasonCode.LOW_CONFIDENCE, (_K.EXPR,), (_C.TICK, _C.DAILY_CLOSE), False),
    ReasonCodeSpec(ReasonCode.NON_TRADING_TIME, (_K.TIME,), (_C.SCHEDULE,), False),
    ReasonCodeSpec(ReasonCode.SUSPENDED, (_K.EVENT,), (_C.TICK, _C.DAILY_CLOSE), False),
    ReasonCodeSpec(ReasonCode.LIMIT_LOCKED, (_K.EXPR,), (_C.TICK,), False),
    ReasonCodeSpec(ReasonCode.ST_OR_DELISTING, (_K.EVENT,), (_C.DAILY_CLOSE,), False),
    ReasonCodeSpec(ReasonCode.NEW_LISTING, (_K.EXPR,), (_C.DAILY_CLOSE,), False),
    ReasonCodeSpec(ReasonCode.INSUFFICIENT_CASH, (_K.EXPR,), (_C.CASH_UPDATE, _C.IMPORT), False),
    ReasonCodeSpec(
        ReasonCode.T1_NOT_SELLABLE, (_K.TIME, _K.EXPR), (_C.SCHEDULE, _C.HOLDING_CHANGE), False
    ),
    ReasonCodeSpec(ReasonCode.NO_POSITION, (_K.EXPR,), (_C.HOLDING_CHANGE, _C.IMPORT), False),
    ReasonCodeSpec(
        ReasonCode.POSITION_CAP_REACHED, (_K.EXPR,), (_C.TICK, _C.HOLDING_CHANGE), False
    ),
    ReasonCodeSpec(ReasonCode.STRATEGY_BUDGET_EXHAUSTED, (_K.EXPR,), (_C.HOLDING_CHANGE,), False),
    ReasonCodeSpec(
        ReasonCode.SECTOR_EXPOSURE_EXCEEDED, (_K.EXPR,), (_C.HOLDING_CHANGE, _C.TICK), False
    ),
    ReasonCodeSpec(ReasonCode.REGIME_MISMATCH, (_K.EXPR,), (_C.DAILY_CLOSE,), False),
    ReasonCodeSpec(ReasonCode.SAME_DIRECTION_PLAN_EXISTS, (_K.EVENT,), (_C.PLAN_CHANGE,), False),
    ReasonCodeSpec(ReasonCode.CONFLICTS_CONFIRMED_PLAN, (_K.USER_ACTION,), (_C.USER_ACTION,), True),
    ReasonCodeSpec(
        ReasonCode.BLOCKLISTED, (_K.USER_ACTION,), (_C.USER_ACTION,), True, "通过 /restrictions"
    ),
    ReasonCodeSpec(ReasonCode.COOLING_OFF, (_K.TIME,), (_C.SCHEDULE,), False),
    ReasonCodeSpec(
        ReasonCode.LOSS_STREAK_PAUSE,
        (_K.USER_ACTION, _K.TIME),
        (_C.USER_ACTION, _C.SCHEDULE),
        True,
    ),
    ReasonCodeSpec(
        ReasonCode.STRATEGY_CONFLICT,
        (_K.USER_ACTION, _K.EXPR),
        (_C.USER_ACTION, _C.TICK),
        True,
    ),
    ReasonCodeSpec(
        ReasonCode.USER_MUTED,
        (_K.USER_ACTION, _K.TIME),
        (_C.USER_ACTION, _C.SCHEDULE),
        True,
        "通过 /restrictions",
    ),
    ReasonCodeSpec(
        ReasonCode.PROFILE_OR_CONSENT_MISSING,
        (_K.USER_ACTION,),
        (_C.USER_ACTION,),
        False,
        "完成相应步骤后系统解除",
    ),
)
