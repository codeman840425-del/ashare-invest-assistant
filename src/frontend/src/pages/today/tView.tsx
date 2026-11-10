/**
 * T-F36：/today 持仓行的做 T 视图 t_view（契约 docs/contracts/intraday-bars.md §3.2、§3.3、§3.5、§5.2，docs/T-A143=362ad41）。
 * 只展示指标（分时均价、偏离、量比、今日可用底仓、数据时间），不给任何动作或数量建议。
 * 时间一律换算到 Asia/Shanghai（Intl 显式 timeZone），与浏览器/机器时区无关。
 */
import type { TView } from '../../api/types';
import { fmtNum, pctClass } from '../../lib/format';
import { T_VIEW_UNAVAILABLE, availableBase, fmtShanghai, isNum, signedPct, tViewHints } from './tViewModel';

export function TViewCell({ code, t }: { code: string; t: TView | null | undefined }) {
  const testId = `t-view-${code}`;
  if (!t || t.data_status === 'unavailable') {
    return <span className="muted small" data-testid={testId} data-state="unavailable">{T_VIEW_UNAVAILABLE}</span>;
  }
  const avail = availableBase(t);
  const asOf = fmtShanghai(t.as_of);
  const hints = tViewHints(t);
  return (
    <span className="small t-view" data-testid={testId} data-state={t.data_status}>
      <span>分时均价 <span className="num" data-testid={`${testId}-vwap`}>{fmtNum(t.vwap)}</span></span>
      {' · '}
      <span>偏离 <span className={`num ${isNum(t.dev_pct) ? pctClass(t.dev_pct) : 'flat'}`} data-testid={`${testId}-dev`}>{isNum(t.dev_pct) ? signedPct(t.dev_pct) : '—'}</span></span>
      {' · '}
      <span>量比 <span className="num" data-testid={`${testId}-vr`}>{fmtNum(t.volume_ratio)}</span></span>
      {' · '}
      <span data-testid={`${testId}-avail`}>今日可用底仓 {avail === null ? '—' : <span className="num">{fmtNum(avail, 0)}</span>} 股</span>
      {' · '}
      <span className="muted" data-testid={`${testId}-asof`}>数据时间 {asOf ?? '—'}</span>
      {t.data_status === 'partial' ? <span className="muted"> （部分数据）</span> : null}
      {hints.map((h) => <span key={h} className="t-view-hint" data-testid={`${testId}-hint`}> {h}</span>)}
    </span>
  );
}
