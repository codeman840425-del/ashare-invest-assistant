import { useMemo, useState } from 'react';
import { Segmented } from 'antd';
import type { BarFreq } from '../../api/enums';
import { useBarsOf } from '../../api/marketQueries';
import { DataStatusTag, ErrorBox, GapNote, Loading } from '../../components/common';
import { IntradayChart } from '../../components/charts/IntradayChart';
import { KlineChart } from '../../components/charts/KlineChart';
import type { ChartMarker } from '../../components/charts/chartBase';
import { GAP_REASON } from '../../i18n/labels';
import { dayMinutes } from '../../lib/market';

const NO_MARKERS: ChartMarker[] = [];
const LIMIT: Record<BarFreq, number> = { '1m': 240, d: 250, w: 120 };
const VIEW_TEXT: Record<BarFreq, string> = { '1m': '分时', d: '日K', w: '周K' };
/** 空态文案按周期区分（评审 T-F22a m11） */
const EMPTY_TEXT: Record<BarFreq, string> = { '1m': '无分时数据（停牌或尚未开盘）', d: '无日 K 数据', w: '无周 K 数据' };

/** 深色分时 / 日 K / 周 K（契约 §7.3 /securities/{code}/bars）；个股与指数共用 */
export function PriceChartPanel({ code, initial = 'd', height = 400, testId }: { code: string; initial?: BarFreq; height?: number; testId?: string }) {
  const [freq, setFreq] = useState<BarFreq>(initial);
  // 评审 m17：切换周期时保留上一个周期的图，新数据到达再替换，不闪“加载中”
  const q = useBarsOf(code, freq, LIMIT[freq], { keepPrevious: true });
  const res = q.data;
  // 占位数据期间按“数据所属周期”绘制（新周期数据到达前，图仍是上一个周期）
  const [shownFreq, setShownFreq] = useState<BarFreq>(freq);
  if (res && !q.isPlaceholderData && shownFreq !== freq) setShownFreq(freq);
  const tradeDate = res && shownFreq === '1m' ? (res.items[0]?.t ?? res.data_as_of).slice(0, 10) : null;
  const minutes = useMemo(() => (tradeDate ? dayMinutes(tradeDate) : []), [tradeDate]);
  // 评审 M2：空图时说明原因（gaps 的原因码 + message）
  const empty = res ? (
    <span>
      {EMPTY_TEXT[shownFreq]}
      {res.gaps.length ? `：${res.gaps.map((g) => GAP_REASON[g.reason]).join('、')}` : ''}
    </span>
  ) : EMPTY_TEXT[shownFreq];
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
        {/* 契约 v0.2.6 Bar：周线取该周最后交易日（评审 m11） */}
        {freq === 'w' ? <span className="muted small">周线日期取该周最后交易日</span> : null}
        {res && !q.isPlaceholderData ? <DataStatusTag status={res.data_status} asOf={res.data_as_of} gaps={res.gaps} /> : null}
      </div>
      {res && !q.isPlaceholderData ? <GapNote status={res.data_status} gaps={res.gaps} asOf={res.data_as_of} testId="chart-gap-note" /> : null}
      <div className="chart-wrap" style={{ height, margin: 6 }} aria-busy={q.isPlaceholderData || undefined}>
        {q.isPending ? (
          <Loading />
        ) : q.isError ? (
          <ErrorBox error={q.error} />
        ) : res!.data_status === 'pending' ? (
          <div className="chart-empty">数据准备中，请稍后刷新</div>
        ) : shownFreq === '1m' ? (
          <IntradayChart bars={res!.items} preClose={res!.pre_close} allMinutes={minutes} markers={NO_MARKERS} empty={empty} />
        ) : (
          <KlineChart bars={res!.items} markers={NO_MARKERS} empty={empty} />
        )}
      </div>
    </section>
  );
}
