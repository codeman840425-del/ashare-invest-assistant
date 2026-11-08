import type { DailyReportStock, Evidence } from '../../api/types';
import { DataStatusTag } from '../../components/common';
import { DIMENSION, GAP_REASON } from '../../i18n/labels';
import { fmtTime } from '../../lib/format';
const STATUS = { declared: '已声明', verified_doc: '文档核实', verified_live: '实测核实', gap: '有缺口', deprecated: '已废弃' };
export function DailyDimensions({ stock, evidence }: { stock: DailyReportStock; evidence: Evidence[] }) {
  const dimensions = stock.dimensions;
  const anchor = (id: string) => `daily-${stock.security_code}-${id}`;
  const ids = [...new Set((dimensions ?? []).flatMap((d) => [...d.facts.flatMap((f) => f.evidence_ids), ...d.feature_refs.flatMap((f) => f.evidence_ids)]))];
  return <div onClick={(e) => e.stopPropagation()}>
    <details className="stc-sec" data-testid={`dimensions-${stock.security_code}`}>
      <summary>六维事实与缺口（不是策略结论）</summary>
      {dimensions == null ? <p className="muted" data-testid="dimensions-legacy">{stock.change_from_previous === 'removed' ? '已移出行没有本期六维分析' : '旧版日报未提供六维分析'}；不补造事实或快照。</p> : <>
        <p className="muted small">分析快照：{stock.analysis_snapshot_id ?? '—（未提供）'}；字段等级与取数完整性独立，不代表通过策略门禁。</p>
        {dimensions.length !== 6 ? <p role="alert">服务端未提供完整六维，缺少的事实不补造。</p> : null}
        {dimensions.map((d) => <section key={d.dimension} className="stc-sec" data-testid={`dimension-${stock.security_code}-${d.dimension}`}>
          <b>{DIMENSION[d.dimension]}</b> <DataStatusTag status={d.data_status} /><span className="small muted"> 数据时点：{d.data_as_of === null ? '—（无来源）' : fmtTime(d.data_as_of)}</span>
          {d.facts.length ? d.facts.map((fact, i) => <p key={i}>{fact.text} {fact.evidence_ids.map((id) => <a key={id} href={`#${anchor(id)}`} aria-label={`查看六维证据 ${id}`}>[{id}]</a>)}</p>) : <p className="muted">暂无已知事实；缺数据不填0，不判定为中性。</p>}
          {d.feature_refs.map((f) => <div key={f.feature_key} className="small"><code>{f.feature_key}</code> · {f.status === null ? '未登记' : STATUS[f.status]} {f.evidence_ids.map((id) => <a key={id} href={`#${anchor(id)}`}>证据 {id}</a>)}</div>)}
          {d.gaps.map((g, i) => <p key={`${g.key}-${i}`} className="small">缺口 · {GAP_REASON[g.reason]}：{g.message}</p>)}
        </section>)}
        <h4>六维证据（本份日报）</h4>
        {ids.map((id) => { const item = evidence.find((e) => e.id === id); return <div key={id} id={anchor(id)} tabIndex={-1} data-testid={`dimension-evidence-${id}`} className="stc-sec small">
          {item ? <>{item.id} · {item.key} = <b>{item.value === null ? '—（缺数据）' : String(item.value)}</b>{item.unit ? ` ${item.unit}` : ''} · 来源 {item.provider} · 数据时间 {fmtTime(item.data_as_of)} · 取得时间 {fmtTime(item.fetched_at)}</> : <span role="alert">证据 {id} 缺失；不补造来源。</span>}
        </div>; })}
      </>}
    </details>
  </div>;
}
