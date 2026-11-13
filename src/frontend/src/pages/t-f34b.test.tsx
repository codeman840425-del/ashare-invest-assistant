/**
 * T-F34b：错误口径的定点用例（在 origin/main 基线上重建）
 *
 * ① 首导未完成：后端 500 INTERNAL_ERROR + details.issue=security_master_bootstrap_required
 *    （T-B94 单内裁定、plan §4.6.6）→ 前端给可理解的提示，不是通用“服务暂时不可用”。
 * ② 北交所旧代码 404 带 details.superseded_by（契约 §7.3）→ 提示改用新代码，不被当“开发中”吞掉。
 * ③ 个股子资源显式清单：清单内未实现路由 404 → “功能开发中”；未登记的同类路径 404 不被吞。
 * ④ ErrorBox 对普通错误的文案不变（回归保护）。
 *
 * 用例前提说明（T-F34b 重建项）：页签内空态只能在页签可渲染时断言，接口整体 404 时应断页面级，
 * 本轮据此把原两条财务页签用例改为页面级断言。
 */
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { ErrorBox } from '../components/common';
import { ApiError } from '../api/client';
import {
  BOOTSTRAP_REQUIRED_ISSUE,
  isBootstrapRequired,
  isRoutePending,
  isStockSubPending,
  isSuperseded,
} from '../api/errorPolicy';
import { errorBody } from '../mocks/handlerUtils';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { preloadRoutes } from '../test/preloadRoutes';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

beforeAll(() => preloadRoutes(routes), 60_000);
beforeEach(() => mockLoginAs('demo_user'));
afterEach(() => server.resetHandlers());

const API = '/api/v1';

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders client={makeQueryClient(true)}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}

/** 构造 ApiError，用于纯判定函数与 ErrorBox 直测（client.ts 的构造签名为位置参数） */
function apiError(status: number, code: string, details: Record<string, unknown> | null, url: string | null = `${API}/securities/920000.BJ`) {
  return new ApiError(status, code, 'm', details, 'r', url);
}

describe('① 首导未完成（bootstrap required）', () => {
  it('判定：500 + details.issue=security_master_bootstrap_required 才命中，其它 500 不命中', () => {
    expect(isBootstrapRequired(apiError(500, 'INTERNAL_ERROR', { issue: BOOTSTRAP_REQUIRED_ISSUE }))).toBe(true);
    expect(isBootstrapRequired(apiError(500, 'INTERNAL_ERROR', { issue: 'other' }))).toBe(false);
    expect(isBootstrapRequired(apiError(500, 'INTERNAL_ERROR', null))).toBe(false);
    expect(isBootstrapRequired(apiError(503, 'SERVICE_UNAVAILABLE', { issue: BOOTSTRAP_REQUIRED_ISSUE }))).toBe(false);
  });

  it('ErrorBox 显示首导未完成的可理解文案，且不显示通用“服务暂时不可用”', () => {
    render(<ErrorBox error={apiError(500, 'INTERNAL_ERROR', { issue: BOOTSTRAP_REQUIRED_ISSUE })} />);
    const box = screen.getByRole('alert');
    expect(box).toHaveTextContent('证券主数据尚未完成首次导入');
    expect(box).toHaveTextContent('联系管理员');
    expect(box).not.toHaveTextContent('服务暂时不可用');
    expect(box).toHaveAttribute('data-code', BOOTSTRAP_REQUIRED_ISSUE);
  });

  it('页面级：详情接口返回 bootstrap 500 → 个股页给出首导提示，不白屏', async () => {
    server.use(
      http.get(`${API}/securities/:code`, () =>
        HttpResponse.json(errorBody('INTERNAL_ERROR', '资源不存在', { issue: BOOTSTRAP_REQUIRED_ISSUE }), { status: 500 }),
      ),
    );
    renderAt('/stocks/600000.SH');
    expect(await screen.findByText(/证券主数据尚未完成首次导入/)).toBeInTheDocument();
    expect(screen.queryByTestId('route-pending')).toBeNull();
  });
});

describe('② 北交所旧代码 superseded_by（真实资源 404 优先）', () => {
  it('判定：404 + details.superseded_by 非空才算 superseded；空串/非 404 不算', () => {
    expect(isSuperseded(apiError(404, 'NOT_FOUND', { superseded_by: '920001.BJ' }))).toBe(true);
    expect(isSuperseded(apiError(404, 'NOT_FOUND', { superseded_by: '' }))).toBe(false);
    expect(isSuperseded(apiError(404, 'NOT_FOUND', null))).toBe(false);
    expect(isSuperseded(apiError(400, 'VALIDATION_ERROR', { superseded_by: '920001.BJ' }))).toBe(false);
  });

  it('ErrorBox 优先显示“已停用·改用新代码”，即使路径同时在开发中清单里', () => {
    render(<ErrorBox error={apiError(404, 'NOT_FOUND', { superseded_by: '920001.BJ' }, `${API}/securities/920000.BJ/bars`)} />);
    expect(screen.queryByTestId('route-pending')).toBeNull();
    expect(screen.getByRole('alert')).toHaveTextContent('920001.BJ');
  });

  it('页面级：详情 404 带 superseded_by → 提示改用新代码，不显示“功能开发中”', async () => {
    server.use(
      http.get(`${API}/securities/:code`, () =>
        HttpResponse.json(errorBody('NOT_FOUND', '证券不存在', { superseded_by: '920001.BJ' }), { status: 404 }),
      ),
    );
    renderAt('/stocks/920000.BJ');
    expect(await screen.findByText(/已停用，请改用/)).toBeInTheDocument();
    expect(screen.getByText('920001.BJ')).toBeInTheDocument();
    expect(screen.queryByTestId('route-pending')).toBeNull();
  });
});

describe('③ 个股子资源显式清单', () => {
  it('五个已注册子资源的真实 404 均不命中“开发中”', () => {
    for (const sub of ['bars', 'financials', 'fund-flows', 'factors', 'announcements']) {
      expect(isStockSubPending(apiError(404, 'NOT_FOUND', null, `${API}/securities/600000.SH/${sub}`))).toBe(false);
    }
    // 未登记：后端将来实现了就会真 404，不能被吞
    expect(isStockSubPending(apiError(404, 'NOT_FOUND', null, `${API}/securities/600000.SH/unknown-sub`))).toBe(false);
    // 详情本身不是子资源
    expect(isStockSubPending(apiError(404, 'NOT_FOUND', null, `${API}/securities/600000.SH`))).toBe(false);
    // 非 404 不命中
    expect(isStockSubPending(apiError(500, 'INTERNAL_ERROR', null, `${API}/securities/600000.SH/bars`))).toBe(false);
  });

  it('ErrorBox：已注册 bars 与财务子资源都显示真实资源错误', () => {
    const { unmount } = render(<ErrorBox error={apiError(404, 'NOT_FOUND', null, `${API}/securities/600000.SH/bars`)} />);
    expect(screen.queryByTestId('route-pending')).toBeNull();
    expect(screen.getByRole('alert')).toHaveTextContent('内容不存在或已删除');
    unmount();
    render(<ErrorBox error={apiError(404, 'NOT_FOUND', null, `${API}/securities/600000.SH/financials`)} />);
    expect(screen.queryByTestId('route-pending')).toBeNull();
    expect(screen.getByRole('alert')).toHaveTextContent('内容不存在或已删除');
  });

  it('页面级：已注册财务接口的真实 404 显示资源错误，不吞成开发中', async () => {
    server.use(
      http.get(`${API}/securities/:code/financials`, () => HttpResponse.json(errorBody('NOT_FOUND', '资源不存在'), { status: 404 })),
    );
    renderAt('/stocks/600000.SH?tab=financials');
    expect(await screen.findByRole('alert')).toHaveTextContent('内容不存在或已删除');
    expect(screen.queryByTestId('route-pending')).toBeNull();
  });
});

describe('④ 回归保护', () => {
  it('普通 500 仍走通用文案（不被 bootstrap 分支影响）', async () => {
    render(<ErrorBox error={apiError(500, 'INTERNAL_ERROR', null)} />);
    const box = screen.getByRole('alert');
    expect(box).toHaveTextContent('服务内部错误，请稍后重试');
    expect(box).not.toHaveTextContent('首次导入');
  });

  it('开发中清单（ROUTE_PENDING_PATHS）判定不受子资源逻辑影响', () => {
    expect(isRoutePending(apiError(404, 'NOT_FOUND', null, `${API}/strategies`))).toBe(true);
    expect(isStockSubPending(apiError(404, 'NOT_FOUND', null, `${API}/strategies`))).toBe(false);
  });
});
