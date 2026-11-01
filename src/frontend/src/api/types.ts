/**
 * API 类型，逐字段对齐 docs/api-contract.md v0.2.2（§1 通用约定、§5 共享对象、§7 端点）。
 * 约定：键名 snake_case；金额/价格/数量/比例为十进制字符串（Decimal）；`score` 为 0–100 整数或 null；
 * 标 `| null` 的字段总是出现。与契约不一致或契约未定的地方记在 reports/T-F01.md「遗留问题」，此处不自行扩展字段。
 */
import type {
  Action, BarAdjust, BarFreq, CandidateSignalState, CheckOn, ComponentHealth, ConfidenceLevel, ConsensusStatus, DataProvider,
  DataStatus, Dimension, DimensionView, EpistemicType, ExecutabilityStatus, GapReason, HealthStatus, Horizon, IngestHealth,
  Lifecycle, MarketRegime, MarketSession, NotificationKind, NotificationTargetType, ReasonCode, ReasonStatus,
  ReconciliationStatus, RegistrationMode, ReleaseKind, RiskControl, RiskLevel, Role, AccountStatus, RuleRole, Severity,
  SignalKind, StrategyEvalState, SuggestionOrigin, SuggestionStatus, TLeg,
} from './enums';

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
  /** 契约 §5.1 写 mairui|local|user_import，§3 data_provider 写 mairui|user_import|user_input|system；按 §3（遗留问题 #1） */
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
/** v0.2.2 `GET /horizon-assessments?security_code=` 周期分类结果（版本化） */
export type HorizonReason = TextWithEvidence & { horizon: Horizon; polarity: 'for' | 'against' };
export interface HorizonAssessment {
  suitable: Horizon[];
  /** 四个周期都有，0–100，不为 null（数据缺失按封顶处理） */
  scores: Record<Horizon, number>;
  /** 每个周期 2–4 条 */
  reasons: HorizonReason[];
  /** 缺失的 f.* 输入键，用来区分“真 0 分”与“缺数据被封顶” */
  inputs_missing: string[];
  classifier_version: string;
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
export interface SuggestionSummaryAction { strategy_key: string; strategy_name: string; action: Action; t_leg: TLeg | null }
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
  pnl: Decimal;
  pnl_pct: Decimal;
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
  confidence: Confidence;
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
  security_code: string;
  name: string;
  suggestion_id: Uuid | null;
  suggestion: SuggestionSummary | null;
  change_from_previous: 'new' | 'changed' | 'unchanged' | 'removed';
  highlights: TextWithEvidence[];
  invalidation: TextWithEvidence[];
  next_watch: TextWithEvidence[];
}
export interface RegimePositionRange { min_pct: Decimal; max_pct: Decimal }
export interface DailyReport extends DataStatusBlock {
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
    position_pct: Decimal;
    pnl_day: Decimal;
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
  consents: Record<string, { version: string; accepted_at: DateTime }>;
  risk_assessment: { level: number; assessed_at: DateTime } | null;
}
export interface RegistrationMeta { mode: RegistrationMode }
export interface PortfolioPosition {
  security_code: string;
  name: string;
  qty: Decimal;
  sellable_qty: Decimal;
  cost_price: Decimal;
  market_value: Decimal;
  pnl: Decimal;
  pnl_pct: Decimal;
  weight_pct: Decimal;
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
}
export interface TerminalAccount {
  account_id: Uuid;
  total_assets: Decimal;
  cash_available: Decimal;
  position_pct: Decimal;
  pnl_day: Decimal;
  regime: MarketRegime | null;
  regime_position_range: RegimePositionRange | null;
  data_status: DataStatus;
}
export interface TerminalResponse {
  server_time: DateTime;
  session: MarketSession;
  account: TerminalAccount | null;
  rows: TerminalRow[];
  truncated: boolean;
  unread_notifications: number;
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
