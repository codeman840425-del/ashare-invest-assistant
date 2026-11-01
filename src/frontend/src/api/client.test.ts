import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { ApiError, apiGet, apiPost, buildUrl } from './client';
import type { Paged, SuggestionListItem, TerminalResponse } from './types';

describe('api client', () => {
  it('只拼同源相对路径 /api/v1/...，拒绝绝对地址', () => {
    expect(buildUrl('/terminal', { scope: 'all', x: undefined, y: null, z: '' })).toBe('/api/v1/terminal?scope=all');
    expect(() => buildUrl('https://example.com/x')).toThrow();
    expect(() => buildUrl('//evil/x')).toThrow();
  });

  it('GET /terminal 返回契约结构（MSW 示例数据）', async () => {
    const t = await apiGet<TerminalResponse>('/terminal', { scope: 'all' });
    expect(Object.keys(t).sort()).toEqual(['account', 'rows', 'server_time', 'session', 'trade_date', 'truncated', 'unread_notifications']);
    expect(t.rows.length).toBeGreaterThan(0);
  });

  it('scope 非法 → 400 VALIDATION_ERROR 信封解析为 ApiError', async () => {
    const err = await apiGet('/terminal', { scope: 'bad' }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    const e = err as ApiError;
    expect(e.status).toBe(400);
    expect(e.code).toBe('VALIDATION_ERROR');
    expect(e.details).toEqual({ fields: [{ field: 'scope', issue: expect.any(String) as unknown }] });
    expect(e.requestId).toMatch(/^mock-/);
  });

  it('未知资源 → 404 NOT_FOUND', async () => {
    const err = (await apiGet('/suggestions/not-exist').catch((e: unknown) => e)) as ApiError;
    expect(err.status).toBe(404);
    expect(err.code).toBe('NOT_FOUND');
  });

  it('非信封错误体 → HTTP_ERROR，并读取 X-Request-Id', async () => {
    server.use(http.get('*/api/v1/me', () => new HttpResponse('oops', { status: 502, headers: { 'X-Request-Id': 'rid-1' } })));
    const err = (await apiGet('/me').catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe('HTTP_ERROR');
    expect(err.status).toBe(502);
    expect(err.requestId).toBe('rid-1');
  });

  it('POST 带 CSRF 头；204 返回 undefined', async () => {
    document.cookie = 'csrf_token=abc123';
    let seen: string | null = null;
    server.use(http.post('*/api/v1/notifications/read-all', ({ request }) => {
      seen = request.headers.get('X-CSRF-Token');
      return new HttpResponse(null, { status: 204 });
    }));
    await expect(apiPost('/notifications/read-all')).resolves.toBeUndefined();
    expect(seen).toBe('abc123');
  });

  it('分页：limit 上限 200，next_cursor 续页', async () => {
    const p = await apiGet<Paged<SuggestionListItem>>('/suggestions', { status: 'active', limit: 2 });
    expect(p.items).toHaveLength(2);
    expect(p.next_cursor).not.toBeNull();
    const p2 = await apiGet<Paged<SuggestionListItem>>('/suggestions', { status: 'active', limit: 2, cursor: p.next_cursor });
    expect(p2.items[0].id).not.toBe(p.items[0].id);
  });
});
