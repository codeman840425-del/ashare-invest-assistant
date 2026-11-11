/**
 * F-10：factors / ETF 空态前端同步（T-A158 裁定）。
 * ① trade_date / factor_set_version 可空：null 显示「—」，不编造日期与版本号；
 * ② ETF 空态 gap=not_applicable、指数空态 gap=no_source，两者都是 200 + 空 items，不是错误；
 * ③ 请求带 ?trade_date= 时原样透传（空态也一样）。
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import type { FactorsResponse } from '../api/marketTypes';
import { NOT_APPLICABLE_TEXT } from '../lib/dataGaps';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { preloadRoutes } from '../test/preloadRoutes';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

beforeAll(() => preloadRoutes(routes), 30_000);
const API = '/api/v1';

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

const emptyFactors = (over: Partial<FactorsResponse>): FactorsResponse => ({
  security_code: '510300.SH', name: '示例沪深300ETF', trade_date: null, factor_set_version: null,
  counts: { total: 0, by_category: {} }, items: [], sources: [], data_status: 'unavailable',
  data_as_of: '2026-10-30T18:30:00+08:00', gaps: [], ...over,
} as FactorsResponse);

describe('① mock：两字段可空（T-A158 ① ②）', { timeout: 20_000 }, () => {
  beforeEach(() => mockLoginAs('demo_user'));
  const get = async (code: string, qs = '') => {
    const r = await fetch(`${API}/securities/${code}/factors${qs}`);
    return (await r.json()) as FactorsResponse;
  };

  it('ETF：trade_date / factor_set_version 均为 null，gap=not_applicable', async () => {
    const f = await get('510300.SH');
    expect(f.trade_date).toBeNull();
    expect(f.factor_set_version).toBeNull();
    expect(f.items).toEqual([]);
    expect(f.counts).toEqual({ total: 0, by_category: {} });
    expect(f.data_status).toBe('unavailable');
    expect(f.gaps.map((g) => g.reason)).toEqual(['not_applicable']);
  });

  it('指数：同形但 gap=no_source，两字段同样为 null', async () => {
    const f = await get('000300.SH');
    expect(f.trade_date).toBeNull();
    expect(f.factor_set_version).toBeNull();
    expect(f.gaps.map((g) => g.reason)).toEqual(['no_source']);
  });

  it('ETF 带 ?trade_date= → 原样透传请求值，其余仍为 null/空', async () => {
    const f = await get('510300.SH', '?trade_date=2026-10-28');
    expect(f.trade_date).toBe('2026-10-28');
    expect(f.factor_set_version).toBeNull();
    expect(f.items).toEqual([]);
  });

  it('股票正常：仍给真实批次日期与版本号，不被空态口径污染', async () => {
    const f = await get('600000.SH');
    expect(f.trade_date).toBe('2026-10-30');
    expect(f.factor_set_version).toBe('mr-factors-85（示例）');
    expect(f.items.length).toBeGreaterThan(0);
  });
});

describe('② 页面：空态与「—」文案', { timeout: 20_000 }, () => {
  beforeEach(() => mockLoginAs('demo_user'));

  it('ETF 因子页签：not_applicable 空态，截面日/因子集显示「—」', async () => {
    renderAt('/stocks/510300.SH?tab=factors');
    const tab = await screen.findByTestId('tab-factors', {}, { timeout: 10_000 });
    expect(await within(tab).findByTestId('factor-empty', {}, { timeout: 8000 })).toHaveTextContent(NOT_APPLICABLE_TEXT);
    const meta = within(tab).getByTestId('factor-meta');
    expect(meta).toHaveTextContent('截面日 —');
    expect(meta).toHaveTextContent('因子集 —');
    expect(tab.textContent).not.toMatch(/mr-factors|synthetic-factors/);
    expect(document.querySelector('.error-box')).toBeNull();
  });

  it('指数因子页签：no_source 空态，不显示「暂无因子数据」以外的编造日期', async () => {
    renderAt('/stocks/000300.SH?tab=factors');
    const tab = await screen.findByTestId('tab-factors', {}, { timeout: 10_000 });
    await waitFor(() => expect(within(tab).getByTestId('factor-meta')).toHaveTextContent('因子集 —'), { timeout: 8000 });
    expect(document.querySelector('.error-box')).toBeNull();
  });

  it('后端返回 null 两字段（模拟后端 PR 形态）→ 页面同样显示「—」，不崩', async () => {
    server.use(http.get(`${API}/securities/:code/factors`, () =>
      HttpResponse.json(emptyFactors({ security_code: '600000.SH', name: '示例银行', gaps: [{ key: 'factors', reason: 'no_source', message: '暂无批次' }] }))));
    renderAt('/stocks/600000.SH?tab=factors');
    const tab = await screen.findByTestId('tab-factors', {}, { timeout: 10_000 });
    const meta = await within(tab).findByTestId('factor-meta', {}, { timeout: 8000 });
    expect(meta).toHaveTextContent('截面日 —');
    expect(meta).toHaveTextContent('共 0 个');
  });
});
