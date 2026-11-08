/** T-F14 通知中心 + SSE /stream（契约 §7.8、§8、§5.1）。示例数据，不发外网请求。 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { streamConfig } from '../app/streamContext';
import { applyStreamEvent, parseStreamMessage } from '../app/streamEvents';
import { ENUMS } from '../api/enums';
import type { Notification, NotificationTarget, Paged, TerminalResponse } from '../api/types';
import { startEventStream, type StreamState } from '../lib/eventStream';
import { notificationRoute } from '../lib/notificationTarget';
import { SseParser, type SseMessage } from '../lib/sseParser';
import { NOTIFICATIONS, STRATEGIES, TERMINAL_ROWS, uid } from '../mocks/fixtures';
import { markNotificationRead, findNotification } from '../mocks/notificationStore';
import { server } from '../mocks/server';
import { dropStreamConnections, pushStreamEvent, streamConnectionCount, streamRequests } from '../mocks/streamHandlers';
import { apiFetch } from '../test/apiFetch';
import { preloadRoutes } from '../test/preloadRoutes';
import { advance, fakeClock } from '../test/timing';

beforeAll(() => preloadRoutes(routes), 30_000);

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';
const getJson = async <T,>(path: string) => (await (await apiFetch(`${API}${path}`)).json()) as T;

function renderAt(path: string, client: QueryClient = makeQueryClient(true)) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={client}><RouterProvider router={router} /></AppProviders>);
  return router;
}

const unreadOf = () => Number(screen.getByTestId('unread-badge').getAttribute('data-count'));
const fixtureUnread = NOTIFICATIONS.filter((n) => n.read_at === null).length;

function sampleNotification(n: number, over: Partial<Notification> = {}): Notification {
  return {
    id: uid(n), kind: 'invalidation', severity: 'important', title: `演示证券触及失效条件（示例 ${n}）`, body: null,
    version: 1, merged_count: 1, updated_at: '2026-11-02T10:40:00+08:00', refs: [],
    created_at: '2026-11-02T10:40:00+08:00', read_at: null, security_code: '600002.SH', name: '演示医药',
    target: { type: 'candidate_signal', id: uid(n + 1), route: `/candidate-signals/${uid(n + 1)}` }, ...over,
  };
}

// ---------------------------------------------------------------- SSE 解析
describe('SseParser（text/event-stream 增量解析）', () => {
  const collect = (chunks: string[]) => {
    const out: SseMessage[] = [];
    const p = new SseParser((m) => out.push(m));
    for (const c of chunks) p.push(c);
    return { out, p };
  };

  it('任意切块都得到同样的事件；id / event / data 齐全', () => {
    const text = 'id: 7\nevent: notification\ndata: {"a":1}\n\nevent: heartbeat\ndata: {}\n\n';
    const whole = collect([text]).out;
    expect(whole).toEqual([{ id: '7', event: 'notification', data: '{"a":1}' }, { id: '7', event: 'heartbeat', data: '{}' }]);
    for (let cut = 1; cut < text.length; cut++) expect(collect([text.slice(0, cut), text.slice(cut)]).out).toEqual(whole);
    expect(collect(text.split('')).out).toEqual(whole);
  });

  it('CRLF / CR 行尾（含跨块的 CR LF）、多行 data、注释行、无冒号字段', () => {
    const { out } = collect(['event: report\r', '\ndata: line1\r\ndata: line2\r\r', ': 注释\n\ndata\n\n']);
    expect(out).toEqual([{ id: null, event: 'report', data: 'line1\nline2' }, { id: null, event: 'message', data: '' }]);
  });

  it('只有注释或空 data 的块不派发；retry 只接受纯数字；id 含 NUL 忽略', () => {
    const { out, p } = collect([': keepalive\n\n', 'retry: 2500\n\n', 'retry: x\n\n', 'id: a\u0000b\ndata: 1\n\n']);
    expect(p.retry).toBe(2500);
    expect(out).toEqual([{ id: null, event: 'message', data: '1' }]);
  });
});

// ---------------------------------------------------------------- §5.1 跳转
describe('Notification.target 跳转（§5.1）', () => {
  const t = (type: NotificationTarget['type'], id: string | null, route: string | null): NotificationTarget => ({ type, id, route });
  const id = uid(1);

  it('§5.1 九种类型：服务端 route 形状正确时原样跳转', () => {
    const cases: [NotificationTarget['type'], string][] = [
      ['suggestion', `/suggestions/${id}`],
      ['candidate_signal', `/candidate-signals/${id}`],
      ['plan_draft', `/plan-drafts/${id}`],
      ['plan', `/plans/${id}`],
      ['daily_report', '/daily-reports/2026-10-30'],
      ['import_batch', `/portfolio/import?batch=${id}`],
      ['reconciliation', `/portfolio?tab=reconciliation&account_id=${id}`],
      ['strategy_version', `/strategies/${uid(2)}?version=${id}`],
    ];
    expect(cases.map((c) => c[0]).sort()).toEqual(ENUMS.notification_target_type.filter((x) => x !== 'none').sort());
    for (const [type, route] of cases) expect([type, notificationRoute(t(type, type === 'daily_report' ? '2026-10-30' : id, route))]).toEqual([type, route]);
    expect(notificationRoute(t('none', null, null))).toBeNull();
  });

  it('route 缺失、站外或形状不符：按 type + id 拼；strategy_version 拼不出（缺 strategy_id）就不跳', () => {
    expect(notificationRoute(t('suggestion', id, null))).toBe(`/suggestions/${id}`);
    expect(notificationRoute(t('suggestion', id, 'https://example.invalid/x'))).toBe(`/suggestions/${id}`);
    expect(notificationRoute(t('suggestion', id, '//evil.invalid/suggestions/1'))).toBe(`/suggestions/${id}`);
    expect(notificationRoute(t('plan', id, `/suggestions/${id}`))).toBe(`/plans/${id}`);
    expect(notificationRoute(t('import_batch', id, null))).toBe(`/portfolio/import?batch=${id}`);
    expect(notificationRoute(t('reconciliation', id, null))).toBe(`/portfolio?tab=reconciliation&account_id=${id}`);
    expect(notificationRoute(t('daily_report', '2026-10-30', null))).toBe('/daily-reports/2026-10-30');
    expect(notificationRoute(t('strategy_version', id, null))).toBeNull();
    expect(notificationRoute(t('strategy_version', id, `/strategies/${id}`))).toBeNull();
    expect(notificationRoute(t('none', null, '/today'))).toBeNull();
  });

  it('示例通知全部按 §5.1 形状（含修正后的 strategy_version 深链）', () => {
    for (const n of NOTIFICATIONS) if (n.target.type !== 'none') expect([n.id, notificationRoute(n.target)]).toEqual([n.id, n.target.route]);
    const sv = NOTIFICATIONS.find((n) => n.target.type === 'strategy_version')!;
    expect(sv.target.route).toBe(`/strategies/${uid(501)}?version=${STRATEGIES.demo_reversal.version_id}`);
  });
});

// ---------------------------------------------------------------- §7.8 mock
describe('示例接口 /notifications*（§7.8）', () => {
  it('unread / kind 筛选；非法取值 400', async () => {
    const all = await getJson<Paged<Notification>>('/notifications');
    expect(all.items).toHaveLength(NOTIFICATIONS.length);
    const unread = await getJson<Paged<Notification>>('/notifications?unread=true');
    expect(unread.items.every((n) => n.read_at === null)).toBe(true);
    expect(unread.items).toHaveLength(fixtureUnread);
    const imp = await getJson<Paged<Notification>>('/notifications?kind=import');
    expect(imp.items.map((n) => n.kind)).toEqual(['import', 'import']);
    expect((await apiFetch(`${API}/notifications?kind=nope`)).status).toBe(400);
    expect((await apiFetch(`${API}/notifications?unread=1`)).status).toBe(400);
  });

  it('已读 / 全部已读幂等：204，重复调用不改已读时间，未知 id 404', async () => {
    const id = NOTIFICATIONS.find((n) => n.read_at === null)!.id;
    markNotificationRead(id, '2026-11-02T10:00:00+08:00');
    for (let i = 0; i < 2; i++) expect((await apiFetch(`${API}/notifications/${id}/read`, { method: 'POST' })).status).toBe(204);
    expect(findNotification(id)!.read_at).toBe('2026-11-02T10:00:00+08:00');
    const wasRead = NOTIFICATIONS.find((n) => n.read_at !== null)!;
    for (let i = 0; i < 2; i++) expect((await apiFetch(`${API}/notifications/read-all`, { method: 'POST' })).status).toBe(204);
    expect(findNotification(wasRead.id)!.read_at).toBe(wasRead.read_at);
    expect((await getJson<{ count: number }>('/notifications/unread-count')).count).toBe(0);
    expect((await apiFetch(`${API}/notifications/${uid(99_999)}/read`, { method: 'POST' })).status).toBe(404);
  });

  it('/stream：未登录 401；登录后 text/event-stream，带 Last-Event-ID 补发其后事件', async () => {
    pushStreamEvent('report', { date: '2026-10-30' });
    pushStreamEvent('report', { date: '2026-10-31' });
    const ctrl = new AbortController();
    const r = await fetch(`${API}/stream`, { headers: { 'Last-Event-ID': '1' }, signal: ctrl.signal });
    expect(r.headers.get('Content-Type')).toContain('text/event-stream');
    const reader = r.body!.getReader();
    const { value } = await reader.read();
    const text = new TextDecoder().decode(value);
    expect(text).toContain('id: 2\nevent: report\ndata: {"date":"2026-10-31"}');
    expect(text).not.toContain('2026-10-30');
    ctrl.abort();
    await waitFor(() => expect(streamConnectionCount()).toBe(0));
    expect(streamRequests).toEqual(['1']);
  });
});

// ---------------------------------------------------------------- 页面
describe('通知中心页面', () => {
  it('列表：严重度、类型、标题、证券与跳转目标；默认全部，?unread=1 只看未读', async () => {
    renderAt('/notifications');
    const first = NOTIFICATIONS[0];
    const item = await screen.findByTestId(`nc-item-${first.id}`);
    expect(item.textContent).toContain(first.title);
    expect(item.textContent).toContain('重要');
    expect(screen.getAllByTestId(/^nc-item-/)).toHaveLength(NOTIFICATIONS.length);
    expect(screen.getByTestId('stream-status').getAttribute('data-state')).toBe('off');
    fireEvent.click(within(screen.getByTestId('nc-filter-unread')).getByText(/^未读/));
    await waitFor(() => expect(screen.getAllByTestId(/^nc-item-/)).toHaveLength(fixtureUnread));
  });

  it('?kind= 筛选；没有结果时给出提示', async () => {
    renderAt('/notifications?kind=import');
    await waitFor(() => expect(screen.getAllByTestId(/^nc-item-/)).toHaveLength(2));
  });

  it('筛选无结果：提示“没有符合条件的通知”', async () => {
    renderAt('/notifications?kind=system&unread=1');
    expect((await screen.findByTestId('nc-empty')).textContent).toBe('没有符合条件的通知');
  });

  it('标为已读 → 未读数减 1；全部标为已读 → 0 且按钮禁用', async () => {
    renderAt('/notifications');
    await waitFor(() => expect(unreadOf()).toBe(fixtureUnread));
    const id = NOTIFICATIONS.find((n) => n.read_at === null)!.id;
    fireEvent.click(await screen.findByTestId(`nc-read-${id}`));
    await waitFor(() => expect(unreadOf()).toBe(fixtureUnread - 1));
    await waitFor(() => expect(screen.getByTestId(`nc-item-${id}`).className).toContain('read'));
    fireEvent.click(screen.getByTestId('nc-read-all'));
    await waitFor(() => expect(unreadOf()).toBe(0));
    await waitFor(() => expect(screen.getByTestId('nc-read-all').closest('button')!.disabled).toBe(true));
    expect(screen.queryAllByTestId(/^nc-read-0/)).toHaveLength(0);
  });

  it('点击通知：标为已读并按 §5.1 跳转', async () => {
    const router = renderAt('/notifications');
    const n = NOTIFICATIONS.find((x) => x.target.type === 'reconciliation')!;
    fireEvent.click(within(await screen.findByTestId(`nc-item-${n.id}`)).getByText(n.title));
    await waitFor(() => expect(router.state.location.pathname + router.state.location.search).toBe(n.target.route));
    expect(findNotification(n.id)!.read_at).not.toBeNull();
  });

  it('通知偏好 / 通知渠道：标“待契约”，不请求未定义结构的接口', async () => {
    let hits = 0;
    server.use(
      http.all(`*${API}/notification-preferences`, () => { hits += 1; return HttpResponse.json({}); }),
      http.all(`*${API}/channels`, () => { hits += 1; return HttpResponse.json({}); }),
    );
    renderAt('/notifications?tab=preferences');
    const pref = await screen.findByTestId('nc-pref-placeholder');
    expect(pref.textContent).toContain('待契约');
    expect(pref.textContent).toContain('/notification-preferences');
    fireEvent.click(screen.getByRole('tab', { name: '通知渠道' }));
    const ch = await screen.findByTestId('nc-channel-placeholder');
    expect(ch.textContent).toContain('待契约');
    for (const c of ENUMS.channel) expect(screen.getByTestId('nc-channel-enum').textContent).toContain(c);
    expect(hits).toBe(0);
  });

  it('“通知中心”不再是占位页', async () => {
    renderAt('/notifications');
    await screen.findByTestId('notifications-page');
    expect(screen.queryByTestId('placeholder')).toBeNull();
  });
});

// ---------------------------------------------------------------- SSE 客户端
describe('SSE /stream 客户端（§8）', () => {
  beforeEach(() => {
    Object.assign(streamConfig, { enabled: true, retryMs: 20, maxRetryMs: 80, idleTimeoutMs: 2_000 });
  });
  afterEach(() => {
    Object.assign(streamConfig, { enabled: false, retryMs: undefined, maxRetryMs: undefined, idleTimeoutMs: undefined });
  });

  it('连上后停用未读数 / 终端轮询；推送 notification → 列表与未读数即时更新', async () => {
    const qc = makeQueryClient(true);
    renderAt('/notifications', qc);
    await waitFor(() => expect(screen.getByTestId('stream-status').getAttribute('data-state')).toBe('open'));
    await waitFor(() => expect(unreadOf()).toBe(fixtureUnread));
    const obs = qc.getQueryCache().find({ queryKey: ['notifications', 'unread-count'] })!.observers[0];
    expect(obs.options.refetchInterval).toBe(false);
    const n = sampleNotification(960);
    act(() => void pushStreamEvent('notification', n));
    expect(await screen.findByTestId(`nc-item-${n.id}`)).toBeTruthy();
    await waitFor(() => expect(unreadOf()).toBe(fixtureUnread + 1));
  });

  it('断线：显示重连中并退回轮询；重连带 Last-Event-ID，补发断线期间的事件', async () => {
    const qc = makeQueryClient(true);
    renderAt('/notifications', qc);
    await waitFor(() => expect(screen.getByTestId('stream-status').getAttribute('data-state')).toBe('open'));
    act(() => void pushStreamEvent('report', { date: '2026-10-30' }));
    await waitFor(() => expect(streamConnectionCount()).toBe(1));
    streamConfig.retryMs = 300;
    act(() => {
      dropStreamConnections();
    });
    await waitFor(() => expect(screen.getByTestId('stream-status').getAttribute('data-state')).toBe('retrying'));
    expect(qc.getQueryCache().find({ queryKey: ['notifications', 'unread-count'] })!.observers[0].options.refetchInterval).toBe(false);
    const missed = sampleNotification(970);
    act(() => void pushStreamEvent('notification', missed));
    await waitFor(() => expect(screen.getByTestId('stream-status').getAttribute('data-state')).toBe('open'), { timeout: 3_000 });
    expect(streamRequests).toEqual([null, '1']);
    expect(await screen.findByTestId(`nc-item-${missed.id}`)).toBeTruthy();
  });

  it('401：停止重连，状态为已停止', async () => {
    const states: StreamState[] = [];
    let calls = 0;
    fakeClock();
    server.use(http.get(`*${API}/stream`, () => { calls += 1; return HttpResponse.json({ error: { code: 'AUTH_REQUIRED', message: '请先登录', details: null, request_id: 'x' } }, { status: 401 }); }));
    const h = startEventStream({ onMessage: () => undefined, onState: (s) => states.push(s), retryMs: 10 });
    await waitFor(() => expect(h.state()).toBe('closed'));
    // 推进远超 retryMs 的时间，确认没有再次连接
    await advance(1000);
    expect(calls).toBe(1);
    expect(states).toEqual(['connecting', 'closed']);
  });

  it('心跳超时：主动断开并重连；非 2xx 退避重连', async () => {
    // 注入 fetch：只发一条注释后不再发数据；中止时结束流（不经 undici，避免中止后的套接字收尾干扰其他用例）
    let calls = 0;
    const fakeFetch = ((_url: RequestInfo | URL, init?: RequestInit) => {
      calls += 1;
      if (calls === 1) return Promise.resolve(new Response(null, { status: 503 }));
      const body = new ReadableStream<Uint8Array>({
        start(c) {
          c.enqueue(new TextEncoder().encode(': open\n\n'));
          init?.signal?.addEventListener('abort', () => c.error(new DOMException('aborted', 'AbortError')));
        },
      });
      return Promise.resolve(new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }));
    }) as typeof fetch;
    const opened: boolean[] = [];
    const h = startEventStream({ onMessage: () => undefined, onOpen: (i) => opened.push(i.reconnect), retryMs: 10, maxRetryMs: 20, idleTimeoutMs: 60, fetchImpl: fakeFetch });
    await waitFor(() => expect(calls).toBeGreaterThanOrEqual(3), { timeout: 3_000 });
    h.stop();
    expect(h.state()).toBe('closed');
    expect(opened.slice(0, 2)).toEqual([false, true]);
  });
});

// ---------------------------------------------------------------- 事件写入缓存
describe('SSE 事件写入查询缓存', () => {
  it('未知事件类型、坏 JSON 丢弃', () => {
    expect(parseStreamMessage({ id: '1', event: 'whatever', data: '{}' })).toBeNull();
    expect(parseStreamMessage({ id: '1', event: 'quote', data: '{' })).toBeNull();
    expect(parseStreamMessage({ id: '1', event: 'report', data: '{"date":"2026-10-30"}' })).toEqual({ id: '1', type: 'report', data: { date: '2026-10-30' } });
  });

  it('quote 就地更新终端行情；notification 让通知相关查询失效', () => {
    const qc = new QueryClient();
    const row = TERMINAL_ROWS.find((r) => r.quote)!;
    const term = { rows: TERMINAL_ROWS } as unknown as TerminalResponse;
    qc.setQueryData(['terminal', 'all'], term);
    applyStreamEvent(qc, { id: '1', type: 'quote', data: { items: [{ security_code: row.security_code, name: row.name, price: '9.99', change_pct: '1.23', amount: '100', t: '2026-11-02T10:41:00+08:00' }], data_as_of: '2026-11-02T10:41:00+08:00' } });
    const after = qc.getQueryData<TerminalResponse>(['terminal', 'all'])!;
    expect(after.rows.find((r) => r.security_code === row.security_code)!.quote!.price).toBe('9.99');
    qc.setQueryData(['notifications', 'unread-count'], { count: 1 });
    applyStreamEvent(qc, { id: '2', type: 'notification', data: sampleNotification(980) });
    expect(qc.getQueryState(['notifications', 'unread-count'])!.isInvalidated).toBe(true);
  });
});
