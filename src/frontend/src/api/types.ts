/**
 * API 类型，逐字段对齐 docs/api-contract.md v0.2.2（§1 通用约定、§5 共享对象、§7 端点）。
 * 约定：键名 snake_case；金额/价格/数量/比例为十进制字符串（Decimal）；`score` 为 0–100 整数或 null；
 * 标 `| null` 的字段总是出现。与契约不一致或契约未定的地方记在 reports/T-F01.md「遗留问题」，此处不自行扩展字段。
 */
import type {
  Action, BarAdjust, BarFreq, CandidateSignalState, CheckOn, ComponentHealth, ConfidenceLevel, ConsensusStatus, DataProvider,
  DataStatus, Dimension, DimensionView, EpistemicType, ExecutabilityStatus, DataLicenceState, GapReason, HealthStatus, Horizon, IngestHealth,
  Lifecycle, MarketRegime, MarketSession, NotificationKind, NotificationTargetType, ReasonCode, ReasonStatus,
  ReconciliationStatus, RegistrationMode, ReleaseKind, RiskControl, RiskLevel, Role, AccountStatus, RuleRole, Severity,
  SignalKind, StrategyEvalState, SuggestionOrigin, SuggestionStatus, TLeg, PlanDraftStatus, AlertOrigin, AlertStatus, PlanConditionKind,
  DataGapScope, SecurityType,
} from './enums';
import type { DailyDimensionAnalysis } from './phase2Types';

export type Decimal = string;
export type DateTime = string;
export type DateStr = string;
export type Uuid = string;

// ---------- §1 ----------
export interface Gap { key: string; reason: GapReason; message: string }
export interface DataStatusBlock { data_status: DataStatus; data_as_of: DateTime; gaps: Gap[] }
export interface Paged<T> { items: T[]; next_cursor: string | null }
export interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown> | null; request_id: string };
}

// ---------- §5.1 ----------
export interface Evidence {
  id: string;
  key: string;
  value: string | number | boolean | null;
  unit: string | null;
  /** v0.2.3：统一为 data_provider 枚举（无 local）；展示层对未知值兜底显示原值 */
  provider: DataProvider;
  endpoint: string | null;
  data_as_of: DateTime;
  fetched_at: DateTime;
  epistemic_type: EpistemicType;
}
export interface RuleRef {
  rule_id: string;
  snippet_id: Uuid | null;
  snippet_version: number | null;
  role: RuleRole;
  dimension: Dimension;
  /** v0.2.2：规则表达式求值为真；数据缺失无法求值为 null */
  passed: boolean | null;
  value: string | null;
  threshold: string | null;
  evidence_ids: string[];
}
export interface ModelRef { model_key: string; version: string; role: 'auxiliary'; output: Record<string, unknown>; evidence_ids: string[] }
export interface TextWithEvidence { text: string; expr: string | null; evidence_ids: string[] }
/** v0.2.3 §5.1 HorizonCap */
/** v0.2.6（T006e）：kind 只有 gate（HG1–HG6）与 data_missing（特征缺失，或 LG0 / LG0B）；IT0 判 0 分是分数，不进 caps */
export interface HorizonCap { horizon: Horizon; cap: number; kind: 'gate' | 'data_missing'; rule_id: string | null; inputs_missing: string[] }
/** v0.2.5 §5.1 HorizonHint：画像类规则（mode: hint）已填写且不满足时的提示；不影响分数与 suitable */
export interface HorizonHint { horizon: Horizon; rule_id: string; text: string }
export type HorizonReason = TextWithEvidence & { horizon: Horizon; polarity: 'for' | 'against' };
/** v0.2.2 `GET /horizon-assessments?security_code=` 周期分类结果（版本化） */
export interface HorizonAssessment {
  suitable: Horizon[];
  /** 四个周期都有，0–100，不为 null（数据缺失按封顶处理） */
  scores: Record<Horizon, number>;
  /** 每个周期 2–4 条 */
  reasons: HorizonReason[];
  /** 缺失的 f.* 输入键，用来区分“真 0 分”与“缺数据被封顶” */
  inputs_missing: string[];
  /** v0.2.3：哪个周期因什么被封顶；同一周期多个封顶取最小 */
  caps: HorizonCap[];
  /** v0.2.5：画像类规则的提示，永不为 null */
  hints: HorizonHint[];
  /** v0.2.3：语义化版本，如 "1.2.0" */
  classifier_version: string;
  snapshot_id: string;
  /** v0.2.3：reasons[].evidence_ids 只在本响应的 evidence[] 内解析 */
  evidence: Evidence[];
}
export interface Stat { value: Decimal | null; n: number; window: string; small_sample: boolean }
export interface ReleaseCondition {
  kind: ReleaseKind;
  expr: string | null;
  at: DateTime | null;
  event: string | null;
  action: string | null;
  check_on: CheckOn[];
  human_text: string;
  machine_checkable: boolean;
}
export interface RiskFlag {
  control: RiskControl;
  level: RiskLevel;
  message: string;
  gated_actions: Action[];
  quantity_cap: Decimal | null;
  evidence_ids: string[];
}
export interface Stops { stop_loss: Decimal | null; take_profit: Decimal | null; time_stop_days: number | null }
export interface Confidence { level: ConfidenceLevel; value: number }
export interface ConfidenceComponents {
  data_completeness: number;
  dimension_agreement: number | null;
  condition_margin: number | null;
  margin_rules: { rule_id: string; value: Decimal; threshold: Decimal; scale: Decimal; scale_kind: 'declared' | 'atr14' | 'abs_threshold'; margin: number; weight: Decimal }[];
}
export interface Bar {
  t: DateStr | DateTime;
  open: Decimal;
  high: Decimal;
  low: Decimal;
  close: Decimal;
  pre_close: Decimal | null;
  /** 股 */
  volume: Decimal;
  /** 元 */
  amount: Decimal;
  /** 仅 1m */
  avg_price: Decimal | null;
  /** v0.2.7：日 K 当日收盘入库后为 true；周 K 见 §6.2；1m 正在形成的一分钟为 false */
  is_final: boolean;
}
export interface WatchlistItem {
  security_code: string;
  name: string;
  focus: boolean;
  group: string | null;
  note: string | null;
  added_at: DateTime;
  refresh_tier: 'tier1' | 'tier2' | null;
}
export interface SignalEvent {
  signal_event_id: string;
  security_code: string;
  name: string;
  kind: SignalKind;
  at: DateTime;
  message: string;
  strategy_key: string | null;
  instance_id: Uuid | null;
  rule_id: string | null;
  price: Decimal | null;
  candidate_signal_id: Uuid | null;
}
export interface NotificationTarget { type: NotificationTargetType; id: string | null; route: string | null }
export interface Notification {
  id: Uuid;
  kind: NotificationKind;
  severity: Severity;
  title: string;
  body: string | null;
  created_at: DateTime;
  read_at: DateTime | null;
  security_code: string | null;
  name: string | null;
  target: NotificationTarget;
}
export interface SuggestionSummaryAction { strategy_key: string; strategy_name: string; action: Action; t_leg: TLeg | null; lifecycle: Lifecycle }
export interface SuggestionSummary {
  id: Uuid;
  created_at: DateTime;
  status: SuggestionStatus;
  consensus: ConsensusStatus;
  actions: SuggestionSummaryAction[];
  executability_status: ExecutabilityStatus;
  divergent_dimensions: Dimension[];
  top_score: number | null;
}
export interface TerminalQuote { price: Decimal; change_pct: Decimal; amount: Decimal; t: DateTime }
export interface TerminalHolding {
  qty: Decimal;
  sellable_qty: Decimal;
  /** 摊薄成本 */
  cost_price: Decimal;
  weight_pct: Decimal;
  /** v0.2.9 #3：无行情时为 null */
  pnl: Decimal | null;
  pnl_pct: Decimal | null;
  /** v0.2.9 #2：null = 不在证券主数据中（本版主要是可转债） */
  security_type: SecurityType | null;
  /** v0.2.9 #2：true = 无行情，weight_pct 按成本估算 */
  estimated: boolean;
}
export interface TerminalRow {
  security_code: string;
  name: string;
  in_watchlist: boolean;
  focus: boolean;
  quote: TerminalQuote | null;
  holding: TerminalHolding | null;
  suggestion: SuggestionSummary | null;
  active_reason_count: number;
  max_risk_level: RiskLevel | null;
  data_status: DataStatus;
  /** v0.2.3：该行行情与建议中较旧者的数据时点；完全无数据为 null */
  data_as_of: DateTime | null;
}

// ---------- §5.2 ----------
export interface DimensionViewEntry { dimension: Dimension; view: DimensionView; score: number | null; rules: RuleRef[] }
export interface StrategyConclusion {
  strategy_version_id: Uuid;
  strategy_key: string;
  strategy_name: string;
  version_no: number;
  instance_id: Uuid | null;
  horizon: Horizon;
  lifecycle: Lifecycle;
  state: StrategyEvalState;
  action: Action;
  t_leg: TLeg | null;
  candidate_signal_id: Uuid | null;
  score: number | null;
  confidence: Confidence & { components: ConfidenceComponents };
  rule_refs: RuleRef[];
  model_refs: ModelRef[];
  priority_weight: Decimal;
  priority_downweighted: boolean;
  dimension_views: DimensionViewEntry[];
  stops: Stops;
  reasons: TextWithEvidence[];
  counter_evidence: TextWithEvidence[];
  invalidation: TextWithEvidence[];
  valid_until: DateTime | null;
}
export interface DimensionCell {
  strategy_key: string;
  strategy_version_id: Uuid;
  view: DimensionView;
  score: number | null;
  key_evidence_ids: string[];
  rules_passed: number;
  rules_total: number;
  /** v0.2.3：role ∈ {weakening, exit} 且已求值的规则数 / 其中命中数；纯离场策略显示“离场 x/y” */
  exit_hits: number;
  exit_total: number;
}
export interface DimensionMatrixRow { dimension: Dimension; divergent: boolean; cells: DimensionCell[] }
export interface Divergence {
  dimensions: Dimension[];
  summary: string;
  resolving_info: { description: string; subscribable: boolean }[];
}
export interface Explanation { source: 'template' | 'llm'; text: string; llm_call_id: string | null }
export interface Suggestion extends DataStatusBlock {
  id: Uuid;
  security_code: string;
  name: string;
  created_at: DateTime;
  status: SuggestionStatus;
  origin: SuggestionOrigin;
  snapshot_id: string;
  feature_set_version: string;
  engine_policy: { version_no: number; content_sha256: string } | null;
  candidate_signal_ids: Uuid[];
  executability: { status: ExecutabilityStatus; reason_ids: Uuid[]; executable_signal_ids: Uuid[]; blocked_signal_ids: Uuid[] };
  plan_draft_ids: Uuid[];
  horizon_assessment: { suitable: Horizon[]; user_overridden: boolean };
  consensus: { status: ConsensusStatus; actions: Partial<Record<Action, number>> };
  strategies: StrategyConclusion[];
  dimension_matrix: DimensionMatrixRow[];
  divergence: Divergence[];
  risk_flags: RiskFlag[];
  evidence: Evidence[];
  explanation: Explanation;
  supersedes_id: Uuid | null;
  superseded_by_id: Uuid | null;
}
/** GET /suggestions 列表元素 = SuggestionSummary + security_code + name */
export interface SuggestionListItem extends SuggestionSummary { security_code: string; name: string }

// ---------- §5.3 ----------
export interface DailyReportStock {
  /** §7.11.1：旧日报及移出行投影为 null，不补造快照。 */
  analysis_snapshot_id: Uuid | null;
  dimensions: DailyDimensionAnalysis[] | null;
  security_code: string;
  name: string;
  /** v0.2.3：日报所属交易日收盘价与涨跌幅（停牌或缺数据为 null） */
  close: Decimal | null;
  change_pct: Decimal | null;
  data_status: DataStatus;
  max_risk_level: RiskLevel | null;
  suggestion_id: Uuid | null;
  suggestion: SuggestionSummary | null;
  change_from_previous: 'new' | 'changed' | 'unchanged' | 'removed' | null;
  change_fields: ('actions' | 'confidence_level' | 'executability' | 'max_risk_level')[];
  highlights: TextWithEvidence[];
  invalidation: TextWithEvidence[];
  next_watch: TextWithEvidence[];
}
export interface RegimePositionRange { min_pct: Decimal; max_pct: Decimal }
export interface DailyReport extends Omit<DataStatusBlock, 'data_as_of'> {
  /** T-A29：实际采用的非空来源时点取最早；全部无来源或旧版缺该键时为null，不借生成时刻。 */
  data_as_of: DateTime | null;
  date: DateStr;
  generated_at: DateTime;
  account_id: Uuid | null;
  market: {
    regime: MarketRegime | null;
    regime_position_range: RegimePositionRange | null;
    breadth: { up: number; down: number; limit_up: number; limit_down: number } | null;
    summary: TextWithEvidence[];
  };
  account: {
    total_assets: Decimal;
    cash: Decimal;
    position_pct: Decimal | null;
    pnl_day: Decimal | null;
    position_vs_regime: 'below' | 'within' | 'above' | null;
  } | null;
  reconciliation: { status: ReconciliationStatus; as_of: DateTime | null; diff_count: number; important_count: number };
  stocks: DailyReportStock[];
  pending: { plan_drafts: number; active_reasons: number };
  explanation: Explanation;
  evidence: Evidence[];
}
export interface DailyReportListItem {
  date: DateStr;
  generated_at: DateTime;
  regime: MarketRegime | null;
  reconciliation_status: ReconciliationStatus;
  stock_count: number;
}

// ---------- §7.6 ----------
/** 契约只给了示例（§7.6），无逐字段表；可空性按示例推断（遗留问题） */
export interface CandidateSignal extends DataStatusBlock {
  id: Uuid;
  instance_id: Uuid;
  strategy_version_id: Uuid;
  strategy_key: string;
  strategy_name: string;
  lifecycle: Lifecycle;
  security_code: string;
  name: string;
  horizon: Horizon;
  state: CandidateSignalState;
  proposed_action: Action;
  t_leg: TLeg | null;
  score: number | null;
  confidence: Confidence;
  stops: Stops;
  rule_refs: RuleRef[];
  evidence: Evidence[];
  counter_evidence: TextWithEvidence[];
  invalidation: TextWithEvidence[];
  model_refs: ModelRef[];
  risk_flags: RiskFlag[];
  gate_results: { gate: string; passed: boolean }[];
  reason_ids: Uuid[];
  plan_draft_ids: Uuid[];
  valid_until: DateTime | null;
  snapshot_id: string;
  feature_set_version: string;
  created_at: DateTime;
}
export interface NonExecutableReason {
  id: Uuid;
  signal_id: Uuid;
  /** v0.2.9 #8：服务端按所属信号联查，只读 */
  security_code: string;
  name: string;
  code: ReasonCode;
  description: string;
  evidence: Evidence[];
  release_condition: ReleaseCondition;
  status: ReasonStatus;
  detected_at: DateTime;
  released_at: DateTime | null;
  release_evidence: Record<string, unknown> | null;
  released_by: 'system' | 'user';
}

// ---------- §7.1 / 7.2 / 7.3 / 7.10 ----------
export interface Me {
  id: Uuid;
  username: string;
  display_name: string;
  role: Role;
  status: AccountStatus;
  entitlements: Record<string, unknown>;
  /** v0.2.6：本人数据证书状态（不含证书值） */
  data_licence_status: DataLicenceState;
}
/** GET /meta/registration */
export interface RegistrationMeta { mode: RegistrationMode }
export interface PortfolioPosition {
  security_code: string;
  name: string;
  /** v0.2.9 #2：null = 不在证券主数据中（本版主要是按 import_as_is 导入的可转债） */
  security_type: SecurityType | null;
  qty: Decimal;
  sellable_qty: Decimal;
  cost_price: Decimal;
  /** v0.2.9 #1：无行情的行为 null（不是 0） */
  market_value: Decimal | null;
  pnl: Decimal | null;
  pnl_pct: Decimal | null;
  /** 无行情的行按成本 qty × cost_price 估算 */
  weight_pct: Decimal;
  /** v0.2.9 #2：true = 无行情、weight_pct 按成本估算 */
  estimated: boolean;
}
export interface Portfolio extends DataStatusBlock {
  cash: Decimal;
  total_assets: Decimal;
  positions: PortfolioPosition[];
  exposure: { sector: { name: string; pct: Decimal }[] };
}
export interface WatchlistResponse { items: WatchlistItem[]; caps: { watchlist: number; focus: number } }
export interface QuoteItem extends DataStatusBlock {
  security_code: string;
  name: string;
  price: Decimal;
  change_pct: Decimal;
  volume: Decimal;
  amount: Decimal;
  t: DateTime;
}
export interface BarsResponse extends DataStatusBlock {
  security_code: string;
  name: string;
  freq: BarFreq;
  adjust: BarAdjust;
  pre_close: Decimal | null;
  items: Bar[];
  next_before: string | null;
  /** v0.2.7：前复权基准日（adjust=none 时为 null）；变化时客户端丢弃同证券同复权方式的缓存并重载 */
  adjust_as_of: DateStr | null;
}
export interface TerminalAccount {
  account_id: Uuid;
  total_assets: Decimal;
  cash_available: Decimal;
  position_pct: Decimal | null;
  pnl_day: Decimal | null;
  regime: MarketRegime | null;
  regime_position_range: RegimePositionRange | null;
  data_status: DataStatus;
}
export interface TerminalResponse {
  server_time: DateTime;
  /** v0.2.3：行情所属交易日（非交易日为最近一个交易日） */
  trade_date: DateStr;
  session: MarketSession;
  account: TerminalAccount | null;
  rows: TerminalRow[];
  truncated: boolean;
  unread_notifications: number;
}
/** v0.2.7 §7.3 /today 补充：提醒（不含 origin=plan_condition） */
export interface TodayAlert {
  id: Uuid;
  rule_id: Uuid;
  origin: AlertOrigin;
  severity: Severity;
  status: AlertStatus;
  security_code: string | null;
  name: string | null;
  title: string;
  triggered_at: DateTime;
  data_as_of: DateTime | null;
  affected_plans: { plan_id: Uuid; plan_version_no: number; condition_id: Uuid | null }[];
  evidence_ids: string[];
}
/** v0.2.7：计划条件已满足（只是事实提示，不下单） */
export interface TodayPlanTrigger {
  plan_id: Uuid;
  plan_version_no: number;
  security_code: string;
  name: string;
  condition_id: Uuid;
  condition_kind: PlanConditionKind;
  condition_text: string;
  triggered_at: DateTime;
  alert_id: Uuid | null;
  evidence_ids: string[];
}
/** v0.2.7：数据完整性缺口 */
export interface TodayDataGap {
  key: string;
  reason: GapReason;
  scope: DataGapScope;
  dataset: string | null;
  message: string;
  security_count: number;
  securities: { security_code: string; name: string }[];
  since: DateTime | null;
  route: string | null;
}
export type TerminalScope = 'all' | 'watchlist' | 'holdings';
export interface UnreadCount { count: number }
export interface HealthReady {
  status: HealthStatus;
  db: ComponentHealth;
  redis: ComponentHealth;
  ingest: IngestHealth;
  checked_at: DateTime;
  version: string;
}

// ---------- v0.2.3 §7.3 /market/overview（最小结构） ----------
export interface MarketIndexQuote { security_code: string; name: string; price: Decimal | null; change_pct: Decimal | null; amount: Decimal | null; t: DateTime | null }
export interface MarketOverview extends DataStatusBlock {
  trade_date: DateStr;
  session: MarketSession;
  indices: MarketIndexQuote[];
  breadth: { up: number; down: number; flat: number; limit_up: number; limit_down: number } | null;
  regime: MarketRegime | null;
  regime_position_range: RegimePositionRange | null;
  turnover_total: Decimal | null;
}

// ---------- §7.3 /today 首页聚合（ETag） ----------
export interface MoreList<T> { items: T[]; more: boolean }
export interface TodayResponse {
  server_time: DateTime;
  trade_date: DateStr;
  session: MarketSession;
  market: { regime: MarketRegime | null; regime_position_range: RegimePositionRange | null; data_status: DataStatus };
  focus: MoreList<TerminalRow>;
  pending_plan_drafts: MoreList<{ id: Uuid; security_code: string; name: string; action: Action; valid_until: DateTime | null; status: PlanDraftStatus }>;
  released_reasons: MoreList<{ reason_id: Uuid; signal_id: Uuid; code: ReasonCode; security_code: string; name: string; released_at: DateTime }>;
  risk_flags: MoreList<RiskFlag & { security_code: string | null; name: string | null; risk_event_id: Uuid | null }>;
  invalidations_today: MoreList<{ suggestion_id: Uuid; security_code: string; name: string; strategy_key: string; text: string; at: DateTime }>;
  daily_report: { date: DateStr; status: 'ready' | 'generating' | 'not_yet' };
  reconciliation: { status: ReconciliationStatus; as_of: DateTime | null; diff_count: number; important_count: number };
  unread_notifications: number;
  // v0.2.7 /today 补充
  alerts: MoreList<TodayAlert>;
  plan_triggers: MoreList<TodayPlanTrigger>;
  data_gaps: MoreList<TodayDataGap>;
  evidence: Evidence[];
}
