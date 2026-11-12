import type { SuggestionTracking, TrackingResult } from '../api/phase2Types';
import { EvidenceChips } from './EvidenceChips';
import { GAP_REASON, ACTION_FULL } from '../i18n/labels';
import { trackingDecimal } from '../lib/trackingDecimal';
import { fmtTime } from '../lib/format';
const STATE = { pending: '尚未到期', complete: '已完成', untradable: '不可成交', excluded: '已排除', unavailable: '到期但数据不足' };
const value = (x: string | null, unit = '') => unit === '%' ? trackingDecimal(x) + (x === null ? '' : '%') : x === null ? '—（缺数据）' : x;
export function TrackingResults({ data }: { data: SuggestionTracking }) {
  const results = data.results ?? [];
  const count = (state: TrackingResult['state']) => results.filter((r) => r.state === state).length;
  return <div data-testid="tracking-results">
    <p><strong>模拟非实际收益</strong> · <b>模拟，不代表实际收益</b></p>
    <p className="small" data-testid="tracking-counts">本卡逐条观测（不是策略聚合有效样本 n）：待到期 {count('pending')} · 不可成交 {count('untradable')} · 排除 {count('excluded')} · 缺数据 {count('unavailable')}</p>
    {!results.length ? <p className="muted">暂无逐条模拟结果；不补算、不用旧聚合数字代替。</p> : results.map((r) => <article className="stc-sec" key={`${r.strategy_version_id}-${r.horizon_days}`} data-testid={`tracking-${r.state}`}>
      <h4>{r.horizon_days} 日 · {STATE[r.state]} · {ACTION_FULL[r.action]}</h4>
      <p className="small">策略版本 {r.strategy_version_id} · 实例 {r.instance_id ?? '—'} · 复权口径 {r.price_basis} · 成本{r.cost_applied ? '已计入' : '未计入'}</p>
      <div>模拟入场：{value(r.entry_price)} / {r.entry_at === null ? '—' : fmtTime(r.entry_at)}；模拟离场：{value(r.exit_price)} / {r.exit_at === null ? '—' : fmtTime(r.exit_at)}</div>
      <div>标的区间收益：{value(r.return_pct, '%')} · 基准 {r.benchmark_code}：{value(r.benchmark_return_pct, '%')} · 超额：{value(r.excess_pct, '%')}</div>
      <div>基准入场 / 离场：{value(r.benchmark_entry_price)} / {value(r.benchmark_exit_price)}；最大回撤 {value(r.max_drawdown_pct, '%')} · 最大上行 {value(r.max_runup_pct, '%')}</div>
      <div>方向是否正确：{r.direction_correct === null ? '—（未判定）' : r.direction_correct ? '是' : '否'} · 失效触发：{r.invalidation_triggered_at === null ? '—' : fmtTime(r.invalidation_triggered_at)}</div>
      {r.exclusion_reason ? <p>排除原因：{r.exclusion_reason}</p> : null}
      <EvidenceChips ids={r.evidence_ids} evidence={r.evidence} />
      {r.gaps.map((g, i) => <p className="small" key={`${g.key}-${i}`}>缺口 · {GAP_REASON[g.reason]}：{g.message}</p>)}
    </article>)}
    {(data.gaps ?? []).map((g, i) => <p className="small" key={`${g.key}-${i}`}>缺口 · {GAP_REASON[g.reason]}：{g.message}</p>)}
  </div>;
}
