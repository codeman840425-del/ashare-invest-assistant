/** T-F22：策略库最小类型（契约 v0.2.6 §7.5 /strategies、/strategy-instances）。完整策略库页在后续任务实现。 */
import type { CardRiskLevel, Horizon, InstanceStatus, Lifecycle } from './enums';
import type { Decimal, Uuid } from './types';

/** GET /strategies 元素 */
export interface StrategyTemplate {
  id: Uuid;
  key: string;
  name: string;
  horizons: Horizon[];
  current_version: { id: Uuid; version_no: number; lifecycle: Lifecycle };
  health: { state: string; weight: Decimal; n: number };
  /**
   * // [待契约确认] 契约 v0.2.6 只在 `/strategy-cards/{id}` 上有 `risk_level: card_risk_level`，`/strategies` 列表元素没有；
   * 前端按此字段判断是否为高风险模板（不按 key 硬编码），缺省视为 normal。已列入 T-F22 遗留问题请架构师补字段。
   */
  risk_level?: CardRiskLevel;
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

/** GET /strategy-instances 元素 // [待契约确认] 契约只写了 POST 请求体，列表元素结构未定义，这里取最小字段 */
export interface StrategyInstance {
  id: Uuid;
  strategy_id: Uuid;
  strategy_version_id: Uuid;
  status: InstanceStatus;
  scope: StrategyInstanceCreate['scope'];
  account_id: Uuid | null;
  security_code: string | null;
  horizon: Horizon;
}
