/** T-F17 候选信号 / 不可执行原因的展示文案 */
import type { ReasonStatus } from '../api/enums';

export const REASON_STATUS: Record<ReasonStatus, { text: string; color: string }> = {
  active: { text: '生效中', color: 'orange' },
  released: { text: '已解除', color: 'green' },
  obsolete: { text: '已作废', color: 'default' },
};
export const RELEASED_BY: Record<'system' | 'user', string> = { system: '系统自动重评解除', user: '你手动解除' };

/** 状态历史 cause 的中文（契约 v0.2.9 #6 枚举 candidate_signal_event_cause；未知值原样显示） */
const CAUSE_TEXT: Record<string, string> = {
  executability_check: '可执行性检查',
  reason_released: '原因解除',
  user: '你的操作',
  expiry: '超过有效期',
  invalidation: '失效条件满足',
  supersede: '被新信号取代',
};
export function causeText(cause: string): string {
  return CAUSE_TEXT[cause] ?? cause;
}

/** 生命周期徽标：只对“模拟中 / 观察中”等非正式状态加醒目徽标 */
export const LIFECYCLE_BADGE: Partial<Record<string, { color: string; tip: string }>> = {
  simulating: { color: 'purple', tip: '该策略版本处于模拟阶段，规则信号仅供观察，不计入正式统计' },
  observing: { color: 'gold', tip: '该策略版本处于观察期，权重下调，规则信号请结合自己的判断' },
  draft: { color: 'default', tip: '该策略版本仍是草稿' },
  retired: { color: 'default', tip: '该策略版本已退役' },
};
