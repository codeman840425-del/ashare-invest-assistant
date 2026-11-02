/** T-F23 裁定跟进：操作计划表单的纯函数（契约 v0.2.9 §7.7B）；组件见 PlanForm.tsx */
import type { FormInstance } from 'antd';
import { ApiError } from '../../api/client';
import type { Action, PlanConditionKind, PlanConditionType } from '../../api/enums';
import { WRITABLE_CONDITION_TYPES, type PlanConditionInput, type PlanConditionParams, type PlanCreate, type PlanVersion } from '../../api/planAlertTypes';

export interface ConditionRow { kind: PlanConditionKind; type: PlanConditionType; value?: string; description: string }
export interface PlanFormValues {
  security_code?: string;
  action: Action;
  qty?: string;
  price?: string;
  rationale: string;
  risks?: string;
  review_date?: string;
  change_reason?: string;
  conditions: ConditionRow[];
}

const blank = (s?: string) => (s ?? '').trim() === '';

export function toParams(type: PlanConditionType, value?: string): PlanConditionParams {
  const v = (value ?? '').trim();
  if (type === 'price_above' || type === 'price_below') return { price: v };
  if (type === 'pct_change') return { pct: v };
  if (type === 'date') return { on: v };
  return {};
}
export function fromVersion(v: PlanVersion): PlanFormValues {
  return {
    action: v.action, qty: v.qty ?? undefined, price: v.price ?? undefined, rationale: v.rationale, risks: v.risks ?? undefined, review_date: v.review_date ?? undefined,
    conditions: v.conditions
      .filter((c) => WRITABLE_CONDITION_TYPES.includes(c.type))
      .map((c) => {
        const p = c.params as Record<string, string | undefined>;
        return { kind: c.kind, type: c.type, value: p.price ?? p.pct ?? p.on, description: c.description };
      }),
  };
}
/** 表单值 → 请求体公共部分（整体替换：空值写 null / []；保留原 stops 等未在表单里的字段由调用方补） */
export function toBody(v: PlanFormValues): Omit<PlanCreate, 'security_code' | 'account_id'> {
  return {
    action: v.action,
    qty: blank(v.qty) ? null : v.qty!.trim(),
    price: blank(v.price) ? null : v.price!.trim(),
    rationale: v.rationale.trim(),
    risks: blank(v.risks) ? null : v.risks!.trim(),
    review_date: blank(v.review_date) ? null : v.review_date!.trim(),
    conditions: (v.conditions ?? []).map((c): PlanConditionInput => ({ kind: c.kind, type: c.type, params: toParams(c.type, c.value), description: c.description.trim() })),
  };
}

/** 400 fields[] → 表单字段（conditions[i].xxx 映射到对应行） */
export function applyPlanErrors(form: FormInstance<PlanFormValues>, e: unknown): boolean {
  if (!(e instanceof ApiError) || e.status !== 400) return false;
  const fs = (e.details?.fields as { field: string; issue: string }[] | undefined) ?? [];
  const ISSUE: Record<string, string> = {
    unknown_security: '证券不存在', not_allowed: '不允许（指数不能建计划，或该字段不可修改）', not_supported: '本版不支持', invalid: '格式不正确', lot_rule: '不符合整手规则',
  };
  const out = fs.map((f) => {
    const m = /^conditions\[(\d+)\]\.?(\w+)?$/.exec(f.field);
    const name = m ? ['conditions', Number(m[1]), m[2] === 'params' ? 'value' : (m[2] ?? 'description')] : [f.field];
    return { name, errors: [ISSUE[f.issue] ?? f.issue] };
  });
  try {
    form.setFields(out as Parameters<typeof form.setFields>[0]);
  } catch {
    /* 未在表单中的字段只在顶部提示 */
  }
  return true;
}
