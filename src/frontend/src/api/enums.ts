/**
 * 契约 v0.2.9 §3 枚举（取值逐字照抄；中文标签见 i18n/labels.ts）。
 * 运行时以 `GET /meta/enums` 为准；这里的常量用于类型推导与 mock 校验。
 */
/** 与 `/meta/enums.version` 对齐的契约版本 */
export const CONTRACT_VERSION = 'v0.2.9';

export const ENUMS = {
  account_status: ['pending', 'approved', 'rejected', 'disabled'],
  role: ['user', 'admin'],
  epistemic_type: ['fact', 'estimate', 'hypothesis', 'execution'],
  horizon: ['intraday_t', 'short', 'swing', 'long'],
  dimension: ['technical', 'capital', 'fundamental', 'sentiment', 'sector_market', 'news'],
  dimension_view: ['bullish', 'bearish', 'neutral', 'unknown'],
  rule_role: ['entry', 'hold', 'weakening', 'exit', 'filter', 'veto', 'counter', 'invalidation'],
  action: ['buy', 'add', 'hold', 'reduce', 'sell', 'wait'],
  t_leg: ['sell_first', 'buy_first'],
  confidence_level: ['high', 'medium', 'low'],
  consensus_status: ['unanimous', 'divergent', 'single', 'none'],
  strategy_eval_state: ['entry_ok', 'not_triggered', 'hold_ok', 'weakening', 'exit_signal', 'vetoed', 'insufficient_data'],
  executability_status: ['executable', 'blocked', 'not_applicable'],
  suggestion_origin: ['daily_batch', 'intraday_event', 'manual_refresh'],
  suggestion_status: ['active', 'superseded', 'invalidated', 'expired'],
  risk_control: ['stop_take', 'position_cap', 'total_exposure', 'sector_concentration', 'loss_streak_drawdown', 'plan_violation'],
  risk_level: ['info', 'warning', 'critical'],
  card_risk_level: ['normal', 'high'],
  // F-04：接口 STRATEGY_CARDS 列表项与详情（契约 §7.4 GET /strategy-cards）
  card_completeness: ['draft', 'documented', 'runnable_candidate', 'promoted', 'retired'],
  card_source_kind: ['builtin', 'admin', 'user', 'llm_draft', 'reference'],
  market_regime: ['uptrend', 'range', 'downtrend'],
  signal_kind: [
    'rule_flip', 'breakout', 'breakdown', 'vwap_deviation', 'volume_spike', 'limit_up_touch', 'limit_down_touch',
    'limit_open', 'invalidation_near', 'stop_hit', 'suspended', 'data_stale',
  ],
  market_session: ['non_trading_day', 'pre_open', 'call_auction', 'morning', 'lunch_break', 'afternoon', 'closing_auction', 'closed'],
  bar_freq: ['1m', 'd', 'w'],
  bar_adjust: ['none', 'qfq', 'hfq'],
  registration_mode: ['closed', 'invite', 'open'],
  notification_target_type: [
    'suggestion', 'candidate_signal', 'plan_draft', 'plan', 'daily_report', 'import_batch', 'reconciliation', 'strategy_version', 'none',
  ],
  notification_ref_type: ['signal', 'plan_condition'],
  explanation_fallback_reason: ['not_enabled', 'budget_exceeded', 'timeout', 'provider_error', 'validation_failed'],
  notification_kind: [
    'suggestion_change', 'invalidation', 'daily_report', 'alert', 'import', 'system', 'reason_released', 'plan_draft_ready',
    'plan_triggered', 'strategy_health', 'data_licence',
  ],
  severity: ['info', 'attention', 'important'],
  channel: ['in_app', 'email', 'wecom_app'],
  data_status: ['fresh', 'stale', 'pending', 'partial', 'unavailable'],
  gap_reason: ['no_source', 'not_yet_published', 'upstream_error', 'quota_deferred', 'user_input_missing', 'data_licence_unavailable', 'not_applicable'],
  data_provider: ['mairui', 'user_import', 'user_input', 'system', 'exchange'],
  source_kind: ['market_data', 'disclosure', 'user_input', 'system_calc'],
  trade_side: ['buy', 'sell'],
  import_status: ['uploaded', 'parsing', 'previewed', 'committed', 'failed', 'discarded', 'reverted'],
  import_severity: ['error', 'warning'],
  import_scope: ['file', 'row', 'field'],
  import_row_status: ['ok', 'warning', 'error', 'skipped'],
  dedup_status: ['new', 'duplicate_in_db', 'duplicate_in_file', 'possible_duplicate_of_manual'],
  reconciliation_status: ['matched', 'diff', 'not_imported'],
  reconciliation_item_kind: ['quantity_mismatch', 'missing_in_broker', 'missing_in_ours', 'cost_differs', 'cash_gap', 'cash_chain_break'],
  lifecycle: ['draft', 'simulating', 'published', 'observing', 'retired'],
  instance_status: ['proposed', 'active', 'paused', 'archived'],
  candidate_signal_state: ['open', 'drafted', 'blocked', 'released', 'confirmed', 'dismissed', 'expired', 'invalidated', 'superseded'],
  // v0.2.9 #6：/candidate-signals/{id}/events 的 cause（确认草案与用户忽略都用 user）
  candidate_signal_event_cause: ['executability_check', 'reason_released', 'user', 'expiry', 'invalidation', 'supersede'],
  // v0.2.9 T-A11（§7.7A 研究候选）
  research_candidate_status: ['researching', 'watching', 'dropped', 'planned'],
  research_candidate_origin: ['strategy_screen', 'suggestion', 'manual', 'from_stock'],
  candidate_decision: ['continue', 'watch', 'drop'],
  reason_status: ['active', 'released', 'obsolete'],
  check_on: ['tick', 'daily_close', 'schedule', 'holding_change', 'cash_update', 'import', 'plan_change', 'user_action'],
  release_kind: ['expr', 'time', 'event', 'user_action'],
  plan_draft_status: ['pending', 'confirmed', 'discarded', 'expired', 'stale'],
  health_status: ['ok', 'degraded', 'down'],
  component_health: ['ok', 'error'],
  ingest_health: ['ok', 'stale', 'paused', 'unknown'],
  // v0.2.6（plan 2.1B）：每用户自用数据证书
  data_licence_status: ['not_set', 'pending_verification', 'active', 'invalid', 'expired', 'quota_exceeded', 'ip_limited', 'paused_by_admin'],
  data_licence_tier: ['free', 'trial', 'monthly', 'annual', 'diamond', 'other'],
  // v0.2.7（T-A08）：个股数据、策略实例、/today 新增枚举（factor_category 键名待 T003，未列入）
  // v0.2.8：加 etf（顺序 stock cdr etf index）；可转债本版不收录
  security_type: ['stock', 'cdr', 'etf', 'index'],
  board: ['main', 'chinext', 'star', 'bse'],
  listing_status: ['listed', 'delisting_period', 'delisted', 'missing_from_list'],
  security_risk_flag: ['st', 'star_st', 'delisting'],
  security_match_kind: ['code_exact', 'name_exact', 'initials_exact', 'code_prefix', 'name_prefix', 'initials_prefix', 'name_contains', 'former_name', 'former_code', 'fuzzy'],
  report_period: ['q1', 'h1', 'q3', 'fy'],
  announcement_category: ['periodic_report', 'other'],
  sector_kind: ['industry', 'concept'],
  industry_taxonomy: ['sw_l1', 'sw_l2', 'csrc'],
  instance_origin: ['classifier', 'user', 'system'],
  instance_event_kind: ['created', 'confirmed', 'paused', 'resumed', 'params_changed', 'archived'],
  instance_sort: ['created_at_desc', 'updated_at_desc', 'strategy_name_asc'],
  sector_sort: ['main_net_desc', 'main_net_asc', 'change_pct_desc', 'change_pct_asc'],
  alert_origin: ['plan_condition', 'holding_event', 'user_custom'],
  alert_status: ['new', 'read', 'checked', 'acted', 'dismissed'],
  plan_condition_kind: ['trigger', 'invalidation'],
  // v0.2.9 #30（§7.7B）
  plan_status: ['active', 'triggered', 'done', 'cancelled'],
  plan_condition_type: ['price_above', 'price_below', 'pct_change', 'indicator', 'event', 'date', 'custom'],
  plan_origin: ['manual', 'plan_draft'],
  data_gap_scope: ['user', 'account', 'security', 'market'],
  // v0.2.9 内，T-A04（#33 ③）：证券主数据对账，只出现在 /admin/securities/reconciliation
  security_reconciliation_kind: ['vendor_stale_listed', 'vendor_unknown', 'quote_missing', 'quote_conflict', 'field_mismatch'],
  security_reconciliation_source: ['mairui_lists', 'mairui_real_all', 'cninfo', 'akshare'],
} as const;

/** §6.1 不可执行原因码（v0.2.5：22 个） */
export const REASON_CODES = [
  'DATA_STALE', 'KEY_DATA_MISSING', 'LOW_CONFIDENCE', 'NON_TRADING_TIME', 'SUSPENDED', 'LIMIT_LOCKED', 'ST_OR_DELISTING',
  'NEW_LISTING', 'INSUFFICIENT_CASH', 'T1_NOT_SELLABLE', 'NO_POSITION', 'POSITION_CAP_REACHED', 'STRATEGY_BUDGET_EXHAUSTED',
  'SECTOR_EXPOSURE_EXCEEDED', 'REGIME_MISMATCH', 'SAME_DIRECTION_PLAN_EXISTS', 'CONFLICTS_CONFIRMED_PLAN', 'BLOCKLISTED',
  'COOLING_OFF', 'LOSS_STREAK_PAUSE', 'STRATEGY_CONFLICT', 'USER_MUTED',
] as const;

type E<K extends keyof typeof ENUMS> = (typeof ENUMS)[K][number];
export type AccountStatus = E<'account_status'>;
export type Role = E<'role'>;
export type EpistemicType = E<'epistemic_type'>;
export type Horizon = E<'horizon'>;
export type Dimension = E<'dimension'>;
export type DimensionView = E<'dimension_view'>;
export type RuleRole = E<'rule_role'>;
export type Action = E<'action'>;
export type TLeg = E<'t_leg'>;
export type ConfidenceLevel = E<'confidence_level'>;
export type ConsensusStatus = E<'consensus_status'>;
export type StrategyEvalState = E<'strategy_eval_state'>;
export type ExecutabilityStatus = E<'executability_status'>;
export type SuggestionOrigin = E<'suggestion_origin'>;
export type SuggestionStatus = E<'suggestion_status'>;
export type RiskControl = E<'risk_control'>;
export type RiskLevel = E<'risk_level'>;
export type MarketRegime = E<'market_regime'>;
export type SignalKind = E<'signal_kind'>;
export type MarketSession = E<'market_session'>;
export type BarFreq = E<'bar_freq'>;
export type BarAdjust = E<'bar_adjust'>;
export type RegistrationMode = E<'registration_mode'>;
export type NotificationTargetType = E<'notification_target_type'>;
export type NotificationKind = E<'notification_kind'>;
export type Severity = E<'severity'>;
export type DataStatus = E<'data_status'>;
export type GapReason = E<'gap_reason'>;
export type DataLicenceState = E<'data_licence_status'>;
export type DataLicenceTier = E<'data_licence_tier'>;
export type DataProvider = E<'data_provider'>;
export type ReconciliationStatus = E<'reconciliation_status'>;
export type ReconciliationItemKind = E<'reconciliation_item_kind'>;
export type ImportStatus = E<'import_status'>;
export type ImportSeverity = E<'import_severity'>;
export type ImportScope = E<'import_scope'>;
export type ImportRowStatus = E<'import_row_status'>;
export type DedupStatus = E<'dedup_status'>;
export type TradeSide = E<'trade_side'>;
export type PlanDraftStatus = E<'plan_draft_status'>;
export type Lifecycle = E<'lifecycle'>;
export type CardRiskLevel = E<'card_risk_level'>;
export type CardCompleteness = E<'card_completeness'>;
export type CardSourceKind = E<'card_source_kind'>;
export type InstanceStatus = E<'instance_status'>;
export type CandidateSignalState = E<'candidate_signal_state'>;
export type CandidateSignalEventCause = E<'candidate_signal_event_cause'>;
export type ResearchCandidateStatus = E<'research_candidate_status'>;
export type ResearchCandidateOrigin = E<'research_candidate_origin'>;
export type CandidateDecision = E<'candidate_decision'>;
export type ReasonStatus = E<'reason_status'>;
export type CheckOn = E<'check_on'>;
export type ReleaseKind = E<'release_kind'>;
export type HealthStatus = E<'health_status'>;
export type ComponentHealth = E<'component_health'>;
export type IngestHealth = E<'ingest_health'>;
export type SecurityType = E<'security_type'>;
export type SourceKind = E<'source_kind'>;
export type Board = E<'board'>;
export type ListingStatus = E<'listing_status'>;
export type SecurityRiskFlag = E<'security_risk_flag'>;
export type SecurityMatchKind = E<'security_match_kind'>;
export type ReportPeriod = E<'report_period'>;
export type AnnouncementCategory = E<'announcement_category'>;
export type SectorKind = E<'sector_kind'>;
export type IndustryTaxonomy = E<'industry_taxonomy'>;
export type InstanceOrigin = E<'instance_origin'>;
export type InstanceEventKind = E<'instance_event_kind'>;
export type InstanceSort = E<'instance_sort'>;
export type SectorSort = E<'sector_sort'>;
export type AlertOrigin = E<'alert_origin'>;
export type AlertStatus = E<'alert_status'>;
export type PlanConditionKind = E<'plan_condition_kind'>;
export type PlanStatus = E<'plan_status'>;
export type PlanConditionType = E<'plan_condition_type'>;
export type PlanOrigin = E<'plan_origin'>;
export type DataGapScope = E<'data_gap_scope'>;
export type SecurityReconciliationKind = E<'security_reconciliation_kind'>;
export type SecurityReconciliationSource = E<'security_reconciliation_source'>;
export type ReasonCode = (typeof REASON_CODES)[number];

export type NotificationRefType = E<'notification_ref_type'>;

/** T-A36 §7.11.4 */
export type ExplanationFallbackReason = E<'explanation_fallback_reason'>;
