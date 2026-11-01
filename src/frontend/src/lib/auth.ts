import type { Me } from '../api/types';
import { ApiError } from '../api/client';

/** 只允许站内路径作为登录后的跳转目标，防止开放重定向 */
export function safeNext(next: string | null | undefined, fallback = '/terminal'): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/login') || next.startsWith('/register')) return fallback;
  return next;
}

/**
 * 契约 plan I2 / v0.2.4 #5：signal_risk_disclosure 需要（重新）同意，或没有测评 / 测评已过期时进入开通引导。
 * 注：用户已取消风险测评与同意弹窗（T-F05 取消），此判断属 T-F02 已提交代码，去留等编排者决定（见 reports/T-F02b.md）。
 */
export const needsOnboarding = (me: Me) =>
  (me.consents.signal_risk_disclosure?.needs_reconsent ?? true) || !me.risk_assessment || me.risk_assessment.status === 'expired';

export const isAuthError = (e: unknown) => e instanceof ApiError && e.status === 401;
export const isNotApproved = (e: unknown) => e instanceof ApiError && e.code === 'ACCOUNT_NOT_APPROVED';

/** 秒数转可读时长 */
export function fmtDuration(s: number) {
  if (s < 60) return `${s} 秒`;
  const m = Math.ceil(s / 60);
  return m < 60 ? `${m} 分钟` : `${Math.floor(m / 60)} 小时 ${m % 60} 分钟`;
}
