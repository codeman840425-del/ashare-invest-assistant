import { additionalSignalInstances } from '../../lib/signalEvents';
import { useMemo } from 'react';
import type { Time } from 'lightweight-charts';
import { useBars, useCandidateSignals, useSecuritySignals } from '../../api/queries';
import { useBarsWindow } from '../../api/marketQueries';
import { chartStops, markerSignals } from './chartStops';
import type { Suggestion, TerminalRow } from '../../api/types';
import { DataStatusTag } from '../../components/common';
import { KlineChart } from '../../components/charts/KlineChart';
import { KlineWindowInfo } from '../../components/charts/KlineWindowInfo';
import { IntradayChart } from '../../components/charts/IntradayChart';
import type { ChartMarker } from '../../components/charts/chartBase';
import { SIGNAL_KIND } from '../../i18n/labels';
import { bjToChartTime, fmtAmount, fmtTime, pctClass, signed } from '../../lib/format';
import { dayMinutes } from '../../lib/market';

export function ChartPanel({ row, suggestion, tradeDate: serverTradeDate = null }: { row: TerminalRow | undefined; suggestion: Suggestion | undefined; tradeDate?: string | null }) {
  const code = row?.security_code;
  // T-F21：日 K 按窗口加载（先 120 根，向左拖到边缘再按 before 取更早一页）
  const daily = useBarsWindow(code, 'd', 120);
  const minute = useBars(code, '1m');
  const cs = useCandidateSignals(code);

  const klineMarkers = useMemo<ChartMarker[]>(
    () => markerSignals(cs.data?.items ?? []).map((c) => ({ time: c.created_at.slice(0, 10) as Time, action: c.proposed_action, label: c.strategy_name.slice(0, 2) })),
    [cs.data],
  );
  // v0.2.3 #16：交易日取 /terminal.trade_date，不再从行情时间截取
  const tradeDate = serverTradeDate ?? minute.data?.items[0]?.t.slice(0, 10) ?? null;
  const events = useSecuritySignals(code, tradeDate);
  const minutes = useMemo(() => (tradeDate ? dayMinutes(tradeDate) : []), [tradeDate]);
  const intradayMarkers = useMemo<ChartMarker[]>(
    () =>
      (events.data?.items ?? [])
        .filter((e) => e.security_code === code && !!tradeDate && e.at.startsWith(tradeDate))
        .map((e) => ({ time: (Math.ceil(bjToChartTime(e.at) / 60) * 60) as Time, action: null, label: [SIGNAL_KIND[e.kind], additionalSignalInstances(e)].filter(Boolean).join(' · ') })),
    [events.data, code, tradeDate],
  );
  const stops = chartStops(suggestion);

  if (!row) return <div className="loading-box">请选择左侧的一只证券</div>;
  const q = row.quote;
  const pre = minute.data?.pre_close ?? null;
  return (
    <>
      <div className="quote-head" data-testid="quote-head">
        <span className="q-name">{row.name}</span>
        <span className="mono muted">{row.security_code}</span>
        {q ? (
          <>
            <span className={`q-price mono ${pctClass(q.change_pct)}`}>{q.price}</span>
            <span className={`mono ${pctClass(q.change_pct)}`}>
              {pre ? signed(Number(q.price) - Number(pre)) : ''} ({signed(q.change_pct)}%)
            </span>
            <span className="muted small mono">成交额 {fmtAmount(q.amount)}</span>
            <span className="muted small mono">{fmtTime(q.t).slice(11)}</span>
          </>
        ) : <span className="muted">无实时行情</span>}
        <DataStatusTag status={row.data_status} asOf={row.data_as_of} gaps={minute.data?.gaps} />
      </div>
      <div className="chart-title">
        日 K（{daily.first?.adjust === 'none' ? '不复权，前复权数据不可用已回落' : '前复权'}）<span className="muted small">　▲/▼ = 候选信号标记（策略简称 + 动作）</span>
        <span className="muted small" data-testid="stop-legend">
          　{stops ? `虚线 = ${stops.legend} 的止损/止盈` : suggestion?.consensus.status === 'divergent' ? '各策略分歧：止损/止盈见右侧各策略，图上不画' : ''}
        </span>
        {daily.first ? <KlineWindowInfo q={daily} unit="日" /> : null}
        <span className="legend"><i style={{ background: '#e3b341' }} />MA5<i style={{ background: '#58a6ff' }} />MA20<i style={{ background: '#bc8cff' }} />MA60</span>
      </div>
      <div className="chart-wrap kline">
        {daily.first ? (
          <KlineChart bars={daily.bars} markers={klineMarkers} stopLoss={stops?.stopLoss} takeProfit={stops?.takeProfit} viewKey={`${code}${daily.first.adjust === 'none' ? ':none' : ''}`} onReachStart={daily.loadOlderAuto} />
        ) : <div className="chart-empty">{daily.isError ? '日 K 加载失败' : '加载中…'}</div>}
      </div>
      <div className="chart-title">分时（不复权 · 黄线 = 均价 · 点线 = 昨收）<span className="muted small">　● = 盘中规则事件</span></div>
      <div className="chart-wrap intraday">
        {minute.data ? <IntradayChart bars={minute.data.items} preClose={minute.data.pre_close} allMinutes={minutes} markers={intradayMarkers} /> : <div className="chart-empty">{minute.isError ? '分时加载失败' : '加载中…'}</div>}
      </div>
      <div style={{ height: 6, flex: 'none' }} />
    </>
  );
}
