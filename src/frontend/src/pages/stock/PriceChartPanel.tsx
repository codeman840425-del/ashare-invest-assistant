import { useMemo, useState } from 'react';
import { Segmented } from 'antd';
import type { BarFreq } from '../../api/enums';
import { useBarsOf } from '../../api/marketQueries';
import { DataStatusTag, ErrorBox, Loading } from '../../components/common';
import { IntradayChart } from '../../components/charts/IntradayChart';
import { KlineChart } from '../../components/charts/KlineChart';
import type { ChartMarker } from '../../components/charts/chartBase';
import { dayMinutes } from '../../lib/market';

const NO_MARKERS: ChartMarker[] = [];
const LIMIT: Record<BarFreq, number> = { '1m': 240, d: 250, w: 120 };
const VIEW_TEXT: Record<BarFreq, string> = { '1m': '分时', d: '日K', w: '周K' };

/** 深色分时 / 日 K / 周 K（契约 §7.3 /securities/{code}/bars）；个股与指数共用 */
export function PriceChartPanel({ code, initial = 'd', height = 400, testId }: { code: string; initial?: BarFreq; height?: number; testId?: string }) {
  const [freq, setFreq] = useState<BarFreq>(initial);
  const q = useBarsOf(code, freq, LIMIT[freq]);
  const res = q.data;
  const tradeDate = res && freq === '1m' ? (res.items[0]?.t ?? res.data_as_of).slice(0, 10) : null;
  const minutes = useMemo(() => (tradeDate ? dayMinutes(tradeDate) : []), [tradeDate]);
  return (
    <section className="panel price-chart" data-testid={testId ?? 'price-chart'}>
      <div className="panel-head">
        <Segmented
          size="small"
          value={freq}
          onChange={(v) => setFreq(v as BarFreq)}
          options={(['1m', 'd', 'w'] as BarFreq[]).map((f) => ({ value: f, label: VIEW_TEXT[f] }))}
          aria-label="图表周期"
        />
        <span className="legend">
          {freq === '1m' ? (
            <>不复权 · 白线 价格<i style={{ background: '#e3b341' }} />均价 · 虚线 昨收</>
          ) : (
            <>前复权<i style={{ background: '#e3b341' }} />MA5<i style={{ background: '#58a6ff' }} />MA20<i style={{ background: '#bc8cff' }} />MA60</>
          )}
        </span>
        <span className="spacer" />
        {freq === 'w' ? <span className="muted small">周线日期取该周最后交易日（口径待契约确认）</span> : null}
        {res ? <DataStatusTag status={res.data_status} asOf={res.data_as_of} gaps={res.gaps} /> : null}
      </div>
      <div className="chart-wrap" style={{ height, margin: 6 }}>
        {q.isPending ? (
          <Loading />
        ) : q.isError ? (
          <ErrorBox error={q.error} />
        ) : res!.data_status === 'pending' ? (
          <div className="chart-empty">数据准备中，请稍后刷新</div>
        ) : freq === '1m' ? (
          <IntradayChart bars={res!.items} preClose={res!.pre_close} allMinutes={minutes} markers={NO_MARKERS} />
        ) : (
          <KlineChart bars={res!.items} markers={NO_MARKERS} />
        )}
      </div>
    </section>
  );
}
