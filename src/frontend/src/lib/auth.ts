import { ApiError } from '../api/client';

/** 只允许站内路径作为登录后的跳转目标，防止开放重定向 */
export function safeNext(next: string | null | undefined, fallback = '/terminal'): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/login') || next.startsWith('/register')) return fallback;
  return next;
}

export const isAuthError = (e: unknown) => e instanceof ApiError && e.status === 401;
export const isNotApproved = (e: unknown) => e instanceof ApiError && e.code === 'ACCOUNT_NOT_APPROVED';

/** 秒数转可读时长 */
export function fmtDuration(s: number) {
  if (s < 60) return `${s} 秒`;
  const m = Math.ceil(s / 60);
  return m < 60 ? `${m} 分钟` : `${Math.floor(m / 60)} 小时 ${m % 60} 分钟`;
}
