/**
 * T-F34b：返修四项 P2 的定点用例。
 * ① 子资源判定收窄到显式清单 + superseded_by 真实资源 404 优先（不被吞成“开发中”）；
 * ② 七组空列表用例等待请求完成再断言（findBy*），通知断言未读数返回后的状态，财务页签断言命中目标元素；
 * ③ /quotes 出错走错误提示（路由未实现 → “功能开发中”），不再显示“无行情缓存”；
 * ④ /strategy-instances 后端已注册、前端仍是占位页：断言占位页 + 请求未发出的说明。
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { ApiError } from '../api/client';
import { isResourceNotFound, isRoutePending, isStockSubPending, ROUTE_PENDING_TEXT } from '../api/errorPolicy';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { preloadRoutes } from '../test/preloadRoutes';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

beforeAll(() => preloadRoutes(routes), 30_000);
const API = '/api/v1';
const emptyPage = () => HttpResponse.json({ items: [], next_cursor: null });
const notFound = (details: Record<string, unknown> | null = null) =>
  HttpResponse.json({ error: { code: 'NOT_FOUND', message: '资源不存在', details, request_id: 'r' } }, { status: 404 });

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}
const e404 = (url: string, details: Record<string, unknown> | null = null) => new ApiError(404, 'NOT_FOUND', '资源不存在', details, null, url);

describe('①判定收窄：显式清单 + superseded_by 优先', { timeout: 20_000 }, () => {
  it('清单内在建的子资源 → 开发中；未登记的同类路径 → 不吞', () => {
    for (const sub of ['bars', 'financials', 'fund-flows', 'factors', 'announcements']) {
      expect(isStockSubPending(e404(`/api/v1/securities/600000.SH/${sub}?freq=d`))).toBe(true);
    }
    // 未登记（已实现或未来实现）的子路由一律不吞
    for (const other of ['dividends', 'shareholders', 'announcements/extra', 'limit-up']) {
      expect(isStockSubPending(e404(`/api/v1/securities/600000.SH/${other}`))).toBe(false);
    }
    // 详情与搜索本身不吞
    expect(isStockSubPending(e404('/api/v1/securities/600000.SH'))).toBe(false);
    expect(isStockSubPending(e404('/api/v1/securities/search?q=600000'))).toBe(false);
  });
  it('superseded_by 真实资源 404 优先：不被“开发中”吞掉', () => {
    const sup = { superseded_by: '920094.BJ' };
    expect(isStockSubPending(e404('/api/v1/securities/430010.BJ/bars', sup))).toBe(false);
    expect(isStockSubPending(e404('/api/v1/securities/430010.BJ/financials', sup))).toBe(false);
    expect(isRoutePending(e404('/api/v1/securities/430010.BJ', sup))).toBe(false);
    // 非 404 或细节非字符串时不触发
    expect(isStockSubPending(new ApiError(500, 'INTERNAL_ERROR', 'x', sup, null, '/api/v1/securities/600000.SH/bars'))).toBe(false);
    expect(isStockSubPending(e404('/api/v1/securities/600000.SH/bars', { superseded_by: 42 }))).toBe(true);
  });
  it('T-F34c：资源语义 404（NOT_FOUND 但 message 非「资源不存在」）不吞成开发中', () => {
    // mocks/handlers.ts 的公告接口对不存在的证券返回 `notFound('证券')` → message「证券 不存在（示例数据）」
    const resource = new ApiError(404, 'NOT_FOUND', '证券 不存在（示例数据）', null, null, '/api/v1/securities/999999.SH/announcements');
    expect(isResourceNotFound(resource)).toBe(true);
    expect(isStockSubPending(resource)).toBe(false);
    // 路由不存在的标准信封（message「资源不存在」）仍归开发中
    const route = new ApiError(404, 'NOT_FOUND', '资源不存在', null, null, '/api/v1/securities/999999.SH/announcements');
    expect(isResourceNotFound(route)).toBe(false);
    expect(isStockSubPending(route)).toBe(true);
    // FastAPI 默认体维持 T-F20 口径（按路由不存在）
    const fastapi = new ApiError(404, 'HTTP_ERROR', 'HTTP 404', null, null, '/api/v1/securities/999999.SH/announcements');
    expect(isResourceNotFound(fastapi)).toBe(false);
    expect(isStockSubPending(fastapi)).toBe(true);
  });

  it('T-F34c：资源语义 404 的公告子资源 → 页面显示资源 404 文案，不是「功能开发中」', async () => {
    mockLoginAs('demo_user');
    // 存在的证券 + 公告接口业务资源 404（handlers.ts 形态：message「证券 不存在（示例数据）」）
    server.use(http.get(`${API}/securities/:code/announcements`, () =>
      HttpResponse.json({ error: { code: 'NOT_FOUND', message: '证券 不存在（示例数据）', details: null, request_id: 'r' } }, { status: 404 })));
    renderAt('/stocks/600000.SH?tab=announcements');
    const tab = await screen.findByTestId('tab-announcements', {}, { timeout: 10_000 });
    await waitFor(() => expect(within(tab).queryByTestId('route-pending')).toBeNull(), { timeout: 8000 });
    expect(await screen.findByText(/证券 不存在|加载失败/, {}, { timeout: 8000 })).toBeInTheDocument();
  });

  it('页面层：详情 404 带 superseded_by → 提示新代码，不显示开发中', async () => {
    mockLoginAs('demo_user');
    server.use(http.get(`${API}/securities/:code`, () => notFound({ superseded_by: '920094.BJ' })));
    renderAt('/stocks/430010.BJ');
    expect(await screen.findByText('未找到该证券', {}, { timeout: 8000 })).toBeInTheDocument();
    expect(await screen.findByText('920094.BJ', {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.queryByTestId('route-pending')).toBeNull();
  });
});

describe('②空列表：等请求完成再断言（findBy*）', { timeout: 30_000 }, () => {
  beforeEach(() => mockLoginAs('demo_user'));

  it('通知：空列表 →「暂无通知」；未读数返回 0 后按钮禁用', async () => {
    server.use(http.get(`${API}/notifications`, emptyPage), http.get(`${API}/notifications/unread-count`, () => HttpResponse.json({ count: 0 })));
    renderAt('/notifications');
    const empty = await screen.findByTestId('nc-empty', {}, { timeout: 8000 });
    expect(empty).toHaveTextContent('暂无通知');
    // 未读数请求完成后才出现确定值（'—' 表示未返回），再断言按钮状态
    await waitFor(() => expect(screen.getByTestId('nc-filter-unread')).not.toHaveTextContent('未读（—）'), { timeout: 8000 });
    expect(screen.getByTestId('nc-filter-unread')).toHaveTextContent('未读（0）');
    expect(screen.getByTestId('nc-read-all')).toBeDisabled();
    expect(document.querySelector('.error-box')).toBeNull();
  });

  // T-F34c：七组都等“请求完成信号”（各自空态元素/表格空态出现）再断言，不再用“没有 loading”这种弱条件
  it.each([
    ['/alerts', '/alerts', '没有符合条件的提醒'],
    ['/candidate-signals', '/candidate-signals', '没有符合条件的候选信号'],
    ['/plans', '/plans', '没有符合条件的计划'],
    ['/candidates', '/candidates', '没有符合条件的研究候选'],
  ] as const)('%s：空列表 → 完成态空态元素出现，无错误框、无「加载失败」', async (path, api, text) => {
    server.use(http.get(`${API}${api}`, emptyPage));
    renderAt(path);
    expect(await screen.findByText(text, {}, { timeout: 8000 })).toBeInTheDocument();
    expect(document.querySelector('.error-box')).toBeNull();
    expect(document.body.textContent).not.toMatch(/加载失败/);
  });

  it('/daily-reports：空列表 → 「暂无日报」（索引页无最新日报即此空态）', async () => {
    server.use(http.get(`${API}/daily-reports`, emptyPage));
    renderAt('/daily-reports');
    expect(await screen.findByText('暂无日报', {}, { timeout: 8000 })).toBeInTheDocument();
    expect(document.querySelector('.error-box')).toBeNull();
    expect(document.body.textContent).not.toMatch(/加载失败/);
  });

  it('/strategies：空列表 → 表格渲染完成（无加载中、无错误框）', async () => {
    server.use(http.get(`${API}/strategies`, emptyPage), http.get(`${API}/accounts`, () => HttpResponse.json({ items: [], next_cursor: null })));
    renderAt('/strategies');
    await waitFor(() => expect(document.body.textContent).not.toMatch(/加载中…/), { timeout: 8000 });
    expect(document.querySelector('.error-box')).toBeNull();
    expect(document.body.textContent).not.toMatch(/加载失败/);
  });

  it('提醒表格：空列表 → 表格内空态文案', async () => {
    server.use(http.get(`${API}/alerts`, emptyPage));
    renderAt('/alerts');
    const empty = await screen.findByText('没有符合条件的提醒', {}, { timeout: 8000 });
    expect(empty.closest('.ant-table')).not.toBeNull();
  });
});

describe('③行情错误入口：不再显示“无行情缓存”', { timeout: 20_000 }, () => {
  beforeEach(() => mockLoginAs('demo_user'));

  it('/quotes 404（路由未实现）→ 行情头显示「功能开发中」，不是“无行情缓存”', async () => {
    server.use(http.get(`${API}/quotes`, notFound));
    renderAt('/stocks/600000.SH');
    await screen.findByTestId('stock-head', {}, { timeout: 8000 });
    const qe = await screen.findByTestId('quote-error', {}, { timeout: 8000 });
    expect(qe).toHaveAttribute('data-kind', 'route-pending');
    expect(qe).toHaveTextContent(ROUTE_PENDING_TEXT);
    expect(screen.queryByTestId('quote-empty')).toBeNull();
  });

  it('/quotes 500 → 错误提示（含错误码），不是“无行情缓存”', async () => {
    server.use(http.get(`${API}/quotes`, () => HttpResponse.json({ error: { code: 'INTERNAL_ERROR', message: '服务器内部错误', details: null, request_id: 'r' } }, { status: 500 })));
    renderAt('/stocks/600000.SH');
    await screen.findByTestId('stock-head', {}, { timeout: 8000 });
    const qe = await screen.findByTestId('quote-error', {}, { timeout: 8000 });
    expect(qe).toHaveAttribute('data-kind', 'error');
    expect(qe).toHaveTextContent('行情加载失败');
    expect(qe).toHaveAttribute('role', 'alert');
    expect(screen.queryByTestId('quote-empty')).toBeNull();
  });

  it('/quotes 返回空 items（200，非错误）→ 仍是「无行情缓存」', async () => {
    server.use(http.get(`${API}/quotes`, () => HttpResponse.json({ items: [] })));
    renderAt('/stocks/600000.SH');
    await screen.findByTestId('stock-head', {}, { timeout: 8000 });
    expect(await screen.findByTestId('quote-empty', {}, { timeout: 8000 })).toHaveTextContent('无行情缓存');
    expect(screen.queryByTestId('quote-error')).toBeNull();
  });

  it('T-F34c：轮询失败保留缓存时，成交量/换手率/市值等派生值一并隐藏（显示「—」）', async () => {
    // 第一次成功拿到行情，之后轮询都失败：react-query 保留 data 但 isError=true
    let n = 0;
    const ok = {
      items: [{ security_code: '600000.SH', name: '示例银行', price: '10.24', change_pct: '2.20', volume: '41230000', amount: '420000000.00',
        t: '2026-11-02T10:31:00+08:00', data_status: 'fresh', data_as_of: '2026-11-02T10:31:00+08:00', gaps: [] }],
    };
    server.use(http.get(`${API}/quotes`, () => {
      n += 1;
      if (n === 1) return HttpResponse.json(ok);
      return HttpResponse.json({ error: { code: 'UPSTREAM_ERROR', message: '上游数据源返回错误', details: null, request_id: 'r' } }, { status: 502 });
    }));
    renderAt('/stocks/600000.SH');
    const head = await screen.findByTestId('stock-head', {}, { timeout: 8000 });
    // 先确认第一次成功渲染过价格与成交量
    await waitFor(() => expect(within(head).getByText('10.24')).toBeInTheDocument(), { timeout: 8000 });
    const volCell = () => within(head).queryByText(/手$/);
    expect(volCell()).not.toBeNull();
    // 轮询失败后（retry 用尽进入 error）：价格与派生值一并隐藏
    await waitFor(() => expect(within(head).queryByText('10.24')).toBeNull(), { timeout: 15_000 });
    expect(volCell()).toBeNull();
    expect(within(head).getByTestId('quote-error')).toBeInTheDocument();
  });
});

describe('④/strategy-instances：后端已注册、前端占位页', { timeout: 20_000 }, () => {
  beforeEach(() => mockLoginAs('demo_user'));
  it('渲染占位页，不请求 /strategy-instances（页面未接入，避免把未做页面伪装成可用）', async () => {
    const hits: string[] = [];
    server.events.on('request:start', ({ request }) => { if (new URL(request.url).pathname === `${API}/strategy-instances`) hits.push(request.url); });
    renderAt('/strategy-instances');
    const ph = await screen.findByTestId('placeholder', {}, { timeout: 8000 });
    expect(ph.textContent).toContain('页面骨架已就位');
    expect(ph.textContent).toContain('/strategy-instances');
    expect(document.querySelector('.error-box')).toBeNull();
    expect(hits).toEqual([]);
  });
});

describe('③补充：财务页签命中目标元素（非图表兜底）', { timeout: 20_000 }, () => {
  beforeEach(() => mockLoginAs('demo_user'));
  // 只拦财务子资源，详情与 K 线仍用 mock 正常数据（避免把整页拖垮，测的只是页签内判定）
  it('子资源 404 → 财务页签内出现「功能开发中」空态', async () => {
    server.use(http.get(`${API}/securities/:code/financials`, () => notFound()));
    // 不带 ?tab=：默认页签就是财务，避免 Tabs 预渲染时序影响
    renderAt('/stocks/600000.SH');
    const tab = await screen.findByTestId('tab-financials', {}, { timeout: 10_000 });
    const pending = await within(tab).findByTestId('route-pending', {}, { timeout: 8000 });
    expect(pending).toHaveTextContent(ROUTE_PENDING_TEXT);
    // 目标是财务页签内的空态，不是图表/其他页签的兜底
    expect(within(tab).queryByTestId('kline')).toBeNull();
  });

  it('子资源 404 带 superseded_by → 页签不吞，仍显示真实错误', async () => {
    server.use(http.get(`${API}/securities/:code/financials`, () => notFound({ superseded_by: '920094.BJ' })));
    renderAt('/stocks/600000.SH');
    const tab = await screen.findByTestId('tab-financials', {}, { timeout: 10_000 });
    await waitFor(() => expect(within(tab).queryByTestId('route-pending')).toBeNull(), { timeout: 8000 });
    expect(within(tab).getByRole('alert')).toHaveTextContent('加载失败');
  });
});
