import type { Me } from '../api/types';
import { ApiError } from '../api/client';

/** 只允许站内路径作为登录后的跳转目标，防止开放重定向 */
export function safeNext(next: string | null | undefined, fallback = '/terminal'): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/login') || next.startsWith('/register')) return fallback;
  return next;
}

/** 契约 plan I2：风险测评 + signal_risk_disclosure 同意都完成后才能使用 ⚖ 功能 */
export const needsOnboarding = (me: Me) => !me.consents.signal_risk_disclosure || !me.risk_assessment;

export const isAuthError = (e: unknown) => e instanceof ApiError && e.status === 401;
export const isNotApproved = (e: unknown) => e instanceof ApiError && e.code === 'ACCOUNT_NOT_APPROVED';

/** 秒数转可读时长 */
export function fmtDuration(s: number) {
  if (s < 60) return `${s} 秒`;
  const m = Math.ceil(s / 60);
  return m < 60 ? `${m} 分钟` : `${Math.floor(m / 60)} 小时 ${m % 60} 分钟`;
}
