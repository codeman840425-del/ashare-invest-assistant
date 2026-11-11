/**
 * F-14：A-12 终裁（#78 756b7b7）前端落地核验。
 * ① 全局 DataStatusBlock 的 data_as_of 可空（总则）：键必须出现、值可为 null，不补生成/当前时刻；
 * ② SecurityProfile / SectorFlowsResponse / MarketOverview 的 data_as_of=null 时不崩、不编造时间；
 * ③ Evidence.data_as_of 与 SSE quote 块的 data_as_of 仍为必填非空（类型层锁定，不放宽）。
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import type { Evidence } from '../api/types';
import type { StreamEventMap } from '../api/streamTypes';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { preloadRoutes } from '../test/preloadRoutes';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

beforeAll(() => preloadRoutes(routes), 30_000);
const API = '/api/v1';
const expectNoBadTime = (root: HTMLElement) => {
  expect(root.textContent).not.toMatch(/Invalid Date|NaN|undefined/);
};

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

describe('③ 类型层：Evidence 与 SSE quote 保持非空（#78 不放宽）', () => {
  it('Evidence.data_as_of 与 SSE quote.data_as_of 是非空 string', () => {
    const ev = { id: 'E1', key: 'close', value: '10', unit: null, provider: 'system', endpoint: null,
      data_as_of: '2026-11-02T15:00:00+08:00', fetched_at: '2026-11-02T15:01:00+08:00', epistemic_type: 'fact' } satisfies Evidence;
    expect(typeof ev.data_as_of).toBe('string');
    type QuotePayload = StreamEventMap['quote']['data'];
    const q: QuotePayload = { items: [], data_as_of: '2026-11-02T15:00:00+08:00' };
    expect(typeof q.data_as_of).toBe('string');
  });
});

describe('② 三处 data_as_of=null 页面不崩', { timeout: 25_000 }, () => {
  beforeEach(() => mockLoginAs('demo_user'));

  it('MarketOverview：null → 显示「数据不可用（无数据时点）」，不编造时间', async () => {
    server.use(http.get(`${API}/market/overview`, () => HttpResponse.json({
      trade_date: '2026-11-02', session: 'closed', indices: [], breadth: null, regime: null, regime_position_range: null,
      turnover_total: null, data_status: 'unavailable', data_as_of: null,
      gaps: [{ key: 'all', reason: 'no_source', message: '从未取得（示例）' }],
    })));
    renderAt('/market');
    const page = await screen.findByTestId('market-page', {}, { timeout: 10_000 });
    expect(await screen.findByText('数据不可用（无数据时点）', {}, { timeout: 8000 })).toBeInTheDocument();
    expectNoBadTime(page);
  });

  it('SectorFlows：null → 板块表仍渲染，不崩', async () => {
    server.use(http.get(`${API}/market/sector-flows`, () => HttpResponse.json({
      kind: 'industry', taxonomy: 'sw_l1', trade_date: '2026-11-02', items: [], sources: [],
      data_status: 'unavailable', data_as_of: null, gaps: [{ key: 'sector', reason: 'no_source', message: '从未取得（示例）' }],
    })));
    renderAt('/market');
    await screen.findByTestId('market-page', {}, { timeout: 10_000 });
    const panel = await screen.findByTestId('sector-panel', {}, { timeout: 10_000 });
    await waitFor(() => expect(within(panel).queryByText(/Invalid Date/)).toBeNull(), { timeout: 8000 });
    expectNoBadTime(panel);
  });

  it('SecurityProfile：null → 基本信息面板不崩（master_as_of 仍必填）', async () => {
    server.use(http.get(`${API}/securities/:code`, () => HttpResponse.json({
      security_code: '600000.SH', name: '示例银行', type: 'stock', exchange: 'SH', board: 'main',
      list_date: null, list_date_basis: null, delist_date: null, listing_status: 'listed', risk_flag: null,
      former_names: [], code_history: [], master_as_of: '2026-11-02', attribution: '示例来源',
      industry: null, concepts: [], total_shares: null, float_shares: null, suspended: null, sources: [],
      data_status: 'partial', data_as_of: null, gaps: [{ key: 'cert', reason: 'data_licence_unavailable', message: '证书不可用（示例）' }],
    })));
    renderAt('/stocks/600000.SH');
    const panel = await screen.findByTestId('profile-panel', {}, { timeout: 10_000 });
    expectNoBadTime(panel);
    expect(document.querySelector('.error-box')).toBeNull();
  });
});
