"""契约 §3 枚举、§4.1 导入提示码与 §6.1 不可执行原因码表 —— **全仓唯一来源**。

``GET /meta/enums`` 直接下发本模块内容；其他模块需要枚举时从这里导入，不要另行定义。
已同步到契约 :data:`CONTRACT_VERSION`（v0.2.7；v0.2 为 T-A01 定稿，原 ``PENDING_T_A01`` 标记已解除；
v0.2.1–v0.2.3 未改 §3 枚举、§4 错误码与 §6.1 原因码的取值；v0.2.4 新增的 ``consent_key``、
``legal_doc_key``、``consent_presentation``、``assessment_status`` 在 v0.2.5（T-A06）作废并删除，
同时删除原因码 ``PROFILE_OR_CONSENT_MISSING``（23 → 22）与错误码 ``CONSENT_REQUIRED``、
``STRATEGY_FIT_ACK_REQUIRED``）。v0.2.6（T-A07）新增 ``data_licence_status``、
``data_licence_tier``，``notification_kind`` 加 ``data_licence``、``gap_reason`` 加
``data_licence_unavailable``，错误码加三个 ``DATA_LICENCE_*``。v0.2.7（T-A08）新增 18 个枚举、
``data_provider`` 加 ``exchange``；``security_type`` 按编排者 Q3 裁定多一个 ``etf``（契约 §3 该行由
T-A09 同步），错误码与原因码不变。

``CONTRACT_ENUMS`` 只登记契约 §3 的命名枚举；契约里以内联字面量出现的取值（如 ``/me/profile`` 的
``effort``、``experience``）在本模块文末“非 §3 取值”一节集中定义，供 DB CHECK 与请求模型复用，
不进入 ``/meta/enums``。
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
# 证据 / 策略 / 信号
# ---------------------------------------------------------------------------


class EpistemicType(StrEnum):
    FACT = "fact"
    ESTIMATE = "estimate"
    HYPOTHESIS = "hypothesis"
    EXECUTION = "execution"


class Horizon(StrEnum):
    INTRADAY_T = "intraday_t"
    SHORT = "short"
    SWING = "swing"
    LONG = "long"


class Dimension(StrEnum):
    TECHNICAL = "technical"
    CAPITAL = "capital"
    FUNDAMENTAL = "fundamental"
    SENTIMENT = "sentiment"
    SECTOR_MARKET = "sector_market"
    NEWS = "news"


class DimensionView(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class RuleRole(StrEnum):
    ENTRY = "entry"
    HOLD = "hold"
    WEAKENING = "weakening"
    EXIT = "exit"
    FILTER = "filter"
    VETO = "veto"
    COUNTER = "counter"
    INVALIDATION = "invalidation"


class Action(StrEnum):
    BUY = "buy"
    ADD = "add"
    HOLD = "hold"
    REDUCE = "reduce"
    SELL = "sell"
    WAIT = "wait"


class TLeg(StrEnum):  # 仅 intraday_t
    SELL_FIRST = "sell_first"
    BUY_FIRST = "buy_first"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConsensusStatus(StrEnum):
    UNANIMOUS = "unanimous"
    DIVERGENT = "divergent"
    SINGLE = "single"
    NONE = "none"


class StrategyEvalState(StrEnum):
    ENTRY_OK = "entry_ok"
    NOT_TRIGGERED = "not_triggered"
    HOLD_OK = "hold_ok"
    WEAKENING = "weakening"
    EXIT_SIGNAL = "exit_signal"
    VETOED = "vetoed"
    INSUFFICIENT_DATA = "insufficient_data"


class ExecutabilityStatus(StrEnum):
    EXECUTABLE = "executable"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class SuggestionOrigin(StrEnum):
    DAILY_BATCH = "daily_batch"
    INTRADAY_EVENT = "intraday_event"
    MANUAL_REFRESH = "manual_refresh"


class SuggestionStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


class RiskControl(StrEnum):  # RiskFlag.control
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


class RiskLevel(StrEnum):  # RiskFlag.level
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class CardRiskLevel(StrEnum):  # L1 卡片风险等级，与 RiskLevel 无关
    NORMAL = "normal"
    HIGH = "high"


class MarketRegime(StrEnum):
    UPTREND = "uptrend"
    RANGE = "range"
    DOWNTREND = "downtrend"


class SignalKind(StrEnum):
    RULE_FLIP = "rule_flip"
    BREAKOUT = "breakout"
    BREAKDOWN = "breakdown"
    VWAP_DEVIATION = "vwap_deviation"
    VOLUME_SPIKE = "volume_spike"
    LIMIT_UP_TOUCH = "limit_up_touch"
    LIMIT_DOWN_TOUCH = "limit_down_touch"
    LIMIT_OPEN = "limit_open"
    INVALIDATION_NEAR = "invalidation_near"
    STOP_HIT = "stop_hit"
    SUSPENDED = "suspended"
    DATA_STALE = "data_stale"


class MarketSession(StrEnum):
    NON_TRADING_DAY = "non_trading_day"
    PRE_OPEN = "pre_open"
    CALL_AUCTION = "call_auction"
    MORNING = "morning"
    LUNCH_BREAK = "lunch_break"
    AFTERNOON = "afternoon"
    CLOSING_AUCTION = "closing_auction"
    CLOSED = "closed"


class BarFreq(StrEnum):  # 取值本身是固定记号（契约 §1 例外）
    M1 = "1m"
    D = "d"
    W = "w"


class BarAdjust(StrEnum):  # 1m 只支持 none
    NONE = "none"
    QFQ = "qfq"
    HFQ = "hfq"


class RegistrationMode(StrEnum):
    CLOSED = "closed"  # V1 默认
    INVITE = "invite"
    OPEN = "open"  # 保留，V1 不用


class NotificationTargetType(StrEnum):
    SUGGESTION = "suggestion"
    CANDIDATE_SIGNAL = "candidate_signal"
    PLAN_DRAFT = "plan_draft"
    PLAN = "plan"
    DAILY_REPORT = "daily_report"
    IMPORT_BATCH = "import_batch"
    RECONCILIATION = "reconciliation"
    STRATEGY_VERSION = "strategy_version"
    NONE = "none"


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
    DATA_LICENCE = "data_licence"  # v0.2.6（T-A07）


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


class GapReason(StrEnum):
    NO_SOURCE = "no_source"
    NOT_YET_PUBLISHED = "not_yet_published"
    UPSTREAM_ERROR = "upstream_error"
    QUOTA_DEFERRED = "quota_deferred"
    USER_INPUT_MISSING = "user_input_missing"
    DATA_LICENCE_UNAVAILABLE = "data_licence_unavailable"  # v0.2.6（T-A07）


class DataProvider(StrEnum):  # Evidence.provider
    MAIRUI = "mairui"
    USER_IMPORT = "user_import"
    USER_INPUT = "user_input"
    SYSTEM = "system"
    #: v0.2.7：沪深北交易所公开证券列表，只用于证券公开主数据（契约 §3，待 Q2 / T-A04 确认来源）
    EXCHANGE = "exchange"


class SourceKind(StrEnum):  # 证据来源类别（plan 3.1）
    MARKET_DATA = "market_data"
    DISCLOSURE = "disclosure"
    USER_INPUT = "user_input"
    SYSTEM_CALC = "system_calc"


# ---------------------------------------------------------------------------
# 成交 / 导入
# ---------------------------------------------------------------------------


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class ImportStatus(StrEnum):  # v0.2：preview_ready→previewed，confirmed→committed，新增 discarded
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PREVIEWED = "previewed"
    COMMITTED = "committed"
    FAILED = "failed"
    DISCARDED = "discarded"
    REVERTED = "reverted"


class ImportSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class ImportScope(StrEnum):
    FILE = "file"
    ROW = "row"
    FIELD = "field"


class ImportRowStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"


class DedupStatus(StrEnum):
    NEW = "new"
    DUPLICATE_IN_DB = "duplicate_in_db"
    DUPLICATE_IN_FILE = "duplicate_in_file"
    POSSIBLE_DUPLICATE_OF_MANUAL = "possible_duplicate_of_manual"


class ReconciliationStatus(StrEnum):
    MATCHED = "matched"
    DIFF = "diff"
    NOT_IMPORTED = "not_imported"


class ReconciliationItemKind(StrEnum):
    QUANTITY_MISMATCH = "quantity_mismatch"
    MISSING_IN_BROKER = "missing_in_broker"
    MISSING_IN_OURS = "missing_in_ours"
    COST_DIFFERS = "cost_differs"
    CASH_GAP = "cash_gap"
    CASH_CHAIN_BREAK = "cash_chain_break"


# ---------------------------------------------------------------------------
# 策略三层
# ---------------------------------------------------------------------------


class CardCompleteness(StrEnum):
    DRAFT = "draft"
    DOCUMENTED = "documented"
    RUNNABLE_CANDIDATE = "runnable_candidate"
    PROMOTED = "promoted"
    RETIRED = "retired"


class Lifecycle(StrEnum):  # CandidateSignal.lifecycle
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


class CandidateSignalState(StrEnum):
    OPEN = "open"
    DRAFTED = "drafted"
    BLOCKED = "blocked"
    RELEASED = "released"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"


class ReasonCode(StrEnum):  # 契约 §6.1；码类取值用大写（契约 §1 大小写规则）
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


class ReasonStatus(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    OBSOLETE = "obsolete"


class CheckOn(StrEnum):
    TICK = "tick"
    DAILY_CLOSE = "daily_close"
    SCHEDULE = "schedule"
    HOLDING_CHANGE = "holding_change"
    CASH_UPDATE = "cash_update"
    IMPORT = "import"
    PLAN_CHANGE = "plan_change"
    USER_ACTION = "user_action"


class ReleaseKind(StrEnum):
    EXPR = "expr"
    TIME = "time"
    EVENT = "event"
    USER_ACTION = "user_action"


class PlanDraftStatus(StrEnum):
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


class SuggestionUserAction(StrEnum):  # 没有 converted_to_plan
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
# 健康检查（契约 §7.10）
# ---------------------------------------------------------------------------


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class ComponentHealth(StrEnum):
    OK = "ok"
    ERROR = "error"


class IngestHealth(StrEnum):
    OK = "ok"
    STALE = "stale"
    PAUSED = "paused"
    UNKNOWN = "unknown"  # Redis 不可用，无法判断


# ---------------------------------------------------------------------------
# 每用户数据证书（契约 v0.2.6，plan §2.1B，T-A07）
# ---------------------------------------------------------------------------


class DataLicenceStatus(StrEnum):
    NOT_SET = "not_set"
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    INVALID = "invalid"
    EXPIRED = "expired"
    QUOTA_EXCEEDED = "quota_exceeded"
    IP_LIMITED = "ip_limited"
    PAUSED_BY_ADMIN = "paused_by_admin"


class DataLicenceTier(StrEnum):
    """用户自报的麦蕊证书档位，决定默认每分钟上限（ingest.yaml ``licences.tier_per_minute``）。"""

    FREE = "free"
    TRIAL = "trial"
    MONTHLY = "monthly"
    ANNUAL = "annual"
    DIAMOND = "diamond"
    OTHER = "other"


#: ``DataLicenceStatus.last_error_code`` 的取值（契约 §5 共享对象，内联字面量）
DATA_LICENCE_ERROR_CODES: Final[tuple[str, ...]] = (
    "101",
    "102",
    "103",
    "429",
    "503",
    "network",
    "http_5xx",
)


# ---------------------------------------------------------------------------
# v0.2.7（T-A08）：证券、个股数据、策略实例、/today 相关枚举（契约 §3，18 个）
# ---------------------------------------------------------------------------


class SecurityType(StrEnum):
    """证券类型。ETF 按编排者 2026-11-02 裁定纳入（契约 v0.2.7 Q3 / plan 第 9 节 53）：
    可出现在搜索与持仓中，但**策略不对 ETF 运行**（见 :mod:`app.strategy.eligibility`）；
    可转债本版不纳入。"""

    STOCK = "stock"
    CDR = "cdr"
    INDEX = "index"
    ETF = "etf"


#: 策略、候选信号可以作用的证券类型（ETF、指数都不在内；plan 第 9 节 53）
STRATEGY_ELIGIBLE_SECURITY_TYPES: Final[frozenset[SecurityType]] = frozenset(
    {SecurityType.STOCK, SecurityType.CDR}
)


class Board(StrEnum):
    MAIN = "main"
    CHINEXT = "chinext"
    STAR = "star"
    BSE = "bse"


class ListingStatus(StrEnum):  # 停牌不是上市状态（SecurityProfile.suspended）
    LISTED = "listed"
    DELISTING_PERIOD = "delisting_period"
    DELISTED = "delisted"
    MISSING_FROM_LIST = "missing_from_list"


class SecurityRiskFlag(StrEnum):  # 同时命中取最高：delisting > star_st > st
    ST = "st"
    STAR_ST = "star_st"
    DELISTING = "delisting"


class SecurityMatchKind(StrEnum):  # 定义顺序即排序层级
    CODE_EXACT = "code_exact"
    NAME_EXACT = "name_exact"
    INITIALS_EXACT = "initials_exact"
    CODE_PREFIX = "code_prefix"
    NAME_PREFIX = "name_prefix"
    INITIALS_PREFIX = "initials_prefix"
    NAME_CONTAINS = "name_contains"
    FORMER_NAME = "former_name"
    FORMER_CODE = "former_code"
    FUZZY = "fuzzy"


class ReportPeriod(StrEnum):
    Q1 = "q1"
    H1 = "h1"
    Q3 = "q3"
    FY = "fy"


class FactorCategory(StrEnum):
    """麦蕊因子的 11 个分类：契约 v0.2.7 写明键名【待 T003 补测】，定稿前为空（``/meta/enums``
    下发空列表，与契约 §3 当前的零个取值一致）。"""


class AnnouncementCategory(StrEnum):
    PERIODIC_REPORT = "periodic_report"
    OTHER = "other"


class SectorKind(StrEnum):
    INDUSTRY = "industry"
    CONCEPT = "concept"


class IndustryTaxonomy(StrEnum):
    SW_L1 = "sw_l1"
    SW_L2 = "sw_l2"
    CSRC = "csrc"


class InstanceOrigin(StrEnum):
    CLASSIFIER = "classifier"
    USER = "user"
    SYSTEM = "system"


class InstanceEventKind(StrEnum):
    CREATED = "created"
    CONFIRMED = "confirmed"
    PAUSED = "paused"
    RESUMED = "resumed"
    PARAMS_CHANGED = "params_changed"
    ARCHIVED = "archived"


class InstanceSort(StrEnum):
    CREATED_AT_DESC = "created_at_desc"  # 默认
    UPDATED_AT_DESC = "updated_at_desc"
    STRATEGY_NAME_ASC = "strategy_name_asc"


class SectorSort(StrEnum):
    MAIN_NET_DESC = "main_net_desc"  # 默认
    MAIN_NET_ASC = "main_net_asc"
    CHANGE_PCT_DESC = "change_pct_desc"
    CHANGE_PCT_ASC = "change_pct_asc"


class AlertOrigin(StrEnum):
    PLAN_CONDITION = "plan_condition"
    HOLDING_EVENT = "holding_event"
    USER_CUSTOM = "user_custom"


class AlertStatus(StrEnum):
    NEW = "new"
    READ = "read"
    CHECKED = "checked"
    ACTED = "acted"
    DISMISSED = "dismissed"


class PlanConditionKind(StrEnum):
    TRIGGER = "trigger"
    INVALIDATION = "invalidation"


class DataGapScope(StrEnum):
    USER = "user"
    ACCOUNT = "account"
    SECURITY = "security"
    MARKET = "market"


class InstancePausedBy(StrEnum):  # StrategyInstance.paused_by（契约 §5.1 内联字面量，非 §3）
    USER = "user"
    SYSTEM = "system"


# ---------------------------------------------------------------------------
# /meta/enums 注册表：契约 §3 的枚举名 → 枚举类（顺序与契约表格一致）
# ---------------------------------------------------------------------------

#: 本模块对应的契约版本（``/meta/enums`` 的 ``version``）
CONTRACT_VERSION: Final = "v0.2.7"

#: ``/meta/enums`` 的 ``enums``：契约 §3 各表名 → 取值（顺序同 §3）。``reason_code`` 不在其中，
#: 只在 ``reason_codes`` 里带解除条件展开（契约 §7.10；评审 M7）。
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
    "strategy_eval_state": StrategyEvalState,
    "executability_status": ExecutabilityStatus,
    "suggestion_origin": SuggestionOrigin,
    "suggestion_status": SuggestionStatus,
    "risk_control": RiskControl,
    "risk_level": RiskLevel,
    "card_risk_level": CardRiskLevel,
    "market_regime": MarketRegime,
    "signal_kind": SignalKind,
    "market_session": MarketSession,
    "bar_freq": BarFreq,
    "bar_adjust": BarAdjust,
    "registration_mode": RegistrationMode,
    "notification_target_type": NotificationTargetType,
    "notification_kind": NotificationKind,
    "severity": Severity,
    "channel": Channel,
    "data_status": DataStatus,
    "gap_reason": GapReason,
    "data_provider": DataProvider,
    "source_kind": SourceKind,
    "trade_side": TradeSide,
    "import_status": ImportStatus,
    "import_severity": ImportSeverity,
    "import_scope": ImportScope,
    "import_row_status": ImportRowStatus,
    "dedup_status": DedupStatus,
    "reconciliation_status": ReconciliationStatus,
    "reconciliation_item_kind": ReconciliationItemKind,
    "card_completeness": CardCompleteness,
    "lifecycle": Lifecycle,
    "instance_status": InstanceStatus,
    "candidate_signal_state": CandidateSignalState,
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
    "health_status": HealthStatus,
    "component_health": ComponentHealth,
    "ingest_health": IngestHealth,
    "data_licence_status": DataLicenceStatus,
    "data_licence_tier": DataLicenceTier,
    # v0.2.7（T-A08 #14）
    "security_type": SecurityType,
    "board": Board,
    "listing_status": ListingStatus,
    "security_risk_flag": SecurityRiskFlag,
    "security_match_kind": SecurityMatchKind,
    "report_period": ReportPeriod,
    "factor_category": FactorCategory,
    "announcement_category": AnnouncementCategory,
    "sector_kind": SectorKind,
    "industry_taxonomy": IndustryTaxonomy,
    "instance_origin": InstanceOrigin,
    "instance_event_kind": InstanceEventKind,
    "instance_sort": InstanceSort,
    "sector_sort": SectorSort,
    "alert_origin": AlertOrigin,
    "alert_status": AlertStatus,
    "plan_condition_kind": PlanConditionKind,
    "data_gap_scope": DataGapScope,
}


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
)


# ---------------------------------------------------------------------------
# 契约 §4.1 导入提示码（IMPORT_*，只出现在 ImportFinding.code，不是 HTTP 错误码）
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImportCodeSpec:
    code: str
    severity: ImportSeverity
    scope: ImportScope
    #: 契约 §4.1“处理”列为“需确认/需选择”的 warning；error 一律 False（见 reports/T-B02.md）
    needs_action: bool


_ER, _WA = ImportSeverity.ERROR, ImportSeverity.WARNING
_FI, _RO, _FD = ImportScope.FILE, ImportScope.ROW, ImportScope.FIELD

IMPORT_CODE_TABLE: Final[tuple[ImportCodeSpec, ...]] = (
    # error · 文件级 8
    ImportCodeSpec("IMPORT_EMPTY_FILE", _ER, _FI, False),
    ImportCodeSpec("IMPORT_FILE_TOO_LARGE", _ER, _FI, False),
    ImportCodeSpec("IMPORT_UNSUPPORTED_FILE_TYPE", _ER, _FI, False),
    ImportCodeSpec("IMPORT_TOO_MANY_ROWS", _ER, _FI, False),
    ImportCodeSpec("IMPORT_ENCODING_UNDETECTED", _ER, _FI, False),
    ImportCodeSpec("IMPORT_UNRECOGNIZED_FORMAT", _ER, _FI, False),
    ImportCodeSpec("IMPORT_REQUIRED_COLUMN_MISSING", _ER, _FI, False),
    ImportCodeSpec("IMPORT_ACCOUNT_MISMATCH", _ER, _FI, False),
    # error · 行/字段级 13
    ImportCodeSpec("IMPORT_ROW_DECODE_ERROR", _ER, _RO, False),
    ImportCodeSpec("IMPORT_ROW_TRUNCATED", _ER, _RO, False),
    ImportCodeSpec("IMPORT_ROW_COLUMN_MISMATCH", _ER, _RO, False),
    ImportCodeSpec("IMPORT_REQUIRED_FIELD_EMPTY", _ER, _FD, False),
    ImportCodeSpec("IMPORT_INVALID_DATE", _ER, _FD, False),
    ImportCodeSpec("IMPORT_FUTURE_DATE", _ER, _FD, False),
    ImportCodeSpec("IMPORT_INVALID_TIME", _ER, _FD, False),
    ImportCodeSpec("IMPORT_INVALID_NUMBER", _ER, _FD, False),
    ImportCodeSpec("IMPORT_INVALID_SECURITY_CODE", _ER, _FD, False),
    ImportCodeSpec("IMPORT_INVALID_QUANTITY", _ER, _FD, False),
    ImportCodeSpec("IMPORT_INVALID_PRICE", _ER, _FD, False),
    ImportCodeSpec("IMPORT_SIDE_QTY_SIGN_MISMATCH", _ER, _RO, False),
    ImportCodeSpec("IMPORT_AMOUNT_MISMATCH", _ER, _RO, False),
    # warning · 文件级 10
    ImportCodeSpec("IMPORT_DUPLICATE_FILE", _WA, _FI, False),
    ImportCodeSpec("IMPORT_NO_DATA_ROWS", _WA, _FI, False),
    ImportCodeSpec("IMPORT_UNKNOWN_COLUMN", _WA, _FI, False),
    ImportCodeSpec("IMPORT_FILE_POSSIBLY_TRUNCATED", _WA, _FI, False),
    ImportCodeSpec("IMPORT_ENCODING_LOW_CONFIDENCE", _WA, _FI, True),
    ImportCodeSpec("IMPORT_FORMAT_LOW_CONFIDENCE", _WA, _FI, True),
    ImportCodeSpec("IMPORT_SNAPSHOT_AS_OF_ASSUMED", _WA, _FI, True),
    ImportCodeSpec("IMPORT_SNAPSHOT_TOTALS_MISMATCH", _WA, _FI, False),
    ImportCodeSpec("IMPORT_SNAPSHOT_SUPERSEDES", _WA, _FI, False),
    ImportCodeSpec("IMPORT_UNSUPPORTED_CURRENCY", _WA, _FI, False),
    # warning · 行/字段级 15
    ImportCodeSpec("IMPORT_NET_AMOUNT_MISMATCH", _WA, _RO, False),
    ImportCodeSpec("IMPORT_UNKNOWN_SECURITY", _WA, _RO, True),
    ImportCodeSpec("IMPORT_MARKET_INFERRED_CONFLICT", _WA, _RO, True),
    ImportCodeSpec("IMPORT_NAME_MISMATCH", _WA, _FD, False),
    ImportCodeSpec("IMPORT_UNKNOWN_BIZ_TYPE", _WA, _RO, True),
    ImportCodeSpec("IMPORT_ROW_CANCELLED", _WA, _RO, False),
    ImportCodeSpec("IMPORT_ROW_REJECTED", _WA, _RO, False),
    ImportCodeSpec("IMPORT_DUPLICATE_IN_DB", _WA, _RO, False),
    ImportCodeSpec("IMPORT_DUPLICATE_IN_FILE", _WA, _RO, False),
    ImportCodeSpec("IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL", _WA, _RO, True),
    ImportCodeSpec("IMPORT_MISSING_OPENING_POSITION", _WA, _RO, False),
    ImportCodeSpec("IMPORT_CASH_CHAIN_BREAK", _WA, _RO, False),
    ImportCodeSpec("IMPORT_NON_TRADING_DAY", _WA, _RO, False),
    ImportCodeSpec("IMPORT_TIME_OUTSIDE_SESSION", _WA, _RO, False),
    ImportCodeSpec("IMPORT_LOT_SIZE_IRREGULAR", _WA, _RO, False),
)


# ---------------------------------------------------------------------------
# 非 §3 取值（契约内联字面量 / plan §3 表字段；不进入 /meta/enums）
# ---------------------------------------------------------------------------


class ProfileEffort(StrEnum):
    """契约 §7.1 ``/me/profile.effort``（v0.2.2 起 plan ``user_profiles.effort`` 与之一致）。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProfileExperience(StrEnum):
    """契约 §7.1 ``/me/profile.experience``。"""

    NOVICE = "novice"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class HorizonAssessmentTrigger(StrEnum):
    """plan §3 ``symbol_horizon_assessments.trigger``（T-A02 新增 ``position_open_close``）。"""

    IMPORT = "import"
    WATCHLIST_ADD = "watchlist_add"
    WEEKLY = "weekly"
    POSITION_OPEN_CLOSE = "position_open_close"
