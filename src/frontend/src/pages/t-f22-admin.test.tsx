/** T-F22 遗留：管理端数据证书列表 /admin/data-licences 与暂停 / 恢复（契约 v0.2.8 §5.1、§7.9；be607b3 重复暂停幂等） */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import type { AdminDataLicence, AdminIngestStatus } from '../api/adminTypes';
import { mockLoginAs } from '../mocks/session';
import { adminLicenceLog } from '../mocks/licenceStore';
import { uid } from '../mocks/fixtures';
import { apiFetch } from '../test/apiFetch';

// 页面模块的冷加载放在等待窗口之外（评审 b23401a N8）
beforeAll(() => preloadRoutes(routes), 30_000);

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';
type Page<T> = { items: T[]; next_cursor: string | null; has_more: boolean };
const list = async () => (await (await apiFetch(`${API}/admin/data-licences?limit=100`)).json()) as Page<AdminDataLicence>;
const act = (id: string, op: 'pause' | 'resume', reason: unknown = '示例理由') =>
  apiFetch(`${API}/admin/data-licences/${id}/${op}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ reason }) });
const rowOf = async (id: string) => (await list()).items.find((x) => x.user_id === id)!;
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}
const KEYS = [
  'status', 'tier', 'has_quant_pro', 'expires_on', 'days_to_expiry', 'last_verified_at', 'last_error_code', 'last_error_at', 'paused_until', 'set_at',
  'licence_id', 'user_id', 'username', 'display_name', 'per_minute_limit', 'calls_last_minute', 'calls_today', 'queue_depth',
].sort();

describe('示例接口与契约一致', () => {
  it('普通用户访问管理端接口为 404', async () => {
    expect((await apiFetch(`${API}/admin/data-licences`)).status).toBe(404);
    expect((await act(uid(13), 'pause')).status).toBe(404);
  });
  it('每位用户一行（含未设置）；字段与 AdminDataLicence 一致，不含证书值或片段', async () => {
    mockLoginAs('admin');
    const d = await list();
    expect(d.items.length).toBeGreaterThan(5);
    for (const r of d.items) {
      expect(Object.keys(r).sort()).toEqual(KEYS);
      expect(JSON.stringify(r)).not.toMatch(/licence"|masked|last4|digest/);
      if (r.status === 'not_set') {
        expect(r.licence_id).toBeNull();
        expect(r.per_minute_limit).toBe(0);
      }
    }
    expect(d.items.some((r) => r.status === 'not_set')).toBe(true);
  });
  it('与 /admin/ingest/status 同一证书的 licence_id、今日调用、队列一致', async () => {
    mockLoginAs('admin');
    const ingest = (await (await apiFetch(`${API}/admin/ingest/status`)).json()) as AdminIngestStatus;
    const rows = (await list()).items;
    for (const l of ingest.licences) {
      const r = rows.find((x) => x.licence_id === l.licence_id)!;
      expect(r).toBeTruthy();
      expect([r.user_id, r.calls_today, r.queue_depth, r.per_minute_limit]).toEqual([l.user_id, l.calls_today, l.queue_depth, l.per_minute_limit]);
    }
  });
  it('暂停 → 204；重复暂停 → 204 且不变、不记审计；恢复 → 验证中', async () => {
    mockLoginAs('admin');
    expect((await act(uid(13), 'pause')).status).toBe(204);
    expect((await rowOf(uid(13))).status).toBe('paused_by_admin');
    const n = adminLicenceLog.length;
    expect((await act(uid(13), 'pause')).status).toBe(204);
    expect(adminLicenceLog.length).toBe(n);
    expect((await act(uid(13), 'resume')).status).toBe(204);
    expect((await rowOf(uid(13))).status).toBe('pending_verification');
  });
  it('未设置且未暂停的用户：暂停 / 恢复 → 409 DATA_LICENCE_NOT_SET', async () => {
    mockLoginAs('admin');
    for (const op of ['pause', 'resume'] as const) {
      const r = await act(uid(4), op);
      expect(r.status).toBe(409);
      expect(((await r.json()) as { error: { code: string } }).error.code).toBe('DATA_LICENCE_NOT_SET');
    }
  });
  it('暂停期间删除了证书：列表仍为已暂停、licence_id 为 null；恢复 → 204，之后为未设置', async () => {
    mockLoginAs('admin');
    const r = await rowOf(uid(7));
    expect([r.status, r.licence_id]).toEqual(['paused_by_admin', null]);
    expect((await act(uid(7), 'resume')).status).toBe(204);
    expect((await rowOf(uid(7))).status).toBe('not_set');
  });
  it('理由为空或超过 200 字 → 400；用户不存在 → 404', async () => {
    mockLoginAs('admin');
    expect((await act(uid(13), 'pause', '')).status).toBe(400);
    expect((await act(uid(13), 'pause', '理'.repeat(201))).status).toBe(400);
    expect((await act(uid(9999), 'pause')).status).toBe(404);
  });
});

describe('/admin/data-licences 页面', () => {
  it('普通用户访问为 404 页', async () => {
    renderAt('/admin/data-licences');
    expect(await screen.findByText(/页面不存在|404/)).toBeInTheDocument();
    expect(screen.queryByTestId('admin-data-licences')).toBeNull();
  });
  it('列表：状态、未设置行没有操作按钮、暂停期间删除证书有标记', async () => {
    mockLoginAs('admin');
    renderAt('/admin/data-licences');
    expect(await screen.findByTestId('lic-status-novice_user')).toHaveTextContent('可用');
    expect(screen.getByTestId('lic-pause-novice_user')).toBeInTheDocument();
    expect(screen.getByTestId('lic-status-new_user')).toHaveTextContent('未设置');
    expect(screen.queryByTestId('lic-pause-new_user')).toBeNull();
    expect(screen.getByTestId('lic-deleted-rejected_user')).toBeInTheDocument();
    expect(screen.getByTestId('lic-resume-rejected_user')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/digest|seed-/);
  });
  it('暂停须填理由并勾选核对（二次确认），确认后状态变为管理员已暂停', async () => {
    mockLoginAs('admin');
    renderAt('/admin/data-licences');
    fireEvent.click(await screen.findByTestId('lic-pause-novice_user'));
    expect(await screen.findByTestId('lic-effect')).toHaveTextContent('只有管理员恢复才能解除');
    const ok = screen.getByTestId('lic-ok');
    expect(ok).toBeDisabled();
    fireEvent.change(screen.getByTestId('lic-reason'), { target: { value: '   ' } });
    fireEvent.click(screen.getByTestId('lic-ack'));
    expect(ok).toBeDisabled();
    fireEvent.change(screen.getByTestId('lic-reason'), { target: { value: '示例：异常调用排查' } });
    expect(ok).not.toBeDisabled();
    fireEvent.click(ok);
    expect(await screen.findByTestId('lic-done')).toHaveTextContent('已暂停');
    await waitFor(() => expect(screen.getByTestId('lic-status-novice_user')).toHaveTextContent('管理员已暂停'));
    expect(adminLicenceLog.at(-1)).toMatchObject({ userId: uid(13), op: 'pause', reason: '示例：异常调用排查' });
    expect(screen.getByTestId('lic-resume-novice_user')).toBeInTheDocument();
  });
  it('恢复（证书已删除）：说明恢复后为未设置，确认后行变为未设置', async () => {
    mockLoginAs('admin');
    renderAt('/admin/data-licences');
    fireEvent.click(await screen.findByTestId('lic-resume-rejected_user'));
    expect(await screen.findByTestId('lic-effect')).toHaveTextContent('之后状态为“未设置”');
    fireEvent.change(screen.getByTestId('lic-reason'), { target: { value: '示例：核查完毕' } });
    fireEvent.click(screen.getByTestId('lic-ack'));
    fireEvent.click(screen.getByTestId('lic-ok'));
    await waitFor(() => expect(screen.getByTestId('lic-status-rejected_user')).toHaveTextContent('未设置'));
    expect(screen.queryByTestId('lic-resume-rejected_user')).toBeNull();
  });
  it('409 DATA_LICENCE_NOT_SET 在弹窗里用管理端文案提示', async () => {
    mockLoginAs('admin');
    renderAt('/admin/data-licences');
    fireEvent.click(await screen.findByTestId('lic-pause-novice_user'));
    // 用户在管理员打开弹窗后删除了证书
    const { deleteLicence } = await import('../mocks/licenceStore');
    deleteLicence(uid(13));
    fireEvent.change(await screen.findByTestId('lic-reason'), { target: { value: '示例' } });
    fireEvent.click(screen.getByTestId('lic-ack'));
    fireEvent.click(screen.getByTestId('lic-ok'));
    expect(await screen.findByTestId('lic-error')).toHaveTextContent('该用户没有设置数据证书');
    expect(screen.getByTestId('lic-error').textContent).not.toMatch(/你还没有/);
  });
  it('本地筛选只作用于已加载的行，并给出说明', async () => {
    mockLoginAs('admin');
    renderAt('/admin/data-licences');
    await screen.findByTestId('lic-status-novice_user');
    fireEvent.click(screen.getByText('未设置', { selector: '.ant-segmented-item-label' }));
    expect(await screen.findByTestId('lic-filter-note')).toHaveTextContent('接口未提供筛选参数');
    expect(screen.queryByTestId('lic-status-novice_user')).toBeNull();
    expect(screen.getByTestId('lic-status-new_user')).toBeInTheDocument();
  });
  it('采集状态页的用户可跳到证书列表并高亮', async () => {
    mockLoginAs('admin');
    const router = renderAt('/admin/ingest');
    const table = await screen.findByTestId('admin-ingest');
    fireEvent.click(await within(table).findByText('novice_user', { exact: false }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/data-licences'));
    expect(router.state.location.search).toBe(`?user=${uid(13)}`);
    await screen.findByTestId('lic-status-novice_user');
    expect(document.querySelector('tr.row-focus')?.textContent).toMatch(/novice_user/);
  });
});
