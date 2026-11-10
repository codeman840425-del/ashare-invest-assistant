/**
 * T-F36/T-F36b：/today 持仓行的做 T 视图 t_view（契约 intraday-bars.md §3.7、today-view.md §10，docs/T-A145=2ddefa5）。
 * 只展示指标（分时均价、偏离、量比、今日可用底仓、数据时间），不给任何动作或数量建议。
 * 状态显示复用 DataStatusTag 与 GapNote（已过期、拉取中、部分缺失、不适用）。
 */
import type { TView } from '../../api/types';
import { DataStatusTag, GapNote } from '../../components/common';
import {
  T_VIEW_CHECKING, T_VIEW_UNAVAILABLE, availableBase, fmtDevPct, fmtShanghai, fmtShanghaiHm, isDec, notApplicableText, tViewHints, withThousands,
} from './tViewModel';

const devClass = (v: string) => (v.trim().startsWith('-') ? 'down' : /^[+]?0*(\.0*)?$/.test(v.trim()) ? 'flat' : 'up');

export function TViewCell({ code, t, nonTradingDay = false }: { code: string; t: TView | null | undefined; nonTradingDay?: boolean }) {
  const testId = `t-view-${code}`;
  if (!t) {
    // 契约：持仓行一律带 t_view；缺失（后端未升级）时保守按不可用
    return <span className="muted small" data-testid={testId} data-state="unavailable">{T_VIEW_UNAVAILABLE}</span>;
  }
  const gaps = t.gaps ?? [];
  const na = notApplicableText(gaps, nonTradingDay);
  if (na) {
    return (
      <span className="muted small" data-testid={testId} data-state="not_applicable">
        <DataStatusTag status={t.data_status} gaps={gaps.filter((g) => g.reason === 'not_applicable')} /> <span data-testid={`${testId}-na`}>{na}</span>
      </span>
    );
  }
  if (t.data_status === 'unavailable') {
    return (
      <span className="muted small" data-testid={testId} data-state="unavailable">
        {T_VIEW_UNAVAILABLE}
        <GapNote status={t.data_status} gaps={gaps} testId={`${testId}-gaps`} />
      </span>
    );
  }
  const pending = t.data_status === 'pending';
  const show = (v: string | null) => (!pending && isDec(v) ? withThousands(v) : '—');
  const avail = pending ? null : availableBase(t);
  const asOf = fmtShanghai(t.as_of);
  const hints = tViewHints(t);
  return (
    <span className="small t-view" data-testid={testId} data-state={t.data_status}>
      {t.data_status !== 'fresh' ? (
        <span data-testid={`${testId}-status`}>
          <DataStatusTag status={t.data_status} gaps={gaps} />
          {t.data_status === 'stale' ? `（截至 ${fmtShanghaiHm(t.as_of) ?? '—'}）` : null}{' '}
        </span>
      ) : null}
      <span>分时均价 <span className="num" data-testid={`${testId}-vwap`}>{show(t.vwap)}</span></span>
      {' · '}
      <span>偏离 <span className={`num ${!pending && isDec(t.dev_pct) ? devClass(t.dev_pct) : 'flat'}`} data-testid={`${testId}-dev`}>{!pending && isDec(t.dev_pct) ? fmtDevPct(t.dev_pct) : '—'}</span></span>
      {' · '}
      <span>量比 <span className="num" data-testid={`${testId}-vr`}>{show(t.volume_ratio)}</span></span>
      {' · '}
      <span data-testid={`${testId}-avail`}>
        今日可用底仓 {avail === null || avail === 'violation' ? '—' : <span className="num">{withThousands(avail)}</span>} 股
        {avail === 'violation' ? <span className="muted" data-testid={`${testId}-checking`}>（{T_VIEW_CHECKING}）</span> : null}
      </span>
      {' · '}
      <span className="muted" data-testid={`${testId}-asof`}>数据时间 {asOf ?? '—'}</span>
      {hints.map((h) => <span key={h} className="t-view-hint" data-testid={`${testId}-hint`}> {h}</span>)}
      {gaps.length && t.data_status !== 'stale' ? <GapNote status={t.data_status} gaps={gaps} testId={`${testId}-gaps`} /> : null}
    </span>
  );
}
