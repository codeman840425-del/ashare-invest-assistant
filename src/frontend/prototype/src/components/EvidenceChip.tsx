import { Tooltip } from 'antd';
import type { Evidence } from '../types/contract';
import { EPISTEMIC } from '../labels';
import { fmtTime } from './common';

const PROVIDER: Record<Evidence['provider'], string> = { mairui: '麦蕊', local: '本地计算', user_import: '用户导入' };
export const providerText = (e: Evidence) => `${PROVIDER[e.provider]}${e.endpoint ? ' ' + e.endpoint : ''}`;

export function EvidenceChips({ ids, evidence }: { ids: string[]; evidence: Evidence[] }) {
  if (!ids.length) return <span className="ev-chip none">无证据引用</span>;
  return (
    <>
      {ids.map((id) => {
        const e = evidence.find((x) => x.id === id);
        if (!e) return <span key={id} className="ev-chip missing">{id}?</span>;
        return (
          <Tooltip
            key={id}
            title={
              <div className="ev-tip">
                <div><b>{e.key}</b> = {String(e.value)}{e.unit ?? ''}（{EPISTEMIC[e.epistemic_type].text}）</div>
                <div>来源：{providerText(e)}</div>
                <div>数据时间：{fmtTime(e.data_as_of)}　抓取：{fmtTime(e.fetched_at)}</div>
              </div>
            }
          >
            <span className="ev-chip">{id} · {fmtTime(e.data_as_of).slice(5, 16)}</span>
          </Tooltip>
        );
      })}
    </>
  );
}
