/** T-F34：today 页顶部状态条、账户总览（A1/A2）、日报缺口行与无候选信号空态（契约 today-view.md §2） */
import { Link } from 'react-router';
import type { DailyReport, TodayResponse } from '../../api/types';
import { fmtNum, pctClass, signed } from '../../lib/format';
import { safeInternalRoute } from './todayRoutes';
import { A1_TEXT, R2_TEXT, S4_SIGNALS_UPDATED, STATE_TEXT, hasSuggestion, type GlobalState, type ReportGapView } from './todayView';

const reportLink = (date: string) => <Link to={`/daily-reports/${encodeURIComponent(date)}`} data-testid="today-status-report-link">查看日报 ›</Link>;

/** 顶部状态条：只显示优先级最高的一条；S9 与「尚未判定」不显示 */
export function TodayStatusBar({ state, today }: { state: GlobalState | null; today: TodayResponse }) {
  if (!state || state === 'S9') return null;
  return (
    <div className="today-card today-status-bar" role="status" data-testid="today-status-bar" data-state={state}>
      <span data-testid="today-status-text">{STATE_TEXT[state]}</span>
      {state === 'S1' ? <> <Link to="/portfolio/import" data-testid="today-status-import">导入交割单</Link></> : null}
      {state === 'S3' ? <span className="muted small"> 交易日 <span className="mono">{today.trade_date}</span></span> : null}
      {state === 'S4' && hasSuggestion(today) ? <span data-testid="today-status-signals-updated">{S4_SIGNALS_UPDATED}</span> : null}
      {state === 'S6' || state === 'S7' || state === 'S8' ? <> {reportLink(today.daily_report.date)}</> : null}
    </div>
  );
}

/** A1/A2：日报 account 为 null 时提示不可算；非空时照常显示，pnl_day 为 null 显示「—」不显示 0 */
export function TodayAccount({ report, today }: { report: DailyReport; today: TodayResponse }) {
  const a = report.account;
  const fix = today.data_gaps.items.some((g) => safeInternalRoute(g.route)?.startsWith('/portfolio/import'));
  return (
    <section className="today-card" data-testid="today-account" data-state={a ? 'A2' : 'A1'} aria-label="账户总览">
      <div className="today-card-head"><span className="today-card-title">账户总览</span><span className="muted small">{report.date} 日报</span></div>
      {a ? (
        <span className="small">
          总资产 <span className="num" data-testid="today-account-total">{fmtNum(a.total_assets)}</span>
          {' '}现金 <span className="num" data-testid="today-account-cash">{fmtNum(a.cash)}</span>
          {' '}仓位占比 <span className="num" data-testid="today-account-position">{a.position_pct === null ? '—' : `${fmtNum(a.position_pct)}%`}</span>
          {' '}日盈亏 <span className={`num ${pctClass(a.pnl_day)}`} data-testid="today-account-pnl">{a.pnl_day === null ? '—' : signed(a.pnl_day)}</span>
        </span>
      ) : (
        <span className="small">
          <span data-testid="today-account-unavailable">{A1_TEXT}</span>
          {fix ? <> <Link to="/portfolio/import" data-testid="today-account-fix">去补录 ›</Link></> : null}
        </span>
      )}
    </section>
  );
}

/** 日报带来的缺口：每只证券一行（代码 + 名称 + 文案），最多 10 只，其余「等 N 只」；页面不出现原始 code 与 pipeline 前缀 */
export function ReportGaps({ view }: { view: ReportGapView }) {
  if (!view.securities.length && !view.general.length) return null;
  return (
    <ul className="today-list" data-testid="today-report-gaps">
      {view.general.map((l) => (
        <li key={l.text} data-testid="report-gap-general">
          <span>{l.text}</span>
          {l.route ? <> <Link className="small" to={l.route} data-testid="report-gap-route">去处理 ›</Link></> : null}
        </li>
      ))}
      {view.securities.map((s) => (
        <li key={s.code} data-testid={`report-gap-sec-${s.code}`}>
          <Link to={`/stocks/${encodeURIComponent(s.code)}`}><span className="mono">{s.code}</span>{s.name ? ` ${s.name}` : ''}</Link>
          {s.lines.map((l) => <span key={l.text} className="today-gap-line">{l.text}</span>)}
        </li>
      ))}
      {view.hiddenCount ? <li className="muted small" data-testid="report-gap-more">等 {view.hiddenCount} 只</li> : null}
    </ul>
  );
}

/** R2：所有 focus 行都没有候选信号，且全局状态为 S9 */
export function NoSignals() {
  return <div className="muted small today-empty" data-testid="today-no-signals">{R2_TEXT}</div>;
}
