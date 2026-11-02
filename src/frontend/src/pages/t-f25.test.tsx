/**
 * T-F25：证券主数据对账页（契约 v0.2.9 内 T-A04 #33 ③④；§7.9 GET /admin/securities/reconciliation；§9 v0.2.9 验收 5、8）。
 * 只读列表、status/kind/source 筛选、§1.2 游标分页、非管理员 404、master.* 告警链到对账页。
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { NAV_ADMIN_RECON, navMoreFor } from '../app/nav';
import { preloadRoutes } from '../test/preloadRoutes';
import type { SecurityReconciliationDiff } from '../api/adminTypes';
import { ENUMS } from '../api/enums';
import { RECON_KIND, RECON_SOURCE } from '../i18n/reconLabels';
import { parseReconFilter } from '../lib/reconFilter';
import { uid } from '../mocks/fixtures';
import { setMockMasterAlerts } from '../mocks/ingestAlerts';
import { RECON_FIXTURES, VENDOR_UNKNOWN_CODE } from '../mocks/reconMock';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { apiFetch } from '../test/apiFetch';

beforeAll(() => preloadRoutes(routes), 30_000);

const API = '/api/v1';
type Page = { items: SecurityReconciliationDiff[]; next_cursor: string | null };
type Err = { error: { code: string; details: { fields?: { field: string; issue: string }[] } } };
const get = async (q = '') => {
  const r = await apiFetch(`${API}/admin/securities/reconciliation${q}`);
  return { status: r.status, body: (await r.json()) as Page & Err };
};
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}
const CONTRACT_KEYS = ['id', 'kind', 'source', 'security_code', 'name', 'source_name', 'field', 'master_value', 'source_value', 'licence_owner',
  'first_seen_on', 'last_seen_on', 'seen_days', 'status', 'resolved_on'].sort();

describe('mock：GET /admin/securities/reconciliation', () => {
  beforeEach(() => mockLoginAs('admin'));

  it('默认 status=open；按 last_seen_on desc, id desc 排序；字段与契约一致', async () => {
    const r = await get();
    expect(r.status).toBe(200);
    expect(r.body.items.length).toBe(RECON_FIXTURES.filter((x) => x.status === 'open').length);
    expect(r.body.items.every((x) => x.status === 'open' && x.resolved_on === null)).toBe(true);
    const keys = r.body.items.map((x) => [x.last_seen_on, x.id].join('|'));
    expect(keys).toEqual([...keys].sort().reverse());
    for (const x of r.body.items) {
      expect(Object.keys(x).sort()).toEqual(CONTRACT_KEYS);
      expect(ENUMS.security_reconciliation_kind).toContain(x.kind);
      expect(ENUMS.security_reconciliation_source).toContain(x.source);
      // licence_owner 只有 mairui_*；field 只有 field_mismatch
      expect(x.licence_owner !== null).toBe(x.source.startsWith('mairui_'));
      expect(x.field !== null).toBe(x.kind === 'field_mismatch');
    }
  });

  it('status=resolved / all', async () => {
    const res = await get('?status=resolved');
    expect(res.body.items.map((x) => x.status)).toEqual(['resolved']);
    expect(res.body.items[0].resolved_on).toBe('2026-10-28');
    const all = await get('?status=all');
    expect(all.body.items.length).toBe(RECON_FIXTURES.length);
  });

  it('kind 逗号多选、source 单选；vendor_unknown 行 name=null 且能看到（验收 5）', async () => {
    const vu = await get('?kind=vendor_unknown');
    expect(vu.body.items).toHaveLength(1);
    expect(vu.body.items[0]).toMatchObject({ security_code: VENDOR_UNKNOWN_CODE, name: null, source_name: '示例未知', licence_owner: { user_id: uid(2), username: 'demo_user' } });
    const two = await get('?kind=quote_missing,field_mismatch');
    expect(new Set(two.body.items.map((x) => x.kind))).toEqual(new Set(['quote_missing', 'field_mismatch']));
    const cn = await get('?source=cninfo');
    expect(cn.body.items.map((x) => x.source)).toEqual(['cninfo']);
    const combo = await get('?status=all&kind=quote_missing&source=mairui_lists');
    expect(combo.body.items).toHaveLength(2);
  });

  it('非法筛选 → 400 VALIDATION_ERROR，fields 指明参数', async () => {
    for (const [q, field] of [['?status=closed', 'status'], ['?kind=foo', 'kind'], ['?kind=vendor_unknown,foo', 'kind'], ['?source=tushare', 'source'], ['?source=cninfo,akshare', 'source']] as const) {
      const r = await get(q);
      expect(r.status).toBe(400);
      expect(r.body.error.code).toBe('VALIDATION_ERROR');
      expect(r.body.error.details.fields?.[0].field).toBe(field);
    }
  });

  it('非管理员 → 404（验收 8）', async () => {
    mockLoginAs('demo_user');
    const r = await get();
    expect(r.status).toBe(404);
  });

  it('§1.2 游标分页：limit=2 逐页取完，不重复不遗漏', async () => {
    const seen: string[] = [];
    let cursor: string | null = null;
    for (let i = 0; i < 10; i++) {
      const r = await get(`?status=all&limit=2${cursor ? `&cursor=${cursor}` : ''}`);
      expect(r.body.items.length).toBeLessThanOrEqual(2);
      seen.push(...r.body.items.map((x) => x.id));
      cursor = r.body.next_cursor;
      if (!cursor) break;
    }
    expect(seen).toHaveLength(RECON_FIXTURES.length);
    expect(new Set(seen).size).toBe(RECON_FIXTURES.length);
  });

  it('quote_conflict 只有代码与天数，不带任何数值', async () => {
    const r = await get('?kind=quote_conflict');
    expect(r.body.items[0]).toMatchObject({ field: null, master_value: null, source_value: null });
    expect(r.body.items[0].seen_days).toBeGreaterThan(0);
  });
});

describe('对账页 UI', () => {
  beforeEach(() => mockLoginAs('admin'));

  it('默认显示未关闭差异：类型、证券、来源与证书所有者、差异内容、持续天数', async () => {
    renderAt('/admin/securities/reconciliation');
    const page = await screen.findByTestId('admin-securities-recon');
    const vu = RECON_FIXTURES.find((x) => x.kind === 'vendor_unknown')!;
    expect(await within(page).findByTestId(`recon-sec-${vu.id}`)).toHaveTextContent(`${VENDOR_UNKNOWN_CODE} 主数据无此代码对方简称：示例未知`);
    expect(screen.getByTestId(`recon-kind-${vu.id}`)).toHaveTextContent(RECON_KIND.vendor_unknown.text);
    const src = screen.getByTestId(`recon-src-${vu.id}`);
    expect(src).toHaveTextContent('麦蕊代码列表证书：demo_user');
    expect(within(src).getByRole('link')).toHaveAttribute('href', `/admin/data-licences?user=${uid(2)}`);
    expect(screen.getByTestId(`recon-seen-${vu.id}`)).toHaveTextContent('3 个工作日2026-10-28 起');
    expect(screen.getByTestId(`recon-status-${vu.id}`)).toHaveTextContent('未关闭');
    const fm = RECON_FIXTURES.find((x) => x.kind === 'field_mismatch' && x.source === 'cninfo')!;
    expect(screen.getByTestId(`recon-diff-${fm.id}`)).toHaveTextContent('上市日期：主数据 2010-01-08 ／ 对方 2010-01-18');
    // quote_conflict 没有差异内容
    const qc = RECON_FIXTURES.find((x) => x.kind === 'quote_conflict')!;
    expect(screen.queryByTestId(`recon-diff-${qc.id}`)).toBeNull();
    // 已关闭的不在默认列表
    const resolved = RECON_FIXTURES.find((x) => x.status === 'resolved')!;
    expect(screen.queryByTestId(`recon-sec-${resolved.id}`)).toBeNull();
    expect(screen.getByTestId('recon-pager-end')).toHaveTextContent(`已显示全部 ${RECON_FIXTURES.length - 1} 条差异`);
  });

  it('地址栏 ?kind= 筛选会传给接口；切到“已关闭”显示关闭日期', async () => {
    const urls: string[] = [];
    const on = ({ request }: { request: Request }) => { if (request.url.includes('/admin/securities/reconciliation')) urls.push(request.url); };
    server.events.on('request:start', on);
    try {
      const router = renderAt('/admin/securities/reconciliation?kind=vendor_unknown');
      const vu = RECON_FIXTURES.find((x) => x.kind === 'vendor_unknown')!;
      await screen.findByTestId(`recon-sec-${vu.id}`);
      expect(screen.getByTestId('recon-pager-end')).toHaveTextContent('已显示全部 1 条差异');
      expect(new URL(urls[0]).searchParams.get('kind')).toBe('vendor_unknown');
      expect(new URL(urls[0]).searchParams.get('status')).toBe('open');
      fireEvent.click(within(screen.getByTestId('recon-status')).getByText('全部'));
      await waitFor(() => expect(router.state.location.search).toBe('?status=all&kind=vendor_unknown'));
      await router.navigate('/admin/securities/reconciliation?status=resolved');
      const resolved = RECON_FIXTURES.find((x) => x.status === 'resolved')!;
      expect(await screen.findByTestId(`recon-status-${resolved.id}`)).toHaveTextContent('已关闭2026-10-28');
      expect(new URL(urls[urls.length - 1]).searchParams.get('kind')).toBeNull();
    } finally {
      server.events.removeListener('request:start', on);
    }
  });

  it('地址栏里不认识的筛选值不发给接口，页面说明已忽略', async () => {
    const urls: string[] = [];
    const on = ({ request }: { request: Request }) => { if (request.url.includes('/admin/securities/reconciliation')) urls.push(request.url); };
    server.events.on('request:start', on);
    try {
      renderAt('/admin/securities/reconciliation?status=closed&kind=vendor_unknown,foo&source=tushare');
      expect(await screen.findByTestId('recon-ignored')).toHaveTextContent('status=closed，kind=foo，source=tushare');
      await screen.findByTestId('recon-pager-end');
      const sp = new URL(urls[0]).searchParams;
      expect([sp.get('status'), sp.get('kind'), sp.get('source')]).toEqual(['open', 'vendor_unknown', null]);
    } finally {
      server.events.removeListener('request:start', on);
    }
  });

  it('接口 400 时显示错误框', async () => {
    server.use(http.get(`${API}/admin/securities/reconciliation`, () => HttpResponse.json(
      { error: { code: 'VALIDATION_ERROR', message: '参数校验失败', details: { fields: [{ field: 'kind', issue: 'x' }] }, request_id: 'r1' } }, { status: 400 },
    ), { once: true }));
    renderAt('/admin/securities/reconciliation');
    expect(await screen.findByRole('alert')).toHaveTextContent('加载失败');
  });

  it('不认识的取值原样显示，不丢行', async () => {
    const odd = { ...RECON_FIXTURES[4], id: uid(31099), kind: 'new_kind', source: 'new_source', field: 'new_field' } as unknown as SecurityReconciliationDiff;
    server.use(http.get(`${API}/admin/securities/reconciliation`, () => HttpResponse.json({ items: [odd], next_cursor: null })));
    renderAt('/admin/securities/reconciliation');
    expect(await screen.findByTestId(`recon-kind-${odd.id}`)).toHaveTextContent('new_kind');
    expect(screen.getByTestId(`recon-src-${odd.id}`)).toHaveTextContent('new_source');
    expect(screen.getByTestId(`recon-diff-${odd.id}`)).toHaveTextContent('new_field：主数据');
  });

  it('非管理员：对账页 404，菜单不含入口；管理员菜单含入口', async () => {
    mockLoginAs('demo_user');
    renderAt('/admin/securities/reconciliation');
    expect(await screen.findByTestId('not-found')).toBeInTheDocument();
    expect(navMoreFor('user')).not.toContainEqual(NAV_ADMIN_RECON);
    expect(navMoreFor('admin')).toContainEqual(NAV_ADMIN_RECON);
    expect(NAV_ADMIN_RECON.path).toBe('/admin/securities/reconciliation');
  });

  it('采集状态页：master.<kind> 告警链到对账页并带 kind 筛选；snapshot_rejected 不加链接；文案仍原样', async () => {
    setMockMasterAlerts({ 'master.snapshot_rejected': 'warning', 'master.vendor_unknown': 'warning', 'master.quote_missing': 'warning' });
    renderAt('/admin/ingest');
    const link = await screen.findByTestId('ingest-alert-recon-master.vendor_unknown');
    expect(link).toHaveAttribute('href', '/admin/securities/reconciliation?kind=vendor_unknown');
    expect(screen.getByTestId('ingest-alert-recon-master.quote_missing')).toHaveAttribute('href', '/admin/securities/reconciliation?kind=quote_missing');
    expect(screen.queryByTestId('ingest-alert-recon-master.snapshot_rejected')).toBeNull();
    expect(screen.getByTestId('ingest-alert-master.vendor_unknown')).toHaveTextContent('行情源出现交易所名单里没有的证券，暂不收录');
  });
});

describe('标签与地址栏解析', () => {
  it('每个 kind / source 都有中文标签', () => {
    for (const k of ENUMS.security_reconciliation_kind) expect(RECON_KIND[k].text.length).toBeGreaterThan(0);
    for (const s of ENUMS.security_reconciliation_source) expect(RECON_SOURCE[s].length).toBeGreaterThan(0);
  });
  it('parseReconFilter：默认 open；kind 去重；非法值进 ignored', () => {
    expect(parseReconFilter(new URLSearchParams(''))).toEqual({ filter: { status: 'open', kinds: [], source: null }, ignored: [] });
    expect(parseReconFilter(new URLSearchParams('status=all&kind=quote_missing,quote_missing,x&source=akshare'))).toEqual({
      filter: { status: 'all', kinds: ['quote_missing'], source: 'akshare' }, ignored: ['kind=x'],
    });
  });
});
