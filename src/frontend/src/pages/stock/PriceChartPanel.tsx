import { useMemo, useState } from 'react';
import { Segmented } from 'antd';
import type { BarFreq } from '../../api/enums';
import { useBarsOf, useBarsWindow } from '../../api/marketQueries';
import { DataStatusTag, ErrorBox, GapNote, Loading } from '../../components/common';
import { IntradayChart } from '../../components/charts/IntradayChart';
import { KlineChart } from '../../components/charts/KlineChart';
import { KlineWindowInfo } from '../../components/charts/KlineWindowInfo';
import type { ChartMarker } from '../../components/charts/chartBase';
import { GAP_REASON } from '../../i18n/labels';
import { dayMinutes } from '../../lib/market';

const NO_MARKERS: ChartMarker[] = [];
/** 分时一次取全天；日 K / 周 K 是窗口大小（T-F21：向左拖到边缘再按 before 取更早一页） */
const LIMIT: Record<BarFreq, number> = { '1m': 240, d: 250, w: 120 };
const VIEW_TEXT: Record<BarFreq, string> = { '1m': '分时', d: '日K', w: '周K' };
/** 空态文案按周期区分（评审 T-F22a m11） */
const EMPTY_TEXT: Record<BarFreq, string> = { '1m': '无分时数据（停牌或尚未开盘）', d: '无日 K 数据', w: '无周 K 数据' };
type KlFreq = Exclude<BarFreq, '1m'>;

/** 深色分时 / 日 K / 周 K（契约 §7.3 /securities/{code}/bars）；个股与指数共用 */
export function PriceChartPanel({ code, initial = 'd', height = 400, testId }: { code: string; initial?: BarFreq; height?: number; testId?: string }) {
  const [freq, setFreq] = useState<BarFreq>(initial);
  // K 线 hook 记住最近一个日/周周期：切到分时时 K 线的 key 不变（缓存仍在，只是不请求）
  const [klFreq, setKlFreq] = useState<KlFreq>(initial === 'w' ? 'w' : 'd');
  if (freq !== '1m' && freq !== klFreq) setKlFreq(freq);
  const minute = useBarsOf(code, '1m', LIMIT['1m'], { enabled: freq === '1m' });
  // T-F21 窗口加载；评审 m17：切换日/周时保留上一个周期的图，新数据到达再替换
  const kl = useBarsWindow(code, klFreq, LIMIT[klFreq], { keepPrevious: true, enabled: freq !== '1m' });

  const curReady = freq === '1m' ? !!minute.data : !!kl.data && !kl.isPlaceholderData;
  const curRes = freq === '1m' ? minute.data : kl.first;
  const curError = freq === '1m' ? (minute.isError && !minute.data ? minute.error : null) : kl.isError && !kl.isFetchNextPageError ? kl.error : null;
  // 新周期数据到达前，图仍按上一个周期绘制（不闪“加载中”）
  const [shownFreq, setShownFreq] = useState<BarFreq>(freq);
  if (curReady && shownFreq !== freq) setShownFreq(freq);
  const shownRes = shownFreq === '1m' ? minute.data : kl.first;
  // A-12/F-14：data_as_of 可为 null（无数据时点），取不到就不认交易日，不能直接 slice
  const minuteStamp = minute.data ? (minute.data.items[0]?.t ?? minute.data.data_as_of) : null;
  const tradeDate = minute.data && shownFreq === '1m' && minuteStamp ? minuteStamp.slice(0, 10) : null;
  const minutes = useMemo(() => (tradeDate ? dayMinutes(tradeDate) : []), [tradeDate]);
  // 评审 M2：空图时说明原因（gaps 的原因码 + message）
  const empty = shownRes ? (
    <span>
      {EMPTY_TEXT[shownFreq]}
      {shownRes.gaps.length ? `：${shownRes.gaps.map((g) => GAP_REASON[g.reason]).join('、')}` : ''}
    </span>
  ) : EMPTY_TEXT[shownFreq];
  const showWindow = shownFreq !== '1m' && freq !== '1m' && curReady;
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
        {showWindow ? <KlineWindowInfo q={kl} unit={freq === 'w' ? '周' : '日'} /> : null}
        {/* 契约 v0.2.6 Bar：周线取该周最后交易日（评审 m11） */}
        {freq === 'w' ? <span className="muted small">周线日期取该周最后交易日</span> : null}
        {curRes && curReady ? <DataStatusTag status={curRes.data_status} asOf={curRes.data_as_of} gaps={curRes.gaps} /> : null}
      </div>
      {curRes && curReady ? <GapNote status={curRes.data_status} gaps={curRes.gaps} asOf={curRes.data_as_of} testId="chart-gap-note" /> : null}
      <div className="chart-wrap" style={{ height, margin: 6 }} aria-busy={(!curReady && !!shownRes) || undefined}>
        {curError ? (
          <ErrorBox error={curError} />
        ) : !shownRes ? (
          <Loading />
        ) : shownRes.data_status === 'pending' ? (
          <div className="chart-empty">数据准备中，请稍后刷新</div>
        ) : shownFreq === '1m' ? (
          <IntradayChart bars={minute.data!.items} preClose={minute.data!.pre_close} allMinutes={minutes} markers={NO_MARKERS} empty={empty} />
        ) : (
          <KlineChart bars={kl.bars} markers={NO_MARKERS} empty={empty} viewKey={`${code}:${shownFreq}`} onReachStart={kl.loadOlderAuto} />
        )}
      </div>
    </section>
  );
}
