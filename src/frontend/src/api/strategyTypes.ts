/** 策略库类型（契约 v0.2.7 §5.1 StrategyInstance、§6.0A、§7.4 /strategies、§7.5 /strategy-instances） */
import type { CardRiskLevel, Horizon, InstanceEventKind, InstanceOrigin, InstanceStatus, Lifecycle, ReasonCode } from './enums';
import type { DateTime, Decimal, Uuid } from './types';

/** GET /strategies 元素 */
export interface StrategyTemplate {
  id: Uuid;
  key: string;
  name: string;
  horizons: Horizon[];
  current_version: { id: Uuid; version_no: number; lifecycle: Lifecycle };
  health: { state: string; weight: Decimal; n: number };
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
