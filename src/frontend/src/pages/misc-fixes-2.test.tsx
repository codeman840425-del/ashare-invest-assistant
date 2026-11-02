/**
 * 前端小修复 2（评审 05d8a16 m1、契约 v0.2.9 #36 refresh 响应体、#35 放弃 / 失败批次不请求逐行预览）。
 * 全部为示例数据，请求由 MSW 拦截，不发外网请求。
 */
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { resetViewedOnce } from '../api/suggestionQueries';
import { StatValue } from '../components/StatValue';
import { suggestionOf, uid } from '../mocks/fixtures';
import { server } from '../mocks/server';
import { emptyStats, state, type MockBatch } from '../mocks/session';
import { apiFetch } from '../test/apiFetch';
import { preloadRoutes } from '../test/preloadRoutes';

configure({ asyncUtilTimeout: 5000 });
beforeAll(() => preloadRoutes(routes), 30_000);
beforeEach(() => resetViewedOnce());

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';
const post = (path: string, body: unknown) => apiFetch(`${API}${path}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

/** 记录本测试发出的请求（方法 + 路径 + 查询串） */
function recordRequests() {
  const seen: string[] = [];
  const fn = ({ request }: { request: Request }) => { const u = new URL(request.url); seen.push(`${request.method} ${u.pathname}${u.search}`); };
  server.events.on('request:start', fn);
  return { seen, stop: () => server.events.removeListener('request:start', fn) };
}

const sgBank = suggestionOf('600000.SH')!;

describe('m1：跟踪收益按服务端原值显示', () => {
  it('StatValue kind=raw 原样显示 decimal 字符串，0.003 不会变成 0.00', () => {
    render(<StatValue s={{ value: '0.003', n: 42, window: '示例窗口', small_sample: false }} kind="raw" testId="v" />);
    expect(screen.getByTestId('v')).toHaveTextContent(/^0\.003/);
    expect(screen.getByTestId('v')).not.toHaveTextContent('0.00 ');
  });

  it('建议详情页的跟踪统计用服务端原值', async () => {
    const window = '近 120 个交易日（示例）';
    server.use(http.get(`${API}/suggestions/:id/tracking`, () => HttpResponse.json({
      t1: { value: '0.003', n: 42, window, small_sample: false },
      t5: { value: '-0.0125', n: 18, window, small_sample: true },
      t20: { value: null, n: 3, window, small_sample: true },
    })));
    renderAt(`/suggestions/${sgBank.id}`);
    expect(await screen.findByTestId('sg-track-t1')).toHaveTextContent(/^0\.003/);
    expect(screen.getByTestId('sg-track-t5')).toHaveTextContent(/^-0\.0125/);
    expect(screen.getByTestId('sg-track-t20')).toHaveTextContent('样本不足');
  });
});

describe('#36：refresh 以响应体为准', () => {
  it('mock：200 {suggestion, changed, superseded_id, data_as_of}；没有任何卡 → suggestion=null、changed=false', async () => {
    const r = await (await post('/suggestions/refresh', { security_code: '600000.SH' })).json();
    expect(Object.keys(r).sort()).toEqual(['changed', 'data_as_of', 'suggestion', 'superseded_id']);
    expect(r).toMatchObject({ changed: true, superseded_id: sgBank.id });
    expect(r.suggestion.supersedes_id).toBe(sgBank.id);
    const none = await post('/suggestions/refresh', { security_code: '600999.SH' });
    expect(none.status).toBe(200);
    expect(await none.json()).toMatchObject({ suggestion: null, changed: false, superseded_id: null });
  });

  it('取代旧卡：按响应体里的 suggestion.id 跳转，不再另发 GET /suggestions?status=active', async () => {
    const rec = recordRequests();
    const router = renderAt(`/suggestions/${sgBank.id}`);
    fireEvent.click(await screen.findByTestId('sg-refresh'));
    await waitFor(() => expect(router.state.location.pathname).not.toBe(`/suggestions/${sgBank.id}`));
    expect(await screen.findByTestId('sg-refresh-msg')).toHaveTextContent('已切换到新卡');
    rec.stop();
    const after = rec.seen.slice(rec.seen.findIndex((x) => x.startsWith('POST /api/v1/suggestions/refresh')));
    // 旧实现刷新后另发 GET /suggestions?security_code=&status=active&limit=1 取当前卡；现在以响应体为准
    expect(after.some((x) => x.startsWith('GET /api/v1/suggestions?') && x.includes('security_code=') && x.includes('limit=1'))).toBe(false);
  });

  it('无变化：changed=false 且 suggestion 是当前卡 → 留在本页并提示没有变化', async () => {
    server.use(http.post(`${API}/suggestions/refresh`, () => HttpResponse.json({ suggestion: sgBank, changed: false, superseded_id: null, data_as_of: sgBank.data_as_of })));
    const router = renderAt(`/suggestions/${sgBank.id}`);
    fireEvent.click(await screen.findByTestId('sg-refresh'));
    expect(await screen.findByTestId('sg-refresh-msg')).toHaveTextContent('当前卡没有变化');
    expect(router.state.location.pathname).toBe(`/suggestions/${sgBank.id}`);
  });

  it('当前没有任何建议：suggestion=null → 提示没有候选信号卡，不跳转', async () => {
    server.use(http.post(`${API}/suggestions/refresh`, () => HttpResponse.json({ suggestion: null, changed: false, superseded_id: null, data_as_of: sgBank.data_as_of })));
    const router = renderAt(`/suggestions/${sgBank.id}`);
    fireEvent.click(await screen.findByTestId('sg-refresh'));
    expect(await screen.findByTestId('sg-refresh-msg')).toHaveTextContent('当前没有候选信号卡');
    expect(router.state.location.pathname).toBe(`/suggestions/${sgBank.id}`);
  });
});

describe('#35：放弃或失败的导入批次不再请求逐行预览', () => {
  const base = () => state.batches.find((b) => b.batch_id === uid(820))!;
  function addBatch(n: number, status: MockBatch['status'], extra: Partial<MockBatch> = {}): string {
    const b0 = base();
    const b: MockBatch = { ...b0, batch_id: uid(n), status, committed_at: null, rows_data: b0.rows_data.map((r) => ({ ...r })), idem: new Map(), ...extra };
    state.batches.push(b);
    return b.batch_id;
  }
  const frozen = { ...emptyStats(), rows: 7, ok: 5, warning: 1, error: 1, new: 6, duplicate_in_db: 1 };

  it('mock：discarded / failed 的 /rows 为 200 空列表，errors.csv 只有表头，discarded 上 resolve → 409', async () => {
    const d = addBatch(831, 'discarded', { rows_data: [], stats_frozen: frozen, file_findings: [] });
    const f = addBatch(832, 'failed', { rows_data: [] });
    for (const id of [d, f]) {
      const r = await apiFetch(`${API}/imports/${id}/rows`);
      expect(r.status).toBe(200);
      expect(await r.json()).toEqual({ items: [], next_cursor: null });
      const csv = (await (await apiFetch(`${API}/imports/${id}/errors.csv`)).text()).replace(/^\uFEFF/, '').trim();
      expect(csv.split(/\r?\n/)).toHaveLength(1);
    }
    expect((await (await apiFetch(`${API}/imports/${d}`)).json()).stats).toMatchObject({ rows: 7, error: 1 });
    expect((await post(`/imports/${d}/findings/${uid(1)}/resolve`, { choice: 'keep_skipped', reason: null })).status).toBe(409);
  });

  it('mock：放弃时删掉预览行，批次头 stats 保留删除前的计数', async () => {
    const id = addBatch(833, 'previewed');
    const before = (await (await apiFetch(`${API}/imports/${id}`)).json()).stats;
    expect(before.rows).toBeGreaterThan(0);
    expect((await post(`/imports/${id}/discard`, {})).status).toBe(200);
    const after = await (await apiFetch(`${API}/imports/${id}`)).json();
    expect(after.status).toBe('discarded');
    expect(after.stats).toEqual(before);
    expect((await (await apiFetch(`${API}/imports/${id}/rows`)).json()).items).toEqual([]);
  });

  it('failed 批次页：不请求 /rows，按批次头 stats 显示计数，不提供只有表头的问题清单', async () => {
    const id = addBatch(834, 'failed', { rows_data: [], stats_frozen: frozen });
    const rec = recordRequests();
    renderAt(`/portfolio/import/${id}`);
    const stats = await screen.findByTestId('import-stats');
    expect(stats).toHaveTextContent('共 7 行');
    expect(within(stats).getByText(/错误 1/)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 300));
    rec.stop();
    expect(rec.seen.filter((x) => x.includes('/rows'))).toEqual([]);
    expect(screen.queryByRole('button', { name: /下载问题清单/ })).toBeNull();
  });

  it('discarded 批次页：不请求 /rows，显示批次头计数', async () => {
    const id = addBatch(835, 'discarded', { rows_data: [], stats_frozen: frozen });
    const rec = recordRequests();
    renderAt(`/portfolio/import/${id}`);
    expect(await screen.findByTestId('import-discarded')).toHaveTextContent('本批次已放弃');
    expect(screen.getByTestId('import-stats')).toHaveTextContent('共 7 行');
    await new Promise((r) => setTimeout(r, 300));
    rec.stop();
    expect(rec.seen.filter((x) => x.includes('/rows'))).toEqual([]);
    expect(screen.queryByRole('button', { name: /下载问题清单/ })).toBeNull();
  });

  it('在预览页放弃：放弃之后不再发出 /rows 请求', async () => {
    const id = addBatch(836, 'previewed');
    const rec = recordRequests();
    const router = renderAt(`/portfolio/import/${id}`);
    await screen.findByTestId('confirm-panel');
    await waitFor(() => expect(rec.seen.some((x) => x.includes(`/imports/${id}/rows`))).toBe(true));
    fireEvent.click(screen.getByRole('button', { name: /放弃本批次/ }));
    fireEvent.click(await screen.findByRole('button', { name: /^放\s*弃$/ }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/portfolio'));
    await new Promise((r) => setTimeout(r, 300));
    rec.stop();
    const i = rec.seen.findIndex((x) => x.startsWith(`POST /api/v1/imports/${id}/discard`));
    expect(i).toBeGreaterThanOrEqual(0);
    expect(rec.seen.slice(i).filter((x) => x.includes('/rows'))).toEqual([]);
  });
});
