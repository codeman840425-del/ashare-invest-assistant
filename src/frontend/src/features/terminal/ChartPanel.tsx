import { useMemo } from 'react';
import type { Time } from 'lightweight-charts';
import { useBars, useCandidateSignals, useSignals } from '../../api/queries';
import type { Suggestion, TerminalRow } from '../../api/types';
import { DataStatusTag } from '../../components/common';
import { KlineChart } from '../../components/charts/KlineChart';
import { IntradayChart } from '../../components/charts/IntradayChart';
import type { ChartMarker } from '../../components/charts/chartBase';
import { SIGNAL_KIND } from '../../i18n/labels';
import { bjToChartTime, fmtAmount, fmtTime, pctClass, signed } from '../../lib/format';
import { dayMinutes } from '../../lib/market';

export function ChartPanel({ row, suggestion }: { row: TerminalRow | undefined; suggestion: Suggestion | undefined }) {
  const code = row?.security_code;
  const daily = useBars(code, 'd');
  const minute = useBars(code, '1m');
  const cs = useCandidateSignals(code);
  const events = useSignals();

  const klineMarkers = useMemo<ChartMarker[]>(
    () => (cs.data?.items ?? []).map((c) => ({ time: c.created_at.slice(0, 10) as Time, action: c.proposed_action, label: c.strategy_name.slice(0, 2) })),
    [cs.data],
  );
  const tradeDate = minute.data?.items[0]?.t.slice(0, 10) ?? row?.quote?.t.slice(0, 10) ?? null;
  const minutes = useMemo(() => (tradeDate ? dayMinutes(tradeDate) : []), [tradeDate]);
  const intradayMarkers = useMemo<ChartMarker[]>(
    () =>
      (events.data?.items ?? [])
        .filter((e) => e.security_code === code && tradeDate && e.at.startsWith(tradeDate))
        .map((e) => ({ time: (Math.ceil(bjToChartTime(e.at) / 60) * 60) as Time, action: null, label: SIGNAL_KIND[e.kind] })),
    [events.data, code, tradeDate],
  );
  const stops = suggestion?.strategies.find((s) => s.stops.stop_loss || s.stops.take_profit)?.stops;

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
        <DataStatusTag status={row.data_status} asOf={q?.t} gaps={minute.data?.gaps} />
      </div>
      <div className="chart-title">
        日 K（前复权）<span className="muted small">　▲/▼ = 候选信号标记（策略简称 + 动作），虚线 = 止损/止盈</span>
        <span className="legend"><i style={{ background: '#e3b341' }} />MA5<i style={{ background: '#58a6ff' }} />MA20<i style={{ background: '#bc8cff' }} />MA60</span>
      </div>
      <div className="chart-wrap kline">
        {daily.data ? <KlineChart bars={daily.data.items} markers={klineMarkers} stopLoss={stops?.stop_loss} takeProfit={stops?.take_profit} /> : <div className="chart-empty">{daily.isError ? '日 K 加载失败' : '加载中…'}</div>}
      </div>
      <div className="chart-title">分时（不复权 · 黄线 = 均价 · 点线 = 昨收）<span className="muted small">　● = 盘中规则事件</span></div>
      <div className="chart-wrap intraday">
        {minute.data ? <IntradayChart bars={minute.data.items} preClose={minute.data.pre_close} allMinutes={minutes} markers={intradayMarkers} /> : <div className="chart-empty">{minute.isError ? '分时加载失败' : '加载中…'}</div>}
      </div>
      <div style={{ height: 6, flex: 'none' }} />
    </>
  );
}
