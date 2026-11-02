/** T-F12 候选信号卡补全（契约 §5.2、§7 /suggestions*）。示例数据，不发外网请求。 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { resetViewedOnce } from '../api/suggestionQueries';
import { SUGGESTIONS, suggestionOf, uid } from '../mocks/fixtures';
import { server } from '../mocks/server';
import { actionLog, REFRESH_MIN_INTERVAL_S } from '../mocks/suggestionHandlers';
import { apiFetch } from '../test/apiFetch';
import { preloadRoutes } from '../test/preloadRoutes';

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

/** 记录本测试发出的请求路径 */
function recordRequests() {
  const seen: string[] = [];
  const fn = ({ request }: { request: Request }) => { seen.push(`${request.method} ${new URL(request.url).pathname}`); };
  server.events.on('request:start', fn);
  return { seen, stop: () => server.events.removeListener('request:start', fn) };
}

const sgBank = suggestionOf('600000.SH')!;
const sgDraftable = suggestionOf('300001.SZ')!;

describe('mock 接口（契约 §7 /suggestions*）', () => {
  it('actions：只收三种 kind；trade_id 仅 acted_trade_linked 填；204', async () => {
    expect((await post(`/suggestions/${sgBank.id}/actions`, { kind: 'converted_to_plan', trade_id: null, note: null })).status).toBe(400);
    expect((await post(`/suggestions/${sgBank.id}/actions`, { kind: 'viewed', trade_id: uid(1), note: null })).status).toBe(400);
    expect((await post(`/suggestions/${uid(7)}/actions`, { kind: 'viewed', trade_id: null, note: null })).status).toBe(404);
    expect((await post(`/suggestions/${sgBank.id}/actions`, { kind: 'dismissed', trade_id: null, note: '示例备注' })).status).toBe(204);
    expect(actionLog.at(-1)).toEqual({ suggestion_id: sgBank.id, kind: 'dismissed', trade_id: null, note: '示例备注' });
  });

  it('refresh：生成新卡并取代旧卡；短时间再刷 → 409 SUGGESTION_REFRESH_TOO_FREQUENT{retry_after_s}', async () => {
    const r = await post('/suggestions/refresh', { security_code: '600000.SH' });
    expect(r.status).toBe(200);
    const list = await (await apiFetch(`${API}/suggestions?security_code=600000.SH&status=active`)).json();
    expect(list.items).toHaveLength(1);
    const nid = list.items[0].id as string;
    expect(nid).not.toBe(sgBank.id);
    const old = await (await apiFetch(`${API}/suggestions/${sgBank.id}`)).json();
    expect(old).toMatchObject({ status: 'superseded', superseded_by_id: nid });
    const again = await post('/suggestions/refresh', { security_code: '600000.SH' });
    expect(again.status).toBe(409);
    const body = await again.json();
    expect(body.error.code).toBe('SUGGESTION_REFRESH_TOO_FREQUENT');
    expect(body.error.details.retry_after_s).toBeGreaterThan(0);
    expect(body.error.details.retry_after_s).toBeLessThanOrEqual(REFRESH_MIN_INTERVAL_S);
  });

  it('tracking：{t1, t5, t20: Stat}；n < 5 时 value=null；status 非法 → 400', async () => {
    const t = await (await apiFetch(`${API}/suggestions/${sgBank.id}/tracking`)).json();
    expect(Object.keys(t).sort()).toEqual(['t1', 't20', 't5']);
    expect(t.t20).toMatchObject({ value: null, small_sample: true });
    expect((await apiFetch(`${API}/suggestions?status=current`)).status).toBe(400);
  });
});

describe('候选信号卡详情页补全', () => {
  it('状态标记、跟踪统计（样本量 / 样本少 / 样本不足）、待契约占位，不请求 /chain；进入页面只记一次 viewed', async () => {
    const rec = recordRequests();
    const router = renderAt(`/suggestions/${sgBank.id}`);
    expect(await screen.findByTestId('sg-status')).toHaveTextContent('当前');
    expect(await screen.findByTestId('sg-track-t1')).toHaveTextContent('n=42');
    expect(screen.getByTestId('sg-track-t5')).toHaveTextContent('样本少');
    expect(screen.getByTestId('sg-track-t20')).toHaveTextContent('样本不足');
    for (const t of ['sg-chain-placeholder', 'sg-track-basis', 'sg-trade-link-placeholder']) expect(screen.getByTestId(t)).toHaveTextContent('待契约');
    expect(screen.getByTestId('sg-supersedes')).toHaveAttribute('href', `/suggestions/${uid(99)}`);
    await waitFor(() => expect(actionLog.filter((a) => a.kind === 'viewed' && a.suggestion_id === sgBank.id)).toHaveLength(1));
    await router.navigate('/terminal');
    await router.navigate(`/suggestions/${sgBank.id}`);
    await screen.findByTestId('sg-status');
    expect(actionLog.filter((a) => a.kind === 'viewed')).toHaveLength(1);
    expect(rec.seen.some((s) => s.endsWith('/chain'))).toBe(false);
    rec.stop();
  });

  it('被取代的卡：提示仅供回看并链接到取代它的卡；拟定计划草案禁用', async () => {
    renderAt(`/suggestions/${uid(99)}`);
    expect(await screen.findByTestId('sg-inactive')).toHaveTextContent('已被取代');
    expect(screen.getByTestId('sg-superseded-by')).toHaveAttribute('href', `/suggestions/${sgBank.id}`);
    for (const b of await screen.findAllByRole('button', { name: '拟定计划草案' })) expect(b).toBeDisabled();
  });

  it('拟定计划草案：可拟定的候选信号可用，生成后跳到草案；不可拟定的禁用', async () => {
    const router = renderAt(`/suggestions/${sgDraftable.id}`);
    const btn = await screen.findByTestId('sg-draft-demo_trend');
    await waitFor(() => expect(btn).toBeEnabled());
    fireEvent.click(btn);
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/plan-drafts\//));
  });

  it('不可拟定（受阻）的候选信号：按钮禁用', async () => {
    renderAt(`/suggestions/${sgBank.id}`);
    const btn = await screen.findByTestId('sg-draft-demo_trend');
    await screen.findByTestId('sg-track-t1');
    expect(btn).toBeDisabled();
  });

  it('规则引用可展开', async () => {
    renderAt(`/suggestions/${sgBank.id}`);
    fireEvent.click(await screen.findByTestId('sg-rules-toggle-demo_trend'));
    expect(await screen.findByText(/规则引用（\d+）/)).toBeInTheDocument();
  });

  it('不再关注本卡：带备注记录 dismissed', async () => {
    renderAt(`/suggestions/${sgBank.id}`);
    fireEvent.click(await screen.findByTestId('sg-dismiss'));
    fireEvent.change(await screen.findByTestId('sg-dismiss-note'), { target: { value: '示例：已在别处跟踪' } });
    fireEvent.click(screen.getByRole('button', { name: /记\s*录/ }));
    expect(await screen.findByTestId('sg-dismissed')).toBeInTheDocument();
    expect(actionLog.find((a) => a.kind === 'dismissed')).toMatchObject({ note: '示例：已在别处跟踪', trade_id: null });
  });

  it('手动刷新：跳到新卡；再次刷新给出 409 等待时间', async () => {
    const router = renderAt(`/suggestions/${sgBank.id}`);
    fireEvent.click(await screen.findByTestId('sg-refresh'));
    await waitFor(() => expect(router.state.location.pathname).not.toBe(`/suggestions/${sgBank.id}`));
    await waitFor(() => expect(screen.getByTestId('sg-supersedes')).toHaveAttribute('href', `/suggestions/${sgBank.id}`));
    fireEvent.click(screen.getByTestId('sg-refresh'));
    expect(await screen.findByTestId('sg-refresh-error')).toHaveTextContent(/刷新过于频繁，请 \d+ 秒后再试/);
  });

  it('LLM 说明：显示 llm_call_id', async () => {
    const llm = { ...sgBank, explanation: { source: 'llm' as const, text: '示例：LLM 改写的说明', llm_call_id: uid(77) } };
    server.use(http.get(`${API}/suggestions/:id`, () => HttpResponse.json(llm)));
    renderAt(`/suggestions/${sgBank.id}`);
    expect(await screen.findByTestId('sg-llm-call')).toHaveTextContent(uid(77));
  });

  it('示例数据：所有卡都在 mock 列表中', () => {
    expect(SUGGESTIONS.length).toBeGreaterThan(0);
  });
});
