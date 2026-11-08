/** T-F30：仅 MSW 合成会话，不填真实管理员密码或执行真实审批。 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { ConfigProvider } from 'antd';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { server } from '../mocks/server';
import { currentUser, mockLoginAs } from '../mocks/session';
import { EXAMPLE_PROMOTION_REPORT } from '../mocks/promotionFixtures';
import { DEMO_REVIEW_ID, LEGACY_REVIEW_ID, MOCK_WRONG_REAUTH } from '../mocks/promotionHandlers';
import { apiGet, apiPost, ApiError } from '../api/client';
import { globalErrorAction } from '../api/errorPolicy';
import type { PromotionSummary } from '../api/promotionTypes';
import type { Paged } from '../api/types';
const API = '/api/v1';
const path = `/admin/strategy-gates?review_id=${DEMO_REVIEW_ID}`;
type Kind = 'decision' | 'lifecycle';
beforeAll(() => preloadRoutes(routes), 30_000);
beforeEach(() => mockLoginAs('admin'));
function renderAt(url = path) {
  const client = makeQueryClient(true);
  const router = createMemoryRouter(routes, { initialEntries: [url] });
  render(<AppProviders client={client}><ConfigProvider theme={{ token: { motion: false } }}><RouterProvider router={router} /></ConfigProvider></AppProviders>);
  return { router, client };
}
async function openDialog(kind: Kind) {
  await screen.findByTestId('approve-g7');
  if (kind === 'decision') {
    fireEvent.change(screen.getByLabelText('G7 审核意见'), { target: { value: '本人核对示例数据' } });
    fireEvent.click(screen.getByRole('checkbox', { name: '本人已核实并确认 G6 警告' }));
    fireEvent.click(screen.getByTestId('approve-g7'));
  } else {
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '目标策略版本' }));
    fireEvent.click(await screen.findByText('门禁草稿（示例数据） · v1', { selector: '.ant-select-item-option-content' }));
    fireEvent.change(screen.getByLabelText('生命周期变更原因'), { target: { value: '本人核对示例版本' } });
    fireEvent.click(screen.getByTestId('to-simulating'));
  }
  const modal = await screen.findByRole('dialog');
  expect(within(modal).getByText(kind === 'decision' ? '审核决定 · 本人密码复核' : '晋级 · 本人密码复核')).toBeInTheDocument();
  const input = within(modal).getByLabelText(kind === 'decision' ? '审核复核密码' : '晋级复核密码') as HTMLInputElement;
  const confirm = within(modal).getByRole('button', { name: kind === 'decision' ? '确认批准 G7' : '确认转入模拟中' });
  return { modal, input, confirm };
}
function approvedReport() {
  server.use(http.get(`${API}/promotion-requests/:id`, () => HttpResponse.json({ ...EXAMPLE_PROMOTION_REPORT, decision: 'approved' })));
}
for (const kind of ['decision', 'lifecycle'] as const) {
  it(`${kind} 密码不预填，确认前不写；成功后清空，密码不在 mutation cache/URL/持久化`, async () => {
    if (kind === 'lifecycle') approvedReport();
    let writes = 0;
    const fakeValue = 'x'.repeat(10);
    server.use(http.post(kind === 'decision' ? `${API}/admin/promotions/:id/decision` : `${API}/admin/strategies/:id/versions/:vid/lifecycle`, async ({ request }) => {
      writes++;
      const body = await request.json() as { password: string; review_id?: string };
      expect(body.password === fakeValue).toBe(true);
      if (kind === 'lifecycle') expect(body.review_id).toBe(DEMO_REVIEW_ID);
      return HttpResponse.json(kind === 'decision' ? {} : { from: 'draft', to: 'simulating' });
    }));
    const { router, client } = renderAt();
    const { modal, input, confirm } = await openDialog(kind);
    expect(input).toHaveValue('');
    expect(input).toHaveAttribute('type', 'password');
    expect(input).toHaveAttribute('autocomplete', 'new-password');
    expect(confirm).toBeDisabled();
    expect(writes).toBe(0);
    fireEvent.change(input, { target: { value: fakeValue } });
    expect(writes).toBe(0);
    fireEvent.click(confirm);
    await waitFor(() => expect(writes).toBe(1));
    await waitFor(() => expect(input).toHaveValue(''));
    await waitFor(() => expect(modal).not.toBeVisible());
    const vars = client.getMutationCache().getAll().map((m) => m.state.variables);
    expect(JSON.stringify(vars).includes(fakeValue)).toBe(false);
    expect(JSON.stringify([localStorage, sessionStorage]).includes(fakeValue)).toBe(false);
    expect((router.state.location.pathname + router.state.location.search).includes(fakeValue)).toBe(false);
  });
  it(`${kind} REAUTH_FAILED 只在弹窗提示并清空，不登出、不跳转、不重试`, async () => {
    if (kind === 'lifecycle') approvedReport();
    const { router, client } = renderAt();
    const { modal, input, confirm } = await openDialog(kind);
    const logs = vi.spyOn(console, 'error').mockImplementation(() => {});
    const info = vi.spyOn(console, 'log').mockImplementation(() => {});
    try {
      fireEvent.change(input, { target: { value: MOCK_WRONG_REAUTH } });
      fireEvent.click(confirm);
      await within(modal).findByText('本次密码复核失败，请重新输入本人密码；当前会话未退出。');
      expect(input).toHaveValue('');
      expect(confirm).toBeDisabled();
      expect(router.state.location.pathname).toBe('/admin/strategy-gates');
      expect(currentUser()?.role).toBe('admin');
      expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
      expect(client.getMutationCache().getAll()).toHaveLength(1);
      expect(JSON.stringify(client.getMutationCache().getAll()[0].state.variables).includes(MOCK_WRONG_REAUTH)).toBe(false);
      expect(JSON.stringify([...logs.mock.calls, ...info.mock.calls]).includes(MOCK_WRONG_REAUTH)).toBe(false);
    } finally { logs.mockRestore(); info.mockRestore(); }
  });
  it(`${kind} 非复核错误返回失败也清空密码`, async () => {
    if (kind === 'lifecycle') approvedReport();
    server.use(http.post(kind === 'decision' ? `${API}/admin/promotions/:id/decision` : `${API}/admin/strategies/:id/versions/:vid/lifecycle`, () => HttpResponse.json({ error: { code: 'INTERNAL_ERROR', message: '示例数据：操作未完成', details: null } }, { status: 500 })));
    renderAt();
    const { modal, input, confirm } = await openDialog(kind);
    fireEvent.change(input, { target: { value: 'x'.repeat(10) } });
    fireEvent.click(confirm);
    await within(modal).findByText(/操作未完成/);
    expect(input).toHaveValue('');
  });
}
it('取消后重开不保留密码，不发送审批', async () => {
  let writes = 0;
  server.use(http.post(`${API}/admin/promotions/:id/decision`, () => { writes++; return HttpResponse.json({}); }));
  renderAt();
  const { modal, input } = await openDialog('decision');
  fireEvent.change(input, { target: { value: 'x'.repeat(10) } });
  fireEvent.click(within(modal).getByRole('button', { name: /取\s*消/ }));
  await waitFor(() => expect(modal).not.toBeVisible());
  fireEvent.click(screen.getByTestId('approve-g7'));
  expect(await screen.findByLabelText('审核复核密码')).toHaveValue('');
  expect(writes).toBe(0);
});
it('会话失效的 AUTH_REQUIRED 仍需重新登录，与 REAUTH_FAILED 区分', () => {
  expect(globalErrorAction(new ApiError(401, 'REAUTH_FAILED', '复核失败', null, null))).toBe('none');
  expect(globalErrorAction(new ApiError(401, 'AUTH_REQUIRED', '会话失效', null, null))).toBe('login');
});
it('legacy_unbound 列表和详情正常返回 null 绑定，前端只读并提示重新申请', async () => {
  const data = await apiGet<Paged<PromotionSummary>>('/admin/promotions', { stale: true });
  expect(data.items.find((r) => r.review_id === LEGACY_REVIEW_ID)).toMatchObject({ version_id: null, content_sha256: null, stale: true, stale_reason: 'legacy_unbound' });
  renderAt(`/admin/strategy-gates?review_id=${LEGACY_REVIEW_ID}`);
  await screen.findByText('历史审核只读展示，要晋级须重新申请（legacy_unbound：历史审核未绑定版本及内容哈希）。');
  fireEvent.change(screen.getByLabelText('G7 审核意见'), { target: { value: '旧记录不可再审批' } });
  expect(screen.getByTestId('approve-g7')).toBeDisabled();
  expect(screen.getByTestId('to-simulating')).toBeDisabled();
  expect(screen.getByText(/历史审核未绑定内容哈希，不补算/)).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
it('夹具 diff=null 不渲染字面 null，也不编造缺口原因', async () => {
  renderAt();
  await screen.findByTestId('approve-g7');
  expect(screen.queryByText('null')).not.toBeInTheDocument();
  expect(screen.getAllByText('未提供差异详情')).toHaveLength(3);
});
it('示例错误密码确实返回 401 REAUTH_FAILED，正确示例复核保持两步', async () => {
  await expect(apiPost(`/admin/promotions/${DEMO_REVIEW_ID}/decision`, { decision: 'approved', comment: '示例数据', ack_warn_gates: ['G6'], password: MOCK_WRONG_REAUTH })).rejects.toMatchObject({ status: 401, code: 'REAUTH_FAILED' });
  const result = await apiPost<PromotionSummary>(`/admin/promotions/${DEMO_REVIEW_ID}/decision`, { decision: 'approved', comment: '示例数据', ack_warn_gates: ['G6'], password: 'x'.repeat(10) });
  expect(result.decision).toBe('approved');
  expect(result.lifecycle).toBe('draft');
});

/** T-F32 / T-A21：未知配额不补成零，真实的零值仍正常展示。 */
it.each([
  { quota: null, expected: '—' },
  { quota: 0, expected: '0' },
  { quota: 3, expected: '3' },
])('每分钟配额增量 $quota 显示 $expected', async ({ quota, expected }) => {
  const report = structuredClone(EXAMPLE_PROMOTION_REPORT);
  report.g6_report.quota_delta_per_min = quota;
  server.use(http.get(`${API}/promotion-requests/:id`, () => HttpResponse.json(report)));
  renderAt();
  await screen.findByTestId('approve-g7');
  expect(screen.getByTestId('quota-delta-per-min').textContent).toBe(expected);
});
