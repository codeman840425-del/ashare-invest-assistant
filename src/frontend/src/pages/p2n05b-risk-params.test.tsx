/** 参数表到用例骨架先经DeepSeek机械转换，全部断言本地对照契约复核。 */
import { fireEvent, render, screen, within, waitFor } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { EXAMPLE_RISK_SETTINGS } from '../mocks/phase2Fixtures';
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
it('恢复默认只取GET返回的source=system值，非硬编码表值，不自动写入', async () => {
  let writes = 0;
  const data = EXAMPLE_RISK_SETTINGS.map((s) => s.control === 'position_cap' ? { ...s, params: { single_position_max_pct: '24' } } : s);
  server.use(http.get(`${API}/risk-controls`, () => HttpResponse.json(data)), http.put(`${API}/risk-controls`, () => { writes++; return HttpResponse.json(data); }));
  renderPage(); const card = await screen.findByTestId('risk-setting-position_cap'); const input = within(card).getByLabelText('单只仓位上限（%）');
  fireEvent.change(input, { target: { value: '30' } }); fireEvent.click(within(card).getByRole('button', { name: /^恢复默认/ }));
  expect(input).toHaveValue(24); expect(writes).toBe(0);
});
it('初读只有user覆盖值时不猜系统默认，不拿文档20当服务器默认', async () => {
  server.use(http.get(`${API}/risk-controls`, () => HttpResponse.json(EXAMPLE_RISK_SETTINGS.map((s) => ({ ...s, source: 'user' })))));
  renderPage(); const card = await screen.findByTestId('risk-setting-position_cap');
  expect(within(card).getByRole('button', { name: /^恢复默认/ })).toBeDisabled(); expect(card).toHaveTextContent('本次读取未返回该项系统默认值');
});
