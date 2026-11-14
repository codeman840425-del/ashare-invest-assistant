import { trackingDecimal } from '../lib/trackingDecimal';
import type { Stat, Suggestion } from '../api/types';
import type { StrategyTracking } from '../api/strategyTypes';
import { useStrategyTemplates } from '../api/strategyQueries';
import { useStrategyTracking } from '../api/signalQueries';
import { DataStatusTag, ErrorBox, Loading } from './common';
import { GAP_REASON } from '../i18n/labels';

export function TrackingStatValue({ stat, kind = 'percent', testId }: { stat: Stat; kind?: 'percent' | 'fraction' | 'ratio'; testId?: string }) {
  const missing = stat.value === null || stat.n < 5;
  const text = missing ? `—（缺口：${stat.n < 5 ? '样本不足' : '值未提供，见缺口说明'}）` : trackingDecimal(stat.value, kind === 'fraction') + (kind === 'ratio' ? '' : '%');
  return <span data-testid={testId}><b className="mono">{text}</b><span className="small muted"> n={stat.n}{stat.small_sample || stat.n < 30 ? '（样本少）' : ''}</span></span>;
}
const count = (value: number) => typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : '—（缺口：计数未提供）';
export function StrategyTrackingStats({ data }: { data: StrategyTracking }) {
  return <div data-testid="strategy-tracking-stats">
    <p><strong>模拟非实际收益</strong> · 模拟，不代表实际收益</p>
    <DataStatusTag status={data.data_status} />
    <p className="small muted">策略版本聚合（{data.scope === 'site' ? '全站匿名' : '本人'}），不是实例级统计；n按各项有效样本，待到期/不可成交/排除不冒充有效n。</p>
    <div className="stat-wrap"><table className="stat-table"><thead><tr><th>持有期</th><th>胜率</th><th>平均收益</th><th>平均超额</th><th>盈亏比</th><th>最长连亏</th><th>待到期</th><th>不可成交</th><th>排除</th></tr></thead>
      <tbody>{data.by_horizon.map((row) => <tr key={row.horizon_days} data-testid={`track-${row.horizon_days}`}>
        <td>{row.horizon_days} 日</td><td><TrackingStatValue stat={row.win_rate} kind="fraction" /></td><td><TrackingStatValue stat={row.avg_return_pct} /></td><td><TrackingStatValue stat={row.avg_excess_pct} /></td><td><TrackingStatValue stat={row.profit_loss_ratio} kind="ratio" /></td>
        <td>{count(row.max_loss_streak)}</td><td>{count(row.pending_count)}</td><td>{count(row.untradable_count)}</td><td>{count(row.excluded_count)}</td>
      </tr>)}</tbody></table></div>
    {!data.by_horizon.length ? <p>缺口：暂无策略版本聚合结果，不填0。</p> : null}
    {data.gaps.map((gap, i) => <p key={`${gap.key}-${i}`}>缺口 · <code>{gap.key}</code> · {GAP_REASON[gap.reason]}：{gap.message}</p>)}
  </div>;
}
function VersionTracking({ strategyId, versionId, name }: { strategyId: string; versionId: string; name: string }) {
  const query = useStrategyTracking(strategyId, versionId);
  return <section className="stc-sec" data-testid={`version-tracking-${versionId}`}><h4>{name} · 本策略版本模拟聚合</h4>{query.isPending ? <Loading /> : query.isError ? <ErrorBox error={query.error} /> : <StrategyTrackingStats data={query.data} />}</section>;
}
export function SuggestionStrategyTracking({ strategies }: { strategies: Suggestion['strategies'] }) {
  const templates = useStrategyTemplates();
  const unique = [...new Map(strategies.map((item) => [item.strategy_version_id, item])).values()];
  if (!unique.length) return <p>缺口：本卡没有关联策略版本，无法显示版本聚合盈亏比。</p>;
  if (templates.isPending) return <Loading />;
  if (templates.isError) return <ErrorBox error={templates.error} />;
  return <div>{unique.map((item) => {
    const template = templates.data.items.find((entry) => entry.key === item.strategy_key);
    return template ? <VersionTracking key={item.strategy_version_id} strategyId={template.id} versionId={item.strategy_version_id} name={item.strategy_name} /> : <p key={item.strategy_version_id}>缺口：无法映射{item.strategy_name}的策略ID，不猜测聚合。</p>;
  })}</div>;
}
