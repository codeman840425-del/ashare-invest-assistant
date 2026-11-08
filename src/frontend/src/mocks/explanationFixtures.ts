import type { ExplanationFallbackReason } from '../api/enums';
import { DIMENSION } from '../i18n/labels';
/** P2N-05i：DeepSeek纯合成草稿经逐句比对、纠正结构后采用；全部为示例数据。 */
import type { DailyReport, Evidence, Explanation, Suggestion } from '../api/types';
type ExampleMode = 'success' | 'disabled' | 'failure' | 'legacy_template' | 'legacy_llm';
const drafts: { name: string; mode: ExampleMode; evidenceId: string; text: string }[] = [
  {
    "name": "success_EXAMPLE_FACT",
    "mode": "success",
    "evidenceId": "EXAMPLE_FACT",
    "text": "示例数据：已登记的事实可查看原记录。"
  },
  {
    "name": "success_EXAMPLE_GAP",
    "mode": "success",
    "evidenceId": "EXAMPLE_GAP",
    "text": "示例数据：缺少信息时保留数据缺口。"
  },
  {
    "name": "success_EXAMPLE_DIVERGENCE",
    "mode": "success",
    "evidenceId": "EXAMPLE_DIVERGENCE",
    "text": "示例数据：不同规则方向并列保留。"
  },
  {
    "name": "success_EXAMPLE_PLAN",
    "mode": "success",
    "evidenceId": "EXAMPLE_PLAN",
    "text": "示例数据：候选信号与计划条件分别展示。"
  },
  {
    "name": "disabled_EXAMPLE_FACT",
    "mode": "disabled",
    "evidenceId": "EXAMPLE_FACT",
    "text": "示例数据：已登记的事实可查看原记录。"
  },
  {
    "name": "disabled_EXAMPLE_GAP",
    "mode": "disabled",
    "evidenceId": "EXAMPLE_GAP",
    "text": "示例数据：缺少信息时保留数据缺口。"
  },
  {
    "name": "disabled_EXAMPLE_DIVERGENCE",
    "mode": "disabled",
    "evidenceId": "EXAMPLE_DIVERGENCE",
    "text": "示例数据：不同规则方向并列保留。"
  },
  {
    "name": "disabled_EXAMPLE_PLAN",
    "mode": "disabled",
    "evidenceId": "EXAMPLE_PLAN",
    "text": "示例数据：候选信号与计划条件分别展示。"
  },
  {
    "name": "failure_EXAMPLE_FACT",
    "mode": "failure",
    "evidenceId": "EXAMPLE_FACT",
    "text": "示例数据：已登记的事实可查看原记录。"
  },
  {
    "name": "failure_EXAMPLE_GAP",
    "mode": "failure",
    "evidenceId": "EXAMPLE_GAP",
    "text": "示例数据：缺少信息时保留数据缺口。"
  },
  {
    "name": "failure_EXAMPLE_DIVERGENCE",
    "mode": "failure",
    "evidenceId": "EXAMPLE_DIVERGENCE",
    "text": "示例数据：不同规则方向并列保留。"
  },
  {
    "name": "failure_EXAMPLE_PLAN",
    "mode": "failure",
    "evidenceId": "EXAMPLE_PLAN",
    "text": "示例数据：候选信号与计划条件分别展示。"
  },
  {
    "name": "legacy_template_EXAMPLE_FACT",
    "mode": "legacy_template",
    "evidenceId": "EXAMPLE_FACT",
    "text": "示例数据：已登记的事实可查看原记录。"
  },
  {
    "name": "legacy_template_EXAMPLE_GAP",
    "mode": "legacy_template",
    "evidenceId": "EXAMPLE_GAP",
    "text": "示例数据：缺少信息时保留数据缺口。"
  },
  {
    "name": "legacy_template_EXAMPLE_DIVERGENCE",
    "mode": "legacy_template",
    "evidenceId": "EXAMPLE_DIVERGENCE",
    "text": "示例数据：不同规则方向并列保留。"
  },
  {
    "name": "legacy_template_EXAMPLE_PLAN",
    "mode": "legacy_template",
    "evidenceId": "EXAMPLE_PLAN",
    "text": "示例数据：候选信号与计划条件分别展示。"
  },
  {
    "name": "legacy_llm_EXAMPLE_FACT",
    "mode": "legacy_llm",
    "evidenceId": "EXAMPLE_FACT",
    "text": "示例数据：已登记的事实可查看原记录。"
  },
  {
    "name": "legacy_llm_EXAMPLE_GAP",
    "mode": "legacy_llm",
    "evidenceId": "EXAMPLE_GAP",
    "text": "示例数据：缺少信息时保留数据缺口。"
  },
  {
    "name": "legacy_llm_EXAMPLE_DIVERGENCE",
    "mode": "legacy_llm",
    "evidenceId": "EXAMPLE_DIVERGENCE",
    "text": "示例数据：不同规则方向并列保留。"
  },
  {
    "name": "legacy_llm_EXAMPLE_PLAN",
    "mode": "legacy_llm",
    "evidenceId": "EXAMPLE_PLAN",
    "text": "示例数据：候选信号与计划条件分别展示。"
  }
];

function syntheticCallId(index: number): string {
  return ['00000000', '0000', '4000', '8000', String(1000 + index).padStart(12, '0')].join('-');
}
export const EXAMPLE_EXPLANATIONS = drafts.map((row, index) => {
  const explanation: Explanation = { source: row.mode === 'success' || row.mode === 'legacy_llm' ? 'llm' : 'template', text: row.text, llm_call_id: null };
  if (!row.mode.startsWith('legacy')) {
    explanation.paragraphs = [{ text: row.text, expr: null, evidence_ids: [row.evidenceId] }];
    explanation.prompt_version = row.mode === 'disabled' ? null : 'TEST-PROMPT-V1';
    explanation.validation_status = row.mode === 'success' ? 'passed' : 'fallback';
    explanation.fallback_reason = row.mode === 'success' ? null : row.mode === 'disabled' ? 'not_enabled' : 'provider_error';
    explanation.llm_call_id = row.mode === 'disabled' ? null : syntheticCallId(index + 1);
  }
  return { name: row.name, mode: row.mode, explanation };
});
export function exampleExplanation(mode: ExampleMode, id = 'EXAMPLE_FACT'): Explanation {
  const row = EXAMPLE_EXPLANATIONS.find((x) => x.name === `${mode}_${id}`);
  if (!row) throw new Error('Unknown synthetic explanation');
  return structuredClone(row.explanation);
}
export function exampleExplanationEvidence(dataAsOf = '2026-10-30T15:00:00+08:00'): Evidence[] {
  return drafts.filter((x) => x.mode === 'success').map((row) => ({
    id: row.evidenceId, key: `TEST.${row.evidenceId}`, value: row.evidenceId === 'EXAMPLE_GAP' ? null : row.text,
    unit: null, provider: 'system', endpoint: null, data_as_of: dataAsOf, fetched_at: dataAsOf, epistemic_type: 'fact',
  }));
}
/** 五种回退样例；不启用/预算拒绝没有调用记录，其余使用运行时生成的虚构id。 */
export function exampleFallbackExplanation(reason: ExplanationFallbackReason): Explanation {
  return { ...exampleExplanation('failure'), fallback_reason: reason, llm_call_id: reason === 'not_enabled' || reason === 'budget_exceeded' ? null : syntheticCallId(100) };
}
function boundExplanation(text: string, ids: string[], index: number, fallback = false): Explanation {
  return { ...(fallback ? exampleFallbackExplanation('validation_failed') : exampleExplanation('success')), text,
    paragraphs: [{ text, expr: null, evidence_ids: ids }], llm_call_id: syntheticCallId(index) };
}
/** 仅MSW生成冻结合成快照；不改任何action/score/confidence或生产接口。 */
export function withExampleSuggestionExplanation(sg: Suggestion, index: number): Suggestion {
  if (!sg.data_as_of) return sg;
  const modes: ExampleMode[] = ['success', 'disabled', 'failure', 'legacy_template', 'legacy_llm'];
  const divergence = sg.divergence.map((d, position) => {
    if (index % 3 === 2) return { ...d }; // 示例旧档，保持缺键。
    if (index % 3 === 1 || position >= 2) return { ...d, explanation: null };
    // MSW端已知规则维度关系；不是浏览器从顶层说明推断归属。
    const related = new Set(sg.strategies.flatMap((strategy) => strategy.dimension_views.filter((view) => d.dimensions.includes(view.dimension)).flatMap((view) => view.rules.flatMap((rule) => rule.evidence_ids))));
    const id = sg.evidence.find((e) => related.has(e.id))?.id;
    const text = `示例数据：${d.dimensions.map((dimension) => DIMENSION[dimension]).join('、')}分歧单独保留。`;
    return { ...d, explanation: id ? boundExplanation(text, [id], 200 + position, position === 1) : null };
  });
  return { ...sg, divergence, explanation: exampleExplanation(modes[index % modes.length], sg.divergence.length ? 'EXAMPLE_DIVERGENCE' : 'EXAMPLE_FACT'), evidence: [...sg.evidence, ...exampleExplanationEvidence(sg.data_as_of)] };
}
export function withExampleReportExplanation(report: DailyReport): DailyReport {
  if (!report.data_as_of) return report; // 旧档不补新元数据/本项解释。
  const stockEvidence: Evidence[] = [];
  const stocks = report.stocks.map((stock, index) => {
    if (index >= 3) return { ...stock }; // 示例旧档缺键。
    if (index === 2) return { ...stock, explanation: null };
    const id = `${stock.security_code}:EXPLANATION`;
    const text = `示例数据：${stock.name}的已登记资料单独保留。`;
    stockEvidence.push({ id, key: 'TEST.stock.explanation', value: text, unit: null, provider: 'system', endpoint: null,
      data_as_of: report.data_as_of!, fetched_at: report.data_as_of!, epistemic_type: 'fact' });
    return { ...stock, explanation: boundExplanation(text, [id], 300 + index, index === 1) };
  });
  return { ...report, stocks, explanation: exampleFallbackExplanation('provider_error'), evidence: [...report.evidence, ...exampleExplanationEvidence(report.data_as_of), ...stockEvidence] };
}
