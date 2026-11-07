/** T-F20：后端未注册路由的 404 → “功能开发中，即将上线”；资源 404 仍显示原文案；stream / unread-count 不再重试 */
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { ApiError } from '../api/client';
import { isRoutePending, ROUTE_PENDING_TEXT } from '../api/errorPolicy';
import { UNREAD_POLL_MS as UNREAD_POLL_MS_FOR_TEST } from '../api/queries';
import { startEventStream } from '../lib/eventStream';
import { server } from '../mocks/server';
import { routePendingHandlers } from '../mocks/routePending';
import { preloadRoutes } from '../test/preloadRoutes';
import { advance, fakeClock } from '../test/timing';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

beforeAll(() => preloadRoutes(routes), 30_000);
const API = '/api/v1';

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

describe('判定：只认契约里不会返回资源 404 的集合端点', () => {
  const e = (url: string, code = 'NOT_FOUND') => new ApiError(404, code, '资源不存在', null, null, url);
  it('集合端点的 404（信封或 FastAPI 默认体）→ 开发中', () => {
    expect(isRoutePending(e('/api/v1/today'))).toBe(true);
    expect(isRoutePending(e('/api/v1/notifications/unread-count'))).toBe(true);
    expect(isRoutePending(e('/api/v1/plans?status=active', 'HTTP_ERROR'))).toBe(true);
  });
  it('带 id 段、account_id、security_code，或其他错误码 → 不算', () => {
    expect(isRoutePending(e('/api/v1/suggestions/abc'))).toBe(false);
    expect(isRoutePending(e('/api/v1/terminal?account_id=x'))).toBe(false);
    expect(isRoutePending(e('/api/v1/candidate-signals?security_code=600000.SH'))).toBe(false);
    expect(isRoutePending(new ApiError(404, 'NOT_FOUND', 'x', null, null))).toBe(false);
    expect(isRoutePending(new ApiError(409, 'CONFLICT', 'x', null, null, '/api/v1/today'))).toBe(false);
  });
});

describe('页面：路由未实现场景', () => {
  for (const [page, shape] of [['/today', 'envelope'], ['/daily-reports', 'envelope'], ['/notifications', 'fastapi'], ['/plans', 'envelope'], ['/strategies', 'envelope']] as const) {
    it(`${page}（${shape}）显示“${ROUTE_PENDING_TEXT}”，不显示加载失败`, async () => {
      server.use(...routePendingHandlers(undefined, shape));
      renderAt(page);
      expect((await screen.findAllByTestId('route-pending'))[0]).toHaveTextContent(ROUTE_PENDING_TEXT);
      expect(screen.queryByText(/加载失败：内容不存在或已删除/)).toBeNull();
    });
  }
  it('资源 NOT_FOUND（详情页）仍显示原文案', async () => {
    server.use(http.get(`${API}/suggestions/:id`, () => HttpResponse.json({ error: { code: 'NOT_FOUND', message: '资源不存在', details: null, request_id: 'r' } }, { status: 404 })));
    renderAt('/suggestions/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee');
    expect(await screen.findByText(/加载失败：内容不存在或已删除/)).toBeInTheDocument();
    expect(screen.queryByTestId('route-pending')).toBeNull();
  });
});

describe('stream / unread-count 遇到路由未实现不再重试', () => {
  it('/stream 404 → closed，不重连', async () => {
    let calls = 0;
    fakeClock();
    server.use(http.get(`*${API}/stream`, () => { calls += 1; return HttpResponse.json({ detail: 'Not Found' }, { status: 404 }); }));
    const h = startEventStream({ onMessage: () => undefined, retryMs: 10 });
    await waitFor(() => expect(h.state()).toBe('closed'));
    await advance(5000);
    expect(calls).toBe(1);
    h.stop();
  });
  it('unread-count 404 → 不再轮询', async () => {
    let calls = 0;
    fakeClock();
    server.use(...routePendingHandlers(['/today']), http.get(`${API}/notifications/unread-count`, () => {
      calls += 1;
      return HttpResponse.json({ error: { code: 'NOT_FOUND', message: '资源不存在', details: null, request_id: 'r' } }, { status: 404 });
    }));
    renderAt('/today');
    await screen.findAllByTestId('route-pending');
    await waitFor(() => expect(calls).toBe(1));
    await advance(UNREAD_POLL_MS_FOR_TEST * 3);
    expect(calls).toBe(1);
  });
});
