import { useEffect, useRef } from 'react';
import { HistogramSeries, LineSeries, createChart, type Time } from 'lightweight-charts';
import type { FundFlowDay } from '../../api/marketTypes';
import { baseOptions } from './chartBase';

/**
 * 日度主力净流入柱（亿元，红正绿负）+ 累计净流入线。
 * plan §2.10 写的是 ECharts；这里沿用已引入的 lightweight-charts，避免为一张柱图新增依赖（见 T-F03 报告）。
 */
export function FundFlowChart({ items }: { items: FundFlowDay[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || items.length === 0) return;
    const chart = createChart(ref.current, {
      ...baseOptions,
      leftPriceScale: { visible: true, borderColor: '#263040' },
      timeScale: { ...baseOptions.timeScale, rightOffset: 1, barSpacing: 8 },
    });
    const bars = chart.addSeries(HistogramSeries, { priceFormat: { type: 'price', precision: 2, minMove: 0.01 }, priceLineVisible: false, title: '主力净流入(亿)' });
    let cum = 0;
    const rows = items.map((d) => {
      const v = Number(d.main_net) / 1e8;
      cum += v;
      return { time: d.trade_date as Time, v, cum };
    });
    bars.setData(rows.map((r) => ({ time: r.time, value: +r.v.toFixed(2), color: r.v >= 0 ? 'rgba(245,56,74,0.75)' : 'rgba(31,179,107,0.75)' })));
    const line = chart.addSeries(LineSeries, {
      priceScaleId: 'left', color: '#e3b341', lineWidth: 1, priceLineVisible: false, title: '累计(亿)', priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });
    line.setData(rows.map((r) => ({ time: r.time, value: +r.cum.toFixed(2) })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [items]);
  if (items.length === 0) return <div className="chart-empty">无资金流数据</div>;
  return <div ref={ref} className="chart-box" data-testid="fund-flow-chart" />;
}
