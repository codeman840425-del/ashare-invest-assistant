/** P2N-05a：机械骨架先由 DeepSeek 出稿，断言由执行者逐项对齐§7.11；全为示例数据。 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { ConfigProvider } from 'antd';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { server } from '../mocks/server';
import { DAILY_REPORTS, REPORT_DATE, PREV_REPORT_DATE, suggestionOf, uid } from '../mocks/fixtures';
import { EXAMPLE_RISK_SETTINGS, exampleTracking } from '../mocks/phase2Fixtures';
import { PHASE2_STATES } from '../mocks/phase2States';
import { riskEvents } from '../mocks/todayFixtures';
import { currentUser, mockLoginAs, state } from '../mocks/session';
import { apiGet, apiPut } from '../api/client';
import { ENUMS } from '../api/enums';
import type { DailyReport, Paged } from '../api/types';
import type { RiskControlSetting, RiskEvaluation, RiskEvent, SuggestionTracking } from '../api/phase2Types';
import { TrackingResults } from '../components/TrackingResults';
import { StrategyTrackingStats, TrackingStatValue, SuggestionStrategyTracking, trackingDecimal } from '../components/TrackingStats';
import { STRATEGY_TEMPLATES, trackingOf } from '../mocks/strategyHandlers';
import type { StrategyTracking } from '../api/strategyTypes';
import { useSuggestionTracking } from '../api/suggestionQueries';
import { useStrategyTracking } from '../api/signalQueries';
import { apiFetch } from '../test/apiFetch';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div /> }));
beforeAll(() => preloadRoutes(routes), 30_000);
const API = '/api/v1';
const bank = suggestionOf('600000.SH')!;
function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><ConfigProvider theme={{ token: { motion: false } }}><RouterProvider router={router} /></ConfigProvider></AppProviders>);
  return router;
}
const settingsBody = (cap: string) => [{ control: 'position_cap', enabled: true, params: { single_position_max_pct: cap } }];
const readSettings = () => apiGet<RiskControlSetting[]>('/risk-controls');
const putRaw = (body: unknown) => apiFetch(`${API}/risk-controls`, { method: 'PUT', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } });

it('六维顺序与证据引用：新日报每股六项、同股前缀、引用不悬空，未登记不升级', async () => {
  const report = await apiGet<DailyReport>(`/daily-reports/${REPORT_DATE}`);
  const ids = new Set(report.evidence.map((e) => e.id));
  for (const stock of report.stocks) {
    expect(stock.analysis_snapshot_id).not.toBeNull();
    expect(stock.dimensions?.map((d) => d.dimension)).toEqual([...ENUMS.dimension]);
    for (const dimension of stock.dimensions ?? []) {
      for (const id of [...dimension.facts.flatMap((f) => f.evidence_ids), ...dimension.feature_refs.flatMap((f) => f.evidence_ids)]) {
        expect(ids.has(id)).toBe(true); expect(id.startsWith(stock.security_code + ':')).toBe(true);
      }
      if (dimension.data_status === 'unavailable') { expect(dimension.facts).toEqual([]); expect(dimension.data_as_of).toBeNull(); expect(dimension.gaps.length).toBeGreaterThan(0); }
    }
    expect(stock.dimensions?.find((d) => d.dimension === 'sentiment')?.feature_refs[0].status).toBeNull();
  }
  expect(PHASE2_STATES).toHaveLength(24);
  expect(report).not.toHaveProperty('status', 'draft');
});
it('六维事实证据可定位，点击不误入候选卡，null显示缺数据而非0', async () => {
  const router = renderAt(`/daily-reports/${REPORT_DATE}`);
  const details = await screen.findByTestId('dimensions-600000.SH');
  fireEvent.click(within(details).getByText('六维事实与缺口（不是策略结论）'));
  const link = within(details).getByRole('link', { name: '查看六维证据 600000.SH:D1' });
  expect(link).toHaveAttribute('href', '#daily-600000.SH-600000.SH:D1');
  fireEvent.click(link);
  expect(router.state.location.pathname).toBe(`/daily-reports/${REPORT_DATE}`);
  expect(within(details).getByTestId('dimension-evidence-600000.SH:D2')).toHaveTextContent('—（缺数据）');
  expect(within(details).getByTestId('dimension-600000.SH-sentiment')).toHaveTextContent('未登记');
});
it('旧日报与移出行为null，不伪装为本期六维分析或补造快照', async () => {
  const old = await apiGet<DailyReport>(`/daily-reports/${PREV_REPORT_DATE}`);
  expect(old.stocks.every((s) => s.analysis_snapshot_id === null && s.dimensions === null)).toBe(true);
  renderAt(`/daily-reports/${PREV_REPORT_DATE}`);
  const removed = await screen.findByTestId('dimensions-000003.SZ');
  fireEvent.click(within(removed).getByText('六维事实与缺口（不是策略结论）'));
  expect(within(removed).getByText(/已移出行没有本期六维分析/)).toBeInTheDocument();
  expect(screen.getAllByTestId('dimensions-legacy').length).toBe(old.stocks.length);
});
it('完全无来源不填零、不判中性；一个维度失败不影响其他维度', async () => {
  const report = structuredClone(DAILY_REPORTS[0]);
  const technical = report.stocks[0].dimensions![0];
  technical.data_status = 'unavailable'; technical.data_as_of = null; technical.facts = [];
  server.use(http.get(`${API}/daily-reports/:date`, () => HttpResponse.json(report)));
  renderAt(`/daily-reports/${REPORT_DATE}`);
  const details = await screen.findByTestId('dimensions-600000.SH'); fireEvent.click(within(details).getByText('六维事实与缺口（不是策略结论）'));
  expect(within(details).getByTestId('dimension-600000.SH-technical')).toHaveTextContent('暂无已知事实；缺数据不填0');
  expect(within(details).getByTestId('dimension-600000.SH-news')).toBeInTheDocument();
});
it('设置成功以响应为准：确认响应前不显示成功，仅提交所改项，返回六项', async () => {
  let release: (() => void) | undefined;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  let received: unknown;
  server.use(http.put(`${API}/risk-controls`, async ({ request }) => {
    received = await request.json(); await pending;
    return HttpResponse.json(EXAMPLE_RISK_SETTINGS.map((s) => s.control === 'position_cap' ? { ...s, source: 'user', params: { single_position_max_pct: '25' } } : s));
  }));
  renderAt('/risk-controls');
  const card = await screen.findByTestId('risk-setting-position_cap');
  fireEvent.change(within(card).getByLabelText('单只仓位上限（%）'), { target: { value: '25' } });
  fireEvent.click(within(card).getByRole('button', { name: /保存/ }));
  await waitFor(() => expect(received).toEqual(settingsBody('25')));
  expect(within(card).queryByText('设置已保存（以服务端响应为准）')).not.toBeInTheDocument();
  release!();
  expect(await within(card).findByText('设置已保存（以服务端响应为准）')).toBeInTheDocument();
  expect(within(card).getByText('本人覆盖值')).toBeInTheDocument();
});
it.each([422, 500])('设置失败不展示成功（%s），不修改服务端已有值', async (status) => {
  server.use(http.put(`${API}/risk-controls`, () => HttpResponse.json({ error: { code: status === 422 ? 'RISK_CONTROL_INVALID_PARAMS' : 'INTERNAL_ERROR', message: '示例数据：设置未接受', details: null } }, { status })));
  renderAt('/risk-controls'); const card = await screen.findByTestId('risk-setting-position_cap');
  fireEvent.change(within(card).getByLabelText('单只仓位上限（%）'), { target: { value: '31' } });
  fireEvent.click(within(card).getByRole('button', { name: /保存/ }));
  await within(card).findByText(/设置未保存/);
  expect(within(card).queryByText('设置已保存（以服务端响应为准）')).not.toBeInTheDocument();
  expect(within(card).getByLabelText('单只仓位上限（%）')).toHaveValue(31);
  expect(await readSettings()).toEqual(EXAMPLE_RISK_SETTINGS);
});
it('重复设置原子拒绝，合法项也不部分写入；source只读', async () => {
  const original = await readSettings();
  expect((await putRaw([...settingsBody('25'), ...settingsBody('30')])).status).toBe(400);
  expect(await readSettings()).toEqual(original);
  expect((await putRaw([{ ...settingsBody('25')[0], source: 'system' }])).status).toBe(400);
  expect(await readSettings()).toEqual(original);
});
it.each([
  { control: 'invalid', enabled: true, params: {} },
  { control: 'position_cap', enabled: true, params: { single_position_max_pct: 25 } },
  { control: 'position_cap', enabled: 'true', params: { single_position_max_pct: '25' } },
  { control: 'stop_take', enabled: true, params: { long_horizon_default_stop_pct: '-20', clamp_to_price_limit: 'true' } },
  { control: 'plan_violation', enabled: true, params: { checks: ['invented_expression'] } },
  { control: 'total_exposure', enabled: true, params: { regime_ranges: { uptrend: ['50'], range: ['40', '60'], downtrend: ['0', '30'] }, regime_confirm_days: 2 } },
])('未知键或参数类型拒绝（$control），未提交项保持原值', async (item) => {
  expect((await putRaw([item])).status).toBe(400); expect(await readSettings()).toEqual(EXAMPLE_RISK_SETTINGS);
});
it('已明确的范围和区间倒置为422，整批原子拒绝', async () => {
  expect((await putRaw(settingsBody('51'))).status).toBe(422);
  const inverted = { control: 'total_exposure', enabled: true, params: { regime_ranges: { uptrend: ['90', '60'], range: ['40', '60'], downtrend: ['0', '30'] }, regime_confirm_days: 2 } };
  expect((await putRaw([...settingsBody('25'), inverted])).status).toBe(422);
  expect(await readSettings()).toEqual(EXAMPLE_RISK_SETTINGS);
});
it('设置按会话用户隔离；未提交项保持原值，GET总是六项', async () => {
  const original = await readSettings();
  const result = await apiPut<RiskControlSetting[]>('/risk-controls', settingsBody('35'));
  expect(result.map((s) => s.control)).toEqual([...ENUMS.risk_control]);
  expect(result.find((s) => s.control === 'stop_take')).toEqual(original[0]);
  mockLoginAs('admin'); expect(await readSettings()).toEqual(EXAMPLE_RISK_SETTINGS);
  mockLoginAs('demo_user'); expect((await readSettings()).find((s) => s.control === 'position_cap')?.params).toEqual({ single_position_max_pct: '35' });
});
it('RC3未知无门控；RC5未接通是unknown，disabled与unknown分开', async () => {
  const data = await apiGet<RiskEvaluation>('/risk-controls/evaluation', { security_code: '600000.SH' });
  expect(data.controls.map((c) => c.control)).toEqual([...ENUMS.risk_control]);
  expect(data.controls[2]).toMatchObject({ state: 'unknown', flags: [] });
  expect(data.controls[4].state).toBe('unknown'); expect(data.controls[5].state).toBe('disabled');
  renderAt('/risk-controls?security_code=600000.SH');
  const rc3 = await screen.findByTestId('risk-state-total_exposure'); expect(rc3).toHaveTextContent('大盘环境未知'); expect(rc3).toHaveTextContent('不施加 RC3 门控');
  expect(screen.getByTestId('risk-state-position_cap')).toHaveTextContent('额度未知');
});
it('风险评价只读不写事件；默认账户排序，缺参400、未知/他人账户404', async () => {
  const before = riskEvents();
  const data = await apiGet<RiskEvaluation>('/risk-controls/evaluation', { security_code: '600000.SH' });
  const first = [...state.accounts].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id))[0];
  expect(data.account_id).toBe(first?.id ?? null); expect(riskEvents()).toEqual(before);
  expect((await apiFetch(`${API}/risk-controls/evaluation`)).status).toBe(400);
  expect((await apiFetch(`${API}/risk-controls/evaluation?security_code=600000.SH&account_id=invalid`)).status).toBe(400);
  expect((await apiFetch(`${API}/risk-controls/evaluation?security_code=999999.SH`)).status).toBe(404);
  expect((await apiFetch(`${API}/risk-controls/evaluation?security_code=600000.SH&account_id=${uid(777)}`)).status).toBe(404);
  mockLoginAs('admin');
  expect((await apiFetch(`${API}/risk-controls/evaluation?security_code=600000.SH&account_id=${first.id}`)).status).toBe(404);
});
it('RC1关闭警示可见，只改勾选不自动保存；当前评价变更不回写日报', async () => {
  const before = structuredClone(DAILY_REPORTS[0]); let writes = 0;
  server.use(http.put(`${API}/risk-controls`, () => { writes++; return HttpResponse.json(EXAMPLE_RISK_SETTINGS); }));
  renderAt('/risk-controls'); const card = await screen.findByTestId('risk-setting-stop_take');
  fireEvent.click(within(card).getByRole('checkbox', { name: /^启用/ }));
  expect(within(card).getByText(/已关闭止损止盈风控/)).toBeInTheDocument(); expect(writes).toBe(0); expect(DAILY_REPORTS[0]).toEqual(before);
});
it('事件游标与筛选：后续cursor照传，保留定位参数并展示本人事件', async () => {
  const examples = riskEvents().slice(0, 2); const seen: (string | null)[] = [];
  server.use(http.get(`${API}/risk-controls/events`, ({ request }) => {
    const url = new URL(request.url); const cursor = url.searchParams.get('cursor'); seen.push(cursor);
    return HttpResponse.json({ items: cursor ? [examples[1]] : [examples[0]], next_cursor: cursor ? null : 'mock-next-page' });
  }));
  const router = renderAt(`/risk-controls?tab=events&event=${examples[0].id}`);
  expect(await screen.findByTestId(`risk-event-${examples[0].id}`)).toHaveTextContent('当前定位事件');
  fireEvent.click(screen.getByRole('button', { name: '加载更多事件' }));
  await screen.findByTestId(`risk-event-${examples[1].id}`); expect(seen).toEqual([null, 'mock-next-page']);
  expect(screen.getByRole('button', { name: '加载更多事件' })).toBeDisabled(); expect(router.state.location.search).toContain('tab=events');
});
it('事件端点复用原状态机，支持status/control/security_code/since及真实空态', async () => {
  const all = await apiGet<Paged<RiskEvent>>('/risk-controls/events', { status: 'cleared', limit: 1 });
  expect(all.items.every((e) => e.status === 'cleared')).toBe(true);
  const empty = await apiGet<Paged<RiskEvent>>('/risk-controls/events', { since: '2099-01-01T00:00:00+08:00' }); expect(empty.items).toEqual([]);
  expect((await apiFetch(`${API}/risk-controls/events?since=invalid`)).status).toBe(400);
  server.use(http.get(`${API}/risk-controls/events`, () => HttpResponse.json({ items: [], next_cursor: null })));
  renderAt('/risk-controls?tab=events'); await screen.findByText('暂无符合条件的风控事件；不是“风险为零”。');
});
it('模拟五种状态与缺基准：单条收益不冒充聚合收益，不填0或猜超额', async () => {
  const data = await apiGet<SuggestionTracking>(`/suggestions/${bank.id}/tracking`);
  expect(data.results.map((r) => r.state)).toEqual(['complete', 'pending', 'untradable', 'excluded', 'unavailable']);
  expect(data.results[0]).toMatchObject({ return_pct: '1.25', benchmark_return_pct: null, excess_pct: null });
  renderAt(`/suggestions/${bank.id}`);
  const tracking = await screen.findByTestId('tracking-results');
  expect(tracking).toHaveTextContent('模拟，不代表实际收益'); expect(tracking).toHaveTextContent('1.25%');
  expect(screen.getByTestId('tracking-counts')).toHaveTextContent('不可成交 1 · 排除 1');
  expect(screen.getByTestId('tracking-complete')).toHaveTextContent('超额：—（缺口：缺数据）');
  expect(screen.getByTestId('tracking-untradable')).toHaveTextContent('排除原因');
  expect(screen.getByTestId('tracking-unavailable')).toHaveTextContent('到期但数据不足');
});
it('逐期唯一与有效n：待到期/不可成交/排除不计有效n，引用可解析', () => {
  const data = exampleTracking(bank);
  expect(new Set(data.results.map((r) => `${r.strategy_version_id}-${r.horizon_days}`)).size).toBe(data.results.length);
  expect(data.t1).toMatchObject({ n: 1, value: null, small_sample: true }); expect(data.t5.n).toBe(0); expect(data.t20.n).toBe(0);
  for (const r of data.results) { expect(r.price_basis).toBe('qfq'); expect(r.evidence_ids.every((id) => r.evidence.some((e) => e.id === id))).toBe(true); if (['untradable', 'excluded'].includes(r.state)) expect(r.exclusion_reason).not.toBeNull(); }
});
it('本人建议隔离：他人/不存在均404，不泄漏单条结果', async () => {
  expect(currentUser()?.username).toBe('demo_user');
  expect((await apiFetch(`${API}/suggestions/${uid(777)}/tracking`)).status).toBe(404);
  mockLoginAs('admin'); expect((await apiFetch(`${API}/suggestions/${bank.id}/tracking`)).status).toBe(404);
});
it('无结果与旧跟踪响应空态：不以聚合统计代替逐条结果', () => {
  const data = exampleTracking({ ...bank, strategies: [] });
  render(<TrackingResults data={data} />); expect(screen.getByText('暂无逐条模拟结果；不补算、不用旧聚合数字代替。')).toBeInTheDocument(); expect(data.t1.n).toBe(0);
});
it('旧跟踪响应缺新增键时兼容展示空态而不崩溃', async () => {
  const data = exampleTracking(bank);
  server.use(http.get(`${API}/suggestions/:id/tracking`, () => HttpResponse.json({ t1: data.t1, t5: data.t5, t20: data.t20 })));
  renderAt(`/suggestions/${bank.id}`); await screen.findByText('暂无逐条模拟结果；不补算、不用旧聚合数字代替。');
});
it('sell/reduce标的区间收益保持原值，不强行取反', () => {
  const data = exampleTracking(bank); data.results = [{ ...data.results[0], action: 'reduce', return_pct: '-1.25' }];
  render(<TrackingResults data={data} />); expect(screen.getByTestId('tracking-complete')).toHaveTextContent('标的区间收益：-1.25%');
});

it('无账户会话完全无来源：快照null，启用项unknown，不借用他人仓位', async () => {
  mockLoginAs('admin');
  const data = await apiGet<RiskEvaluation>('/risk-controls/evaluation', { security_code: '600000.SH' });
  expect(data.account_id).toBeNull(); expect(data.snapshot_id).toBeNull(); expect(data.evidence).toEqual([]);
  expect(data.controls.filter((c) => c.enabled).every((c) => c.state === 'unknown' && c.flags.length === 0)).toBe(true);
});
it('wait不生成有效模拟观测或伪造聚合n；实际可成交价与qfq价格分开留证', () => {
  const wait = bank.strategies.find((v) => v.action === 'wait')!;
  const data = exampleTracking({ ...bank, strategies: [wait] }); expect(data.t1.n).toBe(0); expect(data.results.map((r) => r.state)).toEqual(['excluded']);
  const complete = exampleTracking(bank).results[0];
  expect(complete.evidence.some((e) => e.key.endsWith('.raw'))).toBe(true);
  expect(complete.evidence.some((e) => e.key.includes('qfq_as_of'))).toBe(true);
});

it('RC6启用但未接通时为unknown，不伪装成ok或disabled', async () => {
  await apiPut('/risk-controls', [{ control: 'plan_violation', enabled: true, params: { checks: ['opposite_side'] } }]);
  const evaluation = await apiGet<RiskEvaluation>('/risk-controls/evaluation', { security_code: '600000.SH' });
  expect(evaluation.controls.find((c) => c.control === 'plan_violation')).toMatchObject({ enabled: true, state: 'unknown', flags: [] });
});

it('日报F25未知不沿用range/仓位区间或声称震荡，不给缺收盘价的行补事实', async () => {
  const data = await apiGet<DailyReport>(`/daily-reports/${REPORT_DATE}`);
  expect(data.market.regime).toBeNull(); expect(data.market.regime_position_range).toBeNull(); expect(data.account?.position_vs_regime).toBeNull();
  renderAt(`/daily-reports/${REPORT_DATE}`);
  const account = await screen.findByTestId('report-account'); expect(within(account).queryByRole('img')).not.toBeInTheDocument();
  expect(account).toHaveTextContent('参考仓位区间：缺失');
  for (const stock of data.stocks.filter((s) => s.close === null)) expect(stock.highlights.every((h) => !h.text.includes('收盘 '))).toBe(true);
});

// P2N-05c模拟增量：逐条与版本聚合分开，不在前端重算n或盈亏比。
it.each([['12.3450', '12.35'], ['-2.3450', '-2.35'], ['1.0050', '1.01'], ['-0.0050', '-0.01'], ['0.0000', '0.00'], ['12', '12.00']])('跟踪decimal %s按HALF_UP显示%s，不把_pct再乘百', (input, expected) => {
  expect(trackingDecimal(input)).toBe(expected);
});
it('聚合盈亏比null且n足够时显示缺口而非0/样本不足，保留原始n与不可成交计数', () => {
  const data = trackingOf(STRATEGY_TEMPLATES[1], 'mine');
  data.by_horizon = [{ ...data.by_horizon[0], profit_loss_ratio: { value: null, n: 40, window: '1d', small_sample: false }, avg_return_pct: { value: '12.3450', n: 40, window: '1d', small_sample: false }, pending_count: 2, untradable_count: 3, excluded_count: 4 }];
  data.gaps = [{ key: 'no_losing_samples', reason: 'no_source', message: '示例数据：无亏损样本' }];
  render(<StrategyTrackingStats data={data} />);
  const row = screen.getByTestId('track-1'); expect(row).toHaveTextContent('12.35%'); expect(row).not.toHaveTextContent('1234.50%');
  expect(row).toHaveTextContent('缺口：值未提供'); expect(row).toHaveTextContent('n=40'); expect(row).not.toHaveTextContent('样本不足');
  const cells = within(row).getAllByRole('cell'); expect(cells.slice(-3).map((cell) => cell.textContent)).toEqual(['2', '3', '4']);
  expect(screen.getByTestId('strategy-tracking-stats')).toHaveTextContent('模拟非实际收益'); expect(screen.getByText(/no_losing_samples/)).toBeInTheDocument();
});
it('有亏损无盈利的真实0盈亏比可显示；小样本null必须显示缺口与n，不能擅自填5', () => {
  const { rerender } = render(<TrackingStatValue stat={{ value: '0.0000', n: 5, window: '1d', small_sample: true }} kind="ratio" />);
  expect(screen.getByText('0.00')).toBeInTheDocument(); expect(screen.getByText(/n=5/)).toBeInTheDocument();
  rerender(<TrackingStatValue stat={{ value: null, n: 1, window: '1d', small_sample: true }} />);
  expect(screen.getByText(/缺口：样本不足/)).toBeInTheDocument(); expect(screen.getByText(/n=1/)).toBeInTheDocument(); expect(screen.queryByText('0.00')).not.toBeInTheDocument();
});
it('逐条回撤/runup为空必须显示缺口，保留已知零与两位百分数，标注模拟非实际收益', () => {
  const data = exampleTracking(bank); const result = data.results.find((row) => row.state === 'complete')!;
  result.max_drawdown_pct = null; result.max_runup_pct = '0.0000';
  render(<TrackingResults data={data} />);
  const row = screen.getByTestId('tracking-complete'); expect(row).toHaveTextContent('最大回撤 —（缺口：缺数据）'); expect(row).toHaveTextContent('最大上行 0.00%');
  expect(screen.getByTestId('tracking-results')).toHaveTextContent('模拟非实际收益');
});
it('mock版本统计补齐三计数/DataStatus/gaps；site无逐条结果，错版本404', async () => {
  const template = STRATEGY_TEMPLATES[1]; const base = `/strategies/${template.id}/versions/${template.current_version.id}/tracking`;
  for (const scope of ['mine', 'site']) {
    const data = await apiGet<StrategyTracking>(base, { scope });
    expect(data.scope).toBe(scope); expect(data.gaps[0].message).toContain('示例数据'); expect(data).toHaveProperty('data_status'); expect(data).not.toHaveProperty('results');
    for (const row of data.by_horizon) for (const key of ['pending_count', 'untradable_count', 'excluded_count'] as const) expect(row[key]).toBeGreaterThanOrEqual(0);
  }
  expect((await apiFetch(`${API}/strategies/${template.id}/versions/${uid(999)}/tracking`)).status).toBe(404);
});
it('同版本多实例只显示一份策略聚合；请求scope=mine，不从观测数伪造n', async () => {
  const template = STRATEGY_TEMPLATES.find((item) => item.key === bank.strategies[0].strategy_key)!;
  let requests = 0;
  server.use(http.get(`${API}/strategies/:id/versions/:vid/tracking`, ({ request }) => { requests++; expect(new URL(request.url).searchParams.get('scope')).toBe('mine'); return HttpResponse.json(trackingOf(template, 'mine')); }));
  const duplicated = { ...bank.strategies[0], instance_id: uid(999) };
  render(<AppProviders client={makeQueryClient(true)}><SuggestionStrategyTracking strategies={[bank.strategies[0], duplicated]} /></AppProviders>);
  expect(await screen.findByTestId(`version-tracking-${duplicated.strategy_version_id}`)).toBeInTheDocument();
  await screen.findByTestId('strategy-tracking-stats'); expect(screen.getAllByTestId('strategy-tracking-stats')).toHaveLength(1); expect(requests).toBe(1);
});

function RealSimProbe() {
  const tracking = useSuggestionTracking(process.env.P2N05C_SIM_SUGGESTION_ID);
  const aggregate = useStrategyTracking(process.env.P2N05C_SIM_STRATEGY_ID, process.env.P2N05C_SIM_VERSION_ID!);
  return <>{tracking.data ? <><TrackingStatValue stat={tracking.data.t1} testId="real-card-n" /><TrackingResults data={tracking.data} /></> : null}{aggregate.data ? <StrategyTrackingStats data={aggregate.data} /> : null}</>;
}
it.skipIf(!process.env.P2N05C_SIM_REAL_API)('P2N05c sim real：真实React查询→Vite→逐条与版本聚合，n/计数/盈亏比/回撤/gap/隔离', async () => {
  server.close(); const nativeFetch = globalThis.fetch; const cookies = new Map<string, string>();
  const base = 'http://127.0.0.1:15566'; const journal: { method: string; path: string; status: number }[] = [];
  globalThis.fetch = async (input, init = {}) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url; const original = new URL(raw, base);
    if (!['127.0.0.1', 'localhost'].includes(original.hostname)) throw new Error('仅限本任务回环联调');
    const url = new URL(original.pathname + original.search, base); const headers = new Headers(init.headers); headers.set('Origin', base);
    if (cookies.size) headers.set('Cookie', [...cookies].map(([key, value]) => key + '=' + value).join('; '));
    const response = await nativeFetch(url, { ...init, headers });
    for (const line of response.headers.getSetCookie()) { const first = line.split(';')[0]; const index = first.indexOf('='); cookies.set(first.slice(0, index), first.slice(index + 1)); if (first.startsWith('csrf_token=')) document.cookie = first + '; Path=/'; }
    journal.push({ method: init.method ?? 'GET', path: url.pathname, status: response.status }); return response;
  };
  try {
    const login = await fetch(base + '/api/v1/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'p2n05c_sim_test', password: process.env.P2N05C_TEST_PASSWORD }) }); expect(login.status).toBe(200);
    render(<AppProviders client={makeQueryClient(true)}><RealSimProbe /></AppProviders>);
    const aggregate = await screen.findByTestId('strategy-tracking-stats');
    const row = within(aggregate).getByTestId('track-1'); expect(row).toHaveTextContent('n=5'); expect(row).toHaveTextContent('1.20%'); expect(row).toHaveTextContent('1.33');
    const cells = within(row).getAllByRole('cell'); expect(cells.slice(-3).map((cell) => cell.textContent)).toEqual(['1', '1', '1']);
    expect(await screen.findByTestId('real-card-n')).toHaveTextContent('n=1'); expect(screen.getByTestId('real-card-n')).toHaveTextContent('缺口：样本不足');
    const results = screen.getByTestId('tracking-results'); expect(results).toHaveTextContent('最大回撤 -4.55%'); expect(results).toHaveTextContent('最大上行 10.00%'); expect(results).toHaveTextContent('模拟非实际收益');
    const pending = within(results).getByTestId('tracking-pending'); expect(pending).toHaveTextContent('最大回撤 —（缺口：缺数据）');
    const site = await apiGet<StrategyTracking>(`/strategies/${process.env.P2N05C_SIM_STRATEGY_ID}/versions/${process.env.P2N05C_SIM_VERSION_ID}/tracking`, { scope: 'site' }); expect(site).not.toHaveProperty('results'); expect(site).not.toHaveProperty('security_code');
    expect((await apiFetch(`${API}/suggestions/${process.env.P2N05C_SIM_FOREIGN_ID}/tracking`)).status).toBe(404);
    expect(journal.every((item) => !item.path.includes('/admin/'))).toBe(true);
  } finally {
    globalThis.fetch = nativeFetch; cookies.clear();
    const { writeFileSync } = await import('node:fs'); writeFileSync('/workspace/team/reports/P2N-05c/sim/http-journal.json', JSON.stringify(journal, null, 2));
    server.listen({ onUnhandledFrame: 'error' });
  }
});
