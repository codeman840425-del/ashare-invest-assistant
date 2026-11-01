import type { HorizonCap } from '../api/types';

/**
 * 周期封顶说明（契约 v0.2.3 #23、v0.2.5 #2）：按 HorizonCap.rule_id 显示，不查原因码文案（rule_id 不是 reason_code）。
 * v0.2.5 起画像类规则（SH0 / SH0B / SH0C / IT0B / IT0C）是 mode: hint，只出现在 hints[]（文案由服务端给出），不再封顶；
 * 这里只剩非画像的 requires 规则。文案取自 plan 6.1 horizon_classifier.yaml 的 reason。
 */
export const HORIZON_CAP_RULE_TEXT: Record<string, string> = {
  IT0: '做T 需要已有底仓（T+1：当日买入不能当日卖出）',
  LG0: '已披露财报不足 12 期（或缺失）：基本面历史不完整',
  LG0B: 'ROE(TTM) 缺失：无法判断质量',
};

export function capExplanation(c: HorizonCap): string {
  if (c.kind === 'data_missing') return `缺少输入 ${c.inputs_missing.join('、') || '—'}`;
  if (c.rule_id && HORIZON_CAP_RULE_TEXT[c.rule_id]) return HORIZON_CAP_RULE_TEXT[c.rule_id];
  return `规则 ${c.rule_id ?? '—'} 不满足`;
}
