/**
 * 契约 v0.2.9 §7.7B 操作计划与提醒的结构（#30 前端待定裁定）。字段名逐字照抄；金额与价格为 string(decimal)。
 */
import type { Action, AlertStatus, PlanConditionKind, PlanConditionType, PlanOrigin, PlanStatus } from './enums';
import type { DateTime, Decimal, Evidence, Stops, TodayAlert, Uuid } from './types';

type DateStr = string;

export interface PlanSummary {
  id: Uuid;
  security_code: string;
  name: string;
  account_id: Uuid | null;
  origin: PlanOrigin;
  status: PlanStatus;
  action: Action;
  current_version_no: number;
  /** origin=plan_draft 时为来源草案 */
  plan_draft_id: Uuid | null;
  /** 本版恒为 null（§7.7A） */
  candidate_id: Uuid | null;
  /** 最近一次进入 triggered 的时刻；回到 active 后为 null */
  triggered_at: DateTime | null;
  created_at: DateTime;
  updated_at: DateTime;
}

/** price_above/price_below → {price}；pct_change → {pct}（带符号，相对前收盘）；date → {on}；custom → {} */
export type PlanConditionParams = { price: Decimal } | { pct: Decimal } | { on: DateStr } | Record<string, never>;

export interface PlanCondition {
  id: Uuid;
  kind: PlanConditionKind;
  type: PlanConditionType;
  params: PlanConditionParams;
  /** 1–200；TodayPlanTrigger.condition_text 的来源 */
  description: string;
  epistemic_type: 'hypothesis';
}

export interface PlanChecklistAnswer { id: string; question: string; answer: 'yes' | 'no' | 'unsure'; note: string | null }

export interface PlanVersion {
  plan_id: Uuid;
  version_no: number;
  action: Action;
  qty: Decimal | null;
  price: Decimal | null;
  size_pct_of_assets: Decimal | null;
  max_loss_amount: Decimal | null;
  stops: Stops | null;
  rationale: string;
  risks: string | null;
  review_date: DateStr | null;
  conditions: PlanCondition[];
  /** 第 1 版为 null */
  change_reason: string | null;
  /** 确认草案时的回答；手工计划为 [] */
  checklist_answers: PlanChecklistAnswer[];
  snapshot_id: string | null;
  created_at: DateTime;
}

export interface PlanPendingTrigger {
  condition_id: Uuid;
  condition_kind: PlanConditionKind;
  condition_text: string;
  triggered_at: DateTime;
  alert_id: Uuid | null;
  /** 指向 Plan.evidence */
  evidence_ids: string[];
}

export interface Plan extends PlanSummary {
  current_version: PlanVersion;
  version_count: number;
  pending_triggers: PlanPendingTrigger[];
  evidence: Evidence[];
}

export interface PlanConditionInput { kind: PlanConditionKind; type: PlanConditionType; params: PlanConditionParams; description: string }

/** POST /plans 请求体（origin 由服务端写为 manual；candidate_id 只能为 null） */
export interface PlanCreate {
  security_code: string;
  account_id: Uuid | null;
  action: Action;
  qty?: Decimal | null;
  price?: Decimal | null;
  size_pct_of_assets?: Decimal | null;
  max_loss_amount?: Decimal | null;
  stops?: Stops | null;
  rationale: string;
  risks: string | null;
  review_date: DateStr | null;
  /** 0–20 条 */
  conditions: PlanConditionInput[];
  candidate_id?: null;
}

/** POST /plans/{id}/versions：整体替换；security_code、account_id、origin 不可改 */
export interface PlanVersionCreate extends Omit<PlanCreate, 'security_code' | 'account_id' | 'candidate_id'> {
  base_version_no: number;
  /** 1–200 */
  change_reason: string;
}

export interface PlanClose { status: 'done' | 'cancelled'; note: string | null }

/** Alert = TodayAlert 全部字段 + checklist、snapshot_id、handled_at、evidence；/alerts 含 origin=plan_condition */
export interface Alert extends TodayAlert {
  checklist: string[];
  snapshot_id: string | null;
  /** 最近一次状态变更时刻 */
  handled_at: DateTime | null;
  evidence: Evidence[];
}

export type AlertPatchStatus = Exclude<AlertStatus, 'new'>;

/** 计划可写的条件类型（indicator、event 本版 → 400 not_supported） */
export const WRITABLE_CONDITION_TYPES: readonly PlanConditionType[] = ['price_above', 'price_below', 'pct_change', 'date', 'custom'];

/** §7.7B 提醒状态转换（问题 82）：只能前进；acted、dismissed 为终态 */
export const ALERT_NEXT: Record<AlertStatus, AlertPatchStatus[]> = {
  new: ['read', 'checked', 'acted', 'dismissed'],
  read: ['checked', 'acted', 'dismissed'],
  checked: ['acted', 'dismissed'],
  acted: [],
  dismissed: [],
};
export const isTerminalPlan = (s: PlanStatus) => s === 'done' || s === 'cancelled';
