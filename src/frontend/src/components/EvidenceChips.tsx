import { Tooltip } from 'antd';
import type { Evidence } from '../api/types';
import { EPISTEMIC } from '../i18n/labels';
import { fmtTime, providerText } from '../lib/format';


/** 证据引用：悬停显示 key/值/来源/数据时间/抓取时间/认识论类型 */
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
            trigger={['hover', 'focus']}
            title={
              <div className="ev-tip">
                <div><b>{e.key}</b> = {String(e.value)}{e.unit ?? ''}（{EPISTEMIC[e.epistemic_type].text}）</div>
                <div>来源：{providerText(e)}</div>
                <div>数据时间：{fmtTime(e.data_as_of)}　抓取：{fmtTime(e.fetched_at)}</div>
              </div>
            }
          >
            {/* 评审 7afbc06 m3：可用 Tab 聚焦，聚焦时显示证据详情；Enter/空格不冒泡到外层可点击卡片 */}
            <span className="ev-chip" tabIndex={0} aria-label={`证据 ${id}：${e.key} = ${String(e.value)}${e.unit ?? ''}，${EPISTEMIC[e.epistemic_type].text}`}
              onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') ev.stopPropagation(); }}>
              {id} · {fmtTime(e.data_as_of).slice(5, 16)}
            </span>
          </Tooltip>
        );
      })}
    </>
  );
}
