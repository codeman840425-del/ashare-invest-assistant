/** P2N-05g：T-A31关键状态机与少量既有示例夹具字段对齐；仅MSW/注入流，无外网。 */
import { act, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { routes } from '../app/routes';
import { makeQueryClient } from '../app/queryClient';
import { preloadRoutes } from '../test/preloadRoutes';
import { advance, fakeClock } from '../test/timing';
import { streamRetryDelay, startEventStream } from '../lib/eventStream';
import { createStreamConsumer, parseStreamMessage } from '../app/streamEvents';
import { StreamPollingContext, streamConfig } from '../app/streamContext';
import { useUnreadCount, UNREAD_POLL_MS } from '../api/queries';
import { ENUMS } from '../api/enums';
import { latestNotifications, notificationRefRoute, notificationVersion, projectNotification } from '../lib/notifications';
import { exampleNotificationVersion, exampleOfflineNotification } from '../mocks/notificationStreamFixtures';
import { pushStreamReset } from '../mocks/streamHandlers';
import { markAllNotificationsRead, markNotificationRead, findNotification } from '../mocks/notificationStore';
import { uid } from '../mocks/fixtures';
import { server } from '../mocks/server';
vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div /> }));
beforeAll(() => preloadRoutes(routes), 30_000);
afterEach(() => Object.assign(streamConfig, { enabled: false, retryMs: undefined, maxRetryMs: undefined, idleTimeoutMs: undefined }));

it('version相同丢弃后来正文，即使updated_at更晚；旧记录默认version1', () => {
  const n = exampleNotificationVersion(2); const stale = { ...n, title: '示例数据：同version冲突正文', updated_at: '2026-11-02T12:00:00+08:00' };
  expect(latestNotifications([n, stale])[0].title).toBe(n.title);
  const { version, ...old } = exampleNotificationVersion(); expect(version).toBe(1); expect(projectNotification(old).version).toBe(1);
});
it('通知版本独立于是否加载列表；reset清空事件id缓存而非通知version，旧version仍丢弃', () => {
  const qc = new QueryClient(); const reset = vi.fn(); const consume = createStreamConsumer(qc, reset); const inv = vi.spyOn(qc, 'invalidateQueries');
  const n = exampleNotificationVersion(2); const frame = { id: '1', event: 'notification', data: JSON.stringify(n) }; consume(frame);
  consume({ ...frame, id: '2', data: JSON.stringify({ ...n, title: '示例数据：同版本应丢弃' }) }); expect(inv).toHaveBeenCalledTimes(1);
  consume({ id: '2', event: 'reset', data: JSON.stringify({ reason: 'expired', latest_event_id: '7' }) });
  expect(reset).toHaveBeenCalledWith({ reason: 'expired', latest_event_id: '7' });
  consume({ ...frame, data: JSON.stringify(exampleNotificationVersion(3)) }); expect(inv).toHaveBeenCalledTimes(2); expect(notificationVersion(qc, n.id)).toBe(5); qc.clear();
});
it('read/read-all只在行实际变化时自增version，重复已读不再增', () => {
  const n = findNotification(uid(901))!; const v = n.version;
  markNotificationRead(n.id); expect(findNotification(n.id)?.version).toBe(v + 1); markNotificationRead(n.id); expect(findNotification(n.id)?.version).toBe(v + 1);
  const another = findNotification(uid(903))!; markAllNotificationsRead(); expect(findNotification(another.id)?.version).toBe(another.version + 1);
  markAllNotificationsRead(); expect(findNotification(another.id)?.version).toBe(another.version + 1);
});
it('引用枚举/小写uuid与服务端深链；signal/null不跳，不从条件id猜plan_id', () => {
  expect(ENUMS.notification_ref_type).toEqual(['signal', 'plan_condition']);
  const ref = exampleNotificationVersion().refs[0]; expect(notificationRefRoute(ref)).toBe(`/plans/${uid(7301)}`);
  expect(notificationRefRoute({ ...ref, route: null })).toBeNull(); expect(notificationRefRoute({ ...ref, route: 'https://example.invalid/plans/TEST' })).toBeNull();
  expect(notificationRefRoute(exampleOfflineNotification().refs[0])).toBeNull();
});
it.each([{ version: 0 }, { refs: [{ type: 'future', id: uid(1), at: '2026-11-02T10:00:00Z', route: null }] }, { refs: [{ type: 'signal', id: 'BAD-ID', at: '2026-11-02T10:00:00Z', route: null }] }])('非法version/ref边界丢弃：%j', (bad) => {
  expect(parseStreamMessage({ id: '1', event: 'notification', data: JSON.stringify({ ...exampleNotificationVersion(), ...bad }) })).toBeNull();
});
it.each(['not-decimal', '999'])('MSW首发retry3000，未知Last-Event-ID=%s先发reset且HTTP200', async (id) => {
  const ctrl = new AbortController();
  try {
    const res = await fetch('/api/v1/stream', { headers: { 'Last-Event-ID': id }, signal: ctrl.signal }); expect(res.status).toBe(200);
    const first = await res.body!.getReader().read(); const text = new TextDecoder().decode(first.value);
    expect(text.startsWith('retry: 3000')).toBe(true); expect(text).toContain('event: reset'); expect(text).toContain('"reason":"unknown"');
  } finally { ctrl.abort(); }
});
it('reset重新读取所有通知游标页与未读数，不只读取未读筛选', async () => {
  Object.assign(streamConfig, { enabled: true, retryMs: 20, maxRetryMs: 40, idleTimeoutMs: 2000 }); let offline = false; const paths: string[] = [];
  const first = exampleNotificationVersion(); const extra = exampleOfflineNotification();
  server.use(http.get('*/api/v1/notifications', ({ request }) => {
    const u = new URL(request.url); paths.push(u.search); const unread = u.searchParams.get('unread') === 'true'; const cursor = u.searchParams.get('cursor');
    return HttpResponse.json({ items: cursor ? offline ? [extra] : [] : [first], next_cursor: unread || cursor ? null : 'example-full-next' });
  }), http.get('*/api/v1/notifications/unread-count', () => HttpResponse.json({ count: offline ? 2 : 1 })));
  const qc = makeQueryClient(true); const router = createMemoryRouter(routes, { initialEntries: ['/notifications'] });
  render(<AppProviders client={qc}><RouterProvider router={router} /></AppProviders>);
  await waitFor(() => expect(screen.getByTestId('notification-recovery')).toHaveTextContent('已补读')); const before = paths.length;
  act(() => { offline = true; pushStreamReset('expired'); });
  await screen.findByTestId(`nc-item-${extra.id}`); await waitFor(() => expect(screen.getByTestId('notification-recovery')).toHaveTextContent('已补读'));
  expect(paths.slice(before).some((q) => q.includes('cursor=example-full-next') && !q.includes('unread=true'))).toBe(true);
  expect(screen.getByTestId('unread-badge')).toHaveAttribute('data-count', '2');
});
it('抖动±20%且不越60秒上限', () => {
  expect(streamRetryDelay(3000, 0, 60000, () => 0)).toBe(2400); expect(streamRetryDelay(3000, 0, 60000, () => 1)).toBe(3600);
  expect(streamRetryDelay(3000, 20, 60000, () => 1)).toBe(60000);
});
it('连续3次503建流失败开启轮询；继续指数退避；连上即关闭轮询', async () => {
  fakeClock(); const polls: boolean[] = []; const delays: number[] = []; let calls = 0;
  const fetchImpl: typeof fetch = async (_url, init) => {
    calls++; if (calls <= 3) return new Response(null, { status: 503 });
    return new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode('retry: 3000\n\n')); init?.signal?.addEventListener('abort', () => c.error(new Error('stopped'))); } }), { headers: { 'Content-Type': 'text/event-stream' } });
  };
  const h = startEventStream({ fetchImpl, random: () => 0.5, onMessage: () => undefined, onPolling: (v) => polls.push(v), onRetry: (v) => delays.push(v.delayMs) });
  try {
    await advance(0); expect(polls).toEqual([false]); await advance(3000); expect(polls).toEqual([false]); await advance(6000); expect(polls).toEqual([false, true]);
    expect(delays).toEqual([3000, 6000, 12000]); await advance(12000); expect(h.state()).toBe('open'); expect(polls.at(-1)).toBe(false);
  } finally { h.stop(); }
});
it('短连接不归零退避，持续收到心跳保持60秒后才归零', async () => {
  fakeClock(); let calls = 0; const delays: number[] = []; const failures: number[] = []; const close: (() => void)[] = [];
  const fetchImpl: typeof fetch = async (_url, init) => {
    if (++calls === 1) return new Response(null, { status: 503 });
    return new Response(new ReadableStream({ start(c) {
      c.enqueue(new TextEncoder().encode('retry: 3000\n\n'));
      const timer = setInterval(() => c.enqueue(new TextEncoder().encode(': heartbeat\n\n')), 15000);
      close.push(() => { clearInterval(timer); c.close(); }); init?.signal?.addEventListener('abort', () => { clearInterval(timer); c.error(new Error('stopped')); });
    } }), { headers: { 'Content-Type': 'text/event-stream' } });
  };
  const h = startEventStream({ fetchImpl, random: () => 0.5, onMessage: () => undefined, onRetry: (v) => { delays.push(v.delayMs); failures.push(v.failures); } });
  try {
    await advance(0); await advance(3000); close[0](); await advance(0); expect(delays).toEqual([3000, 6000]);
    await advance(6000); await advance(60000); close[1](); await advance(0); expect(delays).toEqual([3000, 6000, 3000]); expect(failures).toEqual([1, 2, 0]);
  } finally { h.stop(); }
});
it('轮询门控只改变定时器，保持权威初始计数读取；开启后间隔15秒', () => {
  const qc = makeQueryClient(true); let polling = false;
  const { rerender, unmount } = renderHook(() => useUnreadCount(), { wrapper: ({ children }) => <QueryClientProvider client={qc}><StreamPollingContext.Provider value={polling}>{children}</StreamPollingContext.Provider></QueryClientProvider> });
  const query = () => qc.getQueryCache().find({ queryKey: ['notifications', 'unread-count'] })!;
  expect(query().observers[0].options.refetchInterval).toBe(false); polling = true; rerender(); expect(query().observers[0].options.refetchInterval).toBe(UNREAD_POLL_MS); expect(UNREAD_POLL_MS).toBe(15000); unmount(); qc.clear();
});

it('事件id缓存固定1024先进先出，不持久化；第一个id被淘汰后可重新消费', () => {
  const qc = new QueryClient(); const inv = vi.spyOn(qc, 'invalidateQueries'); const consume = createStreamConsumer(qc);
  for (let i = 1; i <= 1025; i++) consume({ id: String(i), event: 'report', data: '{"date":"2026-11-02"}' });
  const before = inv.mock.calls.length; consume({ id: '1', event: 'report', data: '{"date":"2026-11-02"}' }); expect(inv.mock.calls.length).toBe(before + 3); qc.clear();
});
it('45秒无任何字节主动断开；reset不把latest冒充已收到事件，下一连接不带旧游标', async () => {
  // 精确断言 44999/45000ms 边界；此纯注入流用例只允许显式推进时钟。
  vi.useFakeTimers({ shouldAdvanceTime: false, toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
  let calls = 0; const cursors: (string | null)[] = [];
  const fetchImpl: typeof fetch = async (_url, init) => {
    calls++; cursors.push(new Headers(init?.headers).get('Last-Event-ID'));
    return new Response(new ReadableStream({ start(c) {
      const data = calls === 1 ? 'id: 1\nevent: report\ndata: {"date":"2026-11-02"}\n\nevent: reset\ndata: {"reason":"unknown","latest_event_id":"7"}\n\n' : ': connected\n\n';
      c.enqueue(new TextEncoder().encode(data)); init?.signal?.addEventListener('abort', () => c.error(new Error('stopped')));
    } }), { headers: { 'Content-Type': 'text/event-stream' } });
  };
  const h = startEventStream({ fetchImpl, random: () => 0.5, onMessage: () => undefined });
  try {
    await advance(0); expect(h.lastEventId()).toBeNull(); await advance(44999); expect(h.state()).toBe('open');
    await advance(1); expect(h.state()).toBe('retrying'); await advance(3000); expect(cursors).toEqual([null, null]);
  } finally { h.stop(); }
});

// P2N-05h：T-A32两项裁定，不包含AI解释工作。
it('T-A32 非200、200后EOF、45秒读超时连续累计到3次，期间建流成功不归零', async () => {
  fakeClock(); let calls = 0; const failures: number[] = []; const polls: boolean[] = [];
  const fetchImpl: typeof fetch = async (_url, init) => {
    calls++; if (calls === 1) return new Response(null, { status: 503 });
    return new Response(new ReadableStream({ start(c) {
      if (calls === 2) { c.close(); return; }
      c.enqueue(new TextEncoder().encode(': open\n\n')); init?.signal?.addEventListener('abort', () => c.error(new Error('stopped')));
    } }), { headers: { 'Content-Type': 'text/event-stream' } });
  };
  const h = startEventStream({ fetchImpl, random: () => 0.5, onMessage: () => undefined, onPolling: (v) => polls.push(v), onRetry: (v) => failures.push(v.failures) });
  try {
    await advance(0); await advance(3000); expect(failures).toEqual([1, 2]); await advance(6000); expect(h.state()).toBe('open');
    await advance(44999); expect(failures).toEqual([1, 2]); await advance(1); expect(failures).toEqual([1, 2, 3]); expect(polls.at(-1)).toBe(true);
  } finally { h.stop(); }
});
it('T-A32 signal/null引用只显示类型与at，不显示id/不拼按时点定位链接，保留总入口', async () => {
  streamConfig.enabled = false; const n = exampleOfflineNotification(); const ref = n.refs[0];
  server.use(http.get('*/api/v1/notifications', () => HttpResponse.json({ items: [n], next_cursor: null })), http.get('*/api/v1/notifications/unread-count', () => HttpResponse.json({ count: 1 })));
  const router = createMemoryRouter(routes, { initialEntries: ['/notifications'] }); render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  const refs = await screen.findByTestId(`nc-refs-${n.id}`); expect(refs).toHaveTextContent('signal'); expect(refs).toHaveTextContent('10:50'); expect(refs).not.toHaveTextContent(ref.id);
  const links = within(refs).getAllByRole('link'); expect(links).toHaveLength(1); expect(links[0]).toHaveAttribute('href', '/signals'); expect(refs.innerHTML).not.toContain('since=');
});
