/** T-F34：today 页 13 个状态、缺口 code 表、未知兜底、北京时间边界（契约 docs/contracts/today-view.md §2–§4，示例数据） */
import { render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import type { DailyReport, TerminalRow, TodayResponse } from '../api/types';
import { ACTION_SHORT } from '../i18n/labels';
import { DISCLAIMER_TEXT } from '../components/RiskDisclosure';
import { server } from '../mocks/server';
import { TERMINAL_ROWS } from '../mocks/fixtures';
import { todayViewReport } from '../mocks/todayFixtures';
import {
  A1_TEXT, GAP_CODES, R2_TEXT, REPORT_EXPECTED_AT, REPORT_OVERDUE_AT, STATE_TEXT, UNKNOWN_GAP_TEXT, USER_INPUT_GAP_TEXT, buildReportGaps, overdueAt, parsePipelineKey, preReportState, s4Text, shanghaiMinutes,
} from './today/todayView';

beforeAll(() => preloadRoutes(routes), 30_000);
vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

// 整个文件在 America/Denver 下运行，证明判定与机器/浏览器时区无关（共享电脑即为该时区）
const ORIGINAL_TZ = process.env.TZ;
beforeAll(() => { process.env.TZ = 'America/Denver'; });
afterAll(() => { if (ORIGINAL_TZ === undefined) delete process.env.TZ; else process.env.TZ = ORIGINAL_TZ; });

const DATE = '2026-11-10';
/** 北京时间 HH:MM → UTC 的 server_time（Z 结尾，迫使前端自行换算） */
const bj = (t: string) => {
  const [h, m] = t.split(':').map(Number);
  const d = new Date(Date.UTC(2026, 10, 10, h - 8, m));
  return d.toISOString().replace('.000Z', 'Z');
};
const base = TERMINAL_ROWS.find((r) => r.holding)!;
const held: TerminalRow = { ...base, security_code: '000001.SZ', name: '示例甲', suggestion: null };
const withSg: TerminalRow = { ...held, suggestion: base.suggestion ?? TERMINAL_ROWS.find((r) => r.suggestion)!.suggestion };
const empty = { items: [], more: false };

function today(x: Partial<TodayResponse> = {}): TodayResponse {
  return {
    server_time: bj('18:40'), trade_date: DATE, session: 'closed',
    market: { regime: null, regime_position_range: null, data_status: 'fresh' },
    focus: { items: [held], more: false },
    pending_plan_drafts: empty, released_reasons: empty, risk_flags: empty, invalidations_today: empty,
    daily_report: { date: DATE, status: 'ready' },
    reconciliation: { status: 'matched', as_of: null, diff_count: 0, important_count: 0 },
    unread_notifications: 0, alerts: empty, plan_triggers: empty, data_gaps: empty, evidence: [],
    ...x,
  };
}
const ACCOUNT: NonNullable<DailyReport['account']> = { total_assets: '100000.00', cash: '20000.00', position_pct: '80.00', pnl_day: '125.50', position_vs_regime: null };

let urls: string[] = [];
function setup(t: TodayResponse, report: DailyReport | null = todayViewReport(DATE, [], ACCOUNT)) {
  server.use(
    http.get('/api/v1/today', () => HttpResponse.json(t)),
    http.get('/api/v1/daily-reports/:date', ({ params }) => (report && params.date === report.date
      ? HttpResponse.json(report)
      : HttpResponse.json({ error: { code: 'NOT_FOUND', message: '日报不存在', details: null, request_id: 'req-test' } }, { status: 404 }))),
  );
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  render(
    <AppProviders client={makeQueryClient(true)}>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: ['/today'] })} />
    </AppProviders>,
  );
  return screen.findByTestId('today-page');
}
const reportRequests = () => urls.filter((u) => new URL(u).pathname.startsWith('/api/v1/daily-reports/'));
const barState = () => screen.queryByTestId('today-status-bar')?.getAttribute('data-state') ?? 'S9';
beforeEach(() => { urls = []; server.events.on('request:start', ({ request }) => { urls.push(request.url); }); });
afterEach(() => { server.events.removeAllListeners(); });

/** 等日报请求完成并渲染（ready 时）；非 ready 时等一轮让潜在请求有机会发出 */
async function settled(ready: boolean) {
  if (ready) await waitFor(() => expect(screen.queryByTestId('today-account') ?? screen.queryByTestId('today-report-gaps-error')).not.toBeNull());
  else await new Promise((r) => setTimeout(r, 30));
}

describe('T-F34 时间换算（纯函数）', () => {
  it('与进程时区无关：同一 server_time 在任意 TZ 下换算到同一北京时间', () => {
    expect(new Date('2026-11-10T09:20:00Z').getHours()).toBe(2); // 证明本文件确实跑在 America/Denver
    for (const tz of ['America/Denver', 'UTC', 'Pacific/Kiritimati', 'Asia/Shanghai']) {
      process.env.TZ = tz;
      expect(shanghaiMinutes('2026-11-10T09:20:00Z')).toBe(17 * 60 + 20);
      expect(shanghaiMinutes('2026-11-10T17:20:00+08:00')).toBe(17 * 60 + 20);
    }
    process.env.TZ = 'America/Denver';
    expect(shanghaiMinutes('not-a-time')).toBeNull();
  });
  it('边界 14:59/15:00/17:29/17:30/18:30/18:44/18:45（not_yet）与 generating', () => {
    const st = (t: string, status: TodayResponse['daily_report']['status'] = 'not_yet') => preReportState(today({ server_time: bj(t), daily_report: { date: DATE, status } }));
    expect(st('14:59')).toBeNull();
    expect(st('15:00')).toBe('S4');
    expect(st('17:29')).toBe('S4');
    expect(st('17:30')).toBe('S4');
    expect(st('18:30')).toBe('S4');
    expect(st('18:44')).toBe('S4');
    expect(st('18:45')).toBe('S5');
    expect(st('18:45', 'generating')).toBe('S4');
    expect(st('18:50', 'ready')).toBeNull();
  });
  it('「日报约 HH:MM 生成」取自单一常量', () => {
    expect(REPORT_EXPECTED_AT).toBe('18:30');
    expect(STATE_TEXT.S4).toBe(`盘后数据准备中，日报约 ${REPORT_EXPECTED_AT} 生成。`);
  });
  it('⑧ 逾时阈值 = 常量 + 15 分钟：默认 18:45；常量换 17:30 → 17:45，文案随之变化', () => {
    expect(REPORT_OVERDUE_AT).toBe('18:45');
    expect(overdueAt('17:30')).toBe('17:45');
    expect(s4Text('17:30')).toBe('盘后数据准备中，日报约 17:30 生成。');
    expect(s4Text()).toBe(STATE_TEXT.S4);
    const st = (t: string, expectedAt?: string) => preReportState(today({ server_time: bj(t), daily_report: { date: DATE, status: 'not_yet' } }), expectedAt);
    expect(st('18:44')).toBe('S4');
    expect(st('18:45')).toBe('S5');
    expect(st('17:44', '17:30')).toBe('S4');
    expect(st('17:45', '17:30')).toBe('S5');
    expect(st('17:20', '17:30')).toBe('S4');
  });
});

describe('T-F34 缺口 code 表（§2.3，21 行含兜底）', () => {
  const rows: [string, string, boolean][] = [
    ['daily_bars_missing', '今日缺少日 K 数据，未参与分析。', true],
    ['daily_bar_conflict', '日 K 数据有冲突，已沿用首次记录。', true],
    ['daily_bars_after_asof', '日 K 晚于分析截止时间到达，今日未采用。', true],
    ['daily_bars_not_final', '日 K 尚未确认为收盘数据，今日未采用。', true],
    ['security_board_missing', '缺少板块信息，未参与分析。', true],
    ['owned_snapshot_licence_unbound', '数据授权未绑定，结果仅供参考。', true],
    ['owned_snapshot_hash_conflict', '今日数据快照异常，已保留首次结果。', false],
    ['calendar_not_covered', '交易日历未覆盖今天，未做分析。', false],
    ['owned_source_security_missing', '未进入今日数据快照，未参与分析。', true],
    ['owned_source_or_card_missing', '数据快照或策略卡不可用，未做分析。', false],
    ['security_not_eligible', '该证券不在分析范围内（仅支持上市股票）。', true],
    ['active_instances_missing', '还没有启用中的策略实例。', false],
    ['version_unavailable', '策略版本暂不可用。', false],
    ['runtime_lifecycle_blocked', '有策略实例当前状态不能运行。', false],
    ['runtime_source_gate', '策略所需的部分数据尚未验证，未做分析。', false],
    ['engine_policy_seed_missing', '系统配置未就绪，未做分析。', true],
    ['evaluated_input_gaps', '部分输入数据缺失，结果不完整。', true],
  ];
  it('20 个已知 code + 兜底；文案逐字；按证券的 code 归到证券行', () => {
    expect(Object.keys(GAP_CODES)).toHaveLength(20);
    expect(GAP_CODES.daily_bars_not_ready.text).toBe(STATE_TEXT.S6);
    expect(GAP_CODES.owned_market_cache_adapter_missing.text).toBe(STATE_TEXT.S7);
    expect(GAP_CODES.analysis.text).toBe(STATE_TEXT.S8);
    for (const [code, text, sec] of rows) {
      expect(GAP_CODES[code]?.text).toBe(text);
      const v = buildReportGaps([{ key: `pipeline.${code}${sec ? ':000002.SZ' : ''}`, reason: 'no_source', message: '' }], 'S9', () => null);
      expect(sec ? v.securities[0]?.lines[0]?.text : v.general[0]?.text).toBe(text);
    }
    expect(Object.fromEntries(Object.entries(GAP_CODES).filter(([, d]) => d.route).map(([c, d]) => [c, d.route])))
      .toEqual({ active_instances_missing: '/strategy-instances', runtime_lifecycle_blocked: '/strategy-instances' });
  });
  it('解析：去 pipeline. 前缀，在第一个冒号切开；daily_bar_conflict 的「证券:日期」取证券', () => {
    expect(parsePipelineKey('pipeline.runtime_source_gate:a/b:reason')).toEqual({ code: 'runtime_source_gate', param: 'a/b:reason' });
    expect(parsePipelineKey('pipeline.analysis')).toEqual({ code: 'analysis', param: '' });
    expect(parsePipelineKey('account')).toBeNull();
    const v = buildReportGaps([{ key: 'pipeline.daily_bar_conflict:000002.SZ:2026-11-10', reason: 'no_source', message: '' }], 'S9', () => null);
    expect(v.securities.map((s) => s.code)).toEqual(['000002.SZ']);
  });
  it('未知 code 的参数像证券代码时归到该证券行（只显示兜底文案）', () => {
    const v = buildReportGaps([{ key: 'pipeline.unknown_future_code:000001.SZ', reason: 'no_source', message: '' }], 'S9', (c) => (c === '000001.SZ' ? '示例甲' : null));
    expect(v.securities).toEqual([{ code: '000001.SZ', name: '示例甲', lines: [{ text: UNKNOWN_GAP_TEXT }] }]);
    expect(v.general).toEqual([]);
  });
  it('未知 code → 兜底且去重；非 pipeline 缺口：account.<证券>.price、cash、stocks.<证券> 展示，其余不展示', () => {
    const v = buildReportGaps([
      { key: 'pipeline.unknown_a', reason: 'no_source', message: '' }, { key: 'pipeline.unknown_b:x', reason: 'no_source', message: '' },
      { key: 'account', reason: 'user_input_missing', message: '' }, { key: 'account.pnl_day', reason: 'no_source', message: '' },
      { key: 'account.000003.SZ.price', reason: 'no_source', message: '' }, { key: 'cash', reason: 'user_input_missing', message: '' },
      { key: 'stocks.000004.SZ', reason: 'no_source', message: '' }, { key: 'stocks.000004.SZ.money_flow.main_net', reason: 'no_source', message: '' },
      { key: 'stocks.change_from_previous', reason: 'no_source', message: '' }, { key: 'market', reason: 'no_source', message: '' },
    ], 'S9', () => null);
    expect(v.general).toEqual([{ text: UNKNOWN_GAP_TEXT }, { text: '未录入现金。', route: '/portfolio/import' }]);
    expect(v.securities).toEqual([
      { code: '000003.SZ', name: null, lines: [{ text: '缺现价，按成本估算。' }] },
      { code: '000004.SZ', name: null, lines: [{ text: '该股无候选信号。' }] },
    ]);
  });
});

describe('T-F34 全局状态 S1–S9（契约 §4 用例 1–9、16）', () => {
  it('用例1 S1：未导入且无持仓 → 文案 + 导入交割单，不请求日报', async () => {
    await setup(today({ reconciliation: { status: 'not_imported', as_of: null, diff_count: 0, important_count: 0 }, focus: { items: [{ ...held, holding: null }], more: false } }));
    await settled(false);
    expect(barState()).toBe('S1');
    expect(screen.getByTestId('today-status-text')).toHaveTextContent(STATE_TEXT.S1);
    expect(screen.getByRole('link', { name: '导入交割单' })).toHaveAttribute('href', '/portfolio/import');
    expect(reportRequests()).toHaveLength(0);
  });
  it('用例2 S2：已对账但无持仓', async () => {
    await setup(today({ focus: { items: [{ ...held, holding: null }], more: false } }));
    await settled(true);
    expect(barState()).toBe('S2');
    expect(screen.getByTestId('today-status-text')).toHaveTextContent('当前没有持仓，日报只覆盖你的自选。');
  });
  it('用例3 S3：非交易日 → 文案 + trade_date，不请求日报', async () => {
    await setup(today({ session: 'non_trading_day', server_time: bj('10:00'), daily_report: { date: DATE, status: 'not_yet' } }));
    await settled(false);
    expect(barState()).toBe('S3');
    expect(screen.getByTestId('today-status-bar')).toHaveTextContent(`今天休市，没有新的日报。 交易日 ${DATE}`);
    expect(reportRequests()).toHaveLength(0);
  });
  it('用例4 S4：北京 17:20 not_yet，不请求日报', async () => {
    await setup(today({ server_time: bj('17:20'), daily_report: { date: DATE, status: 'not_yet' } }));
    await settled(false);
    expect(barState()).toBe('S4');
    expect(screen.getByTestId('today-status-text')).toHaveTextContent(STATE_TEXT.S4);
    expect(screen.queryByTestId('today-status-signals-updated')).toBeNull();
    expect(reportRequests()).toHaveLength(0);
  });
  it('用例5 S4：北京 17:40 not_yet 且有候选信号 → 追加「候选信号已更新。」；不提前显示分析缺口', async () => {
    await setup(today({ server_time: bj('17:40'), daily_report: { date: DATE, status: 'not_yet' }, focus: { items: [withSg], more: false } }));
    await settled(false);
    expect(barState()).toBe('S4');
    expect(screen.getByTestId('today-status-bar')).toHaveTextContent(`${STATE_TEXT.S4}候选信号已更新。`);
    expect(screen.queryByTestId('today-report-gaps')).toBeNull();
    expect(reportRequests()).toHaveLength(0);
  });
  it('用例6 S5：北京 18:50 not_yet', async () => {
    await setup(today({ server_time: bj('18:50'), daily_report: { date: DATE, status: 'not_yet' } }));
    await settled(false);
    expect(barState()).toBe('S5');
    expect(screen.getByTestId('today-status-text')).toHaveTextContent('今日日报还没有生成，请稍后再看。');
    expect(reportRequests()).toHaveLength(0);
  });
  it('用例7：机器时区 America/Denver、server_time 2026-11-10T09:20:00Z（北京 17:20）→ 仍为 S4', async () => {
    expect(new Date('2026-11-10T09:20:00Z').getDate()).toBe(10);
    expect(new Date('2026-11-10T09:20:00Z').getHours()).toBe(2);
    await setup(today({ server_time: '2026-11-10T09:20:00Z', daily_report: { date: DATE, status: 'not_yet' } }));
    await settled(false);
    expect(barState()).toBe('S4');
  });
  it.each([
    ['17:29', 'S4'], ['17:30', 'S4'], ['18:30', 'S4'], ['18:44', 'S4'], ['18:45', 'S5'],
  ])('时间边界 北京 %s not_yet → %s，且不请求日报', async (t, s) => {
    await setup(today({ server_time: bj(t), daily_report: { date: DATE, status: 'not_yet' } }));
    await settled(false);
    expect(barState()).toBe(s);
    expect(reportRequests()).toHaveLength(0);
  });
  it('generating 时同样不请求日报', async () => {
    await setup(today({ server_time: bj('18:10'), daily_report: { date: DATE, status: 'generating' } }));
    await settled(false);
    expect(barState()).toBe('S4');
    expect(reportRequests()).toHaveLength(0);
  });
  it('用例8 S6：日报含 pipeline.daily_bars_not_ready → 文案 + 日报链接；不出现原始 code', async () => {
    const page = await setup(today({ server_time: bj('18:30') }), todayViewReport(DATE, ['pipeline.daily_bars_not_ready'], ACCOUNT));
    await settled(true);
    expect(barState()).toBe('S6');
    expect(screen.getByTestId('today-status-text')).toHaveTextContent('今日行情数据未就绪，本日报未做策略分析。');
    expect(screen.getByTestId('today-status-report-link')).toHaveAttribute('href', `/daily-reports/${DATE}`);
    expect(screen.getAllByText(STATE_TEXT.S6)).toHaveLength(1); // 已在状态条显示，不在缺口区重复
    expect(page.textContent).not.toContain('daily_bars_not_ready');
    expect(page.textContent).not.toContain('pipeline');
    expect(reportRequests().map((u) => new URL(u).pathname)).toEqual([`/api/v1/daily-reports/${DATE}`]);
  });
  it('用例9 S7：owned_market_cache_adapter_missing', async () => {
    await setup(today(), todayViewReport(DATE, ['pipeline.owned_market_cache_adapter_missing'], ACCOUNT));
    await settled(true);
    expect(barState()).toBe('S7');
    expect(screen.getByTestId('today-status-text')).toHaveTextContent('行情数据源尚未开通，本日报未做策略分析。');
  });
  it('S8：pipeline.analysis；S6 优先于 S7、S8（只显示一条）', async () => {
    await setup(today(), todayViewReport(DATE, ['pipeline.analysis', 'pipeline.owned_market_cache_adapter_missing', 'pipeline.daily_bars_not_ready'], ACCOUNT));
    await settled(true);
    expect(screen.getAllByTestId('today-status-bar')).toHaveLength(1);
    expect(barState()).toBe('S6');
    // 未在状态条显示的 S7、S8 进入缺口区
    const gaps = screen.getByTestId('today-report-gaps');
    expect(gaps).toHaveTextContent(STATE_TEXT.S7);
    expect(gaps).toHaveTextContent(STATE_TEXT.S8);
  });
  it('S8 单独命中', async () => {
    await setup(today(), todayViewReport(DATE, ['pipeline.analysis'], ACCOUNT));
    await settled(true);
    expect(barState()).toBe('S8');
    expect(screen.getByTestId('today-status-text')).toHaveTextContent('今日盘后分析没有完成记录。');
  });
  it('用例16 S9 + R2：无状态条、「今天没有新的候选信号。」、无买入卖出字样、免责提示可见', async () => {
    const page = await setup(today());
    await settled(true);
    expect(screen.queryByTestId('today-status-bar')).toBeNull();
    expect(screen.getByTestId('today-no-signals')).toHaveTextContent(R2_TEXT);
    expect(page.textContent).not.toMatch(/买入|卖出/);
    expect(screen.getByTestId('card-disclaimer')).toBeVisible();
    expect(screen.getByTestId('card-disclaimer')).toHaveTextContent(DISCLAIMER_TEXT);
  });
});

describe('T-F34 账户与候选信号（A1/A2、R1/R2）', () => {
  it('用例14 A1：account 为 null，/today.data_gaps 有去向导入页的 cash 缺口 → 文案 + 去补录', async () => {
    await setup(today({
      data_gaps: { items: [{ key: 'user_input_missing:cash', reason: 'user_input_missing', scope: 'account', dataset: null, message: '未录入现金（示例）', security_count: 0, securities: [], since: null, route: '/portfolio/import' }], more: false },
    }), todayViewReport(DATE, ['account', 'cash'], null));
    await settled(true);
    const acct = screen.getByTestId('today-account');
    expect(acct).toHaveAttribute('data-state', 'A1');
    expect(acct).toHaveTextContent(A1_TEXT);
    expect(within(acct).getByRole('link', { name: '去补录 ›' })).toHaveAttribute('href', '/portfolio/import');
  });
  it('A1：没有去向导入页的缺口时不显示「去补录」', async () => {
    await setup(today(), todayViewReport(DATE, ['account'], null));
    await settled(true);
    expect(screen.getByTestId('today-account')).toHaveAttribute('data-state', 'A1');
    expect(screen.queryByTestId('today-account-fix')).toBeNull();
  });
  it('用例15 A2：pnl_day 为 null → 「—」不显示 0；其余字段照常', async () => {
    await setup(today(), todayViewReport(DATE, ['account.pnl_day'], { ...ACCOUNT, pnl_day: null }));
    await settled(true);
    expect(screen.getByTestId('today-account')).toHaveAttribute('data-state', 'A2');
    expect(screen.getByTestId('today-account-pnl')).toHaveTextContent(/^—$/);
    expect(screen.getByTestId('today-account-total')).toHaveTextContent('100,000.00');
    expect(screen.getByTestId('today-account-cash')).toHaveTextContent('20,000.00');
    expect(screen.getByTestId('today-account-position')).toHaveTextContent('80.00%');
  });
  it('R1：有候选信号时沿用候选信号列（ActionBadge：ACTION_SHORT 徽标 + ACTION_FULL 提示），不显示 R2；免责提示可见', async () => {
    await setup(today({ focus: { items: [withSg], more: false } }));
    await settled(true);
    expect(screen.queryByTestId('today-no-signals')).toBeNull();
    const a = withSg.suggestion!.actions[0]!;
    expect(screen.getByTestId('today-focus')).toHaveTextContent(ACTION_SHORT[a.action]);
    expect(screen.getByTestId('card-disclaimer')).toBeVisible();
  });
  it('R2 不与 S1–S8 同时显示', async () => {
    await setup(today({ server_time: bj('18:50'), daily_report: { date: DATE, status: 'not_yet' } }));
    await settled(false);
    expect(barState()).toBe('S5');
    expect(screen.queryByTestId('today-no-signals')).toBeNull();
  });
  it('日报 404（ready 但未取到）：不判定状态、不显示 R2，提示稍后显示', async () => {
    await setup(today(), null);
    await settled(true);
    expect(screen.queryByTestId('today-status-bar')).toBeNull();
    expect(screen.queryByTestId('today-no-signals')).toBeNull();
    expect(screen.getByTestId('today-report-gaps-error')).toBeInTheDocument();
  });
});

describe('T-F34 数据缺口区（用例 10–13 与通用断言）', () => {
  it('用例10：同一证券两条缺口只占一行、显示两句、带代码和名称；不出现 pipeline', async () => {
    const page = await setup(today({ focus: { items: [held, { ...held, security_code: '000002.SZ', name: '示例乙' }], more: false } }),
      todayViewReport(DATE, ['pipeline.daily_bars_missing:000002.SZ', 'pipeline.owned_source_security_missing:000002.SZ'], ACCOUNT));
    await settled(true);
    const rows = within(screen.getByTestId('today-report-gaps')).getAllByTestId(/^report-gap-sec-/);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent('000002.SZ 示例乙');
    expect(rows[0]).toHaveTextContent('今日缺少日 K 数据，未参与分析。');
    expect(rows[0]).toHaveTextContent('未进入今日数据快照，未参与分析。');
    expect(page.textContent).not.toContain('pipeline');
  });
  it('用例11：security_not_eligible → 文案，无操作按钮', async () => {
    await setup(today(), todayViewReport(DATE, ['pipeline.security_not_eligible:510000.SH'], ACCOUNT));
    await settled(true);
    const row = screen.getByTestId('report-gap-sec-510000.SH');
    expect(row).toHaveTextContent('该证券不在分析范围内（仅支持上市股票）。');
    expect(within(row).queryByTestId('report-gap-route')).toBeNull();
    expect(within(row).queryByRole('button')).toBeNull();
  });
  it('用例12：active_instances_missing → 文案 + 去 /strategy-instances', async () => {
    await setup(today(), todayViewReport(DATE, ['pipeline.active_instances_missing'], ACCOUNT));
    await settled(true);
    const gaps = screen.getByTestId('today-report-gaps');
    expect(gaps).toHaveTextContent('还没有启用中的策略实例。');
    expect(within(gaps).getByTestId('report-gap-route')).toHaveAttribute('href', '/strategy-instances');
  });
  it('用例13：未知 code → 兜底「部分数据暂不可用。」，不显示原始 code', async () => {
    const page = await setup(today(), todayViewReport(DATE, ['pipeline.unknown_future_code:000001.SZ'], ACCOUNT));
    await settled(true);
    expect(screen.getByTestId('report-gap-sec-000001.SZ')).toHaveTextContent(`000001.SZ 示例甲${UNKNOWN_GAP_TEXT}`);
    expect(page.textContent).not.toContain('unknown_future_code');
  });
  it('超过 10 只证券 → 只列 10 行并显示「等 N 只」', async () => {
    const codes = Array.from({ length: 13 }, (_, i) => `0000${String(10 + i)}.SZ`);
    await setup(today(), todayViewReport(DATE, codes.map((c) => `pipeline.daily_bars_missing:${c}`), ACCOUNT));
    await settled(true);
    const gaps = screen.getByTestId('today-report-gaps');
    expect(within(gaps).getAllByTestId(/^report-gap-sec-/)).toHaveLength(10);
    expect(within(gaps).getByTestId('report-gap-more')).toHaveTextContent('等 3 只');
  });
  it('/today.data_gaps 原渲染不变并与日报缺口同在「数据缺口」区；全程不请求 /alerts', async () => {
    await setup(today({
      data_gaps: { items: [{ key: 'user_input_missing:cash', reason: 'user_input_missing', scope: 'account', dataset: null, message: '未录入现金（示例）', security_count: 0, securities: [], since: null, route: '/portfolio/import' }], more: false },
    }), todayViewReport(DATE, ['pipeline.calendar_not_covered'], ACCOUNT));
    await settled(true);
    const area = screen.getByTestId('today-data-gaps');
    expect(within(area).getByTestId('data-gap-user_input_missing:cash')).toHaveTextContent('未录入现金（示例）');
    expect(within(area).getByTestId('today-report-gaps')).toHaveTextContent('交易日历未覆盖今天，未做分析。');
    expect(urls.some((u) => new URL(u).pathname.startsWith('/api/v1/alerts'))).toBe(false);
  });
});

describe('T-F34b 契约 §7 补充裁定（12 条）', () => {
  const cashToday = { items: [{ key: 'cash', reason: 'user_input_missing' as const, scope: 'account' as const, dataset: null, message: '未录入现金（示例）', security_count: 0, securities: [], since: null, route: '/portfolio/import' }], more: false };
  it('§7①-1：北京 18:40、not_yet → S4', async () => {
    await setup(today({ server_time: bj('18:40'), daily_report: { date: DATE, status: 'not_yet' } }));
    await settled(false);
    expect(barState()).toBe('S4');
  });
  it('§7①-2：北京 19:10、generating → S4，不显示 S5', async () => {
    await setup(today({ server_time: bj('19:10'), daily_report: { date: DATE, status: 'generating' } }));
    await settled(false);
    expect(barState()).toBe('S4');
    expect(screen.queryByText(STATE_TEXT.S5)).toBeNull();
  });
  it('§7②：S3 且 status 为 ready → 日报请求 0，无 today-account', async () => {
    await setup(today({ session: 'non_trading_day', daily_report: { date: DATE, status: 'ready' } }));
    await settled(false);
    expect(barState()).toBe('S3');
    expect(reportRequests()).toHaveLength(0);
    expect(screen.queryByTestId('today-account')).toBeNull();
  });
  it('§7③-1：北京 10:00、not_yet、无候选信号 → 不显示状态条与 R2', async () => {
    await setup(today({ server_time: bj('10:00'), session: 'morning', daily_report: { date: DATE, status: 'not_yet' } }));
    await settled(false);
    expect(screen.queryByTestId('today-status-bar')).toBeNull();
    expect(screen.queryByTestId('today-no-signals')).toBeNull();
    expect(screen.queryByText(R2_TEXT)).toBeNull();
    expect(reportRequests()).toHaveLength(0);
  });
  it('§7③-1 边界：北京 14:59 not_yet 不显示 R2；ready 且日报读取成功的 S9 才显示', async () => {
    await setup(today({ server_time: bj('14:59'), daily_report: { date: DATE, status: 'not_yet' } }));
    await settled(false);
    expect(screen.queryByTestId('today-no-signals')).toBeNull();
  });
  it('§7③-2：S2、无候选信号 → 不显示 R2', async () => {
    await setup(today({ focus: { items: [{ ...held, holding: null }], more: false } }));
    await settled(true);
    expect(barState()).toBe('S2');
    expect(screen.queryByTestId('today-no-signals')).toBeNull();
  });
  it('§7④-1：pipeline.future_x:000001.SZ → 归到 000001.SZ 行，显示兜底', async () => {
    await setup(today(), todayViewReport(DATE, ['pipeline.future_x:000001.SZ'], ACCOUNT));
    await settled(true);
    expect(screen.getByTestId('report-gap-sec-000001.SZ')).toHaveTextContent(`000001.SZ 示例甲${UNKNOWN_GAP_TEXT}`);
  });
  it('§7④-2：pipeline.future_gate:f.pe:missing → 通用行，无 /stocks/f.pe 链接', async () => {
    const page = await setup(today(), todayViewReport(DATE, ['pipeline.future_gate:f.pe:missing'], ACCOUNT));
    await settled(true);
    expect(within(screen.getByTestId('today-report-gaps')).getByTestId('report-gap-general')).toHaveTextContent(UNKNOWN_GAP_TEXT);
    expect(screen.queryByTestId('report-gap-sec-f.pe')).toBeNull();
    expect(page.querySelector('a[href="/stocks/f.pe"]')).toBeNull();
  });
  it('§7④ 纯函数：只接受 6 位数字 + .SH/.SZ/.BJ；已知 code 的宽松参数也不生成证券行', () => {
    const v = buildReportGaps(['pipeline.x:000001.SH', 'pipeline.x:830001.BJ', 'pipeline.y:00001.SZ', 'pipeline.y:000001.sz', 'pipeline.y:000001.HK',
      'pipeline.daily_bars_missing:f.pe', 'account.f.pe.price', 'stocks.f.pe'].map((key) => ({ key, reason: 'no_source' as const, message: '' })), 'S9', () => null);
    expect(v.securities.map((x) => x.code)).toEqual(['000001.SH', '830001.BJ']);
    expect(v.general.map((x) => x.text)).toEqual([UNKNOWN_GAP_TEXT, '今日缺少日 K 数据，未参与分析。']);
  });
  it('§7⑤：日报 gaps 含 daily_bars_not_ready 与 analysis → 状态条 S6，缺口区有 S8、无 S6', async () => {
    await setup(today(), todayViewReport(DATE, ['pipeline.daily_bars_not_ready', 'pipeline.analysis'], ACCOUNT));
    await settled(true);
    expect(barState()).toBe('S6');
    const gaps = screen.getByTestId('today-report-gaps');
    expect(gaps).toHaveTextContent(STATE_TEXT.S8);
    expect(gaps).not.toHaveTextContent(STATE_TEXT.S6);
  });
  it('§7⑥：status ready、日报 404 → 读取失败文案，无 today-no-signals、today-account，/today 块照常', async () => {
    await setup(today({ data_gaps: cashToday }), null);
    await settled(true);
    expect(screen.getByTestId('today-report-gaps-error')).toHaveTextContent('日报详情暂时读取失败，分析缺口稍后显示。');
    expect(screen.queryByTestId('today-no-signals')).toBeNull();
    expect(screen.queryByTestId('today-account')).toBeNull();
    expect(screen.queryByTestId('today-status-bar')).toBeNull();
    expect(screen.getByTestId('data-gap-cash')).toBeInTheDocument();
    expect(screen.getByTestId('today-focus')).toBeInTheDocument();
  });
  it('§7⑦-1：account.future_field、reason=user_input_missing → 「有信息待补录。」去 /portfolio/import；同 key 去重', async () => {
    const r = todayViewReport(DATE, [], ACCOUNT);
    const g = { key: 'account.future_field', reason: 'user_input_missing' as const, message: '示例数据' };
    await setup(today(), { ...r, gaps: [g, g, { ...g, key: 'profile.future_x' }] });
    await settled(true);
    const rows = within(screen.getByTestId('today-report-gaps')).getAllByTestId('report-gap-general');
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent(USER_INPUT_GAP_TEXT);
    expect(within(rows[0]!).getByTestId('report-gap-route')).toHaveAttribute('href', '/portfolio/import');
  });
  it('§7⑦-1 纯函数：未列出且 reason 非 user_input_missing 的不显示；已列出不展示的键即使 user_input_missing 也不显示', () => {
    const v = buildReportGaps([
      { key: 'account.future_field', reason: 'no_source', message: '' },
      { key: 'account', reason: 'user_input_missing', message: '' },
      { key: 'account.pnl_day', reason: 'user_input_missing', message: '' },
      { key: 'market', reason: 'user_input_missing', message: '' },
    ], 'S9', () => null);
    expect(v).toEqual({ securities: [], hiddenCount: 0, general: [] });
  });
  it('§7⑦-2：日报 gaps 含 market → 不显示', async () => {
    await setup(today(), todayViewReport(DATE, ['market'], ACCOUNT));
    await settled(true);
    expect(screen.queryByTestId('today-report-gaps')).toBeNull();
    expect(within(screen.getByTestId('today-data-gaps')).getByText('数据完整')).toBeInTheDocument();
  });
  it('§7⑦-3：/today.data_gaps 与日报 gaps 都含 cash → 「未录入现金」只出现一次', async () => {
    const r = todayViewReport(DATE, [], null);
    const page = await setup(today({ data_gaps: cashToday }), { ...r, gaps: [{ key: 'cash', reason: 'user_input_missing', message: '示例数据' }] });
    await settled(true);
    expect((page.textContent ?? '').split('未录入现金').length - 1).toBe(1);
    expect(screen.getByTestId('data-gap-cash')).toBeInTheDocument();
    expect(screen.queryByTestId('today-report-gaps')).toBeNull();
  });
});

describe('T-F34c 契约 §8 c', () => {
  it('§8c：stocks.<证券>.<维度>.<键> + user_input_missing → 该股行「有信息待补录。」去 /portfolio/import；no_source 与 account/account.pnl_day/market.*/stocks.change_from_previous 不显示', async () => {
    const r = todayViewReport(DATE, [], null);
    const gap = (key: string, reason: 'user_input_missing' | 'no_source') => ({ key, reason, message: '示例数据' });
    const page = await setup(today({ focus: { items: [held, { ...held, security_code: '000002.SZ', name: '示例乙' }], more: false } }), {
      ...r,
      gaps: [
        gap('stocks.000001.SZ.technical.cost', 'user_input_missing'),
        gap('stocks.000001.SZ.money_flow.main_net', 'user_input_missing'),
        gap('stocks.000002.SZ.technical.cost', 'no_source'),
        gap('account', 'user_input_missing'), gap('account.pnl_day', 'user_input_missing'),
        gap('market', 'user_input_missing'), gap('market.breadth', 'user_input_missing'),
        gap('stocks.change_from_previous', 'user_input_missing'),
      ],
    });
    await settled(true);
    const area = screen.getByTestId('today-report-gaps');
    const row = within(area).getByTestId('report-gap-sec-000001.SZ');
    expect(row).toHaveTextContent(`000001.SZ 示例甲${USER_INPUT_GAP_TEXT}`);
    expect(within(row).getAllByTestId('report-gap-route').map((a) => a.getAttribute('href'))).toEqual(['/portfolio/import']);
    expect(within(area).queryByTestId('report-gap-sec-000002.SZ')).toBeNull();
    expect(within(area).queryAllByTestId('report-gap-general')).toHaveLength(0);
    expect((page.textContent ?? '').split(USER_INPUT_GAP_TEXT).length - 1).toBe(1);
    expect(screen.getByTestId('today-account')).toHaveAttribute('data-state', 'A1');
  });
});
