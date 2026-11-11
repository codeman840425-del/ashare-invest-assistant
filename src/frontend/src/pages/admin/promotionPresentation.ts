import type { GateResultEntry, PromotionReport } from '../../api/promotionTypes';

const GATES = ['G1', 'G2', 'G3', 'G4', 'G5', 'G6'] as const;
export const NULL_REASON = { no_history: '近 120 日历史不足或未体检', no_comparable_set: '没有可比较的其他模板命中集合' };

/** detail 契约未定类型：字符串原样；对象/数组逐项展开成文字，不猜含义、不显示 [object Object]。 */
export function formatGateDetail(detail: unknown): string {
  if (detail === null || detail === undefined || detail === '') return '—';
  if (typeof detail === 'string') return detail;
  if (typeof detail === 'boolean') return detail ? '是' : '否';
  if (typeof detail === 'number') return String(detail);
  if (Array.isArray(detail)) return detail.length ? detail.map(formatGateDetail).join('、') : '无';
  if (typeof detail === 'object') {
    const entries = Object.entries(detail as Record<string, unknown>);
    return entries.length ? entries.map(([k, v]) => `${k}：${formatGateDetail(v)}`).join('；') : '—';
  }
  return String(detail);
}

/** null 不填 0；夹具失败不能被覆盖成 warn；缺报告不造 pass。 */
export function promotionRows(report: PromotionReport): GateResultEntry[] {
  return GATES.map((gate) => {
    const row = report.gate_results.find((g) => g.gate === gate) ?? { gate, result: 'skipped' as const, detail: '报告缺少该门禁结果' };
    const text = formatGateDetail(row.detail);
    if (gate === 'G6' && report.g6_report.max_jaccard === null) {
      const reason = report.g6_report.max_jaccard_null_reason;
      return { ...row, result: row.result === 'pass' ? 'warn' : row.result,
        detail: `${text}；${reason ? `${reason}：${NULL_REASON[reason]}` : '缺少 max_jaccard_null_reason'}（重合度未通过验证）` };
    }
    return { ...row, detail: text };
  });
}
