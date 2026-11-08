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

export const EXAMPLE_EXPLANATIONS = drafts.map((row) => {
  const explanation: Explanation = { source: row.mode === 'success' || row.mode === 'legacy_llm' ? 'llm' : 'template', text: row.text, llm_call_id: null };
  if (!row.mode.startsWith('legacy')) {
    explanation.paragraphs = [{ text: row.text, expr: null, evidence_ids: [row.evidenceId] }];
    explanation.prompt_version = row.mode === 'disabled' ? null : 'TEST-PROMPT-V1';
    explanation.validation_status = row.mode === 'success' ? 'passed' : 'fallback';
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
/** 仅MSW合成快照；不改任何action/score/confidence或真实接口投影。 */
export function withExampleSuggestionExplanation(sg: Suggestion, index: number): Suggestion {
  if (!sg.data_as_of) return sg;
  const modes: ExampleMode[] = ['success', 'disabled', 'failure', 'legacy_template', 'legacy_llm'];
  return { ...sg, explanation: exampleExplanation(modes[index % modes.length], sg.divergence.length ? 'EXAMPLE_DIVERGENCE' : 'EXAMPLE_FACT'), evidence: [...sg.evidence, ...exampleExplanationEvidence(sg.data_as_of)] };
}
export function withExampleReportExplanation(report: DailyReport): DailyReport {
  // 旧版保留text-only及缺元数据，不把历史记录升级为新记录。
  if (!report.data_as_of) return report;
  return { ...report, explanation: exampleExplanation('failure'), evidence: [...report.evidence, ...exampleExplanationEvidence(report.data_as_of)] };
}
