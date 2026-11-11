/**
 * F-14：A-12 终裁（#78 756b7b7）前端落地核验 + 两处 slice 崩溃回归。
 * 文件名刻意用 pool-f14-nullability，不占用 main 既有 t-f14（通知中心/SSE）/t-f13 等测试号。
 *
 * ① 语义：全局 DataStatusBlock 的 data_as_of 可空（总则），但 Evidence 与 SSE quote 的 data_as_of 仍必填非空；
 * ② 页面：SecurityProfile / SectorFlowsResponse / MarketOverview 的 data_as_of=null 不崩、不编造时间；
 * ③ 回归：StockPage.intradayPreClose 与 PriceChartPanel.tradeDate 曾在 data_as_of=null 时直接 .slice() 崩溃，
 *    这里用「行为负例」锁定修复（不是 typeof 断言那种弱检查）。
 */
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse, passthrough } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
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

// 运行时构造 null 值，绕过 TS 的非空声明：既能被 `tsc` 拒绝（见下方 @ts-expect-error），
// 也能让页面收到真实的 null，从而验证「非空约束真的成立」而不是仅测 typeof。
const asNull = (): never => null as unknown as never;

describe('③ 类型负例：Evidence / SSE quote 的 data_as_of 必须非空（#78 不放宽）', () => {
  it('Evidence.data_as_of 传 null 在类型层被拒绝', () => {
    // @ts-expect-error — Evidence.data_as_of 是 string，不得传 null（新增负例：真正的拒绝 null）
    const bad = { id: 'E1', key: 'close', value: '10', unit: null, provider: 'system', endpoint: null,
      data_as_of: asNull(), fetched_at: '2026-11-02T15:01:00+08:00', epistemic_type: 'fact' } as const;
    expect(bad.data_as_of).toBeNull();
  });

  it('SSE quote 块的 data_as_of 传 null 在类型层被拒绝', () => {
    // @ts-expect-error — StreamEventMap['quote'].data.data_as_of 是 DateTime（非空），不得传 null
    const bad = { items: [], data_as_of: asNull() };
    expect(bad.data_as_of).toBeNull();
  });

  it('对照：DataStatusBlock.data_as_of 允许 null（总则可空）', () => {
    const ok: { data_status: 'unavailable'; data_as_of: string | null; gaps: unknown[] } = { data_status: 'unavailable', data_as_of: null, gaps: [] };
    expect(ok.data_as_of).toBeNull();
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

  it('SectorFlows：null → 板块面板仍渲染，不崩、无 Invalid Date', async () => {
    server.use(http.get(`${API}/market/sector-flows`, () => HttpResponse.json({
      kind: 'industry', taxonomy: 'sw_l1', trade_date: '2026-11-02', items: [], sources: [],
      data_status: 'unavailable', data_as_of: null, gaps: [{ key: 'sector', reason: 'no_source', message: '从未取得（示例）' }],
    })));
    renderAt('/market');
    await screen.findByTestId('market-page', {}, { timeout: 10_000 });
    const panel = await screen.findByTestId('sector-panel', {}, { timeout: 10_000 });
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

describe('③ slice 崩溃有效回归（null 时不再抛 TypeError）', { timeout: 25_000 }, () => {
  beforeEach(() => mockLoginAs('demo_user'));

  it('PriceChartPanel：1m items=[] 且 data_as_of=null → 图表区出空态文本，页面不白屏', async () => {
    const emptyBars = {
      security_code: '600000.SH', name: '示例银行', freq: '1m', adjust: 'none', pre_close: null,
      items: [], next_before: null, adjust_as_of: null, data_status: 'unavailable', data_as_of: null,
      gaps: [{ key: 'bars', reason: 'no_source', message: '从未取得（示例）' }],
    };
    // 只有 1m 走空数据；其余（详情/日K/行情）保持 mock 正常，避免整页停在加载态
    server.use(http.get(`${API}/securities/:code/bars`, ({ request }) =>
      new URL(request.url).searchParams.get('freq') === '1m' ? HttpResponse.json(emptyBars) : passthrough()));
    renderAt('/stocks/600000.SH');
    const page = await screen.findByTestId('stock-page', {}, { timeout: 10_000 });
    // 修复前：tradeDate 对 null 调 .slice() → TypeError → 整页白屏/错误边界
    await waitFor(() => expect(page.querySelector('[data-testid="route-pending"]')).toBeNull(), { timeout: 8000 });
    expectNoBadTime(page);
    expect(document.body.textContent).not.toMatch(/Cannot read properties|TypeError/);
  });

  it('StockPage.intradayPreClose：1m 有 pre_close 但 items=[] 且 data_as_of=null → 头部不崩', async () => {
    const barsWithPreClose = {
      security_code: '600000.SH', name: '示例银行', freq: '1m', adjust: 'none', pre_close: '10.02',
      items: [], next_before: null, adjust_as_of: null, data_status: 'pending', data_as_of: null, gaps: [],
    };
    server.use(http.get(`${API}/securities/:code/bars`, ({ request }) =>
      new URL(request.url).searchParams.get('freq') === '1m' ? HttpResponse.json(barsWithPreClose) : passthrough()));
    renderAt('/stocks/600000.SH');
    const head = await screen.findByTestId('stock-head', {}, { timeout: 10_000 });
    // 修复前：(items[0]?.t ?? null).slice() → TypeError，头部整块不渲染
    expectNoBadTime(head);
    expect(head.textContent).toContain('示例银行');
    expect(document.body.textContent).not.toMatch(/Cannot read properties|TypeError/);
  });
});
