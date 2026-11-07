import { ApiError } from './client';
import type { AnyErrorCode } from './errorCodes';
import type { DataLicenceState } from './enums';
import { LICENCE_STATUS } from '../i18n/licenceLabels';

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
  // 契约 v0.2.6 #6（评审 T-F22a m3）
  DATA_LICENCE_IN_USE: '该证书已绑定到另一个账号；一张证书只能由一位用户使用',
  DATA_LICENCE_NOT_SET: '你还没有设置数据证书',
  DATA_LICENCE_UNAVAILABLE: '你的数据证书不可用，暂时无法拉取最新数据',
  // 计划草案（契约 §7.7，T-F18）
  PLAN_REQUIRES_EXPLAINABLE_SIGNAL: '该候选信号缺少可解释的规则依据，不能拟定计划草案',
  SIGNAL_NOT_EXECUTABLE: '该候选信号还有未解除的不可执行原因，暂不能拟定计划草案',
  STRATEGY_VERSION_NOT_RUNNABLE: '该策略版本当前不可运行（如处于模拟期）',
  PLAN_DRAFT_STALE: '生成草案后条件已变化，草案已失效，请重新生成',
  CHECKLIST_INCOMPLETE: '判断清单还有必答项未作答',
  RISK_ACK_REQUIRED: '请先勾选“我已了解风险”',
  DEVIATION_ACK_REQUIRED: '数量或价格超出草案区间，请确认偏离后再提交',
};

/** 需要附“去设置数据证书”链接的错误码 */
export const LICENCE_ERROR_CODES: readonly string[] = ['DATA_LICENCE_IN_USE', 'DATA_LICENCE_NOT_SET', 'DATA_LICENCE_UNAVAILABLE'];

/** 字节数 → “5 MB” / “26 MB” / “512 KB” */
export function fmtBytes(n: number): string {
  if (n >= 1024 * 1024) return `${+(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

/** 秒数 → “30 秒” / “12 分钟” */
export function fmtWait(s: number): string {
  return s >= 60 ? `${Math.ceil(s / 60)} 分钟` : `${Math.ceil(s)} 秒`;
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
    if (e.code === 'DATA_LICENCE_UNAVAILABLE') {
      const st = e.details?.status as DataLicenceState | undefined;
      const label = st && st in LICENCE_STATUS ? LICENCE_STATUS[st].text : null;
      if (label) return `你的数据证书不可用（${label}），暂时无法拉取最新数据`;
    }
    if (e.code === 'INSTANCE_SCOPE_INVALID') {
      // v0.2.8 #10 / 补充裁定②：按 details.issue 给出具体原因
      const issue = e.details?.issue;
      if (issue === 'security_type_not_supported') return e.details?.security_type === 'etf' ? 'ETF 暂不支持建策略实例' : '该证券类型暂不支持建策略实例';
      if (issue === 'unknown_security') return '证券代码不存在';
    }
    if (e.code === 'SUGGESTION_REFRESH_TOO_FREQUENT') {
      const s = Number(e.details?.retry_after_s);
      if (Number.isFinite(s) && s > 0) return `刷新过于频繁，请 ${fmtWait(s)}后再试`;
    }
    if (e.code === 'RATE_LIMITED') {
      const s = Number(e.details?.retry_after_s);
      if (Number.isFinite(s) && s > 0) return `操作过于频繁，请 ${fmtWait(s)}后再试`;
    }
    const t = ERROR_TEXT[e.code];
    if (t) return t;
    if (e.message && e.code !== 'HTTP_ERROR') return e.message;
    if (e.status >= 500) return '服务暂时不可用，请稍后重试';
    return `请求失败（HTTP ${e.status}）`;
  }
  return (e as Error)?.message ?? String(e);
}

/**
 * T-F20：后端尚未注册的路由。实测后端（src/backend/app/common/errors.py _http_exception_handler）把未注册路由的
 * Starlette 404 转成与资源不存在完全相同的 `404 NOT_FOUND` 信封（message “资源不存在”），响应体无法区分。
 * 因此只按“契约里不会返回资源 404 的集合 / 聚合端点”判断：这些路径（不带 id 段）上的 404 只可能是路由不存在。
 * 带 account_id / security_code 的请求可能因归属或证券不存在而 404（契约 §7.2、#27），一律按原文案处理（保守）。
 * 非信封的 404（如 FastAPI 默认 {"detail":"Not Found"} → HTTP_ERROR）在这些路径上同样算路由不存在。
 */
export const ROUTE_PENDING_PATHS: readonly string[] = [
  '/today', '/daily-reports', '/notifications', '/notifications/unread-count', '/stream', '/suggestions', '/signals',
  '/candidate-signals', '/terminal', '/strategies', '/strategy-instances', '/plans', '/market/overview',
];
export const ROUTE_PENDING_TEXT = '功能开发中，即将上线';
export function isRoutePending(e: unknown): boolean {
  if (!(e instanceof ApiError) || e.status !== 404 || !e.url) return false;
  if (e.code !== 'NOT_FOUND' && e.code !== 'HTTP_ERROR') return false;
  const u = new URL(e.url, 'http://x');
  const path = u.pathname.replace(/^\/api\/v1/, '');
  if (!ROUTE_PENDING_PATHS.includes(path)) return false;
  return !u.searchParams.has('account_id') && !u.searchParams.has('security_code');
}

export type GlobalErrorAction = 'login' | 'csrf' | 'log' | 'none';

/**
 * 全局处理（QueryCache/MutationCache.onError）：401 → 登录页；405 → 控制台（v0.2.5 起没有同意门槛）；
 * 403 CSRF_FAILED → 顶部提示刷新页面，不自动重试（契约 v0.2.9 #30 ④、§1.3）
 */
export function globalErrorAction(e: unknown): GlobalErrorAction {
  if (!(e instanceof ApiError)) return 'none';
  if (e.status === 401 && e.code === 'AUTH_REQUIRED') return 'login';
  if (e.status === 403 && e.code === 'CSRF_FAILED') return 'csrf';
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
