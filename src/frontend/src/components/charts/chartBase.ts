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

/** 视口（逻辑序号区间）+ 当时最左一根的时间 + 所属的图（证券+周期） */
export interface SavedView { key: string; first: string; from: number; to: number }

/** 拖到距窗口左边缘不足这么多根时，请求更早一页（T-F21） */
export const REACH_START_BARS = 10;

/**
 * T-F21 窗口加载后保持视口：左侧拼进 k 根更早的 K 线后，原来看的那段的逻辑序号整体右移 k，
 * 按原最左一根在新数据里的位置平移视口，避免画面跳回最新。换了证券/周期或找不到原最左一根 → null（用默认视口）。
 */
export function shiftView(prev: SavedView | null, key: string, times: readonly string[]): { from: number; to: number } | null {
  if (!prev || prev.key !== key) return null;
  const k = times.indexOf(prev.first);
  if (k < 0) return null;
  return { from: prev.from + k, to: prev.to + k };
}
