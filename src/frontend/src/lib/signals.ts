/** 候选信号的纯函数：终止态、方向、同股方向冲突（T-F17） */
import type { Action, CandidateSignalState } from '../api/enums';
import type { CandidateSignal, NonExecutableReason } from '../api/types';
import { CHECK_ON } from '../i18n/labels';
import { RELEASED_BY } from '../i18n/signalLabels';
import { fmtTime } from './format';

export const TERMINAL_STATES: readonly CandidateSignalState[] = ['confirmed', 'dismissed', 'expired', 'invalidated', 'superseded'];
export const isTerminal = (s: CandidateSignalState) => TERMINAL_STATES.includes(s);

/** buy/add 为增仓方向，reduce/sell 为减仓方向；hold/wait 无方向 */
export function direction(a: Action): 'up' | 'down' | null {
  if (a === 'buy' || a === 'add') return 'up';
  if (a === 'reduce' || a === 'sell') return 'down';
  return null;
}

/** 同一证券、未终止、方向相反的其他信号（并列展示，不合成结论） */
export function conflictsOf(sig: CandidateSignal, all: readonly CandidateSignal[]): CandidateSignal[] {
  const d = direction(sig.proposed_action);
  if (!d || isTerminal(sig.state)) return [];
  return all.filter((o) => o.id !== sig.id && o.security_code === sig.security_code && !isTerminal(o.state) && direction(o.proposed_action) !== null && direction(o.proposed_action) !== d);
}

/** 可拟定计划草案的状态（契约 §7.7：drafted / released） */
export const canDraft = (s: CandidateSignalState) => s === 'drafted' || s === 'released';

/** 禁投名单要在“限制”里移除（契约 §6.1），不走 /release */
const VIA_RESTRICTIONS = new Set(['BLOCKLISTED']);

/** 自动重评状态（契约 v0.2.7 §7.6：由原因的 status / released_at / released_by 推出） */
export function reevalText(r: NonExecutableReason): string {
  if (r.status === 'released') return `${RELEASED_BY[r.released_by]}${r.released_at ? ` · ${fmtTime(r.released_at)}` : ''}`;
  if (r.status === 'obsolete') return '所属信号已结束，该原因作废';
  if (r.release_condition.machine_checkable) return `等待系统自动重评（${r.release_condition.check_on.map((c) => CHECK_ON[c]).join('、')}）`;
  if (VIA_RESTRICTIONS.has(r.code)) return '需在禁投名单中移除后解除';
  return '需你确认后手动解除';
}
export const manuallyReleasable = (r: NonExecutableReason) => r.status === 'active' && !r.release_condition.machine_checkable && !VIA_RESTRICTIONS.has(r.code);


export type SignalsTab = 'signals' | 'released';
/** 目标页读 tab 参数：/today“查看全部”→ ?tab=released；其他值按 signals 处理 */
export const parseTab = (v: string | null): SignalsTab => (v === 'released' ? 'released' : 'signals');
