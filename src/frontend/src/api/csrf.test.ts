/**
 * 契约 §1.3 CSRF 双提交：所有 POST/PUT/PATCH/DELETE（含上传、登出）同时带 Cookie csrf_token（credentials: same-origin）
 * 与请求头 X-CSRF-Token；mock 在缺头、头与 Cookie 不一致、与会话令牌不一致时返回 403 CSRF_FAILED。
 */
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { mockLoginAs, state } from '../mocks/session';
import { ApiError, apiDelete, apiPatch, apiPost, apiPut, apiUpload, request, setCsrfToken } from './client';
import { apiFetch, csrfFromCookie } from '../test/apiFetch';

const API = '/api/v1';
const PROBE = '/csrf-probe';
type Seen = { method: string; token: string | null; credentials: string; cookie: string | undefined };

/**
 * 捕获请求：记录方法、X-CSRF-Token、此时浏览器会附带的 Cookie，以及 client 传给 fetch 的 credentials
 * （测试环境的 fetch 包装不保留 Request.credentials，所以从 fetch 的入参读）。
 */
function probe(): Seen[] {
  const seen: Seen[] = [];
  let lastCredentials = '';
  const real = globalThis.fetch;
  vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    lastCredentials = String(init?.credentials);
    return real(input, init);
  });
  server.use(http.all(`*${API}${PROBE}`, ({ request }) => {
    seen.push({ method: request.method, token: request.headers.get('X-CSRF-Token'), credentials: lastCredentials, cookie: csrfFromCookie() ?? undefined });
    return new HttpResponse(null, { status: 204 });
  }));
  return seen;
}

const errOf = async (p: Promise<unknown>) => (await p.then(() => null, (e: unknown) => e)) as ApiError | null;
const rawPost = (path: string, init: RequestInit = {}) => fetch(`${API}${path}`, { method: 'POST', credentials: 'same-origin', ...init });

afterEach(() => {
  setCsrfToken(null);
  vi.restoreAllMocks();
});

describe('client：每个写方法都带 X-CSRF-Token 与 Cookie', () => {
  it('Cookie 中有令牌（示例会话 mock-csrf）', () => {
    expect(csrfFromCookie()).toBe('mock-csrf');
    expect(state.csrfToken).toBe('mock-csrf');
  });

  const cases: [string, () => Promise<unknown>][] = [
    ['POST', () => apiPost(PROBE, { a: 1 })],
    ['POST（Idempotency-Key）', () => apiPost(PROBE, {}, { idempotencyKey: 'k1' })],
    ['PUT', () => apiPut(PROBE, { a: 1 })],
    ['PATCH', () => apiPatch(PROBE, { a: 1 })],
    ['DELETE', () => apiDelete(PROBE)],
    ['上传 multipart', () => { const f = new FormData(); f.append('file', new Blob(['x']), 'a.txt'); return apiUpload(PROBE, f); }],
    ['request() 直接调用 POST', () => request('POST', PROBE)],
  ];
  for (const [name, call] of cases) {
    it(`${name}：头与 Cookie 一致，credentials=same-origin`, async () => {
      const seen = probe();
      await call();
      expect(seen).toHaveLength(1);
      expect(seen[0].token).toBe('mock-csrf');
      expect(seen[0].token).toBe(seen[0].cookie);
      expect(seen[0].credentials).toBe('same-origin');
    });
  }

  it('GET 不带 X-CSRF-Token', async () => {
    const seen = probe();
    await request('GET', PROBE);
    expect(seen[0].token).toBeNull();
  });

  it('读不到 Cookie 时用登录响应里的令牌兜底；Cookie 存在时以 Cookie 为准', async () => {
    const seen = probe();
    setCsrfToken('from-body');
    await apiPost(PROBE);
    expect(seen[0].token).toBe('mock-csrf');
    document.cookie = 'csrf_token=; Path=/; Max-Age=0';
    await apiPost(PROBE);
    expect(seen[1].token).toBe('from-body');
  });

  it('真实 mock：登出（POST /auth/logout）带头 → 204；之后写请求 401', async () => {
    await expect(apiPost('/auth/logout')).resolves.toBeUndefined();
    expect(csrfFromCookie()).toBeNull();
    expect((await errOf(apiPost('/notifications/read-all')))?.code).toBe('AUTH_REQUIRED');
  });

  it('真实 mock：上传 POST /imports、PUT /me/profile、PATCH、DELETE 都通过 CSRF 校验（不是 403 CSRF_FAILED）', async () => {
    const f = new FormData();
    f.append('file', new Blob(['x']), 'a.txt');
    const results = await Promise.all([
      errOf(apiUpload('/imports', f)),
      errOf(apiPut('/me/profile', { horizon_pref: ['long'] })),
      errOf(apiPatch('/me/data-licence', { tier: 'free' })),
      errOf(apiDelete('/me/data-licence')),
      errOf(apiPost('/notifications/read-all')),
    ]);
    for (const e of results) expect(e?.code).not.toBe('CSRF_FAILED');
  });
});

describe('mock：按契约校验 CSRF', () => {
  it('缺少请求头 → 403 CSRF_FAILED（POST / PUT / PATCH / DELETE）', async () => {
    for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
      const r = await fetch(`${API}/me/data-licence`, { method, credentials: 'same-origin', headers: { 'content-type': 'application/json' }, body: method === 'DELETE' ? undefined : '{}' });
      expect([method, r.status]).toEqual([method, 403]);
      expect(((await r.json()) as { error: { code: string } }).error.code).toBe('CSRF_FAILED');
    }
  });

  it('请求头与 Cookie 不一致 → 403；没有 Cookie、只有请求头 → 403', async () => {
    expect((await rawPost('/notifications/read-all', { headers: { 'X-CSRF-Token': 'other' } })).status).toBe(403);
    document.cookie = 'csrf_token=; Path=/; Max-Age=0';
    expect((await rawPost('/notifications/read-all', { headers: { 'X-CSRF-Token': 'mock-csrf' } })).status).toBe(403);
  });

  it('头与 Cookie 一致但与会话令牌不符 → 403（v0.2.4 验收）', async () => {
    document.cookie = 'csrf_token=forged; Path=/';
    expect((await rawPost('/notifications/read-all', { headers: { 'X-CSRF-Token': 'forged' } })).status).toBe(403);
  });

  it('头、Cookie、会话三者一致 → 通过；GET 不校验', async () => {
    expect((await apiFetch(`${API}/notifications/read-all`, { method: 'POST' })).status).toBe(204);
    expect((await fetch(`${API}/me`)).status).toBe(200);
  });

  it('登录不带头也可以（待定：契约未写登录前请求的例外）；登录轮换令牌，响应体与 Cookie 相同，旧令牌失效', async () => {
    mockLoginAs(null);
    const r = await rawPost('/auth/login', { headers: { 'content-type': 'application/json' }, body: JSON.stringify({ username: 'demo_user', password: 'x'.repeat(12) }) });
    expect(r.status).toBe(200);
    const body = (await r.json()) as { csrf_token: string };
    expect(body.csrf_token).not.toBe('mock-csrf');
    expect(csrfFromCookie()).toBe(body.csrf_token);
    expect((await rawPost('/notifications/read-all', { headers: { 'X-CSRF-Token': 'mock-csrf' } })).status).toBe(403);
    expect((await apiFetch(`${API}/notifications/read-all`, { method: 'POST' })).status).toBe(204);
  });

  it('登出也要 CSRF：缺头 → 403，会话保留', async () => {
    expect((await rawPost('/auth/logout')).status).toBe(403);
    expect(state.currentUserId).not.toBeNull();
  });

  it('/admin/*：非管理员缺 CSRF 仍为 404；管理员缺 CSRF → 403', async () => {
    const path = '/admin/data-licences/x/pause';
    expect((await rawPost(path)).status).toBe(404);
    mockLoginAs('admin');
    expect((await rawPost(path)).status).toBe(403);
  });
});

describe('源码自查：写请求只经 api/client.request 发出', () => {
  it('除 client.ts 外没有直接 fetch 写请求，也没有 XMLHttpRequest / sendBeacon', () => {
    const files = import.meta.glob(['../**/*.ts', '../**/*.tsx', '!../**/*.test.ts', '!../**/*.test.tsx', '!../mocks/**', '!../test/**'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
    expect(Object.keys(files).length).toBeGreaterThan(50);
    const offenders: string[] = [];
    for (const [path, src] of Object.entries(files)) {
      if (path.endsWith('/api/client.ts')) continue;
      if (/XMLHttpRequest|sendBeacon/.test(src)) offenders.push(`${path}: XHR/beacon`);
      for (const m of src.matchAll(/(?<![\w.])fetch\(([^;]*)/g)) if (/method\s*:/.test(m[1])) offenders.push(`${path}: ${m[0].slice(0, 80)}`);
    }
    expect(offenders).toEqual([]);
  });
});
