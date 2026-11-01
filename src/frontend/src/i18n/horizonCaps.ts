import type { HorizonCap } from '../api/types';

/**
 * 周期封顶说明（契约 v0.2.3 #23）：按 HorizonCap.rule_id 显示，不查原因码文案（SH0C / IT0C 不是 reason_code）。
 * 文案描述规则本身，规则 ID 以等宽字体附在后面，便于和 horizon_classifier.yaml 对照。
 */
export const HORIZON_CAP_RULE_TEXT: Record<string, string> = {
  SH0C: '投资经验为新手或画像未填写，短线分数封顶；可在卡片上确认后覆盖',
  IT0C: '投资经验为新手或画像未填写，日内做T 分数封顶；可在卡片上确认后覆盖',
};

export function capExplanation(c: HorizonCap): string {
  if (c.kind === 'data_missing') return `缺少输入 ${c.inputs_missing.join('、') || '—'}`;
  if (c.rule_id && HORIZON_CAP_RULE_TEXT[c.rule_id]) return HORIZON_CAP_RULE_TEXT[c.rule_id];
  return `规则 ${c.rule_id ?? '—'} 不满足`;
}
