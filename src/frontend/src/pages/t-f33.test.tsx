/**
 * T-F33：搜索联动与已知问题展示。
 * ① 后端空结果 200 items:[] → 下拉显示「无匹配证券」空态（旧 404 口径不复存在；MSW 模拟 200 空列表与真后端一致，T-T32 T12）；
 * ② 命中高亮：代码/简称按输入高亮，拼音首字母命中在 matched_text（简称原文）上高亮；
 * ③ T13 详情页「功能开发中」：/securities/{code} 裸 404（信封或 FastAPI 默认体）→ 功能开发中空态，不白屏、不报错堆栈；
 *    北交所旧代码 404（details.superseded_by，契约 §7.3）仍是资源 404 原文案。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { ROUTE_PENDING_TEXT } from '../api/errorPolicy';
import { splitHighlight } from '../lib/searchText';
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

describe('① 空结果：200 items:[] → 空态文案（不是错误）', () => {
  beforeEach(() => mockLoginAs('demo_user'));
  it('搜索无匹配 → 下拉显示「无匹配证券」，不显示错误文案', async () => {
    server.use(http.get(`${API}/securities/search`, () => HttpResponse.json({ items: [], master_as_of: '2026-11-06' })));
    renderAt('/terminal');
    await screen.findByTestId('terminal');
    fireEvent.change(screen.getByLabelText('证券搜索'), { target: { value: '不存在的证券' } });
    const status = await screen.findByTestId('search-status', {}, { timeout: 3000 });
    expect(status).toHaveTextContent('无匹配证券');
    expect(status).not.toHaveTextContent(/加载失败|不存在/);
  });
});

describe('② 命中高亮', () => {
  beforeEach(() => mockLoginAs('demo_user'));
  const type = async (v: string) => {
    await screen.findByTestId('terminal');
    fireEvent.change(screen.getByLabelText('证券搜索'), { target: { value: v } });
  };

  it('代码前缀：60000 → 600000.SH 的「60000」被高亮', async () => {
    renderAt('/terminal');
    await type('60000');
    const opt = await screen.findByTestId('search-hit-600000.SH', {}, { timeout: 3000 });
    const marks = opt.querySelectorAll('mark.search-hl');
    expect(marks.length).toBeGreaterThan(0);
    expect(marks[0].textContent).toBe('60000');
  });
  it('简称包含：示例 → 简称「示例银行」的「示例」被高亮', async () => {
    renderAt('/terminal');
    await type('示例');
    const opt = await screen.findByTestId('search-hit-600000.SH', {}, { timeout: 3000 });
    const marks = opt.querySelectorAll('mark.search-hl');
    expect(marks.length).toBeGreaterThan(0);
    expect(marks[0].textContent).toBe('示例');
  });
  it('拼音首字母（initials_exact）：YHKJ → 命中演示科技，简称原文高亮，match_kind=initials_exact', async () => {
    renderAt('/terminal');
    await type('YHKJ');
    const opt = await screen.findByTestId('search-hit-000001.SZ', {}, { timeout: 3000 });
    expect(opt).toHaveAttribute('data-match', 'initials_exact');
    const matched = opt.querySelector('[data-testid="search-matched-000001.SZ"]');
    expect(matched).toHaveTextContent('拼音首字母：演示科技');
    const marks = opt.querySelectorAll('mark.search-hl');
    // 简称里没有 YHKJ 子串，matched_text 也没有——首字母命中不高亮简称（区别于代码/简称命中）
    expect(marks.length).toBe(0);
  });
  it('拼音首字母前缀（initials_prefix）：YS → 命中示例银行（首字母 YSYH）', async () => {
    renderAt('/terminal');
    await type('YS');
    const opt = await screen.findByTestId('search-hit-600000.SH', {}, { timeout: 3000 });
    expect(opt).toHaveAttribute('data-match', 'initials_prefix');
    expect(opt.querySelector('[data-testid="search-matched-600000.SH"]')).toHaveTextContent('拼音首字母：示例银行');
  });
  it('曾用名：SLFZ → matched_text「示例发展」无高亮、简称不误高亮', async () => {
    renderAt('/terminal');
    await type('SLFZ');
    const opt = await screen.findByTestId('search-hit-600000.SH', {}, { timeout: 3000 });
    expect(opt.querySelector('[data-testid="search-matched-600000.SH"]')).toHaveTextContent('曾用名：示例发展');
  });
  it('splitHighlight：大小写不敏感；未命中返回 null', () => {
    expect(splitHighlight('600000.SH', '60000')).toEqual(['', '60000', '0.SH']);
    expect(splitHighlight('示例银行', '银行')).toEqual(['示例', '银行', '']);
    expect(splitHighlight('600000.SH', '60000'.toLowerCase())).toEqual(['', '60000', '0.SH']);
    expect(splitHighlight('abc', 'xyz')).toBeNull();
    expect(splitHighlight('abc', '')).toBeNull();
  });
});

describe('③ T13 详情页：路由未实现 404 → 「功能开发中」，不白屏', () => {
  beforeEach(() => mockLoginAs('demo_user'));
  const bare404 = (shape: 'envelope' | 'fastapi') =>
    shape === 'envelope'
      ? HttpResponse.json({ error: { code: 'NOT_FOUND', message: '资源不存在', details: null, request_id: 'r' } }, { status: 404 })
      : HttpResponse.json({ detail: 'Not Found' }, { status: 404 });

  it.each([[['envelope']], [['fastapi']]] as const)('裸 404（%s）→ route-pending 空态，保留代码，无报错堆栈', async (shape) => {
    server.use(http.get(`${API}/securities/:code`, () => bare404(shape[0] as 'envelope' | 'fastapi')));
    renderAt('/stocks/600000.SH');
    const el = await screen.findByTestId('route-pending', {}, { timeout: 5000 });
    expect(el).toHaveTextContent(ROUTE_PENDING_TEXT);
    expect(screen.getByTestId('stock-page')).toBeInTheDocument(); // 不白屏
    expect(document.querySelector('.error-box')).toBeNull(); // 不显示错误框/堆栈
  });

  it('北交所旧代码 404（details.superseded_by）→ 仍是资源 404 原文案', async () => {
    server.use(http.get(`${API}/securities/:code`, () =>
      HttpResponse.json({ error: { code: 'NOT_FOUND', message: '资源不存在', details: { superseded_by: '920094.BJ' }, request_id: 'r' } }, { status: 404 })));
    renderAt('/stocks/430010.BJ');
    expect(await screen.findByText('未找到该证券')).toBeInTheDocument();
    expect(await screen.findByText('920094.BJ')).toBeInTheDocument();
    expect(screen.queryByTestId('route-pending')).toBeNull();
  });

  it('500 等其他错误 → 仍走 ErrorBox，不改判', async () => {
    server.use(http.get(`${API}/securities/:code`, () =>
      HttpResponse.json({ error: { code: 'INTERNAL_ERROR', message: '服务器内部错误', details: null, request_id: 'r' } }, { status: 500 })));
    renderAt('/stocks/600000.SH');
    await waitFor(() => expect(document.querySelector('.error-box')).not.toBeNull());
    expect(screen.queryByTestId('route-pending')).toBeNull();
  });

  it('mock 正常档案（/stocks/600000.SH 默认）不受影响', async () => {
    renderAt('/stocks/600000.SH');
    expect(await screen.findByTestId('stock-head', {}, { timeout: 5000 })).toBeInTheDocument();
  });
});
