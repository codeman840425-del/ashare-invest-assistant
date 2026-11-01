import { useEffect, useRef } from 'react';
import { CandlestickSeries, HistogramSeries, LineSeries, LineStyle, createChart, createSeriesMarkers, type Time } from 'lightweight-charts';
import type { Bar } from '../../api/types';
import { DOWN, UP, baseOptions, sma, toSeriesMarker, type ChartMarker } from './chartBase';

/** 日 K / 周 K（前复权）+ 成交量 + MA5/20/60 + 止损/止盈线 + 候选信号标记 */
export function KlineChart({ bars, markers, stopLoss, takeProfit, empty = '无日 K 数据' }: { bars: Bar[]; markers: ChartMarker[]; stopLoss?: string | null; takeProfit?: string | null; empty?: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || bars.length === 0) return;
    const chart = createChart(ref.current, { ...baseOptions, timeScale: { ...baseOptions.timeScale, rightOffset: 4, barSpacing: 6 } });
    const data = bars.map((b) => ({ time: b.t.slice(0, 10) as Time, open: +b.open, high: +b.high, low: +b.low, close: +b.close, volume: +b.volume }));
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN, wickUpColor: UP, wickDownColor: DOWN,
    });
    candle.setData(data.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
    const vol = chart.addSeries(HistogramSeries, { priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    candle.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.24 } });
    vol.setData(data.map((b) => ({ time: b.time, value: b.volume, color: b.close >= b.open ? 'rgba(245,56,74,0.45)' : 'rgba(31,179,107,0.45)' })));
    const closes = data.map((b) => b.close);
    ([[5, '#e3b341'], [20, '#58a6ff'], [60, '#bc8cff']] as const).forEach(([n, color]) => {
      const s = chart.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      s.setData(sma(closes, n).map((v, i) => (v == null ? { time: data[i].time } : { time: data[i].time, value: +v.toFixed(3) })));
    });
    if (stopLoss) candle.createPriceLine({ price: Number(stopLoss), color: DOWN, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: '止损' });
    if (takeProfit) candle.createPriceLine({ price: Number(takeProfit), color: UP, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: '止盈' });
    const times = new Set(data.map((d) => d.time));
    createSeriesMarkers(candle, markers.filter((m) => times.has(m.time)).map(toSeriesMarker).sort((a, b) => String(a.time).localeCompare(String(b.time))));
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, data.length - 90), to: data.length + 3 });
    return () => chart.remove();
  }, [bars, markers, stopLoss, takeProfit]);
  if (bars.length === 0) return <div className="chart-empty" data-testid="chart-empty">{empty}</div>;
  return <div ref={ref} className="chart-box" data-testid="kline" />;
}
