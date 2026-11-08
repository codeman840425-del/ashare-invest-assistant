/** P2N-05j：两项小修的手写定点，全部使用本地示例数据。 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ConfigProvider, Form } from 'antd';
import { MemoryRouter, createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { PlanFormFields } from '../features/plans/PlanForm';
import { beijingPlanDate, planConditionValueIssue, type PlanFormValues } from '../features/plans/planFormModel';
import { additionalSignalInstances } from '../lib/signalEvents';
import { BottomPanel } from '../features/terminal/BottomPanel';
import { ChartPanel } from '../features/terminal/ChartPanel';
import type { ChartMarker } from '../components/charts/chartBase';
import type { PlanConditionType } from '../api/enums';
import type { Paged, SignalEvent } from '../api/types';
import { apiGet } from '../api/client';
import { SIGNAL_EVENTS, TERMINAL_ROWS, TRADE_DATE, suggestionOf, uid } from '../mocks/fixtures';
import { server } from '../mocks/server';
import { preloadRoutes } from '../test/preloadRoutes';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: ({ markers }: { markers?: ChartMarker[] }) => <div data-testid="event-markers">{markers?.map((m) => m.label).join(' | ')}</div> }));
beforeAll(() => preloadRoutes(routes), 30_000);
afterEach(() => vi.restoreAllMocks());
const now = Date.parse('2026-11-08T16:01:00Z'); // 北京时间次日00:01。
it.each(['0', '-0.0000', '+0.00'])('pct=%s在前端提示方向不明', (value) => {
  expect(planConditionValueIssue('pct_change', value, now)).toContain('pct = 0 方向不明，不可写入');
});
it('正负非零及极小非零不被误当零，不给其他类型套pct规则', () => {
  for (const value of ['3.00', '-3.00', '1e-400']) expect(planConditionValueIssue('pct_change', value, now)).toBeNull();
  expect(planConditionValueIssue('price_above', '0', now)).toBeNull();
});
it('北京时间跨午夜：昨天拦截、今天及未来允许，与UTC日期不同', () => {
  expect(beijingPlanDate(Date.parse('2026-11-08T15:59:59Z'))).toBe('2026-11-08'); expect(beijingPlanDate(now)).toBe('2026-11-09');
  expect(planConditionValueIssue('date', '2026-11-08', now)).toContain('北京时间 2026-11-09');
  expect(planConditionValueIssue('date', '2026-11-09', now)).toBeNull(); expect(planConditionValueIssue('date', '2026-11-10', now)).toBeNull();
});
const invalid: { create: boolean; type: PlanConditionType; value: string; issue: RegExp }[] = [
  { create: true, type: 'pct_change', value: '0', issue: /pct = 0 方向不明，不可写入；请填写/ },
  { create: false, type: 'pct_change', value: '-0.00', issue: /pct = 0 方向不明，不可写入；请填写/ },
  { create: true, type: 'date', value: '2026-11-08', issue: /日期不得早于写入当日（北京时间 2026-11-09）/ },
  { create: false, type: 'date', value: '2026-11-08', issue: /日期不得早于写入当日（北京时间 2026-11-09）/ },
];
it.each(invalid)('新建=$create、条件$type：无效值不触发提交，修改后可提交', async ({ create, type, value, issue }) => {
  vi.spyOn(Date, 'now').mockReturnValue(now); const submit = vi.fn();
  const values: PlanFormValues = { security_code: '600000.SH', action: 'buy', rationale: '示例数据：计划依据', change_reason: '示例数据：修改计划条件', conditions: [{ kind: 'trigger', type, value, description: '示例数据：计划条件' }] };
  render(<MemoryRouter><ConfigProvider theme={{ token: { motion: false } }}><Form<PlanFormValues> initialValues={values} onFinish={submit}><PlanFormFields create={create} versioning={!create} /><button type="submit">保存示例计划</button></Form></ConfigProvider></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: '保存示例计划' })); await screen.findByText(issue); expect(submit).not.toHaveBeenCalled();
  const row = screen.getByTestId('plan-f-cond'); const input = within(row).getByPlaceholderText(type === 'date' ? '日期 YYYY-MM-DD' : '涨跌幅 %（非零，带符号）');
  fireEvent.change(input, { target: { value: type === 'date' ? '2026-11-09' : '-3.00' } });
  fireEvent.click(screen.getByRole('button', { name: '保存示例计划' })); await waitFor(() => expect(submit).toHaveBeenCalledOnce());
});
it('条件类型从价格切换到pct时重新校验已有零值', async () => {
  const submit = vi.fn(); const values: PlanFormValues = { action: 'buy', rationale: '示例数据', conditions: [{ kind: 'trigger', type: 'price_above', value: '0', description: '示例数据' }] };
  render(<MemoryRouter><Form<PlanFormValues> initialValues={values} onFinish={submit}><PlanFormFields /><button type="submit">保存示例计划</button></Form></MemoryRouter>);
  const row = screen.getByTestId('plan-f-cond'); fireEvent.mouseDown(within(row).getAllByRole('combobox')[1]);
  fireEvent.click(screen.getByText('涨跌幅', { selector: '.ant-select-item-option-content' }));
  fireEvent.click(screen.getByRole('button', { name: '保存示例计划' })); await screen.findByText(/pct = 0 方向不明，不可写入；请填写/); expect(submit).not.toHaveBeenCalled();
});
it('前端边界允许后仍保留服务端400顶部与行级错误，不显示保存成功', async () => {
  let writes = 0;
  server.use(http.post('*/api/v1/plans', () => { writes++; return HttpResponse.json({ error: { code: 'VALIDATION_ERROR', message: '示例数据：服务端校验失败', details: { fields: [{ field: 'conditions[0].params', issue: 'invalid' }] } } }, { status: 400 }); }));
  const router = createMemoryRouter(routes, { initialEntries: ['/plans'] }); render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  fireEvent.click(await screen.findByTestId('plan-new-btn')); fireEvent.change(screen.getByTestId('plan-f-code'), { target: { value: '600000.SH' } }); fireEvent.change(screen.getByTestId('plan-f-rationale'), { target: { value: '示例数据：计划依据' } });
  fireEvent.click(screen.getByTestId('plan-f-add-cond')); fireEvent.change(screen.getByPlaceholderText('价格'), { target: { value: '10.00' } }); fireEvent.change(screen.getByPlaceholderText('条件说明（1–200 字）'), { target: { value: '示例数据：价格条件' } });
  fireEvent.click(screen.getByTestId('plan-create-ok')); expect(await screen.findByTestId('plan-invalid')).toHaveTextContent('有字段未通过校验'); expect(await screen.findByText('格式不正确')).toBeInTheDocument(); expect(writes).toBe(1); expect(router.state.location.pathname).toBe('/plans');
});
it.each([0, 1, 2, 20])('instance_ids有%s个：只显示超出首个的N，不排序/扇出', (count) => {
  const ids = Array.from({ length: count }, (_, i) => uid(3000 + count - i)); const before = [...ids];
  expect(additionalSignalInstances({ instance_ids: ids })).toBe(count > 1 ? `另 ${count - 1} 个实例` : null); expect(ids).toEqual(before);
});
it('旧响应缺instance_ids时不猜集合、不误显示额外实例', () => {
  const legacy = { ...SIGNAL_EVENTS[0] }; Reflect.deleteProperty(legacy, 'instance_ids'); expect(additionalSignalInstances(legacy)).toBeNull();
});
it('MSW冻结集合有空/单/多实例，一事件仍一行；列表与图形标记显示另2个实例', async () => {
  const response = await apiGet<Paged<SignalEvent>>('/signals', { limit: 50 }); expect(response.items).toHaveLength(SIGNAL_EVENTS.length); expect(new Set(response.items.map((e) => e.signal_event_id)).size).toBe(response.items.length);
  for (const e of response.items) { expect(Array.isArray(e.instance_ids)).toBe(true); expect(e.instance_ids.length).toBeLessThanOrEqual(20); if (e.instance_id) expect(e.instance_ids).toContain(e.instance_id); }
  expect(response.items.some((e) => e.instance_ids.length === 0)).toBe(true); expect(response.items.some((e) => e.instance_ids.length === 1)).toBe(true);
  const multi = response.items.find((e) => e.instance_ids.length === 3)!; expect(multi.instance_ids[0]).toBe(multi.instance_id); expect(multi.message).toContain('示例数据');
  const select = vi.fn(); render(<AppProviders client={makeQueryClient(true)}><MemoryRouter><BottomPanel selected="600000.SH" onSelect={select} /><ChartPanel row={TERMINAL_ROWS.find((r) => r.security_code === '600000.SH')!} suggestion={suggestionOf('600000.SH')!} tradeDate={TRADE_DATE} /></MemoryRouter></AppProviders>);
  expect(await screen.findByTestId(`signal-instances-${multi.signal_event_id}`)).toHaveTextContent('另 2 个实例'); await waitFor(() => expect(screen.getByTestId('event-markers')).toHaveTextContent('另 2 个实例'));
  expect(screen.getByTestId('bottom-panel').querySelectorAll('.event-row')).toHaveLength(response.items.length); fireEvent.click(screen.getByTestId(`signal-instances-${multi.signal_event_id}`)); expect(select).toHaveBeenCalledWith(multi.security_code);
});
