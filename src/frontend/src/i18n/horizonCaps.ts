import type { HorizonCap } from '../api/types';

/**
 * 周期封顶说明（契约 v0.2.3 #23、v0.2.5 #2、v0.2.6 T006e）：按 HorizonCap.kind / rule_id 显示，不查原因码文案（rule_id 不是 reason_code）。
 * v0.2.6 起 kind 只有两种：
 * - gate：证券级闸门 HG1–HG6（判 0 分的 HG1–HG3 记 cap: 0）；
 * - data_missing：必需特征缺失（rule_id = null，inputs_missing 为缺失的 f.* 键），或 LG0 / LG0B 的 else_cap（rule_id 为规则 ID）。
 * 画像类规则（SH0 / SH0B / SH0C / IT0B / IT0C）只进 hints[]；IT0（无底仓）判 0 分是分数，不进 caps。
 * 文案取自 plan 6.1 horizon_classifier.yaml 的 reason。
 */
export const HORIZON_CAP_RULE_TEXT: Record<string, string> = {
  HG1: '分类器只覆盖 A 股股票（ETF、可转债等不分类）',
  HG2: '首版不含北交所',
  HG3: '退市整理期：不分类',
  HG4: '风险警示股票（ST/*ST）：可交易性闸门阻断买入方向，不列为适合',
  HG5: '上市不足 20 个交易日：历史太短',
  HG6: '上市不足 60 个交易日：60 日趋势与动量无法计算',
  LG0: '已披露财报不足 12 期（或缺失）：基本面历史不完整',
  LG0B: 'ROE(TTM) 缺失：无法判断质量',
};

export const CAP_KIND_TEXT: Record<HorizonCap['kind'], string> = { gate: '证券闸门', data_missing: '数据不足' };

export function capExplanation(c: HorizonCap): string {
  if (c.rule_id && HORIZON_CAP_RULE_TEXT[c.rule_id]) return HORIZON_CAP_RULE_TEXT[c.rule_id];
  if (c.kind === 'data_missing') return `缺少输入 ${c.inputs_missing.join('、') || '—'}`;
  return `闸门 ${c.rule_id ?? '—'} 命中`;
}
