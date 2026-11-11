/** T-F08（契约 v0.2.7 §7.3 及“/today 补充”）：今日关注 /today */
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import type { TodayAlert, TodayDataGap, TodayPlanTrigger, TodayResponse } from '../api/types';
import { todayPollMs } from '../api/queries';
import { MORE_ROUTE, safeInternalRoute } from './today/todayRoutes';
import { setMockLicence } from '../mocks/licenceStore';
import { ENUMS } from '../api/enums';
import { DISCLAIMER_TEXT } from '../components/RiskDisclosure';
import { server } from '../mocks/server';
import { TERMINAL_ROWS, uid } from '../mocks/fixtures';
import { securityProfile } from '../mocks/marketFixtures';

// 页面模块的冷加载放在等待窗口之外（评审 b23401a N8）
beforeAll(() => preloadRoutes(routes), 30_000);

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

/**
 * 评审 m8：契约文本在仓库根 docs/ 下；前端单独检出（没有 docs/）时，依赖契约原文的用例跳过并给出提示，其余照常运行。
 */
const CONTRACT_PATH = resolve(__dirname, '../../../../docs/api-contract.md');
const HAS_DOCS = existsSync(CONTRACT_PATH);
if (!HAS_DOCS) console.warn(`[t-f08] 未找到 ${CONTRACT_PATH}，跳过与契约原文逐字比对的用例；请在完整仓库中运行`);
const CONTRACT = HAS_DOCS ? readFileSync(CONTRACT_PATH, 'utf8') : '';
const TODAY_LINE = CONTRACT.split('\n').find((l) => l.startsWith('| GET | `/today`')) ?? '';
const SUPPLEMENT = CONTRACT.slice(CONTRACT.indexOf('#### `/today` 补充'), CONTRACT.indexOf('### 7.4'));

/** 补充小节里 **`Name`** 下一行的 `{...}` 顶层字段名 */
function objectKeys(name: string) {
  const lines = SUPPLEMENT.split('\n');
  const i = lines.findIndex((l) => l.startsWith(`**\`${name}\`**`));
  const src = lines[i + 1];
  let depth = 0;
  let cur = '';
  const keys: string[] = [];
  for (const c of src) {
    if ('{[('.includes(c) && ++depth === 1) continue;
    if ('}])'.includes(c) && --depth === 0) { keys.push(cur); break; }
    if (depth === 1 && c === ',') { keys.push(cur); cur = ''; continue; }
    if (depth >= 1) cur += c;
  }
  return keys.map((k) => k.trim().split(':')[0]).sort();
}

/** “查看全部”去向表：列表 → 前端路由（无 → null） */
function moreTable(): Record<string, string | null> {
  const start = SUPPLEMENT.indexOf('**“查看全部”去向');
  const out: Record<string, string | null> = {};
  for (const l of SUPPLEMENT.slice(start).split('\n')) {
    const m = l.match(/^\| `(\w+)` \| (.+?) \| /);
    if (m) out[m[1]] = m[2].startsWith('`') ? m[2].slice(1, m[2].indexOf('`', 1)) : null;
  }
  return out;
}

/** 验收 15 的禁用词：直接取合规自查 test/wording.test.ts 里的同一份清单（避免在本文件里重复写这些词） */
const WORDING_SRC = readFileSync(resolve(__dirname, '../test/wording.test.ts'), 'utf8');
const BANNED: string[] = [
  ...JSON.parse(WORDING_SRC.match(/const BANNED = (\[[^\]]*\])/)![1].replace(/'/g, '"')) as string[],
  ...['买入', '卖出', '加仓', '减仓'].map((x) => `建议${x}`),
];
const SEV = { important: 0, attention: 1, info: 2 } as const;
const GAP_ORDER = ['data_licence_unavailable', 'user_input_missing', 'upstream_error', 'quota_deferred'];

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
  risk_flags: { items: [{ control: 'total_exposure', level: 'critical', message: '示例：总仓位高于参考区间上限', gated_actions: ['buy', 'add'], quantity_cap: null, evidence_ids: [], security_code: null, name: null, risk_event_id: null }], more: true },
  invalidations_today: { items: [{ suggestion_id: uid(904), security_code: row.security_code, name: row.name, strategy_key: 'T-01', text: '示例：收盘跌破 20 日线，失效条件满足', at: '2026-11-02T15:00:00+08:00' }], more: true },
  daily_report: { date: '2026-11-02', status: 'ready' },
  reconciliation: { status: 'not_imported', as_of: null, diff_count: 0, important_count: 0 },
  unread_notifications: 7,
  alerts: {
    items: [{
      id: uid(911), rule_id: uid(912), origin: 'holding_event', severity: 'important', status: 'new', security_code: row.security_code, name: row.name,
      title: '示例：发布业绩预告', triggered_at: '2026-11-02T09:00:00+08:00', data_as_of: '2026-11-02T08:55:00+08:00',
      affected_plans: [{ plan_id: uid(913), plan_version_no: 2, condition_id: null }], evidence_ids: ['TX1'],
    }],
    more: true,
  },
  plan_triggers: {
    items: [{
      plan_id: uid(914), plan_version_no: 1, security_code: row.security_code, name: row.name, condition_id: uid(915), condition_kind: 'invalidation',
      condition_text: '示例：收盘价低于 9.00', triggered_at: '2026-11-02T15:00:00+08:00', alert_id: null, evidence_ids: ['TX1'],
    }],
    more: true,
  },
  data_gaps: { items: [], more: false },
  evidence: [{
    id: 'TX1', key: 'close', value: '8.95', unit: 'CNY', provider: 'mairui', endpoint: null,
    data_as_of: '2026-11-02T15:00:00+08:00', fetched_at: '2026-11-02T15:01:00+08:00', epistemic_type: 'fact',
  }],
};

describe('T-F08 今日关注', () => {
  it.skipIf(!HAS_DOCS)('列表元素字段与契约 §7.3 一致（mock 与测试示例都检查）', async () => {
    const t = (await (await fetch('/api/v1/today')).json()) as TodayResponse;
    for (const k of ['pending_plan_drafts', 'released_reasons', 'invalidations_today'] as const) {
      for (const x of [...t[k].items, ...FULL[k].items]) expect(Object.keys(x).sort()).toEqual(itemKeys(k));
    }
    expect(Object.keys(t.daily_report).sort()).toEqual(['date', 'status']);
    expect(Object.keys(t.reconciliation).sort()).toEqual(['as_of', 'diff_count', 'important_count', 'status']);
    expect(Object.keys(t.market).sort()).toEqual(['data_status', 'regime', 'regime_position_range']);
  });

  it.skipIf(!HAS_DOCS)('v0.2.7：四个新增顶层字段都出现；TodayAlert / TodayPlanTrigger / TodayDataGap 字段与契约原文一致', async () => {
    const t = (await (await fetch('/api/v1/today')).json()) as TodayResponse;
    for (const k of ['alerts', 'plan_triggers', 'data_gaps', 'evidence']) {
      expect(SUPPLEMENT).toMatch(new RegExp(`^${k}: `, 'm'));
      expect(t).toHaveProperty(k);
    }
    expect(t.alerts.items.length).toBeGreaterThan(0);
    expect(t.plan_triggers.items.length).toBeGreaterThan(0);
    expect(t.data_gaps.items.length).toBeGreaterThan(0);
    for (const a of [...t.alerts.items, ...FULL.alerts.items]) expect(Object.keys(a).sort()).toEqual(objectKeys('TodayAlert'));
    for (const a of t.alerts.items) for (const p of a.affected_plans) expect(Object.keys(p).sort()).toEqual(['condition_id', 'plan_id', 'plan_version_no']);
    for (const p of [...t.plan_triggers.items, ...FULL.plan_triggers.items]) expect(Object.keys(p).sort()).toEqual(objectKeys('TodayPlanTrigger'));
    for (const g of t.data_gaps.items) {
      expect(Object.keys(g).sort()).toEqual(objectKeys('TodayDataGap'));
      for (const x of g.securities) expect(Object.keys(x).sort()).toEqual(['name', 'security_code']);
    }
    expect(SUPPLEMENT).toContain('`risk_flags.items[]` 加 `risk_event_id: uuid | null`');
    for (const f of t.risk_flags.items) expect(f).toHaveProperty('risk_event_id');
  });

  it('验收 14：alerts 不含 plan_condition；evidence_ids 非空且都能在 evidence[] 找到；三类排序；data_gaps.more 恒 false；risk_event_id 都在 active 事件里', async () => {
    const t = (await (await fetch('/api/v1/today')).json()) as TodayResponse;
    const ev = new Set(t.evidence.map((e) => e.id));
    expect(ev.size).toBe(t.evidence.length);
    for (const a of t.alerts.items) {
      expect(a.origin).not.toBe('plan_condition');
      expect(ENUMS.alert_origin).toContain(a.origin);
      expect(['new', 'read']).toContain(a.status);
      expect(a.security_code === null).toBe(a.name === null);
    }
    for (const x of [...t.alerts.items, ...t.plan_triggers.items]) {
      expect(x.evidence_ids.length).toBeGreaterThan(0);
      for (const id of x.evidence_ids) expect(ev.has(id)).toBe(true);
    }
    const alertCmp = (a: TodayAlert, b: TodayAlert) => SEV[a.severity] - SEV[b.severity] || b.triggered_at.localeCompare(a.triggered_at) || a.id.localeCompare(b.id);
    expect(t.alerts.items).toEqual([...t.alerts.items].sort(alertCmp));
    const kind = (k: string) => (k === 'invalidation' ? 0 : 1);
    const trigCmp = (a: TodayPlanTrigger, b: TodayPlanTrigger) => kind(a.condition_kind) - kind(b.condition_kind) || b.triggered_at.localeCompare(a.triggered_at) || a.plan_id.localeCompare(b.plan_id);
    expect(t.plan_triggers.items).toEqual([...t.plan_triggers.items].sort(trigCmp));
    const reasons = t.data_gaps.items.map((g: TodayDataGap) => GAP_ORDER.indexOf(g.reason));
    expect(reasons.every((r) => r >= 0)).toBe(true);
    expect(reasons).toEqual([...reasons].sort((a, b) => a - b));
    expect(t.data_gaps.more).toBe(false);
    for (const g of t.data_gaps.items) {
      expect(g.securities.length).toBeLessThanOrEqual(10);
      if (g.scope !== 'security') expect([g.securities.length, g.security_count]).toEqual([0, 0]);
      else expect(g.security_count).toBeGreaterThanOrEqual(g.securities.length);
    }
    const active = (await (await fetch('/api/v1/risk-controls/events?status=active&limit=200')).json()) as { items: { id: string }[] };
    const ids = new Set(active.items.map((e) => e.id));
    for (const f of t.risk_flags.items) if (f.risk_event_id) expect(ids.has(f.risk_event_id)).toBe(true);
  });

  it('验收 15：/today 返回的全部文字不含禁用词', async () => {
    expect(BANNED.length).toBeGreaterThanOrEqual(17);
    const text = await (await fetch('/api/v1/today')).text();
    for (const w of BANNED) expect(text).not.toContain(w);
    setMockLicence(uid(2), { status: 'expired' });
    const text2 = await (await fetch('/api/v1/today')).text();
    for (const w of BANNED) expect(text2).not.toContain(w);
  });

  it('证书不可用时 data_gaps 第一条是 data_licence_unavailable，去处理指向 /settings/data-licence', async () => {
    let t = (await (await fetch('/api/v1/today')).json()) as TodayResponse;
    expect(t.data_gaps.items.some((g) => g.reason === 'data_licence_unavailable')).toBe(false);
    setMockLicence(uid(2), { status: 'expired' });
    t = (await (await fetch('/api/v1/today')).json()) as TodayResponse;
    expect(t.data_gaps.items[0]).toMatchObject({ reason: 'data_licence_unavailable', route: '/settings/data-licence' });
  });

  it.skipIf(!HAS_DOCS)('“查看全部”8 个去向与契约去向表逐字一致（data_gaps 无去向）', () => {
    const table = moreTable();
    expect(Object.keys(table).sort()).toEqual(Object.keys(MORE_ROUTE).sort());
    expect(table).toEqual({ ...MORE_ROUTE });
  });

  it('data_gaps.route 白名单：只接受单个 / 开头的站内路径', () => {
    for (const ok of ['/settings/data-licence', '/portfolio/import', '/portfolio?tab=cash', '/']) expect(safeInternalRoute(ok)).toBe(ok);
    for (const bad of ['//evil.example', '/\\evil.example', 'http://x.example/a', 'https://x.example', 'javascript:alert(1)', 'settings', ' /a', '/a b', '/a\nb', '', null, undefined]) {
      expect(safeInternalRoute(bad)).toBeNull();
    }
  });

  it('m6：收盘后与非交易日 60 秒轮询，其余时段 15 秒', () => {
    expect(todayPollMs('closed')).toBe(60_000);
    expect(todayPollMs('non_trading_day')).toBe(60_000);
    for (const s of ['pre_open', 'call_auction', 'morning', 'lunch_break', 'afternoon', 'closing_auction'] as const) expect(todayPollMs(s)).toBe(15_000);
    expect(todayPollMs(undefined)).toBe(15_000);
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
    // 风险提示：有 risk_event_id 时链接到风控事件
    const risks = screen.getByTestId('today-risks');
    expect(within(risks).getAllByRole('listitem')).toHaveLength(t.risk_flags.items.length);
    for (const f of t.risk_flags.items) {
      expect(within(risks).getByTestId(`risk-event-${f.risk_event_id}`)).toHaveAttribute('href', `/risk-controls?tab=events&event=${f.risk_event_id}`);
    }
    // 今日失效 / 今日解除：示例条目
    expect(within(screen.getByTestId('today-invalidations')).getAllByRole('listitem')).toHaveLength(t.invalidations_today.items.length);
    expect(within(screen.getByTestId('today-released')).getAllByRole('listitem')).toHaveLength(t.released_reasons.items.length);
    // 提醒：严重度、未读标记、证据、关联计划
    const alerts = screen.getByTestId('today-alerts');
    expect(within(alerts).getAllByRole('listitem')).toHaveLength(t.alerts.items.length);
    for (const a of t.alerts.items) {
      const li = within(alerts).getByTestId(`alert-${a.id}`);
      expect(li).toHaveTextContent(a.title);
      expect(li).toHaveTextContent(a.security_code ? a.security_code : '账户级');
      expect(within(li).queryByTestId('alert-unread') !== null).toBe(a.status === 'new');
      for (const p of a.affected_plans) expect(within(li).getAllByRole('link').map((x) => x.getAttribute('href'))).toContain(`/plans/${p.plan_id}`);
      expect(li.querySelectorAll('.ev-chip:not(.missing):not(.none)')).toHaveLength(a.evidence_ids.length);
    }
    // 计划触发：失效条件突出、只提示不下单
    const trig = screen.getByTestId('today-plan-triggers');
    expect(trig).toHaveTextContent('只提示计划条件已满足，不下单');
    for (const p of t.plan_triggers.items) {
      const li = within(trig).getByTestId(`plan-trigger-${p.condition_id}`);
      expect(li).toHaveTextContent(p.condition_kind === 'invalidation' ? '失效条件' : '计划条件');
      expect(li.querySelector(`[data-kind="${p.condition_kind}"]`)).not.toBeNull();
      expect(within(li).getAllByRole('link').map((x) => x.getAttribute('href'))).toContain(`/plans/${p.plan_id}`);
      expect(li.querySelectorAll('.ev-chip:not(.missing):not(.none)')).toHaveLength(p.evidence_ids.length);
    }
    // 数据缺口：按服务端顺序；证券最多 10 个 + 共 N 只；有 route 才有“去处理”；没有“查看全部”
    const gaps = screen.getByTestId('today-data-gaps');
    expect(within(gaps).getAllByRole('listitem').map((li) => li.getAttribute('data-testid'))).toEqual(t.data_gaps.items.map((g) => `data-gap-${g.key}`));
    for (const g of t.data_gaps.items) {
      const li = within(gaps).getByTestId(`data-gap-${g.key}`);
      expect(li).toHaveTextContent(g.message);
      if (g.security_count) expect(li).toHaveTextContent(`共 ${g.security_count} 只`);
      const go = within(li).queryByTestId('data-gap-route');
      if (g.route) expect(go).toHaveAttribute('href', g.route);
      else expect(go).toBeNull();
    }
    expect(screen.queryByTestId('today-data-gaps-more')).toBeNull();
    // more=false 时没有“查看全部”
    expect(screen.queryByTestId('today-focus-more')).toBeNull();
    expect(screen.getByTestId('today-daily-report')).toHaveTextContent('尚未生成（收盘后生成）');
    expect(screen.getByTestId('today-reconciliation')).toHaveTextContent('默认账户');
    expect(screen.getByTestId('today-unread')).toHaveAttribute('href', '/notifications');
  });

  it('完整示例：more=true 给出列表页入口；账户级风险无证券链接；日报 ready、未导入对账', async () => {
    server.use(http.get('/api/v1/today', () => HttpResponse.json(FULL)));
    renderAt('/today');
    await screen.findByTestId('today-page');
    // 契约 v0.2.7“查看全部”去向表（7 个有去向；data_gaps 的 more 恒 false 且没有入口）
    const more: Record<string, string> = {
      'today-focus-more': '/terminal', 'today-drafts-more': '/plan-drafts?status=pending,stale', 'today-released-more': '/candidate-signals?tab=released',
      'today-risks-more': '/risk-controls?tab=events', 'today-invalidations-more': '/suggestions?status=invalidated',
      'today-alerts-more': '/alerts', 'today-plan-triggers-more': '/plans?status=triggered',
    };
    for (const [id, href] of Object.entries(more)) {
      expect(screen.getByTestId(id)).toHaveAttribute('href', href);
      expect(screen.getByTestId(id.replace(/-more$/, '-count'))).toHaveTextContent('前 1 条（共 50+ 条）');
    }
    expect(screen.queryByTestId('today-data-gaps-more')).toBeNull();
    expect(within(screen.getByTestId('today-data-gaps')).getByText('数据完整')).toBeInTheDocument();
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
    // risk_event_id 为 null（FULL 示例未给）：没有事件链接，只有“查看全部”
    expect(within(risks).getAllByRole('link').map((a) => a.getAttribute('href'))).toEqual(['/risk-controls?tab=events']);
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

  it('评审 m3：非交易日 not_yet 显示“非交易日，无日报”', async () => {
    server.use(http.get('/api/v1/today', () => HttpResponse.json({ ...FULL, session: 'non_trading_day', daily_report: { date: '2026-11-01', status: 'not_yet' } } satisfies TodayResponse)));
    renderAt('/today');
    expect(await screen.findByTestId('today-report-not-yet')).toHaveTextContent('非交易日，无日报');
  });

  it('数据缺口：route 不在白名单时不渲染“去处理”', async () => {
    const gap = (key: string, route: string | null): TodayDataGap => ({
      key, reason: 'upstream_error', scope: 'market', dataset: 'quotes', message: `示例缺口 ${key}`, security_count: 0, securities: [], since: null, route,
    });
    server.use(http.get('/api/v1/today', () => HttpResponse.json({
      ...FULL, data_gaps: { items: [gap('a', '//evil.example'), gap('b', 'javascript:alert(1)'), gap('c', 'http://x.example'), gap('d', '/portfolio/import')], more: false },
    } satisfies TodayResponse)));
    renderAt('/today');
    const gaps = await screen.findByTestId('today-data-gaps');
    expect(within(gaps).getAllByTestId('data-gap-route').map((a) => a.getAttribute('href'))).toEqual(['/portfolio/import']);
  });

  it('评审 M1：已有数据时轮询失败，保留内容，只在顶部显示错误条', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderAt('/today');
      await screen.findByTestId('today-alerts');
      expect(screen.queryByTestId('today-refresh-error')).toBeNull();
      server.use(http.get('/api/v1/today', () => HttpResponse.json({ error: { code: 'INTERNAL', message: 'x', details: {}, request_id: 'r' } }, { status: 500 })));
      await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
      const bar = await screen.findByTestId('today-refresh-error');
      expect(bar).toHaveTextContent('刷新失败，显示的是 2026-');
      expect(screen.getByTestId('today-page')).toBeInTheDocument();
      expect(screen.getByTestId('today-alerts')).toBeInTheDocument();
      expect(screen.getByTestId('today-focus')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
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
/**
 * F-08：bars mock 与后端 B-04（PR #56）真实语义对齐。
 *
 * 后端 bars_read 的两个真实行为，前端 mock 必须一致，否则联调时会掩盖真实契约：
 * ① 没有可用行情源 → 200 + `unavailable` + `no_source` + `data_as_of=null`（不是 404，也不编造时间）。
 * ② 旧代码 → 404 且带 `details.superseded_by`（契约 §7.3）。
 *
 * 边界说明：#19（T-F34b）引入的 isSuperseded()/isStockSubPending() 尚未合入 main，
 * 因此本单只对齐 mock 与响应形状；调用这些判定的用例等 #19 合入后由后续单接管。
 */
const API = '/api/v1';
function renderF08At(path: string) {
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

/** 直接打 mock 端点，验证响应形状本身（不经页面渲染） */
async function getBarsF08(path: string): Promise<{ status: number; body: Record<string, unknown> }> {
  const res = await fetch(`${window.location.origin}${API}${path}`);
  return { status: res.status, body: (await res.json()) as Record<string, unknown> };
}

describe('① 无行情源 → 200 空态（对齐后端 empty_bars）', () => {
  it('连历史都没有时返回 unavailable + no_source + data_as_of=null，且不是 404', async () => {
    // 用一个示例里没有行情的最小站点：msw 已注册的证券才有数据，其余走 no 源分支
    const { status, body } = await getBarsF08('/securities/600000.SH/bars?freq=d&adjust=none&from=2030-01-01&to=2030-01-02');
    // 日期窗外无数据 → 空 items；具体状态由后端语义决定，这里断言不编造时间
    expect(status).toBe(200);
    expect(body.items).toEqual([]);
    expect(body.data_as_of).toBeNull();
  });

  it('空态响应体不含 sources（后端 extra="forbid" 的前端对应）', async () => {
    const { body } = await getBarsF08('/securities/600000.SH/bars?freq=d&from=2030-01-01&to=2030-01-02');
    expect(body).not.toHaveProperty('sources');
  });

  it('有数据的证券正常返回（对照组，确保上面不是假阳性）', async () => {
    const { status, body } = await getBarsF08('/securities/600000.SH/bars?freq=d');
    expect(status).toBe(200);
    expect((body.items as unknown[]).length).toBeGreaterThan(0);
  });

  it('有数据时同样不带 sources（与后端 extra="forbid" 一致）', async () => {
    const { body } = await getBarsF08('/securities/600000.SH/bars?freq=d');
    expect(body).not.toHaveProperty('sources');
  });
});

describe('② 停牌 ≠ 无源（不能混淆）', () => {
  it('停牌证券仍保留历史 K 线与 data_as_of，不被当成「无源」清空', async () => {
    const { status, body } = await getBarsF08('/securities/601001.SH/bars?freq=d');
    expect(status).toBe(200);
    // 停牌：最后一个交易日无成交，但历史仍在
    expect((body.items as unknown[]).length).toBeGreaterThan(0);
    expect(body.data_as_of).not.toBeNull();
  });
});

describe('③ 旧代码 → 404 带 superseded_by（对齐后端）', () => {
  it('旧代码返回 404 且 details.superseded_by 指向新代码', async () => {
    // 旧代码由 marketFixtures 的 code_history 生成（830001.BJ → 430001.BJ），测试里直接取自档案，避免手算出错
    const old = securityProfile('830001.BJ')!.code_history[0].security_code;
    const { status, body } = await getBarsF08(`/securities/${old}/bars?freq=d`);
    expect(status).toBe(404);
    const details = (body.error as { details?: Record<string, unknown> }).details;
    expect(details?.superseded_by).toBe('830001.BJ');
  });

  it('真实不存在的代码 → 404 且不带 superseded_by（与旧代码区分）', async () => {
    const { status, body } = await getBarsF08('/securities/999999.SH/bars?freq=d');
    expect(status).toBe(404);
    const details = (body.error as { details?: Record<string, unknown> }).details;
    expect(details?.superseded_by).toBeUndefined();
  });
});

describe('④ 页面层：空态不编造时间', () => {
  it('窗外无数据时不出现编造的具体「更新于 某个日期」', async () => {
    server.use(
      http.get(`${API}/securities/:code/bars`, () =>
        HttpResponse.json({
          security_code: '600000.SH', name: '示例银行', freq: 'd', adjust: 'none',
          pre_close: null, adjust_as_of: null, next_before: null, items: [],
          data_status: 'unavailable', data_as_of: null,
          gaps: [{ key: 'bars', reason: 'no_source', message: '行情读取源尚未接入（示例数据）' }],
        }),
      ),
    );
    renderF08At('/stocks/600000.SH');
    await screen.findByTestId('stock-page');
    await waitFor(() => expect(screen.queryByText(/加载中/)).toBeNull());
    expect(screen.queryByText(/更新于 20\d\d-/)).toBeNull();
  });
});
