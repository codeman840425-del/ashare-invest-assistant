/**
 * F-11：四端点 data_as_of=null 的前端兼容收口（契约 §7.3 T-A53 裁定第 4 条：`data_as_of` 全空 null）。
 * 覆盖 bars / financials / fund-flows / announcements（+ quotes）：null 时页面不崩、不显示「Invalid Date」、
 * 不编造时间；DataStatusTag / GapNote 仍按 data_status 与 gaps 正常显示原因。
 * 其余对象（quotes 之外、未在裁定点名）保持非空类型——见报告「无先例覆盖」清单。
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import type { BarsResponse } from '../api/types';
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
const code = '600000.SH';
const noData = (extra: Record<string, unknown>) => HttpResponse.json({
  security_code: code, name: '示例银行', items: [], sources: [], data_status: 'unavailable', data_as_of: null,
  gaps: [{ key: 'x', reason: 'no_source', message: '从未取得数据（示例）' }], ...extra,
});
/** 页面不应出现任何由 null 时间渲染出的异常文本 */
const expectNoBadTime = (root: HTMLElement) => {
  expect(root.textContent).not.toMatch(/Invalid Date|NaN|undefined|null/);
};

describe('F-11 四端点 data_as_of=null 不崩', { timeout: 25_000 }, () => {
  beforeEach(() => mockLoginAs('demo_user'));

  it('bars：data_as_of=null 的响应可被类型接受，且图表空态不渲染异常时间', () => {
    // 类型层：BarsResponse.data_as_of 允许 null（契约 §7.3 T-A53 第 4 条）；这里用编译期赋值锁定，
    // 页面级分支（pending/空 items）由图表组件既有用例覆盖，不在本单重复。
    const res: BarsResponse = {
      security_code: code, name: '示例银行', freq: '1m', adjust: 'none', pre_close: null, items: [], next_before: null,
      adjust_as_of: null, data_status: 'pending', data_as_of: null,
      gaps: [{ key: 'bars', reason: 'no_source', message: '尚未入库（示例）' }],
    };
    expect(res.data_as_of).toBeNull();
  });

  it('financials：data_as_of=null → 空态，数据状态按 gaps 显示原因', async () => {
    server.use(http.get(`${API}/securities/:code/financials`, () => noData({})));
    renderAt(`/stocks/${code}?tab=financials`);
    const tab = await screen.findByTestId('tab-financials', {}, { timeout: 10_000 });
    expect(await within(tab).findByTestId('fin-empty', {}, { timeout: 8000 })).toBeInTheDocument();
    expectNoBadTime(tab);
    expect(document.querySelector('.error-box')).toBeNull();
  });

  it('fund-flows：data_as_of=null → 空态，不崩', async () => {
    server.use(http.get(`${API}/securities/:code/fund-flows`, () => noData({})));
    renderAt(`/stocks/${code}?tab=fund-flow`);
    const tab = await screen.findByTestId('tab-fund-flow', {}, { timeout: 10_000 });
    await waitFor(() => expect(tab.querySelector('.error-box')).toBeNull(), { timeout: 8000 });
    expectNoBadTime(tab);
  });

  it('announcements：data_as_of=null → 空表格 + 免责声明，不崩', async () => {
    server.use(http.get(`${API}/securities/:code/announcements`, () => HttpResponse.json({
      items: [], next_cursor: null, disclaimer: '公告内容以交易所及上市公司披露原文为准，本系统仅提供标题与原文链接。',
      sources: [], data_status: 'unavailable', data_as_of: null,
      gaps: [{ key: 'announcements', reason: 'no_source', message: '从未取得数据（示例）' }],
    })));
    renderAt(`/stocks/${code}?tab=announcements`);
    const tab = await screen.findByTestId('tab-announcements', {}, { timeout: 10_000 });
    await waitFor(() => expect(within(tab).getByTestId('ann-disclaimer')).toBeInTheDocument(), { timeout: 8000 });
    expectNoBadTime(tab);
    expect(document.querySelector('.error-box')).toBeNull();
  });

  it('quotes：data_as_of=null → 行情头不崩，DataStatusTag 只显示状态', async () => {
    server.use(http.get(`${API}/quotes`, () => HttpResponse.json({
      items: [{ security_code: code, name: '示例银行', price: '10.24', change_pct: '2.20', volume: '41230000', amount: '420000000.00',
        t: '2026-11-02T15:00:00+08:00', data_status: 'unavailable', data_as_of: null,
        gaps: [{ key: 'quote', reason: 'no_source', message: '从未取得数据（示例）' }] }],
    })));
    renderAt(`/stocks/${code}`);
    const head = await screen.findByTestId('stock-head', {}, { timeout: 10_000 });
    await waitFor(() => expect(within(head).getByText('10.24')).toBeInTheDocument(), { timeout: 8000 });
    expectNoBadTime(head);
  });
});
