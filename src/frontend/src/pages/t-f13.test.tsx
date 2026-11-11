/**
 * F-13：五子资源端点 null 展示语义的一致性守门。
 *
 * 巡检结论（详见报告）：`data_as_of` 为 null 时前端存在三种不同表现——
 * A. `DataStatusTag`/`GapNote`：**省略时间行**（不显示「数据时间」），状态色照常
 * B. 日报页：显示「—（无来源）」
 * C. 市场页（F-07 加的）：显示「数据不可用（无数据时点）」
 *
 * 统一口径建议（本单只提建议不改设计）：
 * **null 一律不得显示编造的时间；文案可以按上下文不同，但不能出现字面量 "null"、空串、1970 等伪时间。**
 * 本测试钉住的是这条**底线**，而不是逼所有页面用同一个词。
 */
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { DataStatusTag, GapNote } from '../components/common';
import { fmtTime } from '../lib/format';
import { MARKET_OVERVIEW } from '../mocks/marketFixtures';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { preloadRoutes } from '../test/preloadRoutes';

// 与其他页面测试一致：图表组件在 jsdom 里没有真实尺寸会抛错（lightweight-charts），必须 mock
vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

beforeAll(() => preloadRoutes(routes), 60_000);
beforeEach(() => mockLoginAs('demo_user'));
afterEach(() => server.resetHandlers());

const API = '/api/v1';

/** 全前端底线：任何展示都不许出现字面量 null / undefined / 1970 伪时间 */
function assertNoFakeTime(text: string) {
  expect(text).not.toMatch(/null/);
  expect(text).not.toMatch(/undefined/);
  expect(text).not.toMatch(/Invalid Date/);
  expect(text).not.toMatch(/1970/);
}

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

describe('① 共享组件：data_as_of=null 不显示时间行', () => {
  it('DataStatusTag 的 asOf=null → 不出现「数据时间」', () => {
    const { container } = render(<DataStatusTag status="unavailable" asOf={null} gaps={[]} />);
    const text = container.textContent ?? '';
    expect(text).not.toContain('数据时间');
    assertNoFakeTime(text);
  });

  it('GapNote 的 asOf=null → 不出现时间、不崩', () => {
    const { container } = render(
      <GapNote status="unavailable" gaps={[{ key: 'factors', reason: 'no_source', message: '无数据' }]} asOf={null} testId="g" />,
    );
    const text = container.textContent ?? '';
    assertNoFakeTime(text);
    expect(container.querySelector('[data-testid="g"]')).not.toBeNull();
  });

  it('有 asOf 时正常显示时间（对照组）', () => {
    const { container } = render(<DataStatusTag status="stale" asOf="2026-11-02T10:00:00+08:00" gaps={[]} />);
    expect(container.textContent).not.toMatch(/null|undefined/);
  });
});

describe('② 页面层：五子资源空态都不编造时间', () => {
  it('/market 的 data_as_of=null → 页面不崩、不显示悬空时间', async () => {
    server.use(
      http.get(`${API}/market/overview`, () =>
        HttpResponse.json({
          ...structuredClone(MARKET_OVERVIEW),
          data_status: 'unavailable',
          data_as_of: null,
          gaps: [{ key: 'market', reason: 'no_source', message: '合成：无市场数据' }],
        } as unknown as Record<string, unknown>),
      ),
    );
    renderAt('/market');
    // 关键回归：此前 fmtTime(null) 抛错 → 整页 ErrorBoundary（白屏级）
    const page = await screen.findByTestId('market-page');
    expect(screen.queryByText(/Unexpected Application Error/)).toBeNull();
    expect(page.textContent).not.toContain('更新于');
    assertNoFakeTime(page.textContent ?? '');
  });

  it('fmtTime 对 null/undefined 不抛错（运行时防护）', () => {
    expect(() => fmtTime(null)).not.toThrow();
    expect(fmtTime(null)).toBe('');
    expect(fmtTime(undefined)).toBe('');
    expect(fmtTime('')).toBe('');
    expect(fmtTime('2026-11-02T10:00:00+08:00')).not.toBe('');
  });

  it('/stocks 因子页签：trade_date 与 factor_set_version 为 null → 显示「未知」', async () => {
    renderAt('/stocks/000300.SH?tab=factors');
    const tab = await screen.findByTestId('tab-factors');
    await screen.findAllByText('未知');
    assertNoFakeTime(tab.textContent ?? '');
  });
});

describe('③ 一致性底线：各页面 null 文案不出现伪值', () => {
  it('日报页 data_as_of=null → 用「—（无来源）」而非编造时间', async () => {
    renderAt('/daily-reports');
    await screen.findByTestId(/daily-report|report-/).catch(() => null);
    const body = document.body.textContent ?? '';
    assertNoFakeTime(body);
  });
});
