/** 计划草案的纯函数（T-F18）：状态、偏离、必答、输入校验 */
import { ENUMS, type PlanDraftStatus } from '../api/enums';
import type { ChecklistAnswer, PlanDraft } from '../api/planTypes';
import { ApiError } from '../api/client';

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

/** 服务端下发的整手参数（400 VALIDATION_ERROR fields[] 中 chosen_qty/lot_rule 元素的 min_buy、step） */
export type LotRule = { min_buy: string | null; step: string | null };

/**
 * 整手提示（契约 v0.2.9 #14、#30 ③）。前端不写死任何板块的整手参数（review-787e453 m1），只用服务端字段：
 * - 买入/加仓：草案 qty_range.lot（递增单位）；收到服务端 lot_rule 后再用其 min_buy、step；
 * - 卖出/减仓：不能超过可卖数量（草案快照）；收到 lot_rule 后按 #30 ③ 公式（等于全部可卖，或 ≥ min_buy 且 (数量 − min_buy) 是 step 的整数倍）。
 * 只提示，以服务端校验为准。
 */
export function lotWarning(d: PlanDraft, qty: string, rule: LotRule | null = null): string | null {
  if (qtyError(qty)) return null;
  const q = Number(qty);
  const num = (v: string | null | undefined) => (v != null && Number.isFinite(Number(v)) && Number(v) > 0 ? Number(v) : null);
  const minBuy = num(rule?.min_buy);
  const step = num(rule?.step);
  if (d.action === 'sell' || d.action === 'reduce') {
    const sellable = Number(d.user_context_snapshot.sellable_qty);
    if (Number.isFinite(sellable) && q > sellable) return `卖出数量不能超过可卖数量 ${d.user_context_snapshot.sellable_qty} 股`;
    if (Number.isFinite(sellable) && q === sellable) return null;
    if (minBuy === null || step === null) return null;
    if (q >= minBuy && (q - minBuy) % step === 0) return null;
    return `卖出数量须不少于 ${minBuy} 股${step > 1 ? `并按 ${step} 股递增` : ''}，或一次卖出全部可卖 ${d.user_context_snapshot.sellable_qty} 股（以交易所规则为准）`;
  }
  if (minBuy !== null && q < minBuy) return `买入数量须不少于 ${minBuy} 股`;
  const lot = step ?? num(d.qty_range.lot);
  if (!lot || lot <= 1) return null;
  return q % lot === 0 ? null : `买入数量须按 ${lot} 股递增`;
}

/** 400 VALIDATION_ERROR 的 lot_rule（契约 v0.2.9 #30 ③ 修正 #14）：min_buy、step 在 details.fields[] 的 chosen_qty 元素里 */
export function lotRuleOf(e: unknown): LotRule | null {
  if (!(e instanceof ApiError) || e.code !== 'VALIDATION_ERROR' || !e.details) return null;
  const det = e.details as Record<string, unknown>;
  const fields = Array.isArray(det.fields) ? (det.fields as Record<string, unknown>[]) : [];
  const hit = fields.find((f) => f.field === 'chosen_qty' && f.issue === 'lot_rule');
  if (!hit) return null;
  const str = (v: unknown) => (typeof v === 'string' || typeof v === 'number' ? String(v) : null);
  return { min_buy: str(hit.min_buy), step: str(hit.step) };
}

/** 必答但未作答的清单项 id */
export function missingRequired(d: PlanDraft, answers: Record<string, ChecklistAnswer['answer'] | undefined>): string[] {
  return d.judgment_checklist.filter((c) => c.required && !answers[c.id]).map((c) => c.id);
}
