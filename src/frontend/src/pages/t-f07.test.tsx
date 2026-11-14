/**
 * F-07：DataStatusBlock.data_as_of 可空收口（契约 T-A53：空数据场景时间戳为 null）。
 *
 * ① 类型层：null 与非 null 都能赋给 DataStatusBlock（编译期由 tsc 保证，这里在运行期再锁一次语义）。
 * ② 页面层：/market 空数据时不显示编造的时间，给「数据不可用」；有数据时正常显示「更新于 …」。
 */
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import type { DataStatusBlock } from '../api/types';
import { errorBody } from '../mocks/handlerUtils';
import { MARKET_OVERVIEW } from '../mocks/marketFixtures';
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

describe('① 类型层：data_as_of 可为 null', () => {
  it('null 与非 null 都可赋给 DataStatusBlock（TS2322 收口）', () => {
    const empty: DataStatusBlock = {
      data_status: 'unavailable',
      data_as_of: null,
      gaps: [{ key: 'financials', reason: 'no_source', message: '无数据' }],
    };
    const filled: DataStatusBlock = { data_status: 'fresh', data_as_of: '2026-11-02T15:00:00+08:00', gaps: [] };
    expect(empty.data_as_of).toBeNull();
    expect(filled.data_as_of).toBe('2026-11-02T15:00:00+08:00');
  });

  it('空数据块经过 JSON 往返后仍为 null（不变成 undefined 或空串）', () => {
    const block: DataStatusBlock = { data_status: 'unavailable', data_as_of: null, gaps: [] };
    const back = JSON.parse(JSON.stringify(block)) as DataStatusBlock;
    expect(back.data_as_of).toBeNull();
  });
});

/** 基于真实示例数据只改 data_as_of，避免手写字段缺失导致页面渲染不出 */
function marketBody(dataAsOf: string | null) {
  return {
    ...structuredClone(MARKET_OVERVIEW),
    data_status: dataAsOf ? 'fresh' : 'unavailable',
    data_as_of: dataAsOf,
    gaps: dataAsOf ? [] : [{ key: 'market', reason: 'no_source', message: '合成：无市场数据' }],
  } as unknown as Record<string, unknown>;
}

describe('② 页面层：空数据不编造时间', () => {
  it('data_as_of=null 时不出现「更新于」（空数据不显示编造时间）', async () => {
    server.use(http.get(`${API}/market/overview`, () => HttpResponse.json(marketBody(null))));
    renderAt('/market');
    // 先确认数据确实已渲染（出现空数据提示），再断言没有编造的时间
    expect(await screen.findByText('数据不可用（无数据时点）')).toBeInTheDocument();
    expect(screen.queryByText(/更新于/)).toBeNull();
  });

  it('data_as_of 有值 → 正常显示「更新于 …」', async () => {
    server.use(
      http.get(`${API}/market/overview`, () => HttpResponse.json(marketBody('2026-11-03T15:00:00+08:00'))),
    );
    renderAt('/market');
    // 等到真实数据渲染（容器在加载态就已存在，不能只等容器）
    expect(await screen.findByText(/更新于/)).toBeInTheDocument();
  });

  it('接口报错时走错误框，不白屏（与空数据区分）', async () => {
    server.use(
      http.get(`${API}/market/overview`, () => HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })),
    );
    renderAt('/market');
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});
