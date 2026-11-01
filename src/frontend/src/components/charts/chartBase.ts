import { ColorType, CrosshairMode, type SeriesMarker, type Time } from 'lightweight-charts';
import type { Action } from '../../api/enums';
import { ACTION_COLOR, ACTION_SHORT } from '../../i18n/labels';

export const UP = '#f5384a';
export const DOWN = '#1fb36b';

export const baseOptions = {
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

/** 图上标记：候选信号（按策略+动作）或盘中规则事件（无动作） */
export interface ChartMarker {
  time: Time;
  action: Action | null;
  label: string;
}

export function toSeriesMarker(m: ChartMarker): SeriesMarker<Time> {
  if (!m.action) return { time: m.time, position: 'aboveBar', color: '#e3a008', shape: 'circle', text: m.label };
  const bull = m.action === 'buy' || m.action === 'add';
  const flat = m.action === 'wait' || m.action === 'hold';
  return {
    time: m.time,
    position: bull ? 'belowBar' : 'aboveBar',
    color: ACTION_COLOR[m.action],
    shape: bull ? 'arrowUp' : flat ? 'circle' : 'arrowDown',
    text: `${m.label}${ACTION_SHORT[m.action]}`,
  };
}

export function sma(values: number[], n: number) {
  return values.map((_, i) => (i < n - 1 ? null : values.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n));
}
