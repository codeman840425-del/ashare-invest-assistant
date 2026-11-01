import type { ApiErrorBody } from './types';
import { ERROR_CODES, isErrorCode, type AnyErrorCode } from './errorCodes';

/** 后端基础路径（契约 §1）。只走同源相对路径；开发/测试由 MSW 拦截，生产由 nginx 反代到后端。 */
export const API_BASE = '/api/v1';

/** 契约 §4 错误信封映射成的异常；`code` 为带类型的错误码（未知码保留原值，按 HTTP 状态归类） */
export class ApiError extends Error {
  readonly status: number;
  readonly code: AnyErrorCode;
  readonly details: Record<string, unknown> | null;
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> | null, requestId: string | null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code as AnyErrorCode;
    this.details = details;
    this.requestId = requestId;
  }
  /** 契约里登记过的码（未登记的码多半是前后端版本不一致） */
  get known(): boolean {
    return isErrorCode(this.code);
  }
  /** 契约 §4 规定的 HTTP 状态（未登记的码为 null） */
  get contractStatus(): number | null {
    return isErrorCode(this.code) ? ERROR_CODES[this.code] : null;
  }
}

/**
 * 弱 ETag 缓存（契约 §7.3、§9：`/terminal`、`/today` 带 If-None-Match，未变返回 304）。
 * 304 时返回上一次 200 的响应体，而不是 undefined（评审 M1：否则 TanStack Query 会把空值写进缓存，表格瞬间变空）。
 * 键为完整 URL（含查询参数）；登出时调用 clearEtagCache()。
 */
const etagCache = new Map<string, { etag: string; data: unknown }>();
export function clearEtagCache() {
  etagCache.clear();
}

function isErrorBody(x: unknown): x is ApiErrorBody {
  if (typeof x !== 'object' || x === null || !('error' in x)) return false;
  const e = (x as { error: unknown }).error;
  return typeof e === 'object' && e !== null && typeof (e as { code?: unknown }).code === 'string';
}

export type QueryParams = Record<string, string | number | boolean | null | undefined>;

/** 拼出同源 URL：路径恒为 `/api/v1/...`，不允许绝对地址（防止误连外网）。 */
export function buildUrl(path: string, params?: QueryParams): string {
  if (!path.startsWith('/') || path.startsWith('//')) throw new Error(`API path must be relative to ${API_BASE}: ${path}`);
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
  const q = qs.toString();
  return `${API_BASE}${path}${q ? `?${q}` : ''}`;
}

function csrfToken(): string | null {
  const m = typeof document !== 'undefined' ? document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) : null;
  return m ? decodeURIComponent(m[1]) : null;
}

export async function request<T>(method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE', path: string, opts: { params?: QueryParams; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const rel = buildUrl(path, opts.params);
  // 浏览器里相对地址即可；jsdom/Node 的 fetch 需要绝对 URL，取当前页面同源
  const url = typeof window !== 'undefined' ? new URL(rel, window.location.origin).toString() : rel;
  const headers: Record<string, string> = { Accept: 'application/json' };
  const cached = method === 'GET' ? etagCache.get(rel) : undefined;
  if (cached) headers['If-None-Match'] = cached.etag;
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') {
    const t = csrfToken();
    if (t) headers['X-CSRF-Token'] = t;
  }
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      credentials: 'same-origin',
      signal: opts.signal,
    });
  } catch (e) {
    if ((e as Error)?.name === 'AbortError') throw e;
    throw new ApiError(0, 'NETWORK_ERROR', '网络连接失败，请检查网络或稍后重试', null, null);
  }
  if (res.status === 304) {
    if (cached) return cached.data as T;
    throw new ApiError(304, 'NOT_MODIFIED', '服务端返回 304，但本地没有可复用的数据', null, res.headers.get('X-Request-Id'));
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    if (isErrorBody(data)) {
      const e = data.error;
      throw new ApiError(res.status, e.code, e.message, e.details, e.request_id ?? res.headers.get('X-Request-Id'));
    }
    throw new ApiError(res.status, 'HTTP_ERROR', `HTTP ${res.status}`, null, res.headers.get('X-Request-Id'));
  }
  const etag = method === 'GET' ? res.headers.get('ETag') : null;
  if (etag) etagCache.set(rel, { etag, data });
  return data as T;
}

export const apiGet = <T>(path: string, params?: QueryParams, signal?: AbortSignal) => request<T>('GET', path, { params, signal });
export const apiPost = <T>(path: string, body?: unknown) => request<T>('POST', path, { body });
