import { useId, useRef } from 'react';
import type { Evidence, Explanation } from '../api/types';
import { EPISTEMIC } from '../i18n/labels';
import { fmtTime, providerText } from '../lib/format';

/** 只读说明区；不接受/计算/写回任何规则动作、分值或置信度。 */
export function ExplanationView({ explanation, evidence, testId, title = '中文解释', callTestId }: {
  explanation: Explanation; evidence: Evidence[]; testId: string; title?: string; callTestId?: string;
}) {
  const prefix = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const details = useRef<HTMLDetailsElement>(null);
  const paragraphs = explanation.paragraphs?.length ? explanation.paragraphs : [{ text: explanation.text, expr: null, evidence_ids: [] }];
  const ids = [...new Set(paragraphs.flatMap((p) => p.evidence_ids))];
  const records = ids.flatMap((id) => { const item = evidence.find((e) => e.id === id); return item ? [item] : []; });
  const anchor = (index: number) => `${prefix}-explanation-evidence-${index}`;
  const template = explanation.source === 'template';
  const inconsistent = (template && explanation.validation_status === 'passed') || (!template && explanation.validation_status === 'fallback');
  const status = inconsistent ? '来源与验证状态不一致，未确认有效' : explanation.validation_status === 'passed' ? '验证通过' : explanation.validation_status === 'fallback' ? '模板兜底' : '验证状态未提供（旧版存档）';
  return <section className="stc-sec small" data-testid={testId} aria-label={title} onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
    <h4>{title} · {inconsistent ? '解释来源待确认' : template ? '模板解释（非 AI 生成）' : 'AI 中文解释'}</h4>
    <div className="muted">提示词版本：{explanation.prompt_version ?? '未提供'} · 验证状态：{status}</div>
    {template && explanation.validation_status === 'fallback' ? <p className="muted">模型未启用或失败时使用模板兜底；接口未提供本次具体回退原因。</p> : null}
    <p className="muted">仅解释已有证据；候选信号/计划条件仍按规则区展示，不改动作、满足度或置信度。</p>
    {paragraphs.map((p, index) => <div key={index}>
      <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{p.text || '解释正文未提供'}</p>
      {p.evidence_ids.length ? [...new Set(p.evidence_ids)].map((id) => {
        const recordIndex = records.findIndex((e) => e.id === id);
        return recordIndex < 0 ? <span className="ev-chip missing" key={id}>引用缺失：{id}（本对象无此证据）</span> : <a className="ev-chip" key={id} href={`#${anchor(recordIndex)}`} aria-label={`查看解释证据 ${id}`} onClick={() => {
          if (details.current) details.current.open = true;
          document.getElementById(anchor(recordIndex))?.focus({ preventScroll: true });
        }}>证据 {id}</a>;
      }) : <span className="muted">未附段落引用；不补造出处。</span>}
    </div>)}
    {explanation.llm_call_id ? <div className="muted" data-testid={callTestId}>LLM 调用记录 <span className="mono">{explanation.llm_call_id}</span>（只读，未约定调用记录跳转路由）</div> : null}
    {records.length ? <details ref={details}>
      <summary>解释引用证据（{records.length} 项；仅本对象）</summary>
      {records.map((e, index) => <div id={anchor(index)} key={e.id} tabIndex={-1} className="stc-sec" data-testid={`${testId}-evidence-${e.id}`}>
        <b>{e.id} · {e.key}</b> = {e.value === null ? '—（缺数据）' : String(e.value)}{e.unit ?? ''}（{EPISTEMIC[e.epistemic_type].text}）
        <div>来源：{providerText(e)} · 数据时间：{fmtTime(e.data_as_of)} · 抓取时间：{fmtTime(e.fetched_at)}</div>
      </div>)}
    </details> : null}
  </section>;
}
