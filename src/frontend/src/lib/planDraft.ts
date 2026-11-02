/** 计划草案的纯函数（T-F18）：状态、偏离、必答、输入校验 */
import { ENUMS, type PlanDraftStatus } from '../api/enums';
import type { ChecklistAnswer, PlanDraft } from '../api/planTypes';

const ALL = ENUMS.plan_draft_status as readonly PlanDraftStatus[];
/** URL ?status=pending,stale → 合法值数组（契约 §7.7：可多值，默认全部） */
export function parseStatuses(v: string | null): PlanDraftStatus[] {
  return (v ?? '').split(',').map((x) => x.trim()).filter((x): x is PlanDraftStatus => (ALL as readonly string[]).includes(x));
}

/** 只有 pending 的草案可确认或放弃；stale / expired 不能修改（契约 §7.7） */
export const canAct = (s: PlanDraftStatus) => s === 'pending';
/** stale：条件已变，可用原 signal_ids 重新生成；expired 同样允许尝试（由服务端判断信号是否仍可拟定） */
export const canRegenerate = (s: PlanDraftStatus) => s === 'stale' || s === 'expired';

const INT = /^\d+$/;
const DEC = /^\d+(\.\d{1,3})?$/;
export const qtyError = (v: string) => (!v.trim() ? '请填写数量' : !INT.test(v.trim()) || Number(v) <= 0 ? '数量须为正整数' : null);
export const priceError = (v: string) => (!v.trim() ? '请填写价格' : !DEC.test(v.trim()) || Number(v) <= 0 ? '价格须为正数，最多 3 位小数' : null);

/** 超出草案区间的字段（与服务端 DEVIATION_ACK_REQUIRED.details.fields 同名） */
export function deviationFields(d: PlanDraft, qty: string, price: string): ('chosen_qty' | 'chosen_price')[] {
  const out: ('chosen_qty' | 'chosen_price')[] = [];
  const q = Number(qty);
  const p = Number(price);
  if (!qtyError(qty) && (q < Number(d.qty_range.min) || q > Number(d.qty_range.max))) out.push('chosen_qty');
  if (!priceError(price) && (p < Number(d.price_range.low) || p > Number(d.price_range.high))) out.push('chosen_price');
  return out;
}

/** 买入须为每手的整数倍（卖出可卖零股）；只提示，以服务端校验为准 */
export function lotWarning(d: PlanDraft, qty: string): string | null {
  const lot = Number(d.qty_range.lot);
  if (qtyError(qty) || !lot || (d.action !== 'buy' && d.action !== 'add')) return null;
  return Number(qty) % lot === 0 ? null : `买入数量通常须为 ${d.qty_range.lot} 的整数倍`;
}

/** 必答但未作答的清单项 id */
export function missingRequired(d: PlanDraft, answers: Record<string, ChecklistAnswer['answer'] | undefined>): string[] {
  return d.judgment_checklist.filter((c) => c.required && !answers[c.id]).map((c) => c.id);
}
