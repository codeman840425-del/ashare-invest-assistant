/** P2N-05f：DeepSeek提供纯合成场景初稿，执行者按冻结契约重写真实断言；全由MSW拦截，无外网。 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { QueryClient } from '@tanstack/react-query';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { streamConfig } from '../app/streamContext';
import { createStreamConsumer, parseStreamMessage } from '../app/streamEvents';
import { readUnreadNotifications } from '../api/notificationQueries';
import { latestNotifications, projectNotification } from '../lib/notifications';
import { exampleNotificationVersion, exampleOfflineNotification } from '../mocks/notificationStreamFixtures';
import { addMockNotification, allNotifications, findNotification, markNotificationRead } from '../mocks/notificationStore';
import { dropStreamConnections, pushStreamEvent, streamConnectionCount, streamRequests, STREAM_RETENTION_MS } from '../mocks/streamHandlers';
import { mockLoginAs } from '../mocks/session';
import { uid } from '../mocks/fixtures';
import { server } from '../mocks/server';
import type { Notification, Paged } from '../api/types';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div /> }));
beforeAll(() => preloadRoutes(routes), 30_000);
beforeEach(() => Object.assign(streamConfig, { enabled: true, retryMs: 40, maxRetryMs: 80, idleTimeoutMs: 2_000 }));
afterEach(() => Object.assign(streamConfig, { enabled: false, retryMs: undefined, maxRetryMs: undefined, idleTimeoutMs: undefined }));
function renderAt() {
  const qc = makeQueryClient(true); const router = createMemoryRouter(routes, { initialEntries: ['/notifications'] });
  render(<AppProviders client={qc}><RouterProvider router={router} /></AppProviders>); return qc;
}
const badge = () => Number(screen.getByTestId('unread-badge').getAttribute('data-count'));
const unreadRows = () => allNotifications().filter((n) => n.read_at === null);
const opened = () => waitFor(() => expect(screen.getByTestId('stream-status')).toHaveAttribute('data-state', 'open'));
const completed = () => waitFor(() => expect(screen.getByTestId('notification-recovery')).toHaveTextContent('已补读'));

it('旧记录投影严格为count1、updated=created、refs空，不计算合并窗', () => {
  const n = exampleNotificationVersion(); const { merged_count, updated_at, refs, ...legacy } = n;
  expect(merged_count).toBe(1); expect(updated_at).toBe(n.created_at); expect(refs).toHaveLength(1);
  expect(projectNotification(legacy)).toMatchObject({ merged_count: 1, updated_at: n.created_at, refs: [] });
});
it('跨页同id只看version，updated_at更晚不代表更新，仍按created排序', () => {
  const old = { ...exampleNotificationVersion(), updated_at: '2026-11-02T10:42:00+08:00' };
  const newer = { ...exampleNotificationVersion(2), updated_at: '2026-11-02T10:41:00+08:00' };
  const another = { ...exampleNotificationVersion(), id: uid(9899), security_code: '600001.SH', name: 'TEST示例另一证券', created_at: '2026-11-02T10:40:30+08:00' };
  const rows = latestNotifications([old, another, newer, old]); expect(rows).toHaveLength(2);
  expect(rows[0].id).toBe(another.id); expect(rows[1].merged_count).toBe(2);
});
it('同id新事件整行重新未读，相同/旧版本重放不撤销已读；未读按行不按merged_count', () => {
  const base = unreadRows().length; const n = exampleNotificationVersion();
  addMockNotification(n); markNotificationRead(n.id, '2026-11-02T10:40:30+08:00'); expect(unreadRows()).toHaveLength(base);
  addMockNotification(exampleNotificationVersion(2)); expect(unreadRows()).toHaveLength(base + 1);
  markNotificationRead(n.id, '2026-11-02T10:41:30+08:00'); addMockNotification(exampleNotificationVersion(2)); addMockNotification(n);
  expect(findNotification(n.id)?.read_at).toBe('2026-11-02T10:41:30+08:00'); expect(allNotifications().filter((r) => r.id === n.id)).toHaveLength(1);
});
it('事件id重复只消费一次，旧notification版本不覆盖缓存，不自增计数', () => {
  const qc = new QueryClient(); const n = exampleNotificationVersion();
  qc.setQueryData(['notifications', 'pages', { unread: false, kind: null }], { pages: [{ items: [n], next_cursor: null }], pageParams: [null] });
  qc.setQueryData(['notifications', 'unread-count'], { count: 7 }); const consume = createStreamConsumer(qc); const inv = vi.spyOn(qc, 'invalidateQueries');
  const frame = { id: '1', event: 'notification', data: JSON.stringify(exampleNotificationVersion(2)) }; consume(frame); consume(frame); expect(inv).toHaveBeenCalledTimes(1);
  consume({ ...frame, id: '2', data: JSON.stringify(n) });
  const data = qc.getQueryData<{ pages: Paged<Notification>[] }>(['notifications', 'pages', { unread: false, kind: null }]);
  expect(data?.pages[0].items[0].merged_count).toBe(2); expect(qc.getQueryData(['notifications', 'unread-count'])).toEqual({ count: 7 }); qc.clear();
});
it.each([{ merged_count: 0 }, { refs: null }, { severity: 'critical' }, { target: '/guessed-path' }])('畸形notification结构丢弃：%j', (bad) => {
  expect(parseStreamMessage({ id: '1', event: 'notification', data: JSON.stringify({ ...exampleNotificationVersion(), ...bad }) })).toBeNull();
});
it('MSW→真实SSE消费→React显示合并次数/更新时间/原始refs；同id新版本只增加一行未读', async () => {
  const baseline = unreadRows().length; renderAt(); await opened(); await completed();
  const n = exampleNotificationVersion(); act(() => { pushStreamEvent('notification', n); }); await screen.findByTestId(`nc-item-${n.id}`);
  act(() => { pushStreamEvent('notification', exampleNotificationVersion(2)); });
  await waitFor(() => expect(screen.getByTestId(`nc-merged-${n.id}`)).toHaveTextContent('合并 2 次变化'));
  expect(screen.getByTestId(`nc-updated-${n.id}`)).toHaveTextContent('10:41'); expect(screen.getAllByTestId(`nc-item-${n.id}`)).toHaveLength(1);
  await waitFor(() => expect(badge()).toBe(baseline + 1));
  const refs = screen.getByTestId(`nc-refs-${n.id}`); fireEvent.click(within(refs).getByText(/合并引用/));
  expect(within(refs).getAllByRole('listitem')).toHaveLength(2); expect(refs).toHaveTextContent('计划条件引用');
  expect(within(refs).getByRole('link', { name: '查看完整盘中规则事件' })).toHaveAttribute('href', '/signals');
  fireEvent.click(screen.getByTestId(`nc-read-${n.id}`)); await waitFor(() => expect(badge()).toBe(baseline));
  act(() => { pushStreamEvent('notification', exampleNotificationVersion(3)); });
  await waitFor(() => expect(screen.getByTestId(`nc-merged-${n.id}`)).toHaveTextContent('合并 3 次变化')); await waitFor(() => expect(badge()).toBe(baseline + 1));
  expect(screen.getByText(/示例数据 · 提醒流仅为MSW/)).toBeInTheDocument();
});
it('首次无ID也补读；超过600秒续传窗后带旧ID重连，仍由本人列表补齐离线通知', async () => {
  let unreadReads = 0;
  server.use(http.get('*/api/v1/notifications', ({ request }) => {
    const unread = new URL(request.url).searchParams.get('unread') === 'true'; if (unread) unreadReads++;
    return HttpResponse.json({ items: unread ? unreadRows() : allNotifications(), next_cursor: null });
  }));
  renderAt(); await opened(); await completed(); expect(unreadReads).toBeGreaterThan(0);
  const first = exampleNotificationVersion(); act(() => { pushStreamEvent('notification', first); }); await screen.findByTestId(`nc-item-${first.id}`);
  const before = unreadReads; const missed = exampleOfflineNotification();
  const now = Date.now(); const clock = vi.spyOn(Date, 'now');
  try {
    act(() => { dropStreamConnections(); pushStreamEvent('notification', missed); clock.mockReturnValue(now + STREAM_RETENTION_MS + 1); });
    await waitFor(() => expect(streamRequests.length).toBeGreaterThan(1)); await opened(); await completed();
    expect(streamRequests[1]).toBe('1'); expect(unreadReads).toBeGreaterThan(before); expect(await screen.findByTestId(`nc-item-${missed.id}`)).toBeInTheDocument();
    expect(badge()).toBe(unreadRows().length);
  } finally { clock.mockRestore(); }
});
it('补读遍历不透明游标到末页，跨页重复只保留较新的同id版本', async () => {
  const seen: (string | null)[] = [];
  server.use(http.get('*/api/v1/notifications', ({ request }) => {
    const u = new URL(request.url); expect(u.searchParams.get('unread')).toBe('true'); const cursor = u.searchParams.get('cursor'); seen.push(cursor);
    return HttpResponse.json({ items: [exampleNotificationVersion(cursor ? 2 : 1)], next_cursor: cursor ? null : 'example-page-2' });
  }));
  const rows = await readUnreadNotifications(); expect(seen).toEqual([null, 'example-page-2']); expect(rows).toHaveLength(1); expect(rows[0].merged_count).toBe(2);
});
it('补读失败不会宣称已补齐；提供手动补读重试，不影响连接状态', async () => {
  let fail = true;
  server.use(http.get('*/api/v1/notifications', ({ request }) => {
    if (new URL(request.url).searchParams.get('unread') === 'true' && fail) return HttpResponse.json({ error: { code: 'MAINTENANCE', message: '示例数据：补读暂不可用', details: null, request_id: 'example' } }, { status: 503 });
    return HttpResponse.json({ items: allNotifications(), next_cursor: null });
  }));
  renderAt(); await opened(); expect(await screen.findByText('离线补读失败，数据可能不完整')).toBeInTheDocument(); fail = false;
  fireEvent.click(screen.getByRole('button', { name: '重新补读' })); await completed();
});
it('示例通知列表及SSE重放只属于当前用户，不向其他会话补发', async () => {
  pushStreamEvent('notification', exampleNotificationVersion(), uid(2)); mockLoginAs('admin');
  expect(allNotifications().some((n) => n.id === uid(9801))).toBe(false);
  const ctrl = new AbortController();
  try {
    const response = await fetch('/api/v1/stream', { headers: { 'Last-Event-ID': '0' }, signal: ctrl.signal });
    const first = await response.body!.getReader().read(); const text = new TextDecoder().decode(first.value);
    expect(text).toContain('connected'); expect(text).not.toContain('候选信号事实变化');
  } finally { ctrl.abort(); }
  await waitFor(() => expect(streamConnectionCount()).toBe(0));
});
