/** 策略库类型（契约 v0.2.7 §5.1 StrategyInstance、§6.0A、§7.4 /strategies、§7.5 /strategy-instances） */
import type { CardRiskLevel, Horizon, InstanceEventKind, InstanceOrigin, InstanceStatus, Lifecycle, ReasonCode } from './enums';
import type { DataStatusBlock, DateTime, Decimal, Stat, Uuid } from './types';

/** GET /strategies 元素 */
export interface StrategyTemplate {
  id: Uuid;
  key: string;
  name: string;
  horizons: Horizon[];
  current_version: { id: Uuid; version_no: number; lifecycle: Lifecycle };
  health: { state: string; weight: Decimal; n: number } | null;
  /** v0.2.7：取当前版本关联 L1 卡片的值，未关联为 normal */
  risk_level: CardRiskLevel;
}

/** POST /strategy-instances 请求体（契约 §7.5；v0.2.5 起没有 fit_ack，v0.2.6 T006e：高风险模板也没有确认字段） */
export interface StrategyInstanceCreate {
  strategy_version_id: Uuid;
  scope: 'account' | 'security' | 'watch_group';
  account_id: Uuid | null;
  security_code: string | null;
  horizon: Horizon;
  param_overrides: Record<string, unknown> | null;
  budget_amount: Decimal | null;
}
export interface StrategyInstanceCreated { id: Uuid; status: 'active'; derived_strategy_version_id: Uuid | null; warnings: string[] }

/** §5.1 StrategyInstance（v0.2.7 完整结构）：version/lifecycle/risk_level 指实际运行的版本（有派生版本时为派生版本） */
export interface StrategyInstance {
  id: Uuid;
  strategy_id: Uuid;
  strategy_key: string;
  strategy_name: string;
  strategy_version_id: Uuid;
  version_no: number;
  lifecycle: Lifecycle;
  derived_strategy_version_id: Uuid | null;
  risk_level: CardRiskLevel;
  status: InstanceStatus;
  origin: InstanceOrigin;
  scope: StrategyInstanceCreate['scope'];
  account_id: Uuid | null;
  security_code: string | null;
  name: string | null;
  horizon: Horizon;
  param_overrides: Record<string, unknown> | null;
  budget_amount: Decimal | null;
  auto_downweight: boolean;
  paused_by: 'user' | 'system' | null;
  pause_reason_code: ReasonCode | null;
  paused_until: DateTime | null;
  created_at: DateTime;
  confirmed_at: DateTime | null;
  updated_at: DateTime;
  archived_at: DateTime | null;
}

/** GET /strategy-instances/{id}/events 元素 */
export interface StrategyInstanceEvent {
  id: Uuid;
  kind: InstanceEventKind;
  from_status: InstanceStatus | null;
  to_status: InstanceStatus | null;
  actor: 'user' | 'system';
  reason_code: ReasonCode | null;
  note: string | null;
  detail: Record<string, unknown> | null;
  at: DateTime;
}

/** GET /strategies/{id}/versions/{vid}/tracking（契约 v0.2.7 §7.4）：所有统计都是 Stat（n < 30 small_sample；n < 5 value=null） */
export interface StrategyTrackingRow {
  horizon_days: 1 | 5 | 20;
  win_rate: Stat;
  avg_return_pct: Stat;
  avg_excess_pct: Stat;
  profit_loss_ratio: Stat;
  max_loss_streak: number;
  pending_count: number;
  untradable_count: number;
  excluded_count: number;
}

export interface StrategyTracking extends DataStatusBlock {
  scope: 'mine' | 'site';
  by_horizon: StrategyTrackingRow[];
}

/**
 * F-05：契约 §7.4 `GET /strategies/{id}/versions/{vid}`（不可变配置，plan §2.5.14 C 节）
 * 后端 app/api/v1/strategy_cards.py version_detail：`{**config, lifecycle, card_version_id, risk_level,
 * param_hash, parent_version_id, internal_check}`。
 *
 * `config` 各块按 plan C 节定义；未列出的块用 `unknown` 承接，避免为展示捏造字段。
 */
export interface StrategyParamsSchemaField {
  type: string;
  default?: unknown;
  min?: number | null;
  max?: number | null;
  step?: number | null;
  desc?: string | null;
}

/** plan C 节 `rules[]` 元素（role ∈ entry/hold/weakening/exit/filter/veto/counter/invalidation） */
export interface StrategyRule {
  id: string;
  dimension: string;
  role: string;
  expr: string;
  weight: number;
  required_features: string[];
}

/** 方案 A：用户只看到是否做过内部检验、方法类型和日期，**不含任何数值或通过与否** */
export interface InternalCheck {
  done: boolean;
  method_types: ('factor_ic' | 'event_study' | 'param_robustness')[];
  checked_on: string | null;
}

export interface StrategyVersionDetail {
  key: string;
  version_no: number;
  kind: string;
  horizons: Horizon[];
  params_schema: Record<string, StrategyParamsSchemaField>;
  rules: StrategyRule[];
  action_map?: Record<string, string> | null;
  stops?: { stop_loss: string | null; take_profit: string | null; time_stop_days: number | null } | null;
  dimension_view_thresholds?: Record<string, number> | null;
  applicability?: Record<string, unknown> | null;
  valid_until?: Record<string, unknown> | null;
  screen?: unknown;
  /** 展示附加字段（后端 version_detail 补出） */
  lifecycle: Lifecycle;
  card_version_id: string | null;
  risk_level: CardRiskLevel;
  param_hash: string;
  parent_version_id: string | null;
  internal_check: InternalCheck;
}
