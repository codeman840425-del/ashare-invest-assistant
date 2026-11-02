/** T-F23 研究候选某一版本的内容（契约 v0.2.9 §7.7A CandidateVersion）：创建时的快照，回看不读最新数据 */
import { Tag } from 'antd';
import { Link } from 'react-router';
import type { CandidateFact, CandidateVersion } from '../../api/candidateTypes';
import { EvidenceChips } from '../../components/EvidenceChips';
import { DataStatusTag, GapNote } from '../../components/common';
import { CANDIDATE_DECISION, NO_COUNTER_EVIDENCE, SOURCE_KIND } from '../../i18n/candidateLabels';
import { CONF_LEVEL, EPISTEMIC, HORIZON } from '../../i18n/labels';
import { fmtTime } from '../../lib/format';

function Facts({ items, evidence, testId }: { items: CandidateFact[]; evidence: CandidateVersion['evidence']; testId: string }) {
  return (
    <>
      {items.map((f, i) => (
        <div key={i} className="tw" data-testid={`${testId}-${i}`}>
          <Tag color={EPISTEMIC[f.epistemic_type].color}>{EPISTEMIC[f.epistemic_type].text}</Tag>
          <span>{f.text}</span>
          {f.expr ? <code>{f.expr}</code> : null}
          <span className="muted small"> · {SOURCE_KIND[f.source_kind] ?? f.source_kind}</span>
          <EvidenceChips ids={f.evidence_ids} evidence={evidence} />
        </div>
      ))}
    </>
  );
}

export function VersionView({ v, testId = 'cand-version' }: { v: CandidateVersion; testId?: string }) {
  const fit = v.fit_assessment;
  return (
    <div className="cand-version" data-testid={testId}>
      <div className="muted small" style={{ marginBottom: 6 }}>
        第 {v.version_no} 版 · {fmtTime(v.created_at)}（北京时间）· 快照 <span className="mono">{v.snapshot_id}</span> · 生成时简称 {v.name}{' '}
        <DataStatusTag status={v.data_status} asOf={v.data_as_of} gaps={v.gaps} />
      </div>
      <GapNote status={v.data_status} gaps={v.gaps} asOf={v.data_as_of} testId={`${testId}-gap`} />
      {v.decision ? (
        <div className="sc-sec" data-testid={`${testId}-decision`}>
          <h4>本版决定</h4>
          <Tag>{CANDIDATE_DECISION[v.decision]}</Tag><span>{v.decision_reason}</span>
        </div>
      ) : null}
      <div className="sc-sec">
        <h4>研究要点（你填写）</h4>
        {v.thesis ? <div className="pre-wrap" data-testid={`${testId}-thesis`}>{v.thesis}</div> : <span className="muted small">未填写</span>}
      </div>
      <div className="sc-sec" data-testid={`${testId}-conditions`}>
        <h4>成立条件（你填写，均为假设）</h4>
        {v.conditions_to_hold.length ? v.conditions_to_hold.map((c, i) => (
          <div key={i} className="tw" data-testid={`${testId}-cond-${i}`}>
            <Tag color={EPISTEMIC[c.epistemic_type].color}>{EPISTEMIC[c.epistemic_type].text}</Tag>
            <span>{c.text}</span>
            <span className="muted small">
              {c.verify_by ? ` · 验证日期 ${c.verify_by}` : ''}{c.verify_method ? ` · 验证方式：${c.verify_method}` : ''}
              {c.confidence ? ` · 把握 ${CONF_LEVEL[c.confidence].text}` : ''}
            </span>
          </div>
        )) : <span className="muted small">未填写</span>}
      </div>
      <div className="sc-sec" data-testid={`${testId}-reasons`}>
        <h4>满足的规则（系统生成）</h4>
        {v.reasons.length ? <Facts items={v.reasons} evidence={v.evidence} testId={`${testId}-reason`} /> : <span className="muted small">无</span>}
      </div>
      <div className="sc-sec" data-testid={`${testId}-counter`}>
        <h4>反证与风险因子（系统生成）</h4>
        {v.counter_evidence.length
          ? <Facts items={v.counter_evidence} evidence={v.evidence} testId={`${testId}-counter`} />
          : <span className="warn small" data-testid={`${testId}-no-counter`}>{NO_COUNTER_EVIDENCE}</span>}
      </div>
      <div className="sc-sec" data-testid={`${testId}-fit`}>
        <h4>与你的适配（只作提示，不影响任何操作）</h4>
        {fit.profile_filled ? null : (
          <div className="muted small" data-testid={`${testId}-no-profile`}>未填写投资画像，未做画像类提示。<Link to="/settings/profile">去填写</Link></div>
        )}
        {fit.holdings_available ? null : (
          <div className="muted small" data-testid={`${testId}-no-holdings`}>未导入持仓，未做持仓类提示。<Link to="/portfolio/import">去导入</Link></div>
        )}
        {fit.hints.map((h, i) => <div key={`h${i}`} className="tw"><Tag>{HORIZON[h.horizon]}</Tag><span>{h.text}</span></div>)}
        {fit.warnings.map((w, i) => (
          <div key={`w${i}`} className="tw" data-testid={`${testId}-warning-${i}`}><span className="warn">{w.text}</span><EvidenceChips ids={w.evidence_ids} evidence={v.evidence} /></div>
        ))}
        {fit.profile_filled && fit.holdings_available && !fit.hints.length && !fit.warnings.length ? <span className="muted small">无提示</span> : null}
      </div>
    </div>
  );
}
