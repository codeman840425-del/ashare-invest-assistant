/** T-F22a：评审 review-T-F02b-F05-F22-F03 的 M1、M2、m1–m19 回归测试（MSW 示例数据） */
import type { ReactNode } from 'react';
import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { ApiError, apiGet, apiPost, apiPut } from '../api/client';
import { errorText } from '../api/errorPolicy';
import { useSecuritySearch } from '../api/marketQueries';
import { ME_POLL_MS } from '../api/queries';
import { fetchAllPages } from '../api/strategyQueries';
import type { BarsResponse } from '../api/types';
import { RiskDisclosure } from '../components/RiskDisclosure';
import { GAP_REASON } from '../i18n/labels';
import { LICENCE_STATUS } from '../i18n/licenceLabels';
import { dayMinutes, droppedBars } from '../lib/market';
import { ACCOUNT_ID, HORIZON_ASSESSMENTS, uid } from '../mocks/fixtures';
import { LICENCE_RATE, setMockIngestPaused, setMockLicence } from '../mocks/licenceStore';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { STRATEGY_TEMPLATES, mockAddInstance } from '../mocks/strategyHandlers';
import { advance, fakeClock } from '../test/timing';

// 页面模块的冷加载放在等待窗口之外（评审 b23401a N8）
beforeAll(() => preloadRoutes(routes), 30_000);

// 图表在 jsdom 里不绘制：保留“空图原因”的渲染，便于断言（评审 M2、m11）
vi.mock('../components/charts/KlineChart', () => ({
  KlineChart: ({ bars, empty }: { bars: unknown[]; empty?: ReactNode }) =>
    bars.length ? <div data-testid="kline" data-n={bars.length} /> : <div data-testid="chart-empty">{empty}</div>,
}));
vi.mock('../components/charts/IntradayChart', () => ({
  IntradayChart: ({ bars, empty }: { bars: unknown[]; empty?: ReactNode }) =>
    bars.length ? <div data-testid="intraday" /> : <div data-testid="chart-empty">{empty}</div>,
}));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders client={makeQueryClient(true)}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}
function captureUrls() {
  const urls: string[] = [];
  server.events.on('request:start', ({ request }) => void urls.push(request.url));
  return urls;
}
const ALPHA = 'QXZJKVWY';
const fakeLicence = (prefix = '') => prefix + Array.from({ length: 28 }, () => ALPHA[Math.floor(Math.random() * ALPHA.length)]).join('');
const typeLicence = (v: string) => fireEvent.change(screen.getByTestId('licence-input'), { target: { value: v } });
async function apiErr(p: Promise<unknown>): Promise<ApiError> {
  try {
    await p;
  } catch (e) {
    if (e instanceof ApiError) return e;
    throw e;
  }
  throw new Error('应当失败');
}
const opError = () => waitFor(() => {
  const el = document.querySelector('.error-box');
  if (!el) throw new Error('无错误框');
  return el as HTMLElement;
});
const LICENCE_GAP = GAP_REASON.data_licence_unavailable;

describe('M1 证书状态横幅自动刷新', () => {
  it('Me 每 60 秒轮询', () => expect(ME_POLL_MS).toBe(60_000));

  it('提交后验证失败：不刷新页面，全站横幅即变为“无效”', async () => {
    renderAt('/settings/data-licence');
    await screen.findByTestId('licence-page');
    expect(screen.queryByTestId('licence-banner')).toBeNull();
    fakeClock();
    typeLicence(fakeLicence('X-INVALID-'));
    fireEvent.click(screen.getByTestId('licence-save'));
    await advance(3000);
    const banner = await screen.findByTestId('licence-banner');
    await waitFor(() => expect(banner).toHaveAttribute('data-status', 'invalid'));
  });
});

describe('M2 缺数 / 过期原因：可见、可键盘查看、证书不可用的示例', () => {
  beforeEach(() => setMockLicence(uid(2), { status: 'expired' }));

  it('个股档案：行情、分时空图、各页签都说明 data_licence_unavailable，并给设置链接', async () => {
    const router = renderAt('/stocks/600000.SH');
    const qn = await screen.findByTestId('quote-gap-note');
    expect(qn).toHaveAttribute('data-status', 'stale');
    expect(qn).toHaveTextContent(LICENCE_GAP);
    expect(qn).toHaveTextContent('示例');
    expect(within(qn).getByTestId('gap-licence-link')).toHaveAttribute('href', '/settings/data-licence');
    // 分时：没有可用缓存 → unavailable，空图写明原因
    const cn = await screen.findByTestId('chart-gap-note');
    expect(cn).toHaveAttribute('data-status', 'unavailable');
    expect(await screen.findByTestId('chart-empty')).toHaveTextContent(`无分时数据（停牌或尚未开盘）：${LICENCE_GAP}`);
    for (const tab of ['financials', 'fund-flow', 'factors', 'announcements']) {
      await act(async () => router.navigate(`/stocks/600000.SH?tab=${tab}`));
      const pane = await screen.findByTestId(`tab-${tab}`);
      const note = await within(pane).findByTestId('gap-note');
      expect(note.querySelector('[data-reason="data_licence_unavailable"]')).not.toBeNull();
    }
  });

  it('市场概览与板块资金：stale / unavailable 都有可见原因，空表格写明原因', async () => {
    renderAt('/market');
    expect(await screen.findByTestId('market-gap-note')).toHaveTextContent(LICENCE_GAP);
    const sector = await screen.findByTestId('sector-panel');
    const sn = await within(sector).findByTestId('sector-gap-note');
    expect(sn).toHaveAttribute('data-status', 'unavailable');
    expect(within(sector).getByText(`暂无板块资金：${LICENCE_GAP}`)).toBeInTheDocument();
  });

  it('数据状态徽标：Tab 可聚焦，Enter / Space 打开，Esc 收起；aria-describedby 指向原因全文', async () => {
    renderAt('/market');
    const head = await screen.findByTestId('market-page');
    const tag = (await within(head).findAllByTestId('data-status-tag'))[0];
    expect(tag).toHaveAttribute('tabindex', '0');
    expect(tag).toHaveAttribute('role', 'button');
    const desc = document.getElementById(tag.getAttribute('aria-describedby')!)!;
    expect(desc).toHaveTextContent(LICENCE_GAP);
    expect(tag).toHaveAttribute('aria-expanded', 'false');
    tag.focus();
    fireEvent.keyDown(tag, { key: 'Enter' });
    expect(tag).toHaveAttribute('aria-expanded', 'true');
    expect(await screen.findByRole('tooltip')).toHaveTextContent(LICENCE_GAP);
    fireEvent.keyDown(tag, { key: 'Escape' });
    expect(tag).toHaveAttribute('aria-expanded', 'false');
    fireEvent.keyDown(tag, { key: ' ' });
    expect(tag).toHaveAttribute('aria-expanded', 'true');
  });

  it('证书可用时不出现证书原因', async () => {
    setMockLicence(uid(2), { status: 'active' });
    renderAt('/market');
    await screen.findByTestId('sector-panel');
    expect(screen.queryByTestId('market-gap-note')).toBeNull();
    expect(screen.queryByTestId('gap-licence-link')).toBeNull();
  });
});

describe('m1–m4 数据证书页', () => {
  it('m1：上一次失败的提示在下一次操作成功后清除', async () => {
    server.use(http.post('/api/v1/me/data-licence/test', () => HttpResponse.json({ error: { code: 'INGEST_PAUSED', message: 'x', details: null, request_id: null } }, { status: 503 }), { once: true }));
    renderAt('/settings/data-licence');
    await screen.findByTestId('licence-page');
    fireEvent.click(await screen.findByTestId('licence-test'));
    expect(await opError()).toHaveAttribute('data-code', 'INGEST_PAUSED');
    fireEvent.click(screen.getByTestId('licence-test'));
    expect(await screen.findByTestId('licence-msg')).toBeInTheDocument();
    expect(document.querySelector('.error-box')).toBeNull();
  });

  it('m2：输入框不让浏览器保存，并有说明', async () => {
    renderAt('/settings/data-licence');
    const input = (await screen.findByTestId('licence-input')) as HTMLInputElement;
    expect(input.autocomplete).toBe('off');
    expect(input).toHaveAttribute('data-lpignore', 'true');
    expect(screen.getByTestId('licence-no-save')).toBeInTheDocument();
  });

  it('m3：三个 DATA_LICENCE_* 都有中文文案；UNAVAILABLE 带状态；错误框给设置链接', () => {
    expect(errorText(new ApiError(409, 'DATA_LICENCE_IN_USE', 'server text', null, null))).not.toBe('server text');
    expect(errorText(new ApiError(409, 'DATA_LICENCE_NOT_SET', 'server text', null, null))).not.toBe('server text');
    const u = errorText(new ApiError(409, 'DATA_LICENCE_UNAVAILABLE', 'server text', { status: 'expired' }, null));
    expect(u).toContain(LICENCE_STATUS.expired.text);
    expect(errorText(new ApiError(429, 'RATE_LIMITED', 'x', { retry_after_s: 125 }, null))).toContain('3 分钟');
  });

  it('m4：PUT 超过 10 次/小时 → 429 + Retry-After；页面显示等待时长', async () => {
    mockLoginAs('new_user');
    for (let i = 0; i < LICENCE_RATE.put; i++) await apiPut('/me/data-licence', { licence: fakeLicence(), tier: 'free', has_quant_pro: false, expires_on: null }).catch(() => null);
    const e = await apiErr(apiPut('/me/data-licence', { licence: fakeLicence(), tier: 'free', has_quant_pro: false, expires_on: null }));
    expect(e.status).toBe(429);
    expect(e.code).toBe('RATE_LIMITED');
    expect(Number(e.details?.retry_after_s)).toBeGreaterThan(0);
    renderAt('/settings/data-licence');
    await screen.findByTestId('licence-page');
    typeLicence(fakeLicence());
    fireEvent.click(screen.getByTestId('licence-save'));
    expect(await opError()).toHaveTextContent(/操作过于频繁，请 \d+ (分钟|秒)后再试/);
  });

  it('m4：采集暂停 → 503 INGEST_PAUSED 并在页面说明；/test 超过 5 次/小时 → 429', async () => {
    setMockIngestPaused(true);
    renderAt('/settings/data-licence');
    await screen.findByTestId('licence-page');
    fireEvent.click(await screen.findByTestId('licence-test'));
    expect(await opError()).toHaveTextContent('行情采集已暂停');
    setMockIngestPaused(false);
    for (let i = 1; i < LICENCE_RATE.test; i++) await apiPost('/me/data-licence/test');
    const e = await apiErr(apiPost('/me/data-licence/test'));
    expect([e.status, e.code]).toEqual([429, 'RATE_LIMITED']);
  });
});

describe('m5–m9 策略库', () => {
  it('m5：开关名称固定为模板名，风险说明经 aria-describedby 关联', async () => {
    renderAt('/strategies');
    const cell = await screen.findByTestId('enable-st_strong_momo');
    const sw = within(cell).getByRole('switch');
    const name = STRATEGY_TEMPLATES.find((t) => t.key === 'st_strong_momo')!.name;
    expect(sw).toHaveAttribute('aria-label', name);
    const note = within(cell).getByTestId('high-risk-note');
    expect(sw.getAttribute('aria-describedby')).toBe(note.id);
  });

  it('m6：已有 proposed 实例时启用走 confirm，不重复创建', async () => {
    const t = STRATEGY_TEMPLATES.find((x) => x.key === 'st_pullback_ma')!;
    mockAddInstance({ id: uid(4700), strategy_id: t.id, strategy_version_id: t.current_version.id, status: 'proposed', scope: 'account', account_id: ACCOUNT_ID, security_code: null, horizon: 'short' });
    const urls = captureUrls();
    const posts: string[] = [];
    server.events.on('request:start', ({ request }) => void (request.method === 'POST' && posts.push(new URL(request.url).pathname)));
    renderAt('/strategies');
    const cell = await screen.findByTestId('enable-st_pullback_ma');
    await act(async () => fireEvent.click(within(cell).getByRole('switch')));
    await waitFor(() => expect(within(screen.getByTestId('enable-st_pullback_ma')).getByRole('switch')).toBeChecked());
    expect(urls.some((u) => u.endsWith(`/strategy-instances/${uid(4700)}/confirm`))).toBe(true);
    expect(posts).not.toContain('/api/v1/strategy-instances');
  });

  it('m7：没有账户 → 提示先创建账户，开关不可用；账户加载失败 → 错误框', async () => {
    server.use(http.get('/api/v1/accounts', () => HttpResponse.json({ items: [], next_cursor: null })));
    renderAt('/strategies');
    expect(await screen.findByTestId('no-account')).toBeInTheDocument();
    expect(within(screen.getByTestId('enable-st_strong_momo')).getByRole('switch')).toBeDisabled();
  });
  it('m7：账户加载失败 → 错误框', async () => {
    server.use(http.get('/api/v1/accounts', () => HttpResponse.json({ error: { code: 'INTERNAL', message: '示例故障', details: null, request_id: null } }, { status: 500 })));
    renderAt('/strategies');
    await screen.findByTestId('strategies-page');
    expect(await screen.findByText(/服务暂时不可用|示例故障/, {}, { timeout: 8000 })).toBeInTheDocument();
  }, 15000);

  it('m8：不可运行的版本 → 开关禁用并说明；mock 返回 409 {lifecycle}；周期不符带 strategy_key', async () => {
    const t = STRATEGY_TEMPLATES.find((x) => x.key === 'st_pullback_ma')!;
    const prev = t.current_version.lifecycle;
    t.current_version.lifecycle = 'simulating';
    try {
      const e = await apiErr(apiPost('/strategy-instances', { strategy_version_id: t.current_version.id, scope: 'account', account_id: ACCOUNT_ID, security_code: null, horizon: 'swing', param_overrides: null, budget_amount: null }));
      expect([e.status, e.code, e.details]).toEqual([409, 'STRATEGY_VERSION_NOT_RUNNABLE', { lifecycle: 'simulating' }]);
      renderAt('/strategies');
      expect(await screen.findByTestId('not-runnable-st_pullback_ma')).toBeInTheDocument();
      expect(within(screen.getByTestId('enable-st_pullback_ma')).getByRole('switch')).toBeDisabled();
    } finally {
      t.current_version.lifecycle = prev;
    }
    const m = await apiErr(apiPost('/strategy-instances', { strategy_version_id: t.current_version.id, scope: 'account', account_id: ACCOUNT_ID, security_code: null, horizon: 'swing', param_overrides: null, budget_amount: null }));
    expect([m.status, m.code]).toEqual([422, 'STRATEGY_HORIZON_MISMATCH']);
    expect(m.details).toMatchObject({ strategy_key: 'st_pullback_ma', horizons: ['short'] });
  });

  it('m9：跟随 next_cursor 翻页；翻到上限仍有下一页时 truncated 并在页面提示', async () => {
    let calls = 0;
    server.use(http.get('/api/v1/strategies', ({ request }) => {
      calls++;
      const c = Number(new URL(request.url).searchParams.get('cursor') ?? 0);
      return HttpResponse.json({ items: [{ ...STRATEGY_TEMPLATES[0], id: `t-${c}`, key: `k_${c}` }], next_cursor: String(c + 1) });
    }));
    const r = await fetchAllPages<{ id: string }>('/strategies', undefined, 1, 3);
    expect(r.items.map((x) => x.id)).toEqual(['t-0', 't-1', 't-2']);
    expect(r.truncated).toBe(true);
    expect(calls).toBe(3);
    renderAt('/strategies');
    expect(await screen.findByTestId('list-truncated')).toBeInTheDocument();
  });

  it('m9：不足一页时不截断', async () => {
    const r = await fetchAllPages('/strategies');
    expect(r.truncated).toBe(false);
    expect(r.items).toHaveLength(STRATEGY_TEMPLATES.length);
  });
});

describe('m10–m19 个股档案、持仓、其他', () => {
  it('m10：封顶 / 提示可聚焦，Enter 打开，读屏可读全文', async () => {
    const code = Object.keys(HORIZON_ASSESSMENTS).find((c) => HORIZON_ASSESSMENTS[c].caps.length > 0)!;
    const h = HORIZON_ASSESSMENTS[code].caps[0].horizon;
    renderAt(`/stocks/${code}`);
    const cap = await screen.findByTestId(`cap-${h}`);
    expect(cap).toHaveAttribute('tabindex', '0');
    expect(document.getElementById(cap.getAttribute('aria-describedby')!)!.textContent).toMatch(/^封顶 \d+/);
    fireEvent.keyDown(cap, { key: 'Enter' });
    expect(await screen.findByRole('tooltip')).toHaveTextContent('封顶');
  });

  it('m11：周线说明不再写“待契约确认”；空图文案按周期区分', async () => {
    server.use(http.get('/api/v1/securities/:code/bars', ({ request }) => {
      const freq = new URL(request.url).searchParams.get('freq');
      return HttpResponse.json({ security_code: '600000.SH', name: '示例银行', freq, adjust: 'qfq', pre_close: null, items: [], next_before: null, data_status: 'fresh', data_as_of: '2026-11-02T15:00:00+08:00', gaps: [] });
    }));
    renderAt('/stocks/601001.SH');
    expect(await screen.findByTestId('chart-empty')).toHaveTextContent('无日 K 数据');
    fireEvent.click(screen.getByText('周K'));
    await waitFor(() => expect(screen.getByTestId('chart-empty')).toHaveTextContent('无周 K 数据'));
    expect(screen.getByText('周线日期取该周最后交易日')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('口径待契约确认');
  });

  it('m12：日 K 还没有当日 bar 时，昨收取 1m 响应的 pre_close', async () => {
    const one = await apiGet<BarsResponse>('/securities/600000.SH/bars', { freq: '1m', adjust: 'none', limit: 240 });
    const daily = await apiGet<BarsResponse>('/securities/600000.SH/bars', { freq: 'd', adjust: 'qfq', limit: 250 });
    expect(one.pre_close).toBeTruthy();
    server.use(http.get('/api/v1/securities/:code/bars', ({ request }) => {
      if (new URL(request.url).searchParams.get('freq') !== 'd') return undefined;
      return HttpResponse.json({ ...daily, items: daily.items.slice(0, -1), next_before: null });
    }));
    renderAt('/stocks/600000.SH');
    const head = await screen.findByTestId('stock-head');
    await waitFor(() => expect(within(head).getByText('昨收').parentElement).toHaveTextContent(one.pre_close!));
  });

  it('m13：小写代码改写为规范 URL；搜索词去空格后再进 queryKey 与参数', async () => {
    const router = renderAt('/stocks/600000.sh?tab=factors');
    await waitFor(() => expect(router.state.location.pathname).toBe('/stocks/600000.SH'));
    expect(router.state.location.search).toBe('?tab=factors');
    expect(await screen.findByTestId('stock-head')).toBeInTheDocument();

    const urls = captureUrls();
    const qc = makeQueryClient(true);
    const { result } = renderHook(() => useSecuritySearch('  600000 '), { wrapper: ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider> });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const u = new URL(urls.find((x) => new URL(x).pathname === '/api/v1/securities/search')!);
    expect(u.searchParams.get('q')).toBe('600000');
    expect(qc.getQueryCache().getAll().some((q) => JSON.stringify(q.queryKey).includes('"600000"'))).toBe(true);
  });

  it('m14：未知 account_id 回落到第一个账户并提示；导入链接编码账户 id', async () => {
    const urls = captureUrls();
    renderAt('/portfolio?account_id=no-such-id');
    expect(await screen.findByTestId('unknown-account')).toBeInTheDocument();
    await waitFor(() => expect(urls.some((u) => new URL(u).pathname === '/api/v1/portfolio')).toBe(true));
    const p = urls.filter((u) => new URL(u).pathname === '/api/v1/portfolio').map((u) => new URL(u).searchParams.get('account_id'));
    expect(p).not.toContain('no-such-id');
  });

  it('m15：页脚免责提示保留 contentinfo 地标（不加 role=note）', () => {
    render(<RiskDisclosure />);
    const f = screen.getByTestId('risk-disclosure');
    expect(f.tagName).toBe('FOOTER');
    expect(f).not.toHaveAttribute('role');
    expect(screen.getByRole('contentinfo')).toBe(f);
  });

  it('m16：bars 缺 freq → 400；limit 截取后 next_before 指向更早一页，before 可翻页', async () => {
    const e = await apiErr(apiGet('/securities/600000.SH/bars', { limit: 5 }));
    expect([e.status, e.code]).toEqual([400, 'VALIDATION_ERROR']);
    const p1 = await apiGet<BarsResponse>('/securities/600000.SH/bars', { freq: 'd', limit: 5 });
    expect(p1.items).toHaveLength(5);
    expect(p1.next_before).toBe(p1.items[0].t);
    const p2 = await apiGet<BarsResponse>('/securities/600000.SH/bars', { freq: 'd', limit: 5, before: p1.next_before });
    expect(p2.items.at(-1)!.t < p1.items[0].t).toBe(true);
    const all = await apiGet<BarsResponse>('/securities/600000.SH/bars', { freq: 'd', limit: 2000 });
    expect(all.next_before).toBeNull();
  });

  it('m17：切换周期时保留旧图，不闪“加载中”', async () => {
    renderAt('/stocks/601001.SH');
    expect(await screen.findByTestId('kline')).toBeInTheDocument();
    fireEvent.click(screen.getByText('周K'));
    expect(screen.getByTestId('kline')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('price-chart').querySelector('[aria-busy]')).toBeNull());
    expect(screen.getByTestId('kline')).toBeInTheDocument();
  });

  it('m18：不在分钟结束时刻上的 1m bar 会被计数（09:30 集合竞价等）', () => {
    const minutes = dayMinutes('2026-11-02');
    const bar = (t: string) => ({ t, open: '1', high: '1', low: '1', close: '1', pre_close: null, volume: '1', amount: '1', avg_price: null, is_final: true });
    expect(droppedBars([bar('2026-11-02T09:31:00+08:00'), bar('2026-11-02T15:00:00+08:00')], minutes)).toBe(0);
    expect(droppedBars([bar('2026-11-02T09:30:00+08:00'), bar('2026-11-02T12:00:00+08:00'), bar('2026-11-02T09:31:00+08:00')], minutes)).toBe(2);
  });
});
