/** T-F08（契约 v0.2.6 §7.3）：今日关注 /today */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import type { TodayResponse } from '../api/types';
import { DISCLAIMER_TEXT } from '../components/RiskDisclosure';
import { server } from '../mocks/server';
import { TERMINAL_ROWS, uid } from '../mocks/fixtures';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const CONTRACT = readFileSync(resolve(__dirname, '../../../../docs/api-contract.md'), 'utf8');
const TODAY_LINE = CONTRACT.split('\n').find((l) => l.startsWith('| GET | `/today`'))!;

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

/** 契约里某个列表元素的字段名，如 pending_plan_drafts: {items: [{id, ...}] */
function itemKeys(list: string) {
  const m = TODAY_LINE.match(new RegExp(`${list}: \\{items: \\[\\{([^}]*)\\}\\]`));
  if (!m) throw new Error(`契约中找不到 ${list}`);
  return m[1].split(',').map((s) => s.trim().split(':')[0]).sort();
}

const row = TERMINAL_ROWS.find((r) => r.suggestion && r.holding)!;
/** 各区都有数据、都被截断的示例（测试专用） */
const FULL: TodayResponse = {
  server_time: '2026-11-02T15:20:00+08:00', trade_date: '2026-11-02', session: 'closed',
  market: { regime: 'range', regime_position_range: { min_pct: '40', max_pct: '60' }, data_status: 'fresh' },
  focus: { items: [row], more: true },
  pending_plan_drafts: { items: [{ id: uid(901), security_code: row.security_code, name: row.name, action: 'reduce', valid_until: '2026-11-03T15:00:00+08:00', status: 'stale' }], more: true },
  released_reasons: { items: [{ reason_id: uid(902), signal_id: uid(903), code: 'T1_NOT_SELLABLE', security_code: row.security_code, name: row.name, released_at: '2026-11-02T09:30:00+08:00' }], more: true },
  risk_flags: { items: [{ control: 'total_exposure', level: 'critical', message: '示例：总仓位高于参考区间上限', gated_actions: ['buy', 'add'], quantity_cap: null, evidence_ids: [], security_code: null, name: null }], more: true },
  invalidations_today: { items: [{ suggestion_id: uid(904), security_code: row.security_code, name: row.name, strategy_key: 'T-01', text: '示例：收盘跌破 20 日线，失效条件满足', at: '2026-11-02T15:00:00+08:00' }], more: true },
  daily_report: { date: '2026-11-02', status: 'ready' },
  reconciliation: { status: 'not_imported', as_of: null, diff_count: 0, important_count: 0 },
  unread_notifications: 7,
};

describe('T-F08 今日关注', () => {
  it('列表元素字段与契约 §7.3 一致（mock 与测试示例都检查）', async () => {
    const t = (await (await fetch('/api/v1/today')).json()) as TodayResponse;
    for (const k of ['pending_plan_drafts', 'released_reasons', 'invalidations_today'] as const) {
      for (const x of [...t[k].items, ...FULL[k].items]) expect(Object.keys(x).sort()).toEqual(itemKeys(k));
    }
    expect(Object.keys(t.daily_report).sort()).toEqual(['date', 'status']);
    expect(Object.keys(t.reconciliation).sort()).toEqual(['as_of', 'diff_count', 'important_count', 'status']);
    expect(Object.keys(t.market).sort()).toEqual(['data_status', 'regime', 'regime_position_range']);
  });

  it('默认 mock：不再是占位页；展示时段、大盘环境、重点关注、草案、风险、日报与对账、免责提示', async () => {
    const t = (await (await fetch('/api/v1/today')).json()) as TodayResponse;
    renderAt('/today');
    const page = await screen.findByTestId('today-page');
    expect(screen.queryByTestId('placeholder')).toBeNull();
    expect(screen.getByTestId('today-session')).toHaveTextContent('上午连续竞价');
    expect(screen.getByTestId('today-regime')).toHaveTextContent('不是指令');
    expect(within(page).getByTestId('card-disclaimer')).toHaveTextContent(DISCLAIMER_TEXT);
    // 重点关注：行数与接口一致，证券链接到个股页
    const focus = screen.getByTestId('today-focus');
    for (const r of t.focus.items) expect(within(focus).getByRole('link', { name: new RegExp(r.security_code) })).toHaveAttribute('href', `/stocks/${r.security_code}`);
    // 草案：链接到 /plan-drafts/{id}
    const drafts = screen.getByTestId('today-drafts');
    expect(t.pending_plan_drafts.items.length).toBeGreaterThan(0);
    for (const d of t.pending_plan_drafts.items) expect(within(drafts).getAllByRole('link').map((a) => a.getAttribute('href'))).toContain(`/plan-drafts/${d.id}`);
    expect(within(screen.getByTestId('today-risks')).getAllByRole('listitem')).toHaveLength(t.risk_flags.items.length);
    // 空列表显示“无”，没有“查看全部”
    expect(within(screen.getByTestId('today-invalidations')).getByText('无')).toBeInTheDocument();
    expect(screen.queryByTestId('today-focus-more')).toBeNull();
    expect(screen.getByTestId('today-daily-report')).toHaveTextContent('尚未生成');
    expect(screen.getByTestId('today-unread')).toHaveAttribute('href', '/notifications');
  });

  it('完整示例：more=true 给出列表页入口；账户级风险无证券链接；日报 ready、未导入对账', async () => {
    server.use(http.get('/api/v1/today', () => HttpResponse.json(FULL)));
    renderAt('/today');
    await screen.findByTestId('today-page');
    const more: Record<string, string> = {
      'today-focus-more': '/terminal', 'today-drafts-more': '/plan-drafts', 'today-released-more': '/candidate-signals',
      'today-risks-more': '/risk-controls', 'today-invalidations-more': '/suggestions',
    };
    for (const [id, href] of Object.entries(more)) expect(screen.getByTestId(id)).toHaveAttribute('href', href);
    expect(screen.getByTestId('today-session')).toHaveTextContent('已收盘');
    const drafts = screen.getByTestId('today-drafts');
    expect(drafts).toHaveTextContent('条件已变');
    expect(drafts).toHaveTextContent('有效至 2026-11-03 15:00');
    const rel = screen.getByTestId('today-released');
    expect(rel).toHaveTextContent('T+1 不可卖');
    expect(within(rel).getByRole('link', { name: new RegExp(row.name) })).toHaveAttribute('href', `/candidate-signals/${uid(903)}`);
    const risks = screen.getByTestId('today-risks');
    expect(risks).toHaveTextContent('账户级');
    expect(risks).toHaveTextContent('RC3 总仓位');
    expect(within(risks).getAllByRole('link').map((a) => a.getAttribute('href'))).toEqual(['/risk-controls']); // 只有“查看全部”
    const inv = screen.getByTestId('today-invalidations');
    expect(within(inv).getByRole('link', { name: new RegExp(row.name) })).toHaveAttribute('href', `/suggestions/${uid(904)}`);
    expect(inv).toHaveTextContent('失效条件满足');
    expect(within(screen.getByTestId('today-daily-report')).getByRole('link')).toHaveAttribute('href', '/daily-reports/2026-11-02');
    expect(within(screen.getByTestId('today-reconciliation')).getByRole('link')).toHaveAttribute('href', '/portfolio/import');
    expect(screen.getByTestId('today-unread')).toHaveTextContent('7');
  });

  it('对账有差异时显示差异数并链接到对账页；日报生成中', async () => {
    server.use(http.get('/api/v1/today', () => HttpResponse.json({
      ...FULL, daily_report: { date: '2026-11-02', status: 'generating' },
      reconciliation: { status: 'diff', as_of: '2026-11-02T15:10:00+08:00', diff_count: 3, important_count: 1 },
    } satisfies TodayResponse)));
    renderAt('/today');
    const rec = await screen.findByTestId('today-reconciliation');
    expect(rec).toHaveTextContent('差异 3 项，其中重要 1 项');
    expect(within(rec).getByRole('link')).toHaveAttribute('href', '/portfolio?tab=reconciliation');
    expect(screen.getByTestId('today-daily-report')).toHaveTextContent('生成中');
  });

  it('接口失败显示错误，不显示空白页', async () => {
    server.use(http.get('/api/v1/today', () => HttpResponse.json({ error: { code: 'INTERNAL', message: 'x', details: {}, request_id: 'r' } }, { status: 500 })));
    renderAt('/today');
    await waitFor(() => expect(screen.getByText(/加载失败/)).toBeInTheDocument());
  });

  it('从顶部导航进入今日关注', async () => {
    const router = renderAt('/terminal');
    await screen.findByTestId('terminal');
    fireEvent.click(screen.getAllByRole('link', { name: '今日关注' })[0]);
    await screen.findByTestId('today-page', undefined, { timeout: 5000 });
    expect(router.state.location.pathname).toBe('/today');
  });
});
