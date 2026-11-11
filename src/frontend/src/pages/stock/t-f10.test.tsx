/**
 * F-10：factors 前端消费对接后端 T-A158 空态裁定。
 *
 * 裁定要点（架构师 T-A158）：`trade_date` 请求合法值原样透传、无批次为 null；
 * `factor_set_version` 无真实版本时 null，**合成版本禁入生产响应**；
 * ETF 用 `not_applicable`、指数/无数据用 `no_source`。
 *
 * 前端守则：两个字段为 null 时如实显示「未知」，**不得用常量兜底**（否则等于伪造因子集版本）。
 */
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { routes } from '../../app/routes';
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

async function getFactors(path: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${window.location.origin}${API}${path}`);
  return (await res.json()) as Record<string, unknown>;
}

describe('① 指数：无源空态（no_source），两字段为 null', () => {
  it('trade_date 与 factor_set_version 均为 null，不下发合成版本名', async () => {
    const body = await getFactors('/securities/000300.SH/factors');
    expect(body.trade_date).toBeNull();
    expect(body.factor_set_version).toBeNull();
    expect(body.items).toEqual([]);
    const gaps = body.gaps as { key: string; reason: string }[];
    expect(gaps.some((g) => g.key === 'factors' && g.reason === 'no_source')).toBe(true);
    // data_as_of 的可空化属于 F-07（#54），本分支未叠加，故此处不断言 null
  });
});

describe('② ETF：not_applicable 空态，两字段为 null', () => {
  it('gap 为 not_applicable，且不含任何合成版本名', async () => {
    const body = await getFactors('/securities/510300.SH/factors');
    expect(body.trade_date).toBeNull();
    expect(body.factor_set_version).toBeNull();
    const gaps = body.gaps as { key: string; reason: string }[];
    expect(gaps.some((g) => g.reason === 'not_applicable')).toBe(true);
    // 不得出现「（示例）」这类合成版本串
    expect(JSON.stringify(body)).not.toContain('mr-factors');
  });
});

describe('③ 页面层：null 时显示「未知」，不拿常量兜底', () => {
  it('指数因子页签显示「未知」而不是编造的截面日/因子集', async () => {
    renderAt('/stocks/000300.SH?tab=factors');
    await screen.findByTestId('tab-factors');
    await waitFor(() => expect(screen.getByTestId('tab-factors').textContent).toMatch(/截面日/));
    const text = screen.getByTestId('tab-factors').textContent ?? '';
    expect(text).toMatch(/未知/);
    // 关键：不得把 null 拼成 "null" 或空白
    expect(text).not.toMatch(/截面日 null/);
    expect(text).not.toMatch(/因子集 null/);
  });

  it('有因子数据时不显示「未知」（对照组）', async () => {
    server.use(
      http.get(`${API}/securities/:code/factors`, () =>
        HttpResponse.json({
          security_code: '600000.SH', name: '示例银行',
          trade_date: '2026-10-30', factor_set_version: 'real-factors-v1',
          counts: { total: 1, by_category: {} },
          items: [{ factor_id: 'f.ma20', feature_key: null, name: '20日均线偏离', category: 'technical', value: '0.10', unit: 'pct', market_rank: 100, market_rank_pct: '50.00' }],
          sources: [], data_status: 'fresh', data_as_of: '2026-10-30T18:30:00+08:00', gaps: [],
        }),
      ),
    );
    renderAt('/stocks/600000.SH?tab=factors');
    await screen.findByTestId('tab-factors');
    await waitFor(() => expect(screen.getByTestId('tab-factors').textContent).toContain('real-factors-v1'));
    expect(screen.getByTestId('tab-factors').textContent).not.toMatch(/截面日 未知/);
  });
});
