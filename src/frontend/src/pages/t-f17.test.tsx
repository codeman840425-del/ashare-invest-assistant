/** T-F17 候选信号卡与不可执行原因（契约 v0.2.8 §7.6，列表与 released_since 见 v0.2.7） */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { ApiError } from '../api/client';
import { errorText } from '../api/errorPolicy';
import { normalizeEvents } from '../api/signalQueries';
import { StatValue } from '../components/StatValue';
import { causeText } from '../i18n/signalLabels';
import { conflictsOf, parseTab, reevalText } from '../lib/signals';
import { CANDIDATE_SIGNALS, REASONS, SUGGESTIONS, uid } from '../mocks/fixtures';
import { LifecycleBadge } from './signals/LifecycleBadge';

// 页面模块的冷加载放在等待窗口之外（评审 b23401a N8）
beforeAll(() => preloadRoutes(routes), 30_000);

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';
const post = (path: string, body: unknown) => fetch(`${API}${path}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

// 示例数据：600000.SH 有一对方向相反的 blocked 信号（uid 1000 买入 / uid 1003 减仓）
const BUY = uid(1000);
const REDUCE = uid(1003);
const SELL_T1 = uid(1016);

describe('纯函数', () => {
  it('同股方向冲突只比较未结束、方向相反的信号', () => {
    const buy = CANDIDATE_SIGNALS.find((c) => c.id === BUY)!;
    expect(conflictsOf(buy, CANDIDATE_SIGNALS).map((c) => c.id)).toEqual([REDUCE]);
    const expired = CANDIDATE_SIGNALS.find((c) => c.security_code === '600000.SH' && c.state === 'expired')!;
    expect(conflictsOf(expired, CANDIDATE_SIGNALS)).toEqual([]);
  });
  it('自动重评状态文案', () => {
    const auto = REASONS.find((r) => r.code === 'POSITION_CAP_REACHED')!;
    expect(reevalText(auto)).toMatch(/^等待系统自动重评/);
    const manual = REASONS.find((r) => r.code === 'STRATEGY_CONFLICT')!;
    expect(reevalText(manual)).toBe('需你确认后手动解除');
    const released = REASONS.find((r) => r.status === 'released')!;
    expect(reevalText(released)).toMatch(/^系统自动重评解除 · /);
    expect(reevalText({ ...manual, status: 'obsolete' })).toMatch(/作废/);
  });
  it('tab 参数、事件包装、cause 文案', () => {
    expect(parseTab('released')).toBe('released');
    expect(parseTab('x')).toBe('signals');
    const e = [{ from: null, to: 'open', cause: 'signal_created', at: '2026-11-02T09:00:00+08:00' }];
    expect(normalizeEvents(e)).toEqual(e);
    expect(normalizeEvents({ items: e })).toEqual(e);
    expect(normalizeEvents(null)).toEqual([]);
    expect(causeText('reason_released:SUSPENDED')).toBe('原因解除（SUSPENDED）');
    expect(causeText('unknown_cause')).toBe('unknown_cause');
  });
  it('统计数字旁显示 n，样本少时加标记，n < 5 显示样本不足', () => {
    const { rerender } = render(<StatValue s={{ value: '0.5500', n: 64, window: '5d', small_sample: false }} testId="s" />);
    expect(screen.getByTestId('s')).toHaveTextContent('55.0%');
    expect(screen.getByTestId('s')).toHaveTextContent('n=64');
    expect(screen.getByTestId('s')).not.toHaveTextContent('样本少');
    rerender(<StatValue s={{ value: '1.2000', n: 12, window: '5d', small_sample: true }} kind="ratio" testId="s" />);
    expect(screen.getByTestId('s')).toHaveTextContent('1.20');
    expect(screen.getByTestId('s')).toHaveTextContent('样本少');
    rerender(<StatValue s={{ value: null, n: 3, window: '5d', small_sample: true }} testId="s" />);
    expect(screen.getByTestId('s')).toHaveTextContent('样本不足');
    expect(screen.getByTestId('s')).toHaveTextContent('n=3');
  });
  it('“模拟中 / 观察中”徽标；已发布不显示', () => {
    const { container, rerender } = render(<LifecycleBadge lifecycle="simulating" />);
    expect(screen.getByTestId('lifecycle-badge')).toHaveTextContent('模拟中');
    rerender(<LifecycleBadge lifecycle="observing" />);
    expect(screen.getByTestId('lifecycle-badge')).toHaveTextContent('观察中');
    rerender(<LifecycleBadge lifecycle="published" />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('列表 /candidate-signals', () => {
  it('显示信号、方向冲突标记与观察中徽标', async () => {
    renderAt('/candidate-signals');
    // 本文件第一次渲染 AG Grid 表格，冷启动较慢：只在这一处单独放宽等待（评审 b23401a N8）
    expect(await screen.findByTestId(`sig-link-${BUY}`, undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByTestId(`conflict-${BUY}`)).toHaveTextContent('方向冲突');
    expect(screen.getByTestId(`conflict-${REDUCE}`)).toBeInTheDocument();
    expect(screen.queryByTestId(`conflict-${SELL_T1}`)).toBeNull();
    expect(screen.getAllByTestId('lifecycle-badge')[0]).toHaveTextContent('观察中');
  });
  it('URL 筛选 state=blocked 只列暂不可执行的信号', async () => {
    renderAt('/candidate-signals?state=blocked');
    const table = await screen.findByTestId('signals-table');
    await waitFor(() => expect(within(table).getAllByText('暂不可执行').length).toBe(5));
    expect(within(table).queryByText('已过期')).toBeNull();
  });
  it('?tab=released：列出今天解除的原因（released_since）', async () => {
    renderAt('/candidate-signals?tab=released');
    const since = await screen.findByTestId('released-since');
    await waitFor(() => expect(since).toHaveTextContent('T00:00:00+08:00'));
    const table = screen.getByTestId('released-table');
    expect(await within(table).findByText('系统自动重评解除')).toBeInTheDocument();
    expect(await within(table).findByText(/演示材料/)).toBeInTheDocument();
  });
  it('released_since 只返回之后解除的原因；格式错误 400', async () => {
    const late = await (await fetch(`${API}/non-executable-reasons?status=released&released_since=${encodeURIComponent('2099-01-01T00:00:00+08:00')}`)).json() as { items: unknown[] };
    expect(late.items).toEqual([]);
    expect((await fetch(`${API}/non-executable-reasons?released_since=abc`)).status).toBe(400);
  });
});

describe('详情 /candidate-signals/{id}', () => {
  it('冲突并列、原因 + 解除条件 + 自动重评状态、状态历史、跟踪统计带 n', async () => {
    renderAt(`/candidate-signals/${BUY}`);
    const conflicts = await screen.findByTestId('signal-conflicts');
    expect(within(conflicts).getByTestId(`conflict-card-${REDUCE}`)).toBeInTheDocument();
    const reasons = screen.getByTestId('signal-reasons');
    await waitFor(() => expect(within(reasons).getAllByTestId('reeval')).toHaveLength(2));
    expect(reasons.textContent).toMatch(/解除条件/);
    expect(reasons.textContent).toMatch(/等待系统自动重评/);
    expect(reasons.textContent).toMatch(/需你确认后手动解除/);
    // 只有 machine_checkable=false 的原因有“手动解除”按钮
    expect(within(reasons).getByTestId(`release-${uid(1002)}`)).toBeInTheDocument();
    expect(within(reasons).queryByTestId(`release-${uid(1001)}`)).toBeNull();
    const events = screen.getByTestId('signal-events');
    expect(await within(events).findByText(/检出不可执行原因/)).toBeInTheDocument();
    const track = screen.getByTestId('signal-tracking');
    expect(await within(track).findByTestId('track-5')).toHaveTextContent(/n=\d+/);
  });
  it('手动解除：唯一生效原因解除后信号变为“原因已解除”', async () => {
    renderAt(`/candidate-signals/${REDUCE}`);
    fireEvent.click(await screen.findByTestId(`release-${uid(1004)}`));
    fireEvent.change(await screen.findByTestId('release-note'), { target: { value: '已核对（示例）' } });
    fireEvent.click(screen.getByTestId('release-ok'));
    await waitFor(() => expect(screen.getByTestId('signal-state')).toHaveTextContent('原因已解除'));
    const reason = screen.getByTestId(`reason-${uid(1004)}`);
    await waitFor(() => expect(reason).toHaveTextContent('已解除'));
    expect(reason).toHaveTextContent('你手动解除');
    expect(reason).toHaveTextContent('备注：已核对（示例）');
  });
  it('可机器判断的原因不能手动解除（409 REASON_NOT_MANUALLY_RELEASABLE）', async () => {
    const res = await post(`/non-executable-reasons/${uid(1001)}/release`, { confirm: true, note: null });
    expect(res.status).toBe(409);
    const body = await res.json() as { error: { code: string } };
    expect(body.error.code).toBe('REASON_NOT_MANUALLY_RELEASABLE');
    expect(errorText(new ApiError(409, body.error.code, '', null, null))).not.toBe('');
  });
  it('忽略信号：状态变为已忽略，生效原因作废，按钮禁用', async () => {
    renderAt(`/candidate-signals/${SELL_T1}`);
    fireEvent.click(await screen.findByTestId('dismiss-btn'));
    fireEvent.click(await screen.findByTestId('dismiss-ok'));
    await waitFor(() => expect(screen.getByTestId('signal-state')).toHaveTextContent('已忽略'));
    await waitFor(() => expect(screen.getByTestId(`reason-${uid(1017)}`)).toHaveTextContent('已作废'));
    expect(screen.getByTestId('dismiss-btn')).toBeDisabled();
    const again = await post(`/candidate-signals/${SELL_T1}/dismiss`, { note: null });
    expect(again.status).toBe(409);
  });
  it('样本少于 5 的策略显示“样本不足”', async () => {
    renderAt(`/candidate-signals/${uid(1021)}`);
    const track = await screen.findByTestId('signal-tracking');
    expect(await within(track).findByTestId('track-1')).toHaveTextContent('样本不足');
    expect(within(track).getByTestId('track-1')).toHaveTextContent('样本少');
  });
  it('不存在的信号显示错误而不是空白', async () => {
    renderAt(`/candidate-signals/${uid(99999)}`);
    expect(await screen.findByText(/不存在/)).toBeInTheDocument();
  });
});

describe('入口', () => {
  it('建议卡详情的策略卡链接到候选信号详情', async () => {
    const sg = SUGGESTIONS.find((x) => x.security_code === '600000.SH')!;
    renderAt(`/suggestions/${sg.id}`);
    const links = await screen.findAllByTestId('to-signal');
    expect(links[0].getAttribute('href')).toMatch(/^\/candidate-signals\//);
  });
});
