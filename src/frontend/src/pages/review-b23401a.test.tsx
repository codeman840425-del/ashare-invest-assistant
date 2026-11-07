/**
 * 评审 b23401a 的修复：d26e1d3 m1/m2/m3 与 N1、N7（N2–N6 见 t-f13，N8 为测试环境还原）。
 * 管理端证书列表、mock 理由去空白、409 文案只认自有键、blocked 信号的 allowed。
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import type { AdminDataLicence } from '../api/adminTypes';
import { ApiError } from '../api/client';
import { transitionText } from '../lib/stateTransition';
import { CANDIDATE_SIGNALS, uid } from '../mocks/fixtures';
import { signalAllowed } from '../mocks/planHandlers';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { apiFetch } from '../test/apiFetch';

// 页面模块的冷加载放在等待窗口之外（评审 b23401a N8）
beforeAll(() => preloadRoutes(routes), 30_000);

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}
const act = (id: string, op: 'pause' | 'resume', reason: unknown) =>
  apiFetch(`${API}/admin/data-licences/${id}/${op}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ reason }) });

/** 以示例列表第一行为模板造 n 行（user_id 用 uid，username 为 demo_NNN） */
async function manyRows(n: number, patch: (i: number) => Partial<AdminDataLicence> = () => ({})): Promise<AdminDataLicence[]> {
  const base = ((await (await apiFetch(`${API}/admin/data-licences?limit=1`)).json()) as { items: AdminDataLicence[] }).items[0];
  return Array.from({ length: n }, (_, i) => ({ ...base, user_id: uid(20000 + i), username: `demo_${String(i).padStart(3, '0')}`, display_name: `示例用户${i}`, ...patch(i) }));
}
function serveRows(rows: AdminDataLicence[], seen: (string | null)[] = []) {
  server.use(http.get(`${API}/admin/data-licences`, ({ request }) => {
    const url = new URL(request.url);
    const limit = Number(url.searchParams.get('limit') ?? 50);
    const start = Number(url.searchParams.get('cursor') ?? 0);
    seen.push(url.searchParams.get('cursor'));
    const next = start + limit < rows.length ? String(start + limit) : null;
    return HttpResponse.json({ items: rows.slice(start, start + limit), next_cursor: next });
  }));
}

describe('d26e1d3 m1：管理端证书列表的到期显示', () => {
  it('已过期显示“已过填写的到期日”、当天显示“今天到期”，不出现“剩 -N 天”（文案按 #40）', async () => {
    mockLoginAs('admin');
    const rows = await manyRows(3, (i) => ({ status: 'active', licence_id: uid(21000 + i), expires_on: '2026-11-02', days_to_expiry: [-5, 0, 12][i] }));
    serveRows(rows);
    renderAt('/admin/data-licences');
    const table = await screen.findByTestId('lic-table');
    await within(table).findByText(/demo_000/);
    const text = table.textContent ?? '';
    expect(text).toContain('2026-11-02（已过填写的到期日）');
    expect(text).toContain('2026-11-02（今天到期）');
    expect(text).toContain('2026-11-02（还剩 12 天）');
    expect(text).not.toMatch(/剩 -\d/);
  });
});

describe('d26e1d3 m2：?user= 指向第 50 行之后的用户', () => {
  it('自动续加载到目标行所在的页，高亮并滚动到该行', async () => {
    mockLoginAs('admin');
    const rows = await manyRows(75);
    const seen: (string | null)[] = [];
    serveRows(rows, seen);
    const scrolled: string[] = [];
    const orig = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (this: Element) { scrolled.push(this.getAttribute('data-row-key') ?? ''); };
    try {
      renderAt(`/admin/data-licences?user=${uid(20000 + 60)}`);
      // 连续加载 2 页、渲染 75 行，单独放宽这一处等待（全局保持默认，评审 b23401a N8）
      await waitFor(() => expect(document.querySelector('tr.row-focus')?.textContent ?? '').toMatch(/demo_060/), { timeout: 8000 });
      expect(seen).toEqual([null, '50']);
      expect(scrolled).toContain(uid(20000 + 60));
      expect(screen.queryByTestId('lic-focus-searching')).toBeNull();
      expect(screen.queryByTestId('lic-focus-missing')).toBeNull();
    } finally {
      Element.prototype.scrollIntoView = orig;
    }
  }, 15_000);
  it('全部加载完仍找不到：给出提示，不再请求', async () => {
    mockLoginAs('admin');
    const rows = await manyRows(70);
    const seen: (string | null)[] = [];
    serveRows(rows, seen);
    renderAt(`/admin/data-licences?user=${uid(99999)}`);
    expect(await screen.findByTestId('lic-focus-missing', undefined, { timeout: 5000 })).toHaveTextContent('列表中没有找到该用户');
    expect(seen).toEqual([null, '50']);
    expect(document.querySelector('tr.row-focus')).toBeNull();
  });
  it('目标行已加载但被本地筛选隐藏：提示切回“全部”', async () => {
    mockLoginAs('admin');
    renderAt(`/admin/data-licences?user=${uid(13)}`);
    await waitFor(() => expect(document.querySelector('tr.row-focus')).not.toBeNull());
    fireEvent.click(within(screen.getByTestId('lic-filter')).getByText('未设置'));
    expect(await screen.findByTestId('lic-focus-hidden')).toBeInTheDocument();
  });
});

describe('d26e1d3 m3：mock 先去掉理由首尾空白再按 1–200 字校验', () => {
  it('纯空白 → 400 required；去空白后 200 字可以，201 字不行', async () => {
    mockLoginAs('admin');
    const r = await act(uid(13), 'pause', '   \n  ');
    expect(r.status).toBe(400);
    expect(((await r.json()) as { error: { details: { fields: { field: string; issue: string }[] } } }).error.details.fields[0]).toEqual({ field: 'reason', issue: 'required' });
    expect((await act(uid(13), 'pause', `  ${'理'.repeat(200)}  `)).status).toBe(204);
    const long = await act(uid(13), 'resume', ` ${'理'.repeat(201)} `);
    expect(long.status).toBe(400);
  });
});

describe('N1：409 文案只认自有键', () => {
  it('from 为原型链上的键时回落到通用文案（返回 null）', () => {
    for (const from of ['toString', 'constructor', '__proto__', 'hasOwnProperty']) {
      const e = new ApiError(409, 'INVALID_STATE_TRANSITION', 'x', { from, to: 'dismissed', allowed: [] }, null);
      expect(transitionText(e, 'signal')).toBeNull();
      expect(transitionText(e, 'draft')).toBeNull();
    }
    const ok = new ApiError(409, 'INVALID_STATE_TRANSITION', 'x', { from: 'dismissed', to: 'drafted', allowed: [] }, null);
    expect(transitionText(ok, 'signal')).toBe('该信号已忽略');
  });
});

describe('N7：blocked 信号的 allowed 含 released', () => {
  it('blocked 的 allowed 仍为 [released, dismissed]；对 blocked 信号拟定草案按 #37 → 409 SIGNAL_NOT_EXECUTABLE', async () => {
    // v0.2.9 #37：不论原因码，blocked 拟定草案一律 SIGNAL_NOT_EXECUTABLE；INVALID_STATE_TRANSITION 只用于终态
    expect(signalAllowed('blocked')).toEqual(['released', 'dismissed']);
    const blocked = CANDIDATE_SIGNALS.find((c) => c.id === uid(1016))!;
    expect(blocked.state).toBe('blocked');
    const r = await apiFetch(`${API}/plan-drafts`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ signal_ids: [blocked.id] }) });
    expect(r.status).toBe(409);
    const b = (await r.json()) as { error: { code: string; details: { reason_ids: string[] } } };
    expect(b.error.code).toBe('SIGNAL_NOT_EXECUTABLE');
    expect(b.error.details.reason_ids).toEqual([uid(1017)]);
  });
});
