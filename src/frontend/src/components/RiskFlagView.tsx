import { Tag } from 'antd';
import type { RiskFlag } from '../api/types';
import { ACTION_SHORT, RISK_CONTROL, RISK_LEVEL } from '../i18n/labels';
import { EvidenceChips } from './EvidenceChips';
import type { Evidence } from '../api/types';

/** 只展示后端门控与限量，不在浏览器重算 RC3/RC4。 */
export function RiskFlagView({ flag: f, evidence }: { flag: RiskFlag; evidence: Evidence[] }) {
  return <div className={`risk-row lv-${f.level}`} data-testid="risk-flag">
    <Tag color={RISK_LEVEL[f.level].color}>{RISK_LEVEL[f.level].text}</Tag><b>{RISK_CONTROL[f.control]}</b>　{f.message}
    <div className="muted small">{f.gated_actions.length ? `已门控（gated）：${f.gated_actions.map((a) => ACTION_SHORT[a]).join('、')}` : '未门控（仅提示或限量）'}
      {f.quantity_cap !== null ? ` · 数量上限 ${f.quantity_cap}` : ''}</div>
    <EvidenceChips ids={f.evidence_ids} evidence={evidence} />
  </div>;
}
