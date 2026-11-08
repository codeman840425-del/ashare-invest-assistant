/** 参数表到用例骨架先经DeepSeek机械转换，全部断言本地对照契约复核。 */
import { fireEvent, render, screen, within, waitFor } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { EXAMPLE_RISK_SETTINGS, exampleEvaluation } from '../mocks/phase2Fixtures';
import { server } from '../mocks/server';
import { apiGet } from '../api/client';
import { apiFetch } from '../test/apiFetch';
import { RISK_PARAM_RULES, type RiskParamRule, type NumericRiskParamRule } from '../lib/riskControlParams';
import type { RiskControlSetting } from '../api/phase2Types';
const API = '/api/v1';
beforeAll(() => preloadRoutes(routes), 30_000);
const numeric = (RISK_PARAM_RULES as readonly RiskParamRule[]).filter((r): r is NumericRiskParamRule => r.kind !== 'boolean');
function renderPage() {
  const router = createMemoryRouter(routes, { initialEntries: ['/risk-controls'] });
  render(<AppProviders client={makeQueryClient(true)}><ConfigProvider theme={{ token: { motion: false } }}><RouterProvider router={router} /></ConfigProvider></AppProviders>);
}
const put = (items: unknown) => apiFetch(`${API}/risk-controls`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(items) });
function itemWith(rule: RiskParamRule, v: unknown) {
  const setting = structuredClone(EXAMPLE_RISK_SETTINGS.find((s) => s.control === rule.control)!);
  let target: object = setting.params; const parts = rule.path.split('.');
  for (const part of parts.slice(0, -1)) { const next: unknown = Reflect.get(target, part); if (!next || typeof next !== 'object') throw new Error('错误测试路径'); target = next; }
  Reflect.set(target, parts[parts.length - 1], v);
  return { control: setting.control, enabled: setting.enabled, params: setting.params };
}
it.each(numeric)('mock $control.$path：超界422+fields键且整次不写入', async (rule) => {
  const v = rule.kind === 'integer' ? rule.max + 1 : rule.kind === 'decimal_pair' ? [String(rule.min), String(rule.max + 1)] : String(rule.max + 1);
  const before = await apiGet<RiskControlSetting[]>('/risk-controls');
  const response = await put([itemWith(rule, v)]); expect(response.status).toBe(422);
  const data = await response.json(); expect(data.error.code).toBe('RISK_CONTROL_INVALID_PARAMS');
  expect(data.error.details.fields.some((f: { field: string }) => f.field.startsWith(`${rule.control}.params.${rule.path}`))).toBe(true);
  expect(await apiGet('/risk-controls')).toEqual(before);
});
it('mock多项更新时后项越界也不写入前项；RC1关闭不能用0替代', async () => {
  const before = await apiGet('/risk-controls');
  const response = await put([{ control: 'position_cap', enabled: true, params: { single_position_max_pct: '25' } }, { control: 'stop_take', enabled: false, params: { long_horizon_default_stop_pct: '0', clamp_to_price_limit: true } }]);
  expect(response.status).toBe(422); expect(await apiGet('/risk-controls')).toEqual(before);
});
it('mock超精度422/整数类型错误400；RC4的100仍保持enabled，RC3跨档不强制单调', async () => {
  expect((await put([{ control: 'position_cap', enabled: true, params: { single_position_max_pct: '20.123' } }])).status).toBe(422);
  const rc3 = EXAMPLE_RISK_SETTINGS.find((s) => s.control === 'total_exposure')!;
  expect((await put([{ control: 'total_exposure', enabled: true, params: { ...rc3.params, regime_confirm_days: 2.5 } }])).status).toBe(400);
  expect((await put([{ control: 'sector_concentration', enabled: true, params: { sw_l1_max_pct: '100', concept_max_pct: '100' } }])).status).toBe(200);
  const settings = await apiGet<RiskControlSetting[]>('/risk-controls'); expect(settings.find((s) => s.control === 'sector_concentration')?.enabled).toBe(true);
  expect((await put([{ control: 'total_exposure', enabled: true, params: { regime_ranges: { uptrend: ['0', '5'], range: ['90', '100'], downtrend: ['50', '60'] }, regime_confirm_days: 5 } }])).status).toBe(200);
});
it('表单min/max/step按契约设置；越界/精度错误本地拦截，2位小数原样提交', async () => {
  let writes = 0; let payload: unknown;
  server.use(http.put(`${API}/risk-controls`, async ({ request }) => { writes++; payload = await request.json(); return HttpResponse.json(EXAMPLE_RISK_SETTINGS); }));
  renderPage(); const card = await screen.findByTestId('risk-setting-stop_take'); const input = within(card).getByLabelText('中长线默认止损比例（%）');
  expect(input).toHaveAttribute('min', '-50'); expect(input).toHaveAttribute('max', '-5'); expect(input).toHaveAttribute('step', '1');
  fireEvent.change(input, { target: { value: '0' } }); expect(within(card).getByRole('button', { name: /^保存/ })).toBeDisabled(); expect(writes).toBe(0);
  fireEvent.change(input, { target: { value: '-20.123' } }); expect(within(card).getByTestId('risk-param-errors-stop_take')).toHaveTextContent('最多2位小数');
  fireEvent.change(input, { target: { value: '-20.25' } }); fireEvent.click(within(card).getByRole('button', { name: /^保存/ }));
  await waitFor(() => expect(writes).toBe(1)); expect(payload).toEqual([{ control: 'stop_take', enabled: true, params: { long_horizon_default_stop_pct: '-20.25', clamp_to_price_limit: true } }]);
});
it('RC3/RC4/RC5输入边界与暂停关闭时的不生效状态', async () => {
  renderPage(); await screen.findByTestId('risk-setting-loss_streak_drawdown');
  const checks = [['大盘环境确认天数', '1', '5'], ['申万一级行业上限（%）', '10', '100'], ['概念集中度上限（%）', '10', '100'], ['已平仓连续亏损笔数', '2', '10'], ['账户高点回撤（%）', '3', '50'], ['策略模拟连续失败次数', '3', '20'], ['暂停交易日数', '1', '20']];
  for (const [label, min, max] of checks) {
    const input = screen.getByLabelText(label);
    // AntD整数控件以ARIA暴露边界，decimal原生输入以min/max暴露。
    if (input.getAttribute('type') === 'number') {
      expect(input).toHaveAttribute('min', min); expect(input).toHaveAttribute('max', max); expect(input).toHaveAttribute('step', '1');
    } else {
      expect(input).toHaveAttribute('aria-valuemin', min); expect(input).toHaveAttribute('aria-valuemax', max);
    }
  }
  const confirmDays = screen.getByLabelText('大盘环境确认天数');
  expect(confirmDays).toHaveValue('2');
  fireEvent.keyDown(confirmDays, { key: 'ArrowUp', code: 'ArrowUp', keyCode: 38 });
  expect(confirmDays).toHaveValue('3');
  fireEvent.click(screen.getByRole('checkbox', { name: '触发时暂停' })); expect(screen.getByLabelText('暂停交易日数')).toBeDisabled();
});
it('恢复默认只取GET返回的同形default，非硬编码表值，不自动写入', async () => {
  let writes = 0;
  const data = EXAMPLE_RISK_SETTINGS.map((s) => s.control === 'position_cap' ? { ...s, source: 'user', enabled: false, params: { single_position_max_pct: '30' }, default: { single_position_max_pct: '24' } } : s);
  server.use(http.get(`${API}/risk-controls`, () => HttpResponse.json(data)), http.put(`${API}/risk-controls`, () => { writes++; return HttpResponse.json(data); }));
  renderPage(); const card = await screen.findByTestId('risk-setting-position_cap'); const input = within(card).getByLabelText('单只仓位上限（%）');
  fireEvent.change(input, { target: { value: '30' } }); fireEvent.click(within(card).getByRole('button', { name: /^恢复默认/ }));
  expect(input).toHaveValue(24); expect(writes).toBe(0);
});
it('缺失default时不猜系统默认，不拿有效值或文档20冒充', async () => {
  server.use(http.get(`${API}/risk-controls`, () => HttpResponse.json(EXAMPLE_RISK_SETTINGS.map((s) => ({ ...s, source: 'user', default: null })))));
  renderPage(); const card = await screen.findByTestId('risk-setting-position_cap');
  expect(within(card).getByRole('button', { name: /^恢复默认/ })).toBeDisabled(); expect(card).toHaveTextContent('响应未提供可信的同形 default');
});

it('六项default同形只读，覆盖后不改变；PUT夹带default拒绝且不部分更新', async () => {
  const original = await apiGet<RiskControlSetting[]>('/risk-controls');
  for (const item of original) expect(Object.keys(item.default).sort()).toEqual(Object.keys(item.params).sort());
  expect((await put([{ control: 'position_cap', enabled: true, params: { single_position_max_pct: '25' } }])).status).toBe(200);
  const after = await apiGet<RiskControlSetting[]>('/risk-controls');
  expect(after.map((s) => s.default)).toEqual(original.map((s) => s.default));
  expect((await put([{ control: 'position_cap', enabled: true, params: { single_position_max_pct: '30' }, default: { single_position_max_pct: '30' } }])).status).toBe(400);
  expect(await apiGet('/risk-controls')).toEqual(after);
});
it.each([undefined, { single_position_max_pct: 20 }, { single_position_max_pct: '99' }, { alien: '20' }])('不可信default禁用恢复且不退回有效值：%j', async (invalid) => {
  server.use(http.get(`${API}/risk-controls`, () => HttpResponse.json(EXAMPLE_RISK_SETTINGS.map((s) => ({ ...s, default: s.control === 'position_cap' ? invalid : s.default })))));
  renderPage(); const card = await screen.findByTestId('risk-setting-position_cap');
  expect(within(card).getByRole('button', { name: /^恢复默认/ })).toBeDisabled();
});
it('恢复同形default覆盖嵌套params并启用默认六项，但需手动保存才PUT', async () => {
  let payload: unknown;
  const data = EXAMPLE_RISK_SETTINGS.map((s) => s.control === 'total_exposure' ? { ...s, source: 'user', enabled: false, params: { regime_ranges: { uptrend: ['0', '1'], range: ['1', '2'], downtrend: ['2', '3'] }, regime_confirm_days: 5 } } : s);
  server.use(http.get(`${API}/risk-controls`, () => HttpResponse.json(data)), http.put(`${API}/risk-controls`, async ({ request }) => { payload = await request.json(); return HttpResponse.json(EXAMPLE_RISK_SETTINGS); }));
  renderPage(); const card = await screen.findByTestId('risk-setting-total_exposure');
  fireEvent.click(within(card).getByRole('button', { name: /^恢复默认/ })); expect(payload).toBeUndefined();
  expect(within(card).getByRole('checkbox', { name: /^启用/ })).toBeChecked();
  fireEvent.click(within(card).getByRole('button', { name: /^保存/ }));
  await waitFor(() => expect(payload).toEqual([{ control: 'total_exposure', enabled: true, params: EXAMPLE_RISK_SETTINGS.find((s) => s.control === 'total_exposure')!.default }]));
});
it('评价unknown及分项/全局gap如实显示，不把带gap的ok显示成通过', async () => {
  const evaluation = exampleEvaluation('600000.SH', '示例数据', null, EXAMPLE_RISK_SETTINGS, new Set());
  const gap = { key: 'test_missing', reason: 'no_source' as const, message: '示例数据：输入缺口' };
  evaluation.gaps = [gap]; evaluation.controls[0] = { control: 'stop_take', enabled: true, state: 'ok', flags: [], gaps: [gap] };
  evaluation.controls[1] = { control: 'position_cap', enabled: true, state: 'unknown', flags: [], gaps: [gap] };
  server.use(http.get(`${API}/risk-controls/evaluation`, () => HttpResponse.json(evaluation)));
  renderPage(); const input = await screen.findByLabelText('风控评价证券代码'); fireEvent.change(input, { target: { value: '600000.SH' } }); fireEvent.click(screen.getByRole('button', { name: '读取当前评价' }));
  expect(await screen.findByTestId('risk-evaluation-gaps')).toHaveTextContent('不能视为通过或正常');
  expect(screen.getByTestId('risk-state-stop_take')).toHaveTextContent('输入存在缺口，不能判为通过');
  expect(screen.getByTestId('risk-state-stop_take')).not.toHaveTextContent('输入齐全，未触发');
  expect(screen.getByTestId('risk-state-position_cap')).toHaveTextContent('未知（输入不足）');
});

it.skipIf(!process.env.P2N05C_REAL_API)('P2N05c real：真实React→Vite→API读取/保存/默认恢复/校验/unknown缺口', async () => {
  server.close();
  const nativeFetch = globalThis.fetch;
  const cookies = new Map<string, string>();
  const base = 'http://127.0.0.1:15565';
  const journal: { method: string; path: string; status: number }[] = [];
  globalThis.fetch = async (input, init = {}) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const original = new URL(raw, base);
    if (!['127.0.0.1', 'localhost'].includes(original.hostname)) throw new Error('仅限本地隔离联调');
    const url = new URL(original.pathname + original.search, base);
    const headers = new Headers(init.headers); headers.set('Origin', base);
    if (cookies.size) headers.set('Cookie', [...cookies].map(([key, value]) => key + '=' + value).join('; '));
    const response = await nativeFetch(url, { ...init, headers });
    for (const line of response.headers.getSetCookie()) {
      const first = line.split(';')[0]; const index = first.indexOf('=');
      cookies.set(first.slice(0, index), first.slice(index + 1));
      if (first.startsWith('csrf_token=')) document.cookie = first + '; Path=/';
    }
    journal.push({ method: init.method ?? 'GET', path: url.pathname, status: response.status });
    return response;
  };
  try {
    const login = await fetch(base + '/api/v1/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'p2n05c_test', password: process.env.P2N05C_TEST_PASSWORD }) });
    expect(login.status).toBe(200);
    renderPage(); const card = await screen.findByTestId('risk-setting-position_cap');
    expect(card).toHaveTextContent('系统有效值');
    const input = within(card).getByLabelText('单只仓位上限（%）');
    fireEvent.change(input, { target: { value: '21.25' } }); fireEvent.click(within(card).getByRole('button', { name: /^保存/ }));
    await within(card).findByText('设置已保存（以服务端响应为准）');
    expect(input).toHaveValue(21.25); expect(card).toHaveTextContent('本人覆盖值');
    fireEvent.click(within(card).getByRole('button', { name: /^恢复默认/ })); expect(input).toHaveValue(20);
    fireEvent.click(within(card).getByRole('button', { name: /^保存/ })); await within(card).findByText('设置已保存（以服务端响应为准）');
    const settings = await apiGet<RiskControlSetting[]>('/risk-controls');
    expect(settings.find((item) => item.control === 'position_cap')?.params).toEqual({ single_position_max_pct: '20' });
    const bad = await put([{ control: 'position_cap', enabled: true, params: { single_position_max_pct: '99' } }]);
    expect(bad.status).toBe(422); expect((await bad.json()).error.details.fields.length).toBeGreaterThan(0);
    const forbidden = await put([{ ...settings[0] }]); expect(forbidden.status).toBe(400);
    const code = screen.getByLabelText('风控评价证券代码'); fireEvent.change(code, { target: { value: '600000.SH' } }); fireEvent.click(screen.getByRole('button', { name: '读取当前评价' }));
    expect(await screen.findByTestId('risk-evaluation-gaps')).toHaveTextContent('不能视为通过或正常');
    expect(screen.getByTestId('risk-state-position_cap')).toHaveTextContent('未知（输入不足）');
    expect(journal.some((item) => item.path.endsWith('/risk-controls/evaluation') && item.status === 200)).toBe(true);
  } finally {
    globalThis.fetch = nativeFetch;
    cookies.clear();
    const { writeFileSync } = await import('node:fs');
    writeFileSync('/workspace/team/reports/P2N-05c/http-journal.json', JSON.stringify(journal, null, 2));
    server.listen({ onUnhandledFrame: 'error' });
  }
});
