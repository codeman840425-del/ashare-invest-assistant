/** T-F36b：t_view 按 T-A145 契约返工（docs/contracts/intraday-bars.md §3.7、today-view.md §10，docs/T-A145=2ddefa5；示例数据） */
import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import type { Gap, TView, TodayFocusRow, TodayResponse } from '../api/types';
import { server } from '../mocks/server';
import { TERMINAL_ROWS } from '../mocks/fixtures';
import { T_VIEW_UNAVAILABLE, fmtDevPct, tViewHints } from './today/tViewModel';

beforeAll(() => preloadRoutes(routes), 30_000);
vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

// 整个文件在 America/Denver 下运行（共享电脑的机器时区）
const ORIGINAL_TZ = process.env.TZ;
beforeAll(() => { process.env.TZ = 'America/Denver'; });
afterAll(() => { if (ORIGINAL_TZ === undefined) delete process.env.TZ; else process.env.TZ = ORIGINAL_TZ; });

const DATE = '2026-11-10';
const empty = { items: [], more: false };
const base = TERMINAL_ROWS.find((r) => r.holding)!;
const TV: TView = {
  vwap: '10.18', dev_pct: '0.5900', volume_ratio: '1.35', base_qty: '1000', sellable_qty: '700', data_status: 'fresh', as_of: '2026-11-10T10:30:00+08:00', gaps: [],
};
const NA = { vwap: null, dev_pct: null, volume_ratio: null, base_qty: null, sellable_qty: null, as_of: null, data_status: 'unavailable' as const };
const row = (t: TView, code = '000001.SZ'): TodayFocusRow => ({ ...base, security_code: code, name: '示例甲', suggestion: null, t_view: t });
const cell = (code = '000001.SZ') => screen.findByTestId(`t-view-${code}`);

async function setup(items: TodayFocusRow[], session: TodayResponse['session'] = 'morning') {
  const body: TodayResponse = {
    server_time: '2026-11-10T10:31:30+08:00', trade_date: DATE, session,
    market: { regime: null, regime_position_range: null, data_status: 'fresh' },
    focus: { items, more: false },
    pending_plan_drafts: empty, released_reasons: empty, risk_flags: empty, invalidations_today: empty,
    daily_report: { date: DATE, status: 'not_yet' },
    reconciliation: { status: 'matched', as_of: null, diff_count: 0, important_count: 0 },
    unread_notifications: 0, alerts: empty, plan_triggers: empty, data_gaps: empty, evidence: [],
  };
  server.use(http.get('/api/v1/today', () => HttpResponse.json(body)));
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  render(
    <AppProviders client={makeQueryClient(true)}>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: ['/today'] })} />
    </AppProviders>,
  );
  return screen.findByTestId('today-page');
}
const THR = { dev_pct_threshold: '2', volume_ratio_threshold: '2' };

describe('T-F36b（契约 §3.7 前端八条）', () => {
  it('t-f36b dev_pct 按百分数显示', async () => {
    expect(fmtDevPct('0.5900')).toBe('+0.59%');
    expect(fmtDevPct('-1.2350')).toBe('-1.24%'); // ROUND_HALF_UP 远离零
    expect(fmtDevPct('0.0050')).toBe('+0.01%');
    expect(fmtDevPct('-0.0040')).toBe('0.00%');
    expect(fmtDevPct('12.3456')).toBe('+12.35%');
    expect(tViewHints({ ...TV, dev_pct: '2.0000', ...THR })).toContain('偏离分时均价已达阈值（±2.00%）');
    await setup([row({ ...TV, dev_pct: '0.5900' })]);
    const c = await cell();
    expect(within(c).getByTestId('t-view-000001.SZ-dev')).toHaveTextContent(/^\+0\.59%$/);
    expect(c).not.toHaveTextContent('59.00%');
  });

  it('t-f36b 阈值字段缺省不提示', async () => {
    expect(tViewHints({ ...TV, dev_pct: '50.0000', volume_ratio: '9.00' })).toEqual([]);
    expect(tViewHints({ ...TV, dev_pct: '-50.0000', volume_ratio: '9.00', dev_pct_threshold: null, volume_ratio_threshold: null })).toEqual([]);
    expect(tViewHints({ ...TV, dev_pct: '-50.0000', volume_ratio: '9.00', dev_pct_threshold: '2' })).toEqual(['偏离分时均价已达阈值（±2.00%）']);
    await setup([row({ ...TV, dev_pct: '-50.0000', volume_ratio: '9.00' })]);
    const c = await cell();
    expect(within(c).queryByTestId('t-view-000001.SZ-hint')).toBeNull();
    expect(within(c).getByTestId('t-view-000001.SZ-dev')).toHaveTextContent('-50.00%');
  });

  it('t-f36b stale 不提示且标已过期', async () => {
    const t: TView = { ...TV, dev_pct: '3.0000', volume_ratio: '3.00', ...THR, data_status: 'stale', as_of: '2026-11-10T02:28:00Z' };
    expect(tViewHints(t)).toEqual([]);
    await setup([row(t)]);
    const c = await cell();
    expect(c).toHaveAttribute('data-state', 'stale');
    expect(within(c).getByTestId('t-view-000001.SZ-status')).toHaveTextContent('已过期（截至 10:28）');
    expect(within(c).getByTestId('t-view-000001.SZ-vwap')).toHaveTextContent('10.18'); // 照常显示数值
    expect(within(c).queryByTestId('t-view-000001.SZ-hint')).toBeNull();
  });

  it('t-f36b pending 显示拉取中', async () => {
    const t: TView = { ...TV, ...THR, dev_pct: '3.0000', volume_ratio: '3.00', data_status: 'pending', as_of: null };
    expect(tViewHints(t)).toEqual([]);
    await setup([row(t)]);
    const c = await cell();
    expect(within(c).getByTestId('t-view-000001.SZ-status')).toHaveTextContent('拉取中');
    for (const k of ['vwap', 'dev', 'vr']) expect(within(c).getByTestId(`t-view-000001.SZ-${k}`)).toHaveTextContent(/^—$/);
    expect(within(c).getByTestId('t-view-000001.SZ-avail')).toHaveTextContent('今日可用底仓 — 股');
    expect(within(c).queryByTestId('t-view-000001.SZ-hint')).toBeNull();
  });

  it('t-f36b 可卖超底仓显示核对中', async () => {
    const clampGap: Gap = { key: 't_view.sellable_qty', reason: 'upstream_error', message: '可卖数量与底仓不一致，已按较小值显示' };
    await setup([
      row({ ...TV, base_qty: '1000', sellable_qty: '1500' }, '000001.SZ'),
      row({ ...TV, base_qty: '1000', sellable_qty: '-100' }, '000002.SZ'),
      row({ ...TV, base_qty: '12000', sellable_qty: '12000', data_status: 'partial', gaps: [clampGap] }, '000003.SZ'),
    ]);
    for (const code of ['000001.SZ', '000002.SZ']) {
      const a = within(await cell(code)).getByTestId(`t-view-${code}-avail`);
      expect(a).toHaveTextContent('今日可用底仓 — 股（数据核对中）');
    }
    // 后端已截断并给 gap：原样显示后端值，GapNote 列出原因
    const c3 = await cell('000003.SZ');
    expect(within(c3).getByTestId('t-view-000003.SZ-avail')).toHaveTextContent('今日可用底仓 12,000 股');
    expect(within(c3).queryByTestId('t-view-000003.SZ-checking')).toBeNull();
    expect(within(c3).getByTestId('t-view-000003.SZ-gaps')).toHaveTextContent('可卖数量与底仓不一致，已按较小值显示');
  });

  it('t-f36b 不适用三种 key', async () => {
    const na = (key: string): TView => ({ ...NA, gaps: [{ key, reason: 'not_applicable', message: '示例数据' }] });
    await setup([row(na('t_view.base_qty'), '000001.SZ'), row(na('t_view.security_type'), '510000.SH'), row(na('t_view.session'), '000002.SZ')]);
    const expectNa = async (code: string, text: string) => {
      const c = await cell(code);
      expect(c).toHaveAttribute('data-state', 'not_applicable');
      expect(within(c).getByTestId(`t-view-${code}-na`)).toHaveTextContent(text);
      expect(c).toHaveTextContent('不适用');
      expect(c).not.toHaveTextContent(T_VIEW_UNAVAILABLE);
      expect(c).not.toHaveTextContent('偏离');
    };
    await expectNa('000001.SZ', '不适用：昨日无底仓。');
    await expectNa('510000.SH', '不适用：该品种暂不提供做 T 视图。');
    await expectNa('000002.SZ', '开盘后显示。');
  });

  it('t-f36b 不适用 t_view.session 在非交易日为「今日休市。」', async () => {
    await setup([row({ ...NA, gaps: [{ key: 't_view.session', reason: 'not_applicable', message: '示例数据' }] })], 'non_trading_day');
    expect(within(await cell()).getByTestId('t-view-000001.SZ-na')).toHaveTextContent(/^今日休市。$/);
  });

  it('t-f36b 量比为空显示原因', async () => {
    const g = (message: string): Gap => ({ key: 't_view.volume_ratio', reason: 'no_source', message });
    const t1: TView = { ...TV, volume_ratio: null, data_status: 'partial', gaps: [g('历史分时不足 5 个交易日')], dev_pct: '2.0000', ...THR };
    // partial：只对字段齐全的那一项提示
    expect(tViewHints(t1)).toEqual(['偏离分时均价已达阈值（±2.00%）']);
    await setup([row(t1, '000001.SZ'), row({ ...TV, volume_ratio: null, data_status: 'partial', gaps: [g('今日无成交')] }, '000002.SZ')]);
    const c1 = await cell('000001.SZ');
    expect(within(c1).getByTestId('t-view-000001.SZ-vr')).toHaveTextContent(/^—$/);
    expect(within(c1).getByTestId('t-view-000001.SZ-gaps')).toHaveTextContent('历史分时不足 5 个交易日');
    expect(within(c1).getAllByTestId('t-view-000001.SZ-hint')).toHaveLength(1);
    expect(within(await cell('000002.SZ')).getByTestId('t-view-000002.SZ-gaps')).toHaveTextContent('今日无成交');
  });

  it('t-f36b 均价原样显示不再舍入', async () => {
    await setup([
      row({ ...TV, vwap: '1234.50', volume_ratio: '1.30', base_qty: '12000', sellable_qty: '12000' }, '000001.SZ'),
      row({ ...TV, vwap: '10.125', volume_ratio: '0.805' }, '000002.SZ'),
    ]);
    const c1 = await cell('000001.SZ');
    expect(within(c1).getByTestId('t-view-000001.SZ-vwap')).toHaveTextContent(/^1,234\.50$/);
    expect(within(c1).getByTestId('t-view-000001.SZ-vr')).toHaveTextContent(/^1\.30$/);
    expect(within(c1).getByTestId('t-view-000001.SZ-avail')).toHaveTextContent('今日可用底仓 12,000 股');
    const c2 = await cell('000002.SZ');
    expect(within(c2).getByTestId('t-view-000002.SZ-vwap')).toHaveTextContent(/^10\.125$/);
    expect(within(c2).getByTestId('t-view-000002.SZ-vr')).toHaveTextContent(/^0\.805$/);
  });
});
