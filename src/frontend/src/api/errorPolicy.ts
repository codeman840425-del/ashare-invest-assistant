import { ApiError } from './client';
import type { AnyErrorCode } from './errorCodes';

/**
 * 按错误码给用户看的中文文案（评审 M2）。只覆盖终端/日报/建议卡等页面会遇到的码；
 * 其余码回落到服务端 message，再回落到按 HTTP 状态的通用文案。
 */
export const ERROR_TEXT: Partial<Record<AnyErrorCode, string>> = {
  VALIDATION_ERROR: '请求参数有误',
  INVALID_CURSOR: '列表位置已失效，请刷新后重试',
  AUTH_REQUIRED: '登录已过期，请重新登录',
  INVALID_CREDENTIALS: '用户名或密码错误',
  ACCOUNT_NOT_APPROVED: '账号尚未通过审核或已停用',
  ACCOUNT_LOCKED: '登录失败次数过多，账号暂时锁定',
  CSRF_FAILED: '页面已过期，请刷新后重试',
  FORBIDDEN: '没有权限执行该操作',
  ENTITLEMENT_LIMIT_REACHED: '已达到当前权益上限',
  NOT_FOUND: '内容不存在或已删除',
  METHOD_NOT_ALLOWED: '前端调用方式与接口不一致（已记录到控制台）',
  PAYLOAD_TOO_LARGE: '文件过大，超过上传上限',
  CONFLICT: '数据冲突，请刷新后重试',
  IDEMPOTENCY_CONFLICT: '重复提交，请勿多次点击',
  VERSION_CONFLICT: '数据已被修改，请刷新后重试',
  IMMUTABLE_RESOURCE: '该内容生成后不可修改',
  SUGGESTION_SUPERSEDED: '该候选信号卡已被新版本取代',
  SUGGESTION_REFRESH_TOO_FREQUENT: '刷新过于频繁，请稍后再试',
  SUGGESTION_INSUFFICIENT_DATA: '必备数据缺失，暂未生成候选信号卡',
  FRESH_DATA_REQUIRED: '行情数据暂未更新，请稍后再试',
  INGEST_PAUSED: '行情采集已暂停，当前显示的是缓存数据',
  UPSTREAM_ERROR: '数据源返回异常，请稍后重试',
  UPSTREAM_RATE_LIMITED: '数据源限流，请求已排队，请稍后重试',
  UPSTREAM_UNAVAILABLE: '数据源暂不可用，请稍后重试',
  RATE_LIMITED: '操作过于频繁，请稍后再试',
  INTERNAL_ERROR: '服务内部错误，请稍后重试',
  MAINTENANCE: '系统维护中，请稍后再试',
  NETWORK_ERROR: '网络连接失败，请检查网络或稍后重试',
  NOT_MODIFIED: '数据未变化，但本地缓存缺失，请刷新页面',
};

/** 字节数 → “5 MB” / “26 MB” / “512 KB” */
export function fmtBytes(n: number): string {
  if (n >= 1024 * 1024) return `${+(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    // 带参数的文案（评审 m6 / m7）
    if (e.code === 'FRESH_DATA_REQUIRED') {
      const s = Number(e.details?.retry_after_s);
      if (Number.isFinite(s) && s > 0) return `行情数据暂未更新，请 ${Math.ceil(s)} 秒后再试`;
    }
    if (e.code === 'PAYLOAD_TOO_LARGE') {
      const max = Number(e.details?.max_bytes);
      if (Number.isFinite(max) && max > 0) return `文件过大，超过单次上传上限 ${fmtBytes(max)}`;
    }
    const t = ERROR_TEXT[e.code];
    if (t) return t;
    if (e.message && e.code !== 'HTTP_ERROR') return e.message;
    if (e.status >= 500) return '服务暂时不可用，请稍后重试';
    return `请求失败（HTTP ${e.status}）`;
  }
  return (e as Error)?.message ?? String(e);
}

export type GlobalErrorAction = 'login' | 'log' | 'none';

/** 全局处理（QueryCache/MutationCache.onError）：401 → 登录页；405 → 控制台（v0.2.5 起没有同意门槛） */
export function globalErrorAction(e: unknown): GlobalErrorAction {
  if (!(e instanceof ApiError)) return 'none';
  if (e.status === 401 && e.code === 'AUTH_REQUIRED') return 'login';
  if (e.status === 405 || e.code === 'METHOD_NOT_ALLOWED') return 'log';
  return 'none';
}

/**
 * 重试策略（评审 m1）：4xx 不重试；5xx/网络错误重试 1 次。
 * FRESH_DATA_REQUIRED 只出现在写操作（如 manual_refresh），不做自动重试，提示用户按 retry_after_s 再试（裁定 T-F01 #2，评审 m6）。
 */
export function shouldRetry(failureCount: number, e: unknown): boolean {
  if (!(e instanceof ApiError)) return failureCount < 1;
  if (e.code === 'FRESH_DATA_REQUIRED') return false;
  if (e.status === 0 || e.status >= 500) return failureCount < 1;
  return false;
}

/** 有 details.retry_after_s 时按它等待（上限 30 秒），否则指数退避 1s/2s/4s */
export function retryDelay(failureCount: number, e: unknown): number {
  const after = e instanceof ApiError ? Number(e.details?.retry_after_s) : NaN;
  if (Number.isFinite(after) && after > 0) return Math.min(after, 30) * 1000;
  return Math.min(1000 * 2 ** failureCount, 8000);
}

type Listener = (action: GlobalErrorAction, e: ApiError) => void;
const listeners = new Set<Listener>();
/** AppShell 订阅后执行跳转；Query 层不依赖路由 */
export function onGlobalApiError(l: Listener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
export function handleGlobalError(e: unknown) {
  const action = globalErrorAction(e);
  if (action === 'none') return;
  const err = e as ApiError;
  if (action === 'log') {
    console.error(`[api] ${err.status} ${err.code}：${err.message}`, err.details, err.requestId);
    return;
  }
  listeners.forEach((l) => l(action, err));
}
