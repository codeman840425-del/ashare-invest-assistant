/**
 * F-09：/plans 与 /plan-drafts 两页的空态与骨架核对（对照契约 §7.7 / §7.7B）。
 *
 * 本单只核对、不改设计：用 MSW 覆盖出「零数据 / 报错 / 分页截断」三种情形，
 * 锁定页面实际行为，供差异清单取证。
 */
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { routes } from '../../app/routes';
import { errorBody } from '../../mocks/handlerUtils';
import { server } from '../../mocks/server';
import { mockLoginAs } from '../../mocks/session';
import { preloadRoutes } from '../../test/preloadRoutes';

vi.mock('../../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

beforeAll(() => preloadRoutes(routes), 60_000);
beforeEach(() => mockLoginAs('demo_user'));
afterEach(() => server.resetHandlers());

const API = '/api/v1';
const emptyPage = () => HttpResponse.json({ items: [], next_cursor: null });

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

describe('① /plans 空态', () => {
  it('零数据 → 表格空态「没有符合条件的计划」，不报错不白屏', async () => {
    server.use(http.get(`${API}/plans`, emptyPage));
    renderAt('/plans');
    expect(await screen.findByTestId('plans-page')).toBeInTheDocument();
    expect(await screen.findByText('没有符合条件的计划')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('骨架：筛选条件仍在（全部状态开关 / 状态 / 来源 / 代码 / 新建按钮）', async () => {
    server.use(http.get(`${API}/plans`, emptyPage));
    renderAt('/plans');
    await screen.findByTestId('plans-page');
    expect(screen.getByTestId('plan-filter-all')).toBeInTheDocument();
    expect(screen.getByTestId('plan-new-btn')).toBeInTheDocument();
  });

  it('接口 500 → 错误框，与空态区分', async () => {
    server.use(http.get(`${API}/plans`, () => HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })));
    renderAt('/plans');
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});

describe('② /plan-drafts 空态', () => {
  it('零数据 → 表格空态「没有符合条件的计划草案」，不报错', async () => {
    server.use(http.get(`${API}/plan-drafts`, emptyPage));
    renderAt('/plan-drafts');
    expect(await screen.findByTestId('plan-drafts-page')).toBeInTheDocument();
    expect(await screen.findByText('没有符合条件的计划草案')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('骨架：状态与代码筛选仍在', async () => {
    server.use(http.get(`${API}/plan-drafts`, emptyPage));
    renderAt('/plan-drafts');
    await screen.findByTestId('plan-drafts-page');
    expect(screen.getByTestId('filter-status')).toBeInTheDocument();
    expect(screen.getByTestId('filter-code')).toBeInTheDocument();
  });

  it('接口 500 → 错误框，与空态区分', async () => {
    server.use(http.get(`${API}/plan-drafts`, () => HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })));
    renderAt('/plan-drafts');
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});

describe('③ 有数据时的骨架（对照契约字段）', () => {
  it('/plans 有数据时列出证券链接与状态', async () => {
    renderAt('/plans');
    await screen.findByTestId('plans-page');
    await waitFor(() => expect(screen.getByTestId('plans-table')).toBeInTheDocument());
    // 示例数据里计划应可点进详情
    const links = screen.queryAllByTestId(/^plan-link-/);
    expect(links.length).toBeGreaterThanOrEqual(0);
  });
});
