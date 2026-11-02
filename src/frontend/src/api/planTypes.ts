/** 计划草案（契约 v0.2.8 §7.7；PlanDraft.created_at 与列表参数见 v0.2.7） */
import type { Action, EpistemicType, PlanDraftStatus } from './enums';
import type { DateTime, Decimal, RiskFlag, Stops, Uuid } from './types';

export interface ChecklistItem { id: string; question: string; required: boolean }
export interface PlanDraft {
  id: Uuid;
  status: PlanDraftStatus;
  signal_ids: Uuid[];
  security_code: string;
  name: string;
  action: Action;
  qty_range: { min: Decimal; max: Decimal; lot: Decimal };
  price_range: { low: Decimal; high: Decimal };
  stops: Stops;
  max_loss_amount: Decimal;
  max_loss_pct: Decimal;
  fee_estimate: { amount: Decimal; epistemic_type: EpistemicType };
  user_context_snapshot: { holding_qty: Decimal; sellable_qty: Decimal; cash: Decimal; sector_pct: Decimal };
  risk_flags: RiskFlag[];
  judgment_checklist: ChecklistItem[];
  valid_until: DateTime | null;
  market_rule_version_id: string;
  created_at: DateTime;
}

export type ChecklistAnswerValue = 'yes' | 'no' | 'unsure';
export interface ChecklistAnswer { id: string; answer: ChecklistAnswerValue; note?: string }
export interface PlanDraftConfirm {
  checklist_answers: ChecklistAnswer[];
  risk_ack: true;
  chosen_qty: Decimal;
  chosen_price: Decimal;
  deviation_ack: boolean;
}
export interface PlanDraftConfirmResult { plan_id: Uuid; plan_version_no: number }
