/**
 * T-F26：证券搜索显示曾用名命中与 quote_missing（契约 v0.2.9 内 T-A04 #33 ②，SecurityHit；§9 v0.2.9 验收 3、5、7），
 * 以及 #41：搜索不缓存（staleTime 0、不写本地存储）、429 按 retry_after_s 暂停、输入防抖 250 ms；网关 414。
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import type { SecurityHit } from '../api/marketTypes';
import { uid } from '../mocks/fixtures';
import { deleteLicence, resetLicences, setMockLicence } from '../mocks/licenceStore';
import { VENDOR_UNKNOWN_CODE, openQuoteMissingFor } from '../mocks/reconMock';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { searchErrorText, QUOTE_MISSING_TEXT } from '../lib/searchText';
import { ApiError } from '../api/client';
import { searchQLength } from '../api/marketQueries';
import { apiFetch } from '../test/apiFetch';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

beforeAll(() => preloadRoutes(routes), 30_000);
afterEach(() => resetLicences());

const API = '/api/v1';
type Res = { items: SecurityHit[]; master_as_of: string; error?: { code: string; details: { fields?: { field: string }[] } } };
const search = async (qs: string) => {
  const r = await apiFetch(`${API}/securities/search?${qs}`);
  return { status: r.status, body: (await r.json()) as Res };
};
const hitOf = (b: Res, code: string) => b.items.find((h) => h.security_code === code);
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}
const DEMO = uid(2);

describe('mock：/securities/search 曾用名（验收 3）', () => {
  beforeEach(() => mockLoginAs('demo_user'));
  it('SLFZ（曾用名首字母）→ former_name，matched_text 为曾用名原文', async () => {
    const r = await search('q=SLFZ');
    expect(r.status).toBe(200);
    const h = hitOf(r.body, '600000.SH');
    expect(h).toMatchObject({ match_kind: 'former_name', matched_text: '示例发展', name: '示例银行' });
  });
  it('slfz 小写同样命中；搜曾用名原文得到同一结果', async () => {
    const a = (await search('q=slfz')).body.items.map((h) => [h.security_code, h.match_kind, h.matched_text]);
    const b = (await search(`q=${encodeURIComponent('示例发展')}`)).body.items.map((h) => [h.security_code, h.match_kind, h.matched_text]);
    expect(a).toEqual([['600000.SH', 'former_name', '示例发展']]);
    expect(b).toEqual(a);
  });
  it('当前简称命中优先于曾用名（层级），matched_text 为 null', async () => {
    const r = await search(`q=${encodeURIComponent('示例银行')}`);
    expect(hitOf(r.body, '600000.SH')).toMatchObject({ match_kind: 'name_exact', matched_text: null });
  });
  it('档案 former_names 含曾用名', async () => {
    const r = await apiFetch(`${API}/securities/600000.SH`);
    const p = (await r.json()) as { former_names: { name: string }[] };
    expect(p.former_names.map((f) => f.name)).toEqual(['示例发展']);
  });
});

describe('mock：隔离区与参数（验收 5，#33 ② ⑥）', () => {
  beforeEach(() => mockLoginAs('demo_user'));
  it('vendor_unknown 代码搜不到，/securities/{code} → 404', async () => {
    expect((await search(`q=${VENDOR_UNKNOWN_CODE.slice(0, 6)}`)).body.items).toEqual([]);
    expect((await apiFetch(`${API}/securities/${VENDOR_UNKNOWN_CODE}`)).status).toBe(404);
  });
  it('include_delisted 只收 true|false，否则 400 fields[0].field=include_delisted', async () => {
    expect((await search('q=600000&include_delisted=true')).status).toBe(200);
    expect((await search('q=600000&include_delisted=false')).status).toBe(200);
    const bad = await search('q=600000&include_delisted=yes');
    expect(bad.status).toBe(400);
    expect(bad.body.error?.details.fields?.[0].field).toBe('include_delisted');
  });
});

describe('mock：quote_missing 按本人证书（验收 7）', () => {
  it('证书可用：有未关闭 quote_missing 差异 → true，没有 → false', async () => {
    mockLoginAs('demo_user');
    expect(openQuoteMissingFor(DEMO).has('830001.BJ')).toBe(true);
    expect(hitOf((await search('q=830001')).body, '830001.BJ')?.quote_missing).toBe(true);
    expect(hitOf((await search('q=600000')).body, '600000.SH')?.quote_missing).toBe(false);
  });
  it('别人证书下的差异不算本人的：admin 搜 830001 → false', async () => {
    mockLoginAs('admin');
    expect(hitOf((await search('q=830001')).body, '830001.BJ')?.quote_missing).toBe(false);
  });
  it('未设置证书或证书不可用 → null', async () => {
    mockLoginAs('demo_user');
    setMockLicence(DEMO, { status: 'invalid' });
    expect(hitOf((await search('q=830001')).body, '830001.BJ')?.quote_missing).toBeNull();
    deleteLicence(DEMO);
    expect(hitOf((await search('q=830001')).body, '830001.BJ')?.quote_missing).toBeNull();
  });
  it('ETF、指数恒为 null', async () => {
    mockLoginAs('demo_user');
    expect(hitOf((await search('q=510300')).body, '510300.SH')?.quote_missing).toBeNull();
    expect(hitOf((await search('q=000300&types=index')).body, '000300.SH')?.quote_missing).toBeNull();
  });
});

describe('顶栏搜索 UI', { timeout: 15_000 }, () => {
  beforeEach(() => mockLoginAs('demo_user'));
  const type = async (v: string) => {
    await screen.findByTestId('terminal');
    fireEvent.change(screen.getByLabelText('证券搜索'), { target: { value: v } });
  };

  it('SLFZ → 显示“曾用名：示例发展”，选中进 600000.SH', async () => {
    const router = renderAt('/terminal');
    await type('SLFZ');
    const m = await screen.findByTestId('search-matched-600000.SH', {}, { timeout: 3000 });
    expect(m).toHaveTextContent('曾用名：示例发展');
    expect(screen.getByTestId('search-hit-600000.SH')).toHaveAttribute('data-match', 'former_name');
    fireEvent.click(screen.getByTestId('search-hit-600000.SH'));
    await waitFor(() => expect(router.state.location.pathname).toBe('/stocks/600000.SH'));
  });
  it('quote_missing=true 显示徽标；false/null 不显示', async () => {
    renderAt('/terminal');
    await type('830001');
    expect(await screen.findByTestId('search-quote-missing-830001.BJ', {}, { timeout: 3000 })).toHaveTextContent(QUOTE_MISSING_TEXT);
    fireEvent.change(screen.getByLabelText('证券搜索'), { target: { value: '510300' } });
    await screen.findByTestId('search-hit-510300.SH', {}, { timeout: 3000 });
    expect(screen.queryByTestId('search-quote-missing-510300.SH')).toBeNull();
  });
  it('超过 20 个字符：前端提示，不发请求', async () => {
    let calls = 0;
    server.use(http.get(`${API}/securities/search`, () => { calls += 1; return HttpResponse.json({ items: [], master_as_of: '2026-10-30' }); }));
    renderAt('/terminal');
    await type('一二三四五六七八九十一二三四五六七八九十一');
    expect(await screen.findByTestId('search-status', {}, { timeout: 3000 })).toHaveTextContent('最多 20 个字符');
    expect(calls).toBe(0);
  });
  it('400 显示“搜索词不符合要求”', async () => {
    server.use(http.get(`${API}/securities/search`, () => HttpResponse.json(
      { error: { code: 'VALIDATION_ERROR', message: 'q 归一化后为空', details: { fields: [{ field: 'q', issue: 'invalid' }] }, request_id: null } }, { status: 400 })));
    renderAt('/terminal');
    await type('600000');
    expect(await screen.findByTestId('search-status', {}, { timeout: 3000 })).toHaveTextContent('搜索词不符合要求');
  });
  it('网关 414（非 JSON）显示“请求地址过长”', async () => {
    server.use(http.get(`${API}/securities/search`, () => new HttpResponse('Request-URI Too Large', { status: 414, headers: { 'Content-Type': 'text/html' } })));
    renderAt('/terminal');
    await type('600000');
    expect(await screen.findByTestId('search-status', {}, { timeout: 3000 })).toHaveTextContent('请求地址过长');
  });
  it('429：不重试，按 retry_after_s 暂停（期间换词也不发），到点后重查当前输入', async () => {
    let calls = 0;
    server.use(http.get(`${API}/securities/search`, () => {
      calls += 1;
      if (calls === 1) {
        return HttpResponse.json({ error: { code: 'RATE_LIMITED', message: '请求过于频繁', details: { retry_after_s: 1 }, request_id: null } },
          { status: 429, headers: { 'Retry-After': '1' } });
      }
      return HttpResponse.json({ items: [{ security_code: '600000.SH', name: '示例银行', type: 'stock', exchange: 'SH', board: 'main', listing_status: 'listed',
        risk_flag: null, match_kind: 'code_exact', matched_text: null, quote_missing: false }], master_as_of: '2026-10-30' });
    }));
    renderAt('/terminal');
    await type('600000');
    expect(await screen.findByTestId('search-status', {}, { timeout: 3000 })).toHaveTextContent('请 1 秒后再试');
    fireEvent.change(screen.getByLabelText('证券搜索'), { target: { value: '60000' } });
    await act(() => new Promise((r) => setTimeout(r, 400)));
    expect(calls).toBe(1);
    expect(screen.getByTestId('search-status')).toHaveTextContent('搜索过于频繁');
    await screen.findByTestId('search-hit-600000.SH', {}, { timeout: 3000 });
    expect(calls).toBe(2);
  });
});

describe('#41：不写本地存储；工具函数', { timeout: 15_000 }, () => {
  it('搜索后 localStorage / sessionStorage 不出现 securities 数据', async () => {
    mockLoginAs('demo_user');
    renderAt('/terminal');
    await screen.findByTestId('terminal');
    fireEvent.change(screen.getByLabelText('证券搜索'), { target: { value: 'SLFZ' } });
    await screen.findByTestId('search-matched-600000.SH', {}, { timeout: 3000 });
    const dump = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage });
    expect(dump).not.toMatch(/示例发展|600000\.SH|master_as_of/);
  });
  it('searchQLength 按 NFKC、去空白计数；searchErrorText', () => {
    expect(searchQLength(' ６０００００ ')).toBe(6);
    expect(searchQLength('示例 发展')).toBe(4);
    expect(searchErrorText(new ApiError(414, 'HTTP_ERROR', 'HTTP 414', null, null))).toContain('请求地址过长');
    expect(searchErrorText(new ApiError(429, 'RATE_LIMITED', 'x', { retry_after_s: 2.2 }, null))).toBe('搜索过于频繁，请 3 秒后再试');
  });
});
