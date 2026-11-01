import { useEffect, useRef } from 'react';
import {
  CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, LineStyle, createChart, createSeriesMarkers,
  type IChartApi, type SeriesMarker, type Time, type UTCTimestamp,
} from 'lightweight-charts';
import { ACTION_COLOR, ACTION_SHORT } from '../labels';
import { STRATEGIES, dailyBars, dailyMarkers, intraday, intradayMarkers, specOf, type ChartMarker } from '../mock/data';

const UP = '#f5384a';
const DOWN = '#1fb36b';
const baseOptions = {
  autoSize: true,
  layout: {
    background: { type: ColorType.Solid, color: '#0d1117' },
    textColor: '#8b949e',
    fontSize: 11,
    fontFamily: 'JetBrains Mono, Menlo, Consolas, monospace',
    attributionLogo: true, // Lightweight Charts（Apache-2.0）按许可展示署名
  },
  grid: { vertLines: { color: '#1b2230' }, horzLines: { color: '#1b2230' } },
  crosshair: { mode: CrosshairMode.Normal },
  rightPriceScale: { borderColor: '#263040' },
  timeScale: { borderColor: '#263040' },
};

function toMarker(m: ChartMarker): SeriesMarker<Time> {
  const bull = m.action === 'buy' || m.action === 'add';
  const wait = m.action === 'wait' || m.action === 'hold';
  return {
    time: m.time as Time,
    position: bull ? 'belowBar' : wait ? 'aboveBar' : 'aboveBar',
    color: ACTION_COLOR[m.action],
    shape: bull ? 'arrowUp' : wait ? 'circle' : 'arrowDown',
    text: `${STRATEGIES[m.strategy_key]?.name.slice(0, 2) ?? ''}${ACTION_SHORT[m.action]}${m.text === '候选' || m.text === '先卖' ? '·' + m.text : ''}`,
  };
}

function sma(values: number[], n: number) {
  return values.map((_, i) => (i < n - 1 ? null : values.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n));
}

export function KlineChart({ code, stopLoss, takeProfit }: { code: string; stopLoss?: string | null; takeProfit?: string | null }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart: IChartApi = createChart(ref.current, { ...baseOptions, timeScale: { ...baseOptions.timeScale, rightOffset: 4, barSpacing: 6 } });
    const bars = dailyBars(code);
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN, wickUpColor: UP, wickDownColor: DOWN,
      priceLineVisible: true,
    });
    candle.setData(bars.map((b) => ({ time: b.time as Time, open: b.open, high: b.high, low: b.low, close: b.close })));
    const vol = chart.addSeries(HistogramSeries, { priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    candle.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.24 } });
    vol.setData(bars.map((b) => ({ time: b.time as Time, value: b.volume, color: b.close >= b.open ? 'rgba(245,56,74,0.45)' : 'rgba(31,179,107,0.45)' })));
    const closes = bars.map((b) => b.close);
    ([[5, '#e3b341'], [20, '#58a6ff'], [60, '#bc8cff']] as const).forEach(([n, color]) => {
      const s = chart.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      s.setData(sma(closes, n).map((v, i) => (v == null ? { time: bars[i].time as Time } : { time: bars[i].time as Time, value: +v.toFixed(3) })));
    });
    if (stopLoss) candle.createPriceLine({ price: Number(stopLoss), color: DOWN, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: '止损' });
    if (takeProfit) candle.createPriceLine({ price: Number(takeProfit), color: UP, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: '止盈' });
    createSeriesMarkers(candle, dailyMarkers(code).map(toMarker).sort((a, b) => String(a.time).localeCompare(String(b.time))));
    chart.timeScale().setVisibleLogicalRange({ from: bars.length - 90, to: bars.length + 3 });
    return () => chart.remove();
  }, [code, stopLoss, takeProfit]);
  return <div ref={ref} className="chart-box" data-testid="kline" />;
}

export function IntradayChart({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const spec = specOf(code);
    const chart = createChart(ref.current, {
      ...baseOptions,
      timeScale: { ...baseOptions.timeScale, timeVisible: true, secondsVisible: false },
      handleScroll: false, handleScale: false,
    });
    const pts = intraday(code);
    const price = chart.addSeries(LineSeries, { color: '#e6edf3', lineWidth: 1, priceLineVisible: false });
    const avg = chart.addSeries(LineSeries, { color: '#e3b341', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    const vol = chart.addSeries(HistogramSeries, { priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false, priceFormat: { type: 'volume' } });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    price.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.26 } });
    price.setData(pts.map((p) => (p.price == null ? { time: p.time as UTCTimestamp } : { time: p.time as UTCTimestamp, value: p.price })));
    avg.setData(pts.map((p) => (p.avg == null ? { time: p.time as UTCTimestamp } : { time: p.time as UTCTimestamp, value: p.avg })));
    let last = spec.prev_close;
    vol.setData(pts.map((p) => {
      if (p.volume == null) return { time: p.time as UTCTimestamp };
      const c = (p.price ?? last) >= last ? 'rgba(245,56,74,0.55)' : 'rgba(31,179,107,0.55)';
      last = p.price ?? last;
      return { time: p.time as UTCTimestamp, value: p.volume, color: c };
    }));
    price.createPriceLine({ price: spec.prev_close, color: '#6e7681', lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: true, title: '昨收' });
    createSeriesMarkers(price, intradayMarkers(code).map(toMarker).sort((a, b) => Number(a.time) - Number(b.time)));
    chart.timeScale().setVisibleLogicalRange({ from: 0, to: pts.length - 1 });
    return () => chart.remove();
  }, [code]);
  return <div ref={ref} className="chart-box" data-testid="intraday" />;
}
