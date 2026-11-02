/** T-A09 前端同步（契约 v0.2.8 与 67d123a 补充裁定、编排者 Q63 可转债裁定） */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { ApiError } from '../api/client';
import { CONTRACT_VERSION } from '../api/enums';
import { errorText } from '../api/errorPolicy';
import type { AdminIngestStatus } from '../api/adminTypes';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { setMockLicence, setMockLicenceSettingsEnabled } from '../mocks/licenceStore';
import { PORTFOLIO, uid } from '../mocks/fixtures';
import { apiFetch } from '../test/apiFetch';

// 页面模块的冷加载放在等待窗口之外（评审 b23401a N8）
beforeAll(() => preloadRoutes(routes), 30_000);

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';
const getJson = async <T,>(path: string) => (await (await apiFetch(`${API}${path}`)).json()) as T;
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

describe('版本', () => {
  it('CONTRACT_VERSION = v0.2.9（v0.2.9 起）', () => expect(CONTRACT_VERSION).toBe('v0.2.9'));
});

describe('ETF（v0.2.8 #3–#8）', () => {
  it('默认搜索含 ETF；排序 stock > cdr > etf > index', async () => {
    const def = await getJson<{ items: { security_code: string; type: string }[] }>(`/securities/search?q=${encodeURIComponent('沪深300')}&limit=20`);
    expect(def.items.map((x) => x.type)).toContain('etf');
    expect(def.items.map((x) => x.type)).not.toContain('index');
    const all = await getJson<{ items: { type: string }[] }>(`/securities/search?q=${encodeURIComponent('300')}&types=stock,cdr,etf,index&limit=20`);
    const rank = { stock: 0, cdr: 1, etf: 2, index: 3 } as Record<string, number>;
    const ranks = all.items.map((x) => rank[x.type]);
    expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
  });
  it('ETF 个股页：类型标签、价格 3 位小数、行业等显示“不适用”', async () => {
    renderAt('/stocks/510300.SH');
    expect(await screen.findByTestId('security-type-tag')).toHaveTextContent('ETF');
    await waitFor(() => expect(screen.getByTestId('stock-head').textContent).toMatch(/3\.948/));
    const panel = await screen.findByTestId('profile-panel');
    expect(within(panel).getAllByText('不适用').length).toBeGreaterThan(0);
    expect(panel.textContent).toMatch(/3 位小数/);
  });
  it('ETF 的财务、资金流、因子、公告显示“不适用”而不是报错或空表', async () => {
    renderAt('/stocks/510300.SH?tab=financials');
    expect(await screen.findByTestId('fin-empty')).toHaveTextContent('不适用');
    for (const [label, id] of [['资金流', 'flow-empty'], ['因子', 'factor-empty'], ['公告', 'ann-empty']] as const) {
      fireEvent.click(screen.getByRole('tab', { name: label }));
      expect(await screen.findByTestId(id)).toHaveTextContent('不适用');
    }
  });
  it('建策略实例的 422 按 issue 给出文案', () => {
    expect(errorText(new ApiError(422, 'INSTANCE_SCOPE_INVALID', 'x', { security_type: 'etf', issue: 'security_type_not_supported' }, null))).toBe('ETF 暂不支持建策略实例');
    expect(errorText(new ApiError(422, 'INSTANCE_SCOPE_INVALID', 'x', { issue: 'unknown_security' }, null))).toBe('证券代码不存在');
  });
});

describe('数据证书（v0.2.8 #12/#14，补充裁定③）', () => {
  it('管理员暂停时禁用“测试证书”并说明；接口也返回 409', async () => {
    setMockLicence(uid(2), { status: 'paused_by_admin' });
    renderAt('/settings/data-licence');
    expect(await screen.findByTestId('licence-paused')).toBeInTheDocument();
    expect(screen.getByTestId('licence-test')).toBeDisabled();
    const r = await apiFetch(`${API}/me/data-licence/test`, { method: 'POST' });
    expect(r.status).toBe(409);
    expect(((await r.json()) as { error: { code: string; details: { status: string } } }).error).toMatchObject({ code: 'DATA_LICENCE_UNAVAILABLE', details: { status: 'paused_by_admin' } });
  });
  it('暂停期间 PUT → 202，状态仍为管理员暂停', async () => {
    setMockLicence(uid(2), { status: 'paused_by_admin' });
    const licence = Array.from({ length: 28 }, () => 'QXZJKVWY'[Math.floor(Math.random() * 8)]).join('');
    const r = await apiFetch(`${API}/me/data-licence`, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ licence, tier: 'free', has_quant_pro: false, expires_on: null }) });
    expect(r.status).toBe(202);
    expect(((await r.json()) as { status: string }).status).toBe('paused_by_admin');
  });
  it('设置开关关闭：测试返回 503 MAINTENANCE 后显示“设置暂未开放”，保存与测试禁用，删除仍可用', async () => {
    setMockLicenceSettingsEnabled(false);
    renderAt('/settings/data-licence');
    fireEvent.click(await screen.findByTestId('licence-test'));
    expect(await screen.findByTestId('licence-closed')).toHaveTextContent('设置暂未开放');
    await waitFor(() => expect(screen.getByTestId('licence-test')).toBeDisabled());
    expect(screen.getByTestId('licence-save')).toBeDisabled();
    expect(screen.getByText('删除证书').closest('button')).not.toBeDisabled();
    expect(screen.queryByText(/维护中/)).toBeNull();
  });
});

describe('管理端采集状态（v0.2.8 #1）', () => {
  it('非管理员 404', async () => {
    expect((await apiFetch(`${API}/admin/ingest/status`)).status).toBe(404);
  });
  it('按证书一行、not_set 不列出、异常状态在前；不含全站 licence 键与证书值', async () => {
    mockLoginAs('admin');
    const res = await apiFetch(`${API}/admin/ingest/status`);
    const text = await res.text();
    const d = JSON.parse(text) as AdminIngestStatus & { licence?: unknown };
    expect(d.licence).toBeUndefined();
    expect(d.licences_truncated).toBe(false);
    expect(d.licences.map((x) => x.status)).toEqual(['quota_exceeded', 'paused_by_admin', 'paused_by_admin', 'active', 'active', 'active']);
    expect(d.licences.every((x) => x.status !== 'not_set')).toBe(true);
    expect(text).not.toMatch(/seed-/);
    renderAt('/admin/ingest');
    const table = await screen.findByTestId('admin-ingest');
    expect(await within(table).findByTestId('ingest-status-quota_exceeded')).toHaveTextContent('今日额度已用完');
    expect(within(table).getAllByTestId('ingest-status-paused_by_admin')).toHaveLength(2);
  });
  it('普通用户访问 /admin/ingest 为 404 页', async () => {
    renderAt('/admin/ingest');
    expect(await screen.findByTestId('not-found')).toBeInTheDocument();
  });
});

describe('可转债持仓（编排者 Q63；T-B46 R6 起只看 security_type / estimated）', () => {
  it('不在主数据的行显示“不在主数据·估算”，现价/市值/盈亏为“—”，仓位与总资产标“估算”，不链接个股页', async () => {
    renderAt('/portfolio');
    const tag = await screen.findByTestId('est-label-113050.SH');
    expect(tag).toHaveTextContent('不在主数据·估算');
    const row = tag.closest('tr')!;
    expect(within(row).getAllByText('—').length).toBe(4);
    expect(screen.getByTestId('est-weight-113050.SH')).toHaveTextContent('估算');
    expect(screen.getByTestId('total-est')).toHaveTextContent('估算');
    expect(screen.getByTestId('est-note')).toHaveTextContent('部分持仓不在证券主数据中');
    expect(within(row).queryByRole('link')).toBeNull();
  });
  it('没有估算行时不标估算', async () => {
    server.use(http.get(`${API}/portfolio`, () =>
      HttpResponse.json({ ...PORTFOLIO, positions: PORTFOLIO.positions.filter((x) => !x.estimated) })));
    renderAt('/portfolio');
    await screen.findByTestId('positions-tab');
    expect(screen.queryByTestId('total-est')).toBeNull();
    expect(screen.queryByTestId('est-note')).toBeNull();
  });
});
