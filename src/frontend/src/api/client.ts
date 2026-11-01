import type { ApiErrorBody } from './types';

/** 后端基础路径（契约 §1）。只走同源相对路径；开发/测试由 MSW 拦截，生产由 nginx 反代到后端。 */
export const API_BASE = '/api/v1';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown> | null;
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> | null, requestId: string | null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
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
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') {
    const t = csrfToken();
    if (t) headers['X-CSRF-Token'] = t;
  }
  const res = await fetch(url, {
    method,
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    credentials: 'same-origin',
    signal: opts.signal,
  });
  if (res.status === 204 || res.status === 304) return undefined as T;
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
  return data as T;
}

export const apiGet = <T>(path: string, params?: QueryParams, signal?: AbortSignal) => request<T>('GET', path, { params, signal });
export const apiPost = <T>(path: string, body?: unknown) => request<T>('POST', path, { body });
