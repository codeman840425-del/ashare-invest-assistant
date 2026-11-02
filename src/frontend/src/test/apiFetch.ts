/**
 * 测试里直接调用示例接口（不经 api/client）时使用：与浏览器里的前端一样，
 * 写请求（POST/PUT/PATCH/DELETE）带上 Cookie csrf_token 的值作为 X-CSRF-Token 请求头（契约 §1.3 双提交）。
 * 测试缺头、头与 Cookie 不一致等情况时，直接用 fetch。
 */
const WRITE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export function csrfFromCookie(): string | null {
  const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

export function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? 'GET').toUpperCase();
  const headers = new Headers(init.headers);
  const token = csrfFromCookie();
  if (WRITE.has(method) && token && !headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', token);
  return fetch(input, { credentials: 'same-origin', ...init, headers });
}
