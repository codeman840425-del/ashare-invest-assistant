/** T-F36：/today 持仓行做 T 视图 t_view（契约 docs/contracts/intraday-bars.md §3.5、§3.7、§5.2；T-F36b 按 T-A145=2ddefa5 同步修正；示例数据） */
import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import type { TView, TodayFocusRow, TodayResponse } from '../api/types';
import { DISCLAIMER_TEXT } from '../components/RiskDisclosure';
import { server } from '../mocks/server';
import { TERMINAL_ROWS } from '../mocks/fixtures';
import { T_VIEW_UNAVAILABLE, absAtLeast, availableBase, fmtShanghai, tViewHints } from './today/tViewModel';

beforeAll(() => preloadRoutes(routes), 30_000);
vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

// 整个文件在 America/Denver 下运行（共享电脑的机器时区），证明显示与机器时区无关
const ORIGINAL_TZ = process.env.TZ;
beforeAll(() => { process.env.TZ = 'America/Denver'; });
afterAll(() => { if (ORIGINAL_TZ === undefined) delete process.env.TZ; else process.env.TZ = ORIGINAL_TZ; });

const DATE = '2026-11-10';
const empty = { items: [], more: false };
const base = TERMINAL_ROWS.find((r) => r.holding)!;
const TV: TView = {
  vwap: '10.18', dev_pct: '0.5900', volume_ratio: '1.35', base_qty: '1000', sellable_qty: '700', data_status: 'fresh', as_of: '2026-11-10T02:31:00Z', gaps: [],
};
const row = (t: TView | null | undefined, code = '000001.SZ'): TodayFocusRow => ({ ...base, security_code: code, name: '示例甲', suggestion: null, t_view: t });

function today(items: TodayFocusRow[]): TodayResponse {
  return {
    server_time: '2026-11-10T02:31:30Z', trade_date: DATE, session: 'morning',
    market: { regime: null, regime_position_range: null, data_status: 'fresh' },
    focus: { items, more: false },
    pending_plan_drafts: empty, released_reasons: empty, risk_flags: empty, invalidations_today: empty,
    daily_report: { date: DATE, status: 'not_yet' },
    reconciliation: { status: 'matched', as_of: null, diff_count: 0, important_count: 0 },
    unread_notifications: 0, alerts: empty, plan_triggers: empty, data_gaps: empty, evidence: [],
  };
}
async function setup(items: TodayFocusRow[]) {
  server.use(http.get('/api/v1/today', () => HttpResponse.json(today(items))));
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  render(
    <AppProviders client={makeQueryClient(true)}>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: ['/today'] })} />
    </AppProviders>,
  );
  return screen.findByTestId('today-page');
}

describe('T-F36 做 T 视图（契约 §5.2 四条）', () => {
  it('t-f36 t_view 正常显示', async () => {
    const page = await setup([row(TV)]);
    const cell = await screen.findByTestId('t-view-000001.SZ');
    expect(cell).toHaveAttribute('data-state', 'fresh');
    expect(within(cell).getByTestId('t-view-000001.SZ-vwap')).toHaveTextContent('10.18');
    expect(within(cell).getByTestId('t-view-000001.SZ-dev')).toHaveTextContent(/^\+0\.59%$/);
    expect(within(cell).getByTestId('t-view-000001.SZ-vr')).toHaveTextContent('1.35');
    expect(within(cell).getByTestId('t-view-000001.SZ-avail')).toHaveTextContent('今日可用底仓 700 股');
    expect(within(cell).getByTestId('t-view-000001.SZ-asof')).toHaveTextContent('数据时间 2026-11-10 10:31');
    expect(cell).toHaveTextContent('分时均价');
    expect(within(cell).queryByTestId('t-view-000001.SZ-hint')).toBeNull();
    expect(page.textContent).not.toMatch(/买入|卖出/); // 合规禁词另由 test/wording.test.ts 全源扫描
    expect(screen.getByTestId('card-disclaimer')).toBeVisible();
    expect(screen.getByTestId('card-disclaimer')).toHaveTextContent(DISCLAIMER_TEXT);
  });

  it('t-f36 t_view 不可用', async () => {
    // T-F36b：持仓行一律带 t_view；不可用 = data_status unavailable 且无 not_applicable，并附原因；非持仓行 t_view 为 null，不显示做 T 视图
    const gap = { key: 't_view', reason: 'no_source' as const, message: '今日分时数据未取到（示例）' };
    await setup([
      row({ ...TV, vwap: null, dev_pct: null, volume_ratio: null, as_of: null, data_status: 'unavailable', gaps: [gap] }, '000002.SZ'),
      { ...row(null, '000003.SZ'), holding: null },
    ]);
    const cell = await screen.findByTestId('t-view-000002.SZ');
    expect(cell).toHaveAttribute('data-state', 'unavailable');
    expect(cell).toHaveTextContent(T_VIEW_UNAVAILABLE);
    expect(cell).toHaveTextContent('今日分时数据未取到（示例）');
    expect(cell).not.toHaveTextContent('偏离');
    expect(within(cell).queryByTestId('t-view-000002.SZ-dev')).toBeNull();
    expect(screen.queryByTestId('t-view-000003.SZ')).toBeNull();
  });

  it('t-f36 t_view partial：缺的指标为「—」', async () => {
    await setup([row({ ...TV, volume_ratio: null, dev_pct: null, data_status: 'partial', gaps: [{ key: 't_view.volume_ratio', reason: 'no_source', message: '历史分时不足 5 个交易日' }] })]);
    const cell = await screen.findByTestId('t-view-000001.SZ');
    expect(within(cell).getByTestId('t-view-000001.SZ-vr')).toHaveTextContent(/^—$/);
    expect(within(cell).getByTestId('t-view-000001.SZ-dev')).toHaveTextContent(/^—$/);
    expect(cell).toHaveTextContent('部分数据');
  });

  it('t-f36 可用底仓不超过昨日底仓', async () => {
    // T-F36b：前端不再截断，原样显示；违反（大于底仓或为负）显示「—」并附「数据核对中」
    expect(availableBase({ base_qty: '1000', sellable_qty: '700' })).toBe('700');
    expect(availableBase({ base_qty: '1000', sellable_qty: '1000' })).toBe('1000');
    expect(availableBase({ base_qty: '1000', sellable_qty: '1500' })).toBe('violation');
    expect(availableBase({ base_qty: '1000', sellable_qty: '-5' })).toBe('violation');
    expect(availableBase({ base_qty: '-100', sellable_qty: '50' })).toBe('violation');
    expect(availableBase({ base_qty: null, sellable_qty: '300' })).toBe('300');
    expect(availableBase({ base_qty: '1000', sellable_qty: null })).toBeNull();
    await setup([row({ ...TV, base_qty: '1000', sellable_qty: '1500' })]);
    const avail = await screen.findByTestId('t-view-000001.SZ-avail');
    expect(avail).toHaveTextContent('今日可用底仓 — 股（数据核对中）');
    expect(avail).not.toHaveTextContent('1,000');
    expect(avail).not.toHaveTextContent('1,500');
  });

  it('t-f36 时区按北京时间', async () => {
    expect(new Date('2026-11-10T02:31:00Z').getHours()).toBe(19); // 本文件确实跑在 America/Denver（前一日 19:31）
    for (const tz of ['America/Denver', 'UTC', 'Asia/Shanghai', 'Pacific/Kiritimati']) {
      process.env.TZ = tz;
      expect(fmtShanghai('2026-11-10T02:31:00Z')).toBe('2026-11-10 10:31');
      expect(fmtShanghai('2026-11-10T10:31:00+08:00')).toBe('2026-11-10 10:31');
    }
    process.env.TZ = 'America/Denver';
    expect(fmtShanghai(null)).toBeNull();
    expect(fmtShanghai('bad')).toBeNull();
    await setup([row({ ...TV, as_of: '2026-11-10T07:00:00Z' })]);
    expect(await screen.findByTestId('t-view-000001.SZ-asof')).toHaveTextContent('数据时间 2026-11-10 15:00');
  });
});

describe('T-F36 提示位（编排者更正：只在后端返回阈值字段时显示；字段名前端暂定）', () => {
  it('有阈值字段：刚好在阈值上显示、刚好在阈值下不显示（偏离正负两侧与量比；十进制精确比较；百分数不再 ×100）', () => {
    const t = (dev: string, vr: string) => ({ ...TV, dev_pct: dev, volume_ratio: vr, dev_pct_threshold: '2', volume_ratio_threshold: '2' });
    expect(tViewHints(t('2.0000', '2'))).toHaveLength(2);
    expect(tViewHints(t('-2.0000', '2.00'))).toHaveLength(2);
    expect(tViewHints(t('1.9999999999999999999', '1.9999999999999999999'))).toEqual([]);
    expect(tViewHints(t('-1.9999', '1.99'))).toEqual([]);
    expect(tViewHints(t('2.0000000000000000001', '1.50'))).toEqual(['偏离分时均价已达阈值（±2.00%）']);
    expect(tViewHints(t('0.0100', '2.0000000000000000001'))).toEqual(['量比已达阈值（2 倍）']);
    expect(absAtLeast('0.30000000000000004', '0.3')).toBe(true);
    expect(absAtLeast('0.29999999999999999', '0.3')).toBe(false);
    for (const h of tViewHints(t('5.0000', '3'))) expect(h).not.toMatch(/买|卖|推荐/);
  });
  it('没有阈值字段（缺失或 null）：偏离、量比很大也不显示', async () => {
    expect(tViewHints({ ...TV, dev_pct: '50.0000', volume_ratio: '9.00' })).toEqual([]);
    expect(tViewHints({ ...TV, dev_pct: '-50.0000', volume_ratio: '9.00', dev_pct_threshold: null, volume_ratio_threshold: null })).toEqual([]);
    await setup([row({ ...TV, dev_pct: '-50.0000', volume_ratio: '9.00' })]);
    const cell = await screen.findByTestId('t-view-000001.SZ');
    expect(within(cell).queryByTestId('t-view-000001.SZ-hint')).toBeNull();
  });
  it('有阈值字段时页面显示提示', async () => {
    await setup([row({ ...TV, dev_pct: '-2.0000', volume_ratio: '2.00', dev_pct_threshold: '2', volume_ratio_threshold: '2.00' })]);
    const hints = await screen.findAllByTestId('t-view-000001.SZ-hint');
    expect(hints.map((h) => h.textContent?.trim())).toEqual(['偏离分时均价已达阈值（±2.00%）', '量比已达阈值（2.00 倍）']);
  });
  it('默认 mock：持仓行带 t_view，且不带阈值字段', async () => {
    const t = (await (await fetch('/api/v1/today')).json()) as TodayResponse;
    const held = t.focus.items.filter((r) => r.holding);
    expect(held.some((r) => r.t_view && r.t_view.data_status !== 'unavailable')).toBe(true);
    for (const r of held) {
      expect(r.t_view).toBeTruthy();
      expect(Object.keys(r.t_view!).sort()).toEqual(['as_of', 'base_qty', 'data_status', 'dev_pct', 'gaps', 'sellable_qty', 'volume_ratio', 'vwap']);
      for (const k of ['vwap', 'dev_pct', 'volume_ratio', 'base_qty', 'sellable_qty'] as const) expect(['string', 'object']).toContain(typeof r.t_view![k]);
    }
    for (const r of t.focus.items.filter((x) => !x.holding)) expect(r.t_view ?? null).toBeNull();
  });
});
