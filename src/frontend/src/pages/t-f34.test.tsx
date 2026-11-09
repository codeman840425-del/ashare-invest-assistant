/**
 * T-F34：终端/页面 API 层已验证问题的前端自查修复（只修已验证问题，不改设计）。
 * ① 空态与 API 行为一致：200 空列表 ≠ 错误（通知/提醒/候选信号/计划/策略/日报/研究候选）；
 * ② 入口与路由现状一致：后端已实现的 /strategies 为真实页；仍无路由的 /strategy-instances 保持占位页；
 * ③「功能开发中」口径回改：T-B100 已补 GET /securities/{code}，裸 404 = 证券不存在；
 *    个股子资源（bars/财务/资金流/因子/公告）路由仍未实现，404 仍按「功能开发中」展示（isStockSubPending）；
 * ④ 通知/提醒空态（T69/T70 API 已验）：0 条给空态文案，不报错。
 */
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { ApiError } from '../api/client';
import { isRoutePending, isStockSubPending, ROUTE_PENDING_TEXT } from '../api/errorPolicy';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { preloadRoutes } from '../test/preloadRoutes';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

beforeAll(() => preloadRoutes(routes), 30_000);
const API = '/api/v1';
const emptyPage = () => HttpResponse.json({ items: [], next_cursor: null });
const notFoundEnvelope = () => HttpResponse.json({ error: { code: 'NOT_FOUND', message: '资源不存在', details: null, request_id: 'r' } }, { status: 404 });

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

describe('② 入口与路由现状一致（新增判定的单元层）', () => {
  const e404 = (url: string) => new ApiError(404, 'NOT_FOUND', '资源不存在', null, null, url);
  it('详情路由已实现：/securities/{code} 的 404 不再判为“开发中”', () => {
    expect(isRoutePending(e404('/api/v1/securities/600000.SH'))).toBe(false);
    expect(isStockSubPending(e404('/api/v1/securities/600000.SH'))).toBe(false);
  });
  it('子资源路由仍未实现：bars/财务/资金流/因子/公告的 404 → 开发中', () => {
    for (const sub of ['bars', 'financials', 'fund-flows', 'factors', 'announcements']) {
      expect(isStockSubPending(e404(`/api/v1/securities/600000.SH/${sub}?freq=d`))).toBe(true);
    }
  });
  it('不误判：搜索、详情本身、500 错误、资源 409', () => {
    expect(isStockSubPending(e404('/api/v1/securities/search?q=600000'))).toBe(false);
    expect(isStockSubPending(e404('/api/v1/securities/600000.SH'))).toBe(false);
    expect(isStockSubPending(new ApiError(500, 'INTERNAL_ERROR', 'x', null, null, '/api/v1/securities/600000.SH/bars'))).toBe(false);
    // 通用判定新增的聚合端点仍受 account_id / security_code 排除约束
    expect(isRoutePending(e404('/api/v1/quotes?codes=600000.SH'))).toBe(true);
    expect(isRoutePending(e404('/api/v1/market/sector-flows?kind=industry'))).toBe(true);
  });
});

describe('① 空列表 ≠ 错误：200 items:[] 展示空态文案', { timeout: 20_000 }, () => {
  beforeEach(() => mockLoginAs('demo_user'));
  const lists = ['/notifications', '/alerts', '/candidate-signals', '/plans', '/strategies', '/daily-reports', '/candidates'];
  it.each(lists)('%s：接口返回空列表 → 不出现错误框', async (api) => {
    server.use(http.get(`${API}${api}`, emptyPage));
    renderAt(api);
    await waitFor(() => expect(document.querySelector('.error-box')).toBeNull(), { timeout: 8000 });
    await waitFor(() => expect(document.body.textContent).not.toMatch(/加载失败/), { timeout: 8000 });
  });
  it('通知空列表：显示「暂无通知」，未读为 0 时“全部标为已读”禁用', async () => {
    server.use(http.get(`${API}/notifications`, emptyPage), http.get(`${API}/notifications/unread-count`, () => HttpResponse.json({ count: 0 })));
    renderAt('/notifications');
    expect(await screen.findByTestId('nc-empty', {}, { timeout: 8000 })).toHaveTextContent('暂无通知');
    expect(screen.getByTestId('nc-read-all')).toBeDisabled();
    expect(document.querySelector('.error-box')).toBeNull();
  });
  it('提醒空列表：表格空态「没有符合条件的提醒」', async () => {
    server.use(http.get(`${API}/alerts`, emptyPage));
    renderAt('/alerts');
    expect(await screen.findByText('没有符合条件的提醒', {}, { timeout: 8000 })).toBeInTheDocument();
    expect(document.querySelector('.error-box')).toBeNull();
  });
});

describe('③ 详情页已补路由、子资源仍开发中', { timeout: 20_000 }, () => {
  beforeEach(() => mockLoginAs('demo_user'));
  it('裸 404 → 资源 404「未找到该证券」，不是「功能开发中」', async () => {
    server.use(http.get(`${API}/securities/:code`, notFoundEnvelope));
    renderAt('/stocks/999999.SH');
    expect(await screen.findByText('未找到该证券', {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.queryByTestId('route-pending')).toBeNull();
    expect(document.querySelector('.error-box')).toBeNull();
  });
  it('财务页签遇子资源 404 → 页面内展示「功能开发中」，不报错堆栈', async () => {
    server.use(http.get(`${API}/securities/:code/:sub`, notFoundEnvelope));
    renderAt('/stocks/600000.SH?tab=financials');
    const pending = await screen.findAllByTestId('route-pending', {}, { timeout: 8000 });
    expect(pending.some((el) => el.textContent?.includes(ROUTE_PENDING_TEXT))).toBe(true);
  });
});
