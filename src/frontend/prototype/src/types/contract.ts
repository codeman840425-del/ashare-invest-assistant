/**
 * 按 docs/api-contract.md（MVP v1）与 plan.md §2.5.5 / §0A.2 手写的 TS 类型。
 * 字段名一律照契约（snake_case）。契约未给出结构、原型自行假设的字段，
 * 用注释 `// [原型假设]` 标明，并在 reports/T-F00.md 的“遗留问题”中列出。
 */

// ---------- §1 通用 ----------
/** string(decimal)：十进制字符串 */
export type Decimal = string;
/** string(datetime)：ISO 8601，+08:00 */
export type DateTime = string;
/** string(date)：YYYY-MM-DD */
export type DateStr = string;

// ---------- §3 枚举 ----------
export type EpistemicType = 'fact' | 'estimate' | 'hypothesis' | 'execution';
export type Horizon = 'intraday_t' | 'short' | 'swing' | 'long';
export type Dimension = 'technical' | 'capital' | 'fundamental' | 'sentiment' | 'sector_market' | 'news';
export type DimensionView = 'bullish' | 'bearish' | 'neutral' | 'unknown';
export type RuleRole = 'entry' | 'hold' | 'weakening' | 'exit' | 'filter' | 'veto' | 'counter' | 'invalidation';
export type Action = 'buy' | 'add' | 'hold' | 'reduce' | 'sell' | 'wait';
export type TLeg = 'sell_first' | 'buy_first';
export type ConfidenceLevel = 'high' | 'medium' | 'low';
export type ConsensusStatus = 'unanimous' | 'divergent' | 'single' | 'none';
export type SuggestionOrigin = 'daily_batch' | 'intraday_event' | 'manual_refresh';
export type SuggestionStatus = 'active' | 'superseded' | 'invalidated' | 'expired';
export type RiskControl =
  | 'stop_take'
  | 'position_cap'
  | 'total_exposure'
  | 'sector_concentration'
  | 'loss_streak_drawdown'
  | 'plan_violation';
export type RiskLevel = 'info' | 'warning' | 'critical';
export type MarketRegime = 'uptrend' | 'range' | 'downtrend';
export type NotificationKind =
  | 'suggestion_change'
  | 'invalidation'
  | 'daily_report'
  | 'alert'
  | 'import'
  | 'system'
  | 'reason_released'
  | 'plan_draft_ready'
  | 'plan_triggered'
  | 'strategy_health';
export type Severity = 'info' | 'attention' | 'important';
export type DataStatus = 'fresh' | 'stale' | 'pending' | 'partial' | 'unavailable';
export type Lifecycle = 'draft' | 'simulating' | 'published' | 'observing' | 'retired';
export type CandidateSignalState =
  | 'open'
  | 'drafted'
  | 'blocked'
  | 'released'
  | 'confirmed'
  | 'dismissed'
  | 'expired'
  | 'invalidated'
  | 'superseded';
export type ReasonCode =
  | 'DATA_STALE'
  | 'KEY_DATA_MISSING'
  | 'LOW_CONFIDENCE'
  | 'NON_TRADING_TIME'
  | 'SUSPENDED'
  | 'LIMIT_LOCKED'
  | 'ST_OR_DELISTING'
  | 'NEW_LISTING'
  | 'INSUFFICIENT_CASH'
  | 'T1_NOT_SELLABLE'
  | 'NO_POSITION'
  | 'POSITION_CAP_REACHED'
  | 'STRATEGY_BUDGET_EXHAUSTED'
  | 'SECTOR_EXPOSURE_EXCEEDED'
  | 'REGIME_MISMATCH'
  | 'SAME_DIRECTION_PLAN_EXISTS'
  | 'CONFLICTS_CONFIRMED_PLAN'
  | 'BLOCKLISTED'
  | 'COOLING_OFF'
  | 'LOSS_STREAK_PAUSE'
  | 'STRATEGY_CONFLICT'
  | 'USER_MUTED'
  | 'PROFILE_OR_CONSENT_MISSING';
export type ReasonStatus = 'active' | 'released' | 'obsolete';
export type CheckOn =
  | 'tick'
  | 'daily_close'
  | 'schedule'
  | 'holding_change'
  | 'cash_update'
  | 'import'
  | 'plan_change'
  | 'user_action';
export type ReleaseKind = 'expr' | 'time' | 'event' | 'user_action';
export type GapReason = 'no_source' | 'not_yet_published' | 'upstream_error' | 'quota_deferred' | 'user_input_missing';

// ---------- §1.1 数据状态 ----------
export interface Gap {
  key: string;
  reason: GapReason;
  message: string;
}
export interface DataStatusBlock {
  data_status: DataStatus;
  data_as_of: DateTime;
  gaps: Gap[];
}

// ---------- §5 共享对象 ----------
export interface Evidence {
  id: string;
  key: string; // feature_key
  value: string | number | boolean | null;
  unit: string | null;
  provider: 'mairui' | 'local' | 'user_import';
  endpoint: string | null;
  data_as_of: DateTime;
  fetched_at: DateTime;
  epistemic_type: EpistemicType;
}
export interface RuleRef {
  rule_id: string;
  snippet_id: string | null;
  snippet_version: number | null;
  role: RuleRole;
  dimension: Dimension;
  passed: boolean;
  value: string | null;
  threshold: string | null;
  evidence_ids: string[];
}
export interface ModelRef {
  model_key: string;
  version: string;
  role: 'auxiliary';
  output: Record<string, unknown>;
  evidence_ids: string[];
}
export interface TextWithEvidence {
  text: string;
  expr: string | null;
  evidence_ids: string[];
}
export interface Stat {
  value: Decimal | null;
  n: number;
  window: string;
  small_sample: boolean;
}
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
export interface Confidence {
  level: ConfidenceLevel;
  value: number; // 0–1 两位小数
}
export interface Stops {
  stop_loss: Decimal | null;
  take_profit: Decimal | null;
  time_stop_days: number | null;
}

// ---------- §7.6 候选信号 ----------
export interface CandidateSignal extends DataStatusBlock {
  id: string;
  instance_id: string;
  strategy_version_id: string;
  strategy_key: string;
  lifecycle: Lifecycle;
  security_code: string;
  horizon: Horizon;
  state: CandidateSignalState;
  proposed_action: Action;
  t_leg: TLeg | null;
  score: number;
  confidence: Confidence;
  stops: Stops;
  rule_refs: RuleRef[];
  evidence: Evidence[];
  counter_evidence: TextWithEvidence[];
  invalidation: TextWithEvidence[];
  model_refs: ModelRef[];
  risk_flags: RiskFlag[];
  gate_results: { gate: string; passed: boolean }[];
  reason_ids: string[];
  plan_draft_ids: string[];
  valid_until: DateTime;
  snapshot_id: string;
  feature_set_version: string;
  created_at: DateTime;
}

export interface NonExecutableReason {
  id: string;
  signal_id: string;
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

// ---------- plan.md §2.5.5 Suggestion（候选信号卡）JSON 视图 ----------
/** §2.5.5 中 dimension_views[].rules[] 的元素（注意：与 RuleRef 字段名不同，见报告遗留问题） */
export interface DimensionRuleResult {
  rule_id: string;
  pass: boolean;
  value: string | null;
  threshold: string | null;
  evidence_id: string;
}
export interface DimensionViewItem {
  dimension: Dimension;
  view: DimensionView;
  score: number | null; // §2.5.5 示例为 0–1（0.83）；契约 §1 写“0–100 整数分数”，口径未定
  rules: DimensionRuleResult[];
}
export interface SuggestionStrategy {
  strategy_version_id: string;
  strategy_key: string;
  version_no: number;
  horizon: Horizon;
  action: Action;
  t_leg?: TLeg | null; // [原型假设] §2.5.5 未列，CandidateSignal 有
  score: number;
  confidence: Confidence;
  lifecycle: Lifecycle;
  rule_refs: Partial<RuleRef>[];
  model_refs: ModelRef[];
  priority_weight: number;
  priority_downweighted: boolean;
  dimension_views: DimensionViewItem[];
  stop_loss: Decimal | null;
  take_profit: Decimal | null;
  invalidation: TextWithEvidence[]; // §2.5.5 示例为 {expr, evidence_id}，原型按契约 TextWithEvidence
  reasons: TextWithEvidence[];
  counter_evidence: TextWithEvidence[];
  candidate_signal_id?: string; // [原型假设] 用于把策略列关联到候选信号
}
export interface DimensionMatrixRow {
  dimension: Dimension;
  cells: { strategy_key: string; view: DimensionView; score?: number | null; key_evidence?: string }[]; // score/key_evidence 为 [原型假设]
}
export interface Divergence {
  dimensions: Dimension[];
  summary: string;
  resolving_info: { description: string; subscribable: boolean }[];
}
export interface Suggestion extends DataStatusBlock {
  id: string;
  security_code: string;
  created_at: DateTime;
  origin: SuggestionOrigin;
  status?: SuggestionStatus; // [原型假设] 头表状态，§2.5.5 正文未列
  snapshot_id: string;
  feature_set_version: string;
  candidate_signal_ids: string[];
  executability: { status: 'executable' | 'blocked' | 'not_applicable'; reason_ids: string[] }; // 取值集合 [原型假设]
  plan_draft_ids: string[];
  horizon_assessment: { suitable: Horizon[]; user_overridden: boolean };
  consensus: { status: ConsensusStatus; actions: Partial<Record<Action, number>> };
  strategies: SuggestionStrategy[];
  dimension_matrix: DimensionMatrixRow[];
  divergence: Divergence[];
  risk_flags: RiskFlag[];
  evidence: Evidence[];
  explanation: { source: 'template' | 'llm'; text: string; llm_call_id: string | null };
  supersedes_id: string | null;
}

// ---------- §7.3 行情 ----------
export interface QuoteItem extends DataStatusBlock {
  security_code: string;
  price: Decimal;
  change_pct: Decimal;
  volume: Decimal;
  amount: Decimal;
  t: DateTime;
}
/** /securities/{code}/bars 单根 K 线。契约未给出元素结构，全部字段为 [原型假设] */
export interface Bar {
  t: DateTime | DateStr;
  open: Decimal;
  high: Decimal;
  low: Decimal;
  close: Decimal;
  volume: Decimal;
  avg_price?: Decimal; // 分时均价 [原型假设]
}

// ---------- §7.2 持仓 ----------
export interface PortfolioPosition {
  security_code: string;
  qty: Decimal;
  sellable_qty: Decimal;
  cost: Decimal;
  market_value: Decimal;
  pnl: Decimal;
  weight_pct: Decimal;
}
export interface Portfolio extends DataStatusBlock {
  cash: Decimal;
  total_assets: Decimal;
  positions: PortfolioPosition[];
  exposure: { sector: { name: string; pct: Decimal }[] };
}

// ---------- §7.8 通知 / §8 SSE ----------
export interface NotificationItem {
  id: string;
  kind: NotificationKind;
  severity: Severity;
  title: string;
  created_at: DateTime; // [原型假设] 契约只给出 SSE 的 {id, kind, severity, title}
  read: boolean; // [原型假设]
  link?: string; // [原型假设]
}
/** SSE `signal` 事件：{signal_event_id, security_code, kind, at}；kind 取值契约未定义 */
export interface SignalEvent {
  signal_event_id: string;
  security_code: string;
  kind: string;
  at: DateTime;
}

// ---------- 契约未给出结构的对象（全部为 [原型假设]，见报告遗留问题） ----------
/** 自选列表元素：契约 §7.3 只给出路径和 focus 开关 */
export interface WatchlistItem {
  security_code: string;
  name: string; // 证券简称：契约 quotes/portfolio 均无 name 字段
  focus: boolean;
  in_portfolio: boolean;
}
/** 盘后日报：契约 §7.8 只写“盘后日报（不可变）”，无字段结构 */
export interface DailyReportStock {
  security_code: string;
  name: string;
  suggestion_id: string;
  close: Decimal;
  change_pct: Decimal;
  facts: TextWithEvidence[];
  position: PortfolioPosition | null;
  consensus: Suggestion['consensus'];
  strategies: Pick<SuggestionStrategy, 'strategy_key' | 'horizon' | 'action' | 'score' | 'confidence' | 'stop_loss' | 'take_profit' | 'invalidation'>[];
  risk_flags: RiskFlag[];
  blocked_reason_codes: ReasonCode[];
  data_status: DataStatus;
  gaps: Gap[];
}
export interface DailyReport extends DataStatusBlock {
  date: DateStr;
  generated_at: DateTime;
  account: {
    total_assets: Decimal;
    cash: Decimal;
    market_value: Decimal;
    position_pct: Decimal;
    day_pnl: Decimal;
    day_pnl_pct: Decimal;
    market_regime: MarketRegime;
    regime_exposure_range_pct: [Decimal, Decimal];
    reconciliation: 'matched' | 'diff' | 'not_imported';
    exposure: Portfolio['exposure'];
    risk_flags: RiskFlag[];
  };
  stocks: DailyReportStock[];
  summary: { source: 'template' | 'llm'; text: string };
}
