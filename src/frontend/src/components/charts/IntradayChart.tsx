import { useEffect, useRef } from 'react';
import { HistogramSeries, LineSeries, LineStyle, createChart, createSeriesMarkers, type UTCTimestamp } from 'lightweight-charts';
import type { Bar } from '../../api/types';
import { bjToChartTime } from '../../lib/format';
import { baseOptions, toSeriesMarker, type ChartMarker } from './chartBase';

/** 分时（1m，不复权）：价格线 + 均价线（avg_price）+ 昨收线 + 成交量；未来分钟留白到 15:00 */
export function IntradayChart({ bars, preClose, allMinutes, markers }: { bars: Bar[]; preClose: string | null; allMinutes: string[]; markers: ChartMarker[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || bars.length === 0) return;
    const chart = createChart(ref.current, {
      ...baseOptions,
      timeScale: { ...baseOptions.timeScale, timeVisible: true, secondsVisible: false },
      handleScroll: false,
      handleScale: false,
    });
    const byTime = new Map(bars.map((b) => [bjToChartTime(b.t), b]));
    const times = allMinutes.map((t) => bjToChartTime(t) as UTCTimestamp);
    const price = chart.addSeries(LineSeries, { color: '#e6edf3', lineWidth: 1, priceLineVisible: false });
    const avg = chart.addSeries(LineSeries, { color: '#e3b341', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    const vol = chart.addSeries(HistogramSeries, { priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false, priceFormat: { type: 'volume' } });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    price.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.26 } });
    price.setData(times.map((t) => (byTime.has(t) ? { time: t, value: +byTime.get(t)!.close } : { time: t })));
    avg.setData(times.map((t) => {
      const a = byTime.get(t)?.avg_price;
      return a ? { time: t, value: +a } : { time: t };
    }));
    let last = preClose ? +preClose : +bars[0].open;
    vol.setData(times.map((t) => {
      const b = byTime.get(t);
      if (!b) return { time: t };
      const c = +b.close >= last ? 'rgba(245,56,74,0.55)' : 'rgba(31,179,107,0.55)';
      last = +b.close;
      return { time: t, value: +b.volume, color: c };
    }));
    if (preClose) price.createPriceLine({ price: +preClose, color: '#6e7681', lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: true, title: '昨收' });
    const have = new Set<number>(times);
    createSeriesMarkers(price, markers.filter((m) => have.has(m.time as number)).map(toSeriesMarker).sort((a, b) => Number(a.time) - Number(b.time)));
    chart.timeScale().setVisibleLogicalRange({ from: 0, to: times.length - 1 });
    return () => chart.remove();
  }, [bars, preClose, allMinutes, markers]);
  if (bars.length === 0) return <div className="chart-empty">无分时数据（停牌或尚未开盘）</div>;
  return <div ref={ref} className="chart-box" data-testid="intraday" />;
}
