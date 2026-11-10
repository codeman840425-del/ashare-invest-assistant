/** T-F33 自选股入口（契约 docs/contracts/watchlist.md，T-A129 4c89336）：mock 接口五分支 + api client 头 + 页面入口交互。示例数据。 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { apiFetch } from '../test/apiFetch';
import { server } from '../mocks/server';
import { clearMockWatchlist, setMockWatchlistCap, watchlistNow } from '../mocks/watchlistHandlers';
import { ApiError } from '../api/client';
import { addWatchlist, fetchWatchlist, removeWatchlist, watchlistErrorText } from '../api/watchlistQueries';
import type { WatchlistItem, WatchlistResponse } from '../api/types';

beforeAll(() => preloadRoutes(routes), 30_000);

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';
type Err = { error: { code: string; details: Record<string, unknown> | null } };
const WAIT = { timeout: 5000 };
const post = async (body: unknown, key?: string) => {
  const r = await apiFetch(`${API}/watchlist`, {
    method: 'POST', headers: { 'content-type': 'application/json', ...(key ? { 'Idempotency-Key': key } : {}) }, body: JSON.stringify(body),
  });
  return { status: r.status, body: (await r.json()) as unknown };
};
const del = async (code: string) => {
  const r = await apiFetch(`${API}/watchlist/${encodeURIComponent(code)}`, { method: 'DELETE' });
  return { status: r.status, text: await r.text() };
};
const codes = () => watchlistNow().map((x) => x.security_code);
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

describe('mock：/watchlist 五分支', () => {
  it('GET：本人有效行按加入时间升序，refresh_tier 为 null，caps 完整', async () => {
    const r = (await (await apiFetch(`${API}/watchlist`)).json()) as WatchlistResponse;
    expect(r.items.length).toBeGreaterThan(0);
    expect(r.items.map((x) => x.added_at)).toEqual([...r.items.map((x) => x.added_at)].sort());
    expect(r.items.every((x) => x.refresh_tier === null)).toBe(true);
    // T-F33b：示例上限与后端回落值（realtime.yaml）一致
    expect(r.caps).toEqual({ watchlist: 100, focus: 20 });
  });
  it('201：裸 6 位代码规范化；省略 group/note 为 null；同键同体重放返回同一 201，不新增行', async () => {
    const before = codes().length;
    const a = await post({ security_code: '600002' }, 'k-demo-1');
    expect(a.status).toBe(201);
    const item = a.body as WatchlistItem;
    expect(item).toMatchObject({ security_code: '600002.SH', name: '演示医药', group: null, note: null, focus: false, refresh_tier: null });
    const b = await post({ security_code: '600002' }, 'k-demo-1');
    expect(b.status).toBe(201);
    expect(b.body).toEqual(item);
    expect(codes().length).toBe(before + 1);
    const c = await post({ security_code: '600002.SH' }, 'k-demo-1');
    expect(c.status).toBe(409);
    expect((c.body as Err).error.code).toBe('IDEMPOTENCY_CONFLICT');
  });
  it('409：已在自选（sh600000 规范化后重复）→ CONFLICT{field, existing_id}，行数不变', async () => {
    const before = codes().length;
    const r = await post({ security_code: 'sh600000' });
    expect(r.status).toBe(409);
    const e = (r.body as Err).error;
    expect(e.code).toBe('CONFLICT');
    expect(e.details).toMatchObject({ field: 'security_code' });
    expect(typeof e.details!.existing_id).toBe('string');
    expect(codes().length).toBe(before);
  });
  it('403：达到上限 → ENTITLEMENT_LIMIT_REACHED{key, limit, current}；重复优先 409', async () => {
    const n = codes().length;
    setMockWatchlistCap(n);
    const r = await post({ security_code: '600002.SH' });
    expect(r.status).toBe(403);
    expect((r.body as Err).error).toMatchObject({ code: 'ENTITLEMENT_LIMIT_REACHED', details: { key: 'watchlist.per_user_cap', limit: n, current: n } });
    expect((await post({ security_code: '600000.SH' })).status).toBe(409);
    expect(codes().length).toBe(n);
  });
  it('204 / 404：软删成功无体；再删 404；从未加入 404；格式非法 400 invalid', async () => {
    const d = await del('600000');
    expect(d.status).toBe(204);
    expect(d.text).toBe('');
    expect(codes()).not.toContain('600000.SH');
    expect((await del('600000.SH')).status).toBe(404);
    expect((await del('600002.SH')).status).toBe(404);
    const bad = await del('60000X');
    expect(bad.status).toBe(400);
    expect((JSON.parse(bad.text) as Err).error.details).toEqual({ fields: [{ field: 'security_code', issue: 'invalid' }] });
  });
  it('400：指数 security_type_not_supported、主数据没有 unknown_security、group 超长 too_long、未知键', async () => {
    const issue = async (body: unknown) => ((await post(body)).body as Err).error.details!.fields as { field: string; issue: string }[];
    expect(await issue({ security_code: '000300.SH' })).toEqual([{ field: 'security_code', issue: 'security_type_not_supported' }]);
    expect(await issue({ security_code: '600999.SH' })).toEqual([{ field: 'security_code', issue: 'unknown_security' }]);
    expect(await issue({ security_code: 'ABC' })).toEqual([{ field: 'security_code', issue: 'invalid' }]);
    expect(await issue({ security_code: '600002.SH', group: 'x'.repeat(33) })).toEqual([{ field: 'group', issue: 'too_long' }]);
  });
  it('400 请求体层（契约 §5，T-F33b）：未知键 unknown field、缺字段 required、空体 required；类型错只断言 field', async () => {
    const fields = async (body: unknown) => {
      const r = await post(body);
      expect(r.status).toBe(400);
      expect((r.body as Err).error.code).toBe('VALIDATION_ERROR');
      return (r.body as Err).error.details!.fields as { field: string; issue: string }[];
    };
    const before = codes().length;
    expect(await fields({ security_code: '600002.SH', focus: true })).toContainEqual({ field: 'focus', issue: 'unknown field' });
    expect(await fields({})).toContainEqual({ field: 'security_code', issue: 'required' });
    // 不断言 pydantic 英文原句，只断言 field
    expect((await fields({ security_code: 600000 }))[0].field).toBe('security_code');
    expect((await fields({ security_code: '600002.SH', group: 1 }))[0].field).toBe('group');
    expect((await fields([]))[0].field).toBe('body');
    const empty = await apiFetch(`${API}/watchlist`, { method: 'POST', headers: { 'content-type': 'application/json' } });
    expect(empty.status).toBe(400);
    expect(((await empty.json()) as Err).error.details).toEqual({ fields: [{ field: 'body', issue: 'required' }] });
    expect(codes().length).toBe(before);
  });
  it('写请求缺 CSRF 头 → 403 CSRF_FAILED（统一前置）', async () => {
    const r = await fetch(`${API}/watchlist`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ security_code: '600002.SH' }) });
    expect(r.status).toBe(403);
    expect(((await r.json()) as Err).error.code).toBe('CSRF_FAILED');
  });
});

describe('api client：头与错误文案', () => {
  it('POST 带 Idempotency-Key 与 X-CSRF-Token；DELETE 带 X-CSRF-Token、代码 URL 编码；GET 不带 CSRF', async () => {
    const seen: { method: string; path: string; idem: string | null; csrf: string | null }[] = [];
    server.use(http.all(`${API}/watchlist*`, ({ request }) => {
      seen.push({ method: request.method, path: new URL(request.url).pathname, idem: request.headers.get('Idempotency-Key'), csrf: request.headers.get('X-CSRF-Token') });
      return undefined;
    }));
    await addWatchlist({ security_code: '600002.SH' }, 'k-demo-2');
    await removeWatchlist('600002.SH');
    await fetchWatchlist();
    expect(seen.map((s) => [s.method, s.path])).toEqual([['POST', '/api/v1/watchlist'], ['DELETE', '/api/v1/watchlist/600002.SH'], ['GET', '/api/v1/watchlist']]);
    expect(seen[0].idem).toBe('k-demo-2');
    expect(seen[0].csrf).toBeTruthy();
    expect(seen[1].csrf).toBeTruthy();
    expect(seen[2].csrf).toBeNull();
  });
  it('五分支映射：201 结果、409 已在自选、403 上限（含数值）、404 已不在自选、204 返回 undefined', async () => {
    expect((await addWatchlist({ security_code: '600002.SH' }, 'k-demo-3')).security_code).toBe('600002.SH');
    const e409 = await addWatchlist({ security_code: '600002.SH' }, 'k-demo-4').catch((e: unknown) => e);
    expect(e409).toBeInstanceOf(ApiError);
    expect(watchlistErrorText(e409, 'add')).toBe('已在自选');
    setMockWatchlistCap(codes().length);
    const eDup = await addWatchlist({ security_code: '300001.SZ' }, 'k-demo-5').catch((e: unknown) => e);
    // 300001.SZ 已在示例自选里 → 先判重 409；删掉后再加才是 403
    expect(watchlistErrorText(eDup, 'add')).toBe('已在自选');
    expect(await removeWatchlist('300001.SZ')).toBeUndefined();
    setMockWatchlistCap(codes().length);
    const e403b = await addWatchlist({ security_code: '300001.SZ' }, 'k-demo-6').catch((e: unknown) => e);
    const n = codes().length;
    expect(watchlistErrorText(e403b, 'add')).toBe(`自选已达上限（${n}/${n} 只），请先移出部分自选`);
    const e404 = await removeWatchlist('300001.SZ').catch((e: unknown) => e);
    expect(watchlistErrorText(e404, 'remove')).toBe('该证券已不在自选中');
    expect(watchlistErrorText(new ApiError(403, 'ENTITLEMENT_LIMIT_REACHED', 'x', null, null), 'add')).toBe('自选已达上限，请先移出部分自选');
    // ③ 并发兜底时后端 existing_id 可能为 null：文案不依赖该字段
    expect(watchlistErrorText(new ApiError(409, 'CONFLICT', 'x', { field: 'security_code', existing_id: null }, null), 'add')).toBe('已在自选');
    // 请求体层 400（pydantic 原句）只给通用文案
    expect(watchlistErrorText(new ApiError(400, 'VALIDATION_ERROR', '参数校验失败', { fields: [{ field: 'focus', issue: 'unknown field' }] }, null), 'add')).toBe('加入自选失败：参数校验失败');
  });
});

describe('页面入口', () => {
  it('个股页：加自选 201 → 变为移出自选；再移出 204 → 变回加自选', async () => {
    renderAt('/stocks/600002.SH');
    const box = await screen.findByTestId('watchlist-stock', undefined, WAIT);
    fireEvent.click(await within(box).findByTestId('watchlist-add', undefined, WAIT));
    await waitFor(() => expect(within(box).getByTestId('watchlist-feedback')).toHaveTextContent('已加入自选'), WAIT);
    expect(codes()).toContain('600002.SH');
    fireEvent.click(await within(box).findByTestId('watchlist-remove', undefined, WAIT));
    await waitFor(() => expect(within(box).getByTestId('watchlist-feedback')).toHaveTextContent('已移出自选'), WAIT);
    expect(await within(box).findByTestId('watchlist-add', undefined, WAIT)).toBeEnabled();
    expect(codes()).not.toContain('600002.SH');
  });
  it('个股页 409：页面加载后别处已加入 → 提示「已在自选」并按服务端纠正为移出自选', async () => {
    renderAt('/stocks/600002.SH');
    const box = await screen.findByTestId('watchlist-stock', undefined, WAIT);
    const btn = await within(box).findByTestId('watchlist-add', undefined, WAIT);
    await waitFor(() => expect(btn).toBeEnabled(), WAIT);
    expect((await post({ security_code: '600002.SH' })).status).toBe(201);
    fireEvent.click(btn);
    await waitFor(() => expect(within(box).getByTestId('watchlist-feedback')).toHaveTextContent('已在自选'), WAIT);
    expect(within(box).getByTestId('watchlist-feedback')).toHaveAttribute('data-kind', 'warn');
    expect(await within(box).findByTestId('watchlist-remove', undefined, WAIT)).toBeInTheDocument();
  });
  it('个股页 403：达到上限 → 提示上限与数值，按钮仍为加自选', async () => {
    setMockWatchlistCap(codes().length);
    renderAt('/stocks/600002.SH');
    const box = await screen.findByTestId('watchlist-stock', undefined, WAIT);
    const btn = await within(box).findByTestId('watchlist-add', undefined, WAIT);
    await waitFor(() => expect(btn).toBeEnabled(), WAIT);
    fireEvent.click(btn);
    const n = codes().length;
    await waitFor(() => expect(within(box).getByTestId('watchlist-feedback')).toHaveTextContent(`自选已达上限（${n}/${n} 只）`), WAIT);
    expect(within(box).getByTestId('watchlist-add')).toBeInTheDocument();
  });
  it('个股页 404：页面加载后别处已移出 → 提示已不在自选并纠正为加自选', async () => {
    renderAt('/stocks/600000.SH');
    const box = await screen.findByTestId('watchlist-stock', undefined, WAIT);
    const btn = await within(box).findByTestId('watchlist-remove', undefined, WAIT);
    expect((await del('600000.SH')).status).toBe(204);
    fireEvent.click(btn);
    await waitFor(() => expect(within(box).getByTestId('watchlist-feedback')).toHaveTextContent('该证券已不在自选中'), WAIT);
    expect(await within(box).findByTestId('watchlist-add', undefined, WAIT)).toBeInTheDocument();
  });
  it('个股页：指数不可加入（U1 保守默认），按钮禁用', async () => {
    renderAt('/stocks/000300.SH');
    const box = await screen.findByTestId('watchlist-stock', undefined, WAIT);
    expect(within(box).getByTestId('watchlist-add')).toBeDisabled();
  });
  it('今日关注：重点关注行有移出自选入口；我的自选列表可移出', async () => {
    renderAt('/today');
    const row = await screen.findByTestId('watchlist-focus-600000.SH', undefined, WAIT);
    expect(await within(row).findByTestId('watchlist-remove', undefined, WAIT)).toBeInTheDocument();
    const item = await screen.findByTestId('watchlist-item-300001.SZ', undefined, WAIT);
    fireEvent.click(within(item).getByTestId('watchlist-remove'));
    await waitFor(() => expect(screen.queryByTestId('watchlist-item-300001.SZ')).toBeNull(), WAIT);
    expect(codes()).not.toContain('300001.SZ');
  });
  it('今日关注：自选为空时显示空态', async () => {
    clearMockWatchlist();
    renderAt('/today');
    expect(await screen.findByTestId('today-watchlist-empty', undefined, WAIT)).toHaveTextContent('还没有自选股');
    expect(screen.getByTestId('today-watchlist-count')).toHaveTextContent('0 /');
  });
  it('持仓页：持仓行有加自选入口，点击后加入', async () => {
    renderAt('/portfolio');
    const cell = await screen.findByTestId('watchlist-pos-600002.SH', undefined, WAIT);
    const btn = await within(cell).findByTestId('watchlist-add', undefined, WAIT);
    await waitFor(() => expect(btn).toBeEnabled(), WAIT);
    fireEvent.click(btn);
    await waitFor(() => expect(within(cell).getByTestId('watchlist-feedback')).toHaveTextContent('已加入自选'), WAIT);
    expect(codes()).toContain('600002.SH');
  });
});
