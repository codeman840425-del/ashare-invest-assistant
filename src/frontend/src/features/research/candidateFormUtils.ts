/** T-F23 研究候选表单的纯函数（与组件分文件，满足 react-refresh） */
import type { FormInstance } from 'antd';
import { ApiError } from '../../api/client';
import type { ConfidenceLevel } from '../../api/enums';
import type { CandidateConditionInput } from '../../api/candidateTypes';
import { CANDIDATE_ISSUE } from '../../i18n/candidateLabels';

export const MAX_CONDITIONS = 10;
export interface ConditionValues { text?: string; verify_by?: string; verify_method?: string; confidence?: ConfidenceLevel | null }

/** 表单值 → CandidateConditionInput（空串按 null） */
export const toConditionInputs = (xs: ConditionValues[] | undefined): CandidateConditionInput[] =>
  (xs ?? []).map((c) => ({
    text: (c.text ?? '').trim(),
    verify_by: c.verify_by?.trim() || null,
    verify_method: c.verify_method?.trim() || null,
    confidence: c.confidence ?? null,
  }));
export const fromConditions = (xs: CandidateConditionInput[]): ConditionValues[] =>
  xs.map((c) => ({ text: c.text, verify_by: c.verify_by ?? '', verify_method: c.verify_method ?? '', confidence: c.confidence }));

const FIELD_LABEL: Record<string, string> = {
  thesis: '研究要点', security_code: '证券', suggestion_id: '来源', origin: '来源', decision: '决定', decision_reason: '理由',
  base_version_no: '版本', conditions_to_hold: '成立条件',
};

/**
 * 400 VALIDATION_ERROR 映射到表单项；返回不能落到某一项上的问题（显示在表单顶部）。
 * `conditions_to_hold[i]`（verification_required）落到第 i 条的“验证方式”，`conditions_to_hold[i].text` 落到条件文字。
 */
export function applyCandidateErrors(form: FormInstance, e: unknown, known: readonly string[]): string[] {
  if (!(e instanceof ApiError) || e.code !== 'VALIDATION_ERROR') return [];
  const fields = (e.details as { fields?: { field: string; issue: string }[] } | null)?.fields ?? [];
  const rest: string[] = [];
  const set: { name: (string | number)[]; errors: string[] }[] = [];
  for (const f of fields) {
    const msg = CANDIDATE_ISSUE[f.issue] ?? f.issue;
    const m = /^conditions_to_hold\[(\d+)\](?:\.(\w+))?$/.exec(f.field);
    if (m) {
      const sub = m[2] ?? 'verify_method';
      set.push({ name: ['conditions_to_hold', Number(m[1]), sub], errors: [msg] });
      continue;
    }
    if (known.includes(f.field)) set.push({ name: [f.field], errors: [msg] });
    else rest.push(`${FIELD_LABEL[f.field] ?? f.field}：${msg}`);
  }
  form.setFields(set);
  return rest;
}
