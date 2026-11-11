/** F-16: 路由级 /market smoke；依赖 #82 已冻结的空时点修复，不复制生产实现。 */
import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { MARKET_OVERVIEW } from '../mocks/marketFixtures';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { preloadRoutes } from '../test/preloadRoutes';

// 只替换 canvas 图表；路由、查询、MarketPage、状态和时点展示均走真实实现。
vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
beforeAll(() => preloadRoutes(routes), 30_000);
beforeEach(() => mockLoginAs('demo_user'));

const RESPONSE_NAME = 'F16 响应专属指数（合成）';

function renderScenario(path: string, asOf: string | null) {
  // 在渲染前注册，避免首次请求抢跑命中默认 mock。
  server.use(http.get('/api/v1/market/overview', () => HttpResponse.json({
    ...MARKET_OVERVIEW,
    data_as_of: asOf,
    indices: MARKET_OVERVIEW.indices.map((item, index) => ({
      ...item, name: index === 0 ? RESPONSE_NAME : item.name,
    })),
  })));
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const client = makeQueryClient(true);
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(<AppProviders client={client}><RouterProvider router={router} /></AppProviders>);
  return { ...view, client, router };
}

async function expectResponseRendered() {
  // 独有名称只在本次 overview 响应成功渲染后出现，不依赖加载态共用 testid。
  const strip = await screen.findByRole('list', { name: '主要指数' });
  expect(await within(strip).findByText(RESPONSE_NAME)).toBeInTheDocument();
  expect(within(strip).getAllByRole('listitem')).toHaveLength(MARKET_OVERVIEW.indices.length);
  const page = screen.getByTestId('market-page');
  expect(within(page).getByText('市场概览')).toBeInTheDocument();
  expect(within(page).getByText(MARKET_OVERVIEW.trade_date)).toBeInTheDocument();
  expect(within(page).getByTestId('index-chart')).toBeInTheDocument();
  expect(within(page).getByTestId('breadth-panel')).toHaveTextContent('涨跌分布');
  expect(within(page).getByTestId('regime-panel')).toHaveTextContent('参考仓位区间');
  expect(within(page).getByTestId('sector-panel')).toBeInTheDocument();
  return page;
}

describe('F-16 市场页时点 smoke（真实路由与查询，MSW 合成）', () => {
  it.each(['/market', '/market/overview'])('%s：null 时点响应渲染全部面板且不编造更新时间', async (path) => {
    const view = renderScenario(path, null);
    try {
      const page = await expectResponseRendered();
      const header = page.querySelector('.mk-head');
      expect(header).not.toBeNull();
      expect(header).toHaveTextContent('数据不可用（无数据时点）');
      expect(header).not.toHaveTextContent('更新于');
      expect(header).not.toHaveTextContent(/Invalid Date|undefined|NaN|更新于\s*null/);
      expect(view.router.state.location.pathname).toBe(path);
    } finally {
      view.unmount();
      view.client.clear();
    }
  });

  it.each([
    ['北京时间', '2026-11-02T15:30:00+08:00'],
    ['UTC', '2026-11-02T07:30:00Z'],
  ])('%s：有值时点保留并显示北京时间', async (_label, stamp) => {
    const view = renderScenario('/market', stamp);
    try {
      const page = await expectResponseRendered();
      const header = page.querySelector('.mk-head');
      expect(header).not.toBeNull();
      expect(header).toHaveTextContent('更新于 2026-11-02 15:30');
      expect(header).not.toHaveTextContent('数据不可用（无数据时点）');
    } finally {
      view.unmount();
      view.client.clear();
    }
  });
});
