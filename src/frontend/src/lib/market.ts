import type { Bar } from '../api/types';
import { bjToChartTime } from './format';

/**
 * A 股连续竞价分钟的“结束时刻”序列（09:31–11:30、13:01–15:00，共 240 根）。
 * 契约 §5.1：1m bar 的 t 为该分钟结束时刻；口径待 T003 实测确认（遗留问题）。
 */
export function minuteEnds(): string[] {
  const out: string[] = [];
  const push = (from: number, to: number) => {
    for (let t = from; t <= to; t++) out.push(`${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`);
  };
  push(9 * 60 + 31, 11 * 60 + 30);
  push(13 * 60 + 1, 15 * 60);
  return out;
}

/** 某交易日全部分钟（+08:00 时间串） */
export const dayMinutes = (date: string) => minuteEnds().map((m) => `${date}T${m}:00+08:00`);

/**
 * 不在 240 个分钟结束时刻里的 bar 个数（评审 T-F22a m18）。口径（分钟结束时刻）待 T003 / T-B05 确认；
 * 确认前不静默丢弃：开发模式下告警，并在图上用 data-dropped 标出。
 */
export function droppedBars(bars: Bar[], allMinutes: string[]): number {
  const have = new Set(allMinutes.map((t) => bjToChartTime(t)));
  return bars.filter((b) => !have.has(bjToChartTime(b.t))).length;
}

