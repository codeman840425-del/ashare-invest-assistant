import type { CandidateSignal, Suggestion } from '../../api/types';
import type { CandidateSignalState } from '../../api/enums';

export interface ChartStops {
  stopLoss: string | null;
  takeProfit: string | null;
  /** 图例里写明止损/止盈线来自哪个策略 */
  legend: string;
}

/**
 * 日 K 上的止损/止盈线（评审 M5）：
 * - 分歧（divergent）时不画，各策略的止损/止盈只在右侧并列展示，避免把某一个策略的价位当成“结论”；
 * - 否则只画给出了价位的策略；若多个策略价位不同，同样不画（不合并、不挑选）；
 * - 画线时图例写出策略名。
 */
export function chartStops(sg: Suggestion | undefined): ChartStops | null {
  if (!sg || sg.consensus.status === 'divergent' || sg.consensus.status === 'none') return null;
  const withStops = sg.strategies.filter((s) => s.stops.stop_loss || s.stops.take_profit);
  if (!withStops.length) return null;
  const sig = (s: (typeof withStops)[number]) => `${s.stops.stop_loss ?? ''}|${s.stops.take_profit ?? ''}`;
  if (new Set(withStops.map(sig)).size > 1) return null;
  const s = withStops[0];
  return { stopLoss: s.stops.stop_loss, takeProfit: s.stops.take_profit, legend: withStops.map((x) => x.strategy_name).join('、') };
}

/** 日 K 只标记仍有意义的候选信号；已作废/过期/被取代/驳回的不画（评审 m8） */
export const MARKER_STATES: ReadonlySet<CandidateSignalState> = new Set(['open', 'drafted', 'blocked', 'released', 'confirmed']);
export const markerSignals = (items: CandidateSignal[]) => items.filter((c) => MARKER_STATES.has(c.state));
