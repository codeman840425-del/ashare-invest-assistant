/** T-F29 契约与权限回归，全部为合成示例数据。 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { server } from '../mocks/server';
import { currentUser, mockLoginAs } from '../mocks/session';
import { EXAMPLE_PROMOTION_REPORT } from '../mocks/promotionFixtures';
import { DEMO_REVIEW_ID } from '../mocks/promotionHandlers';
import { apiGet, apiPost } from '../api/client';
import { confirmMockPromotion } from '../test/confirmMockPromotion';
import { uid } from '../mocks/fixtures';
import type { PromotionSummary } from '../api/promotionTypes';
import type { Paged } from '../api/types';
const API = '/api/v1';
const path = `/admin/strategy-gates?review_id=${DEMO_REVIEW_ID}`;
beforeAll(() => preloadRoutes(routes), 30_000);
beforeEach(() => mockLoginAs('admin'));
function renderAt(url = path) {
  const router = createMemoryRouter(routes, { initialEntries: [url] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}
async function fillApproval() {
  await screen.findByTestId('approve-g7');
  fireEvent.change(screen.getByLabelText('G7 审核意见'), { target: { value: '本人已核对示例数据' } });
}
async function fillLifecycle() {
  await screen.findByTestId('approve-g7');
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '目标策略版本' }));
  fireEvent.click(await screen.findByText('门禁草稿（示例数据） · v1', { selector: '.ant-select-item-option-content' }));
  fireEvent.change(screen.getByLabelText('生命周期变更原因'), { target: { value: '本人已核对绑定版本' } });
}
it('警告默认不勾；意见不足以放行，确认后才发送 ack_warn_gates', async () => {
  let body: unknown;
  server.use(http.post(`${API}/admin/promotions/:id/decision`, async ({ request }) => { body = await request.json(); return HttpResponse.json({}); }));
  renderAt();
  await fillApproval();
  const checkbox = screen.getByRole('checkbox', { name: '本人已核实并确认 G6 警告' });
  expect(checkbox).not.toBeChecked();
  expect(screen.getByTestId('approve-g7')).toBeDisabled();
  expect(body).toBeUndefined();
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByTestId('approve-g7'));
  await confirmMockPromotion('decision');
  await waitFor(() => expect(body).toEqual({ decision: 'approved', comment: '本人已核对示例数据', ack_warn_gates: ['G6'], password: 'x'.repeat(10) }));
});
it('非管理员直达不可见且不请求审核列表和报告', async () => {
  mockLoginAs('demo_user');
  let reads = 0;
  server.use(http.get(`${API}/admin/promotions`, () => { reads++; return HttpResponse.json({ items: [], next_cursor: null }); }));
  renderAt();
  await screen.findByTestId('not-found');
  expect(screen.queryByTestId('approve-g7')).not.toBeInTheDocument();
  expect(reads).toBe(0);
});
it('示例 admin 登录不改变默认普通用户；管理员可取审核列表', async () => {
  mockLoginAs('demo_user');
  expect(currentUser()?.role).toBe('user');
  await apiPost('/auth/login', { username: 'admin', password: 'x'.repeat(10) });
  expect(currentUser()?.role).toBe('admin');
  const data = await apiGet<Paged<PromotionSummary>>('/admin/promotions');
  expect(data.items[0].card_key).toContain('示例数据');
  renderAt('/admin/strategy-gates');
  fireEvent.click(await screen.findByRole('button', { name: '查看报告' }));
  await screen.findByTestId('approve-g7');
});
it('游标分页保持筛选，筛选变化重置游标，并可从列表进入报告', async () => {
  const queries: URLSearchParams[] = [];
  server.use(http.get(`${API}/admin/promotions`, ({ request }) => {
    const q = new URL(request.url).searchParams; queries.push(q);
    return HttpResponse.json({ items: [], next_cursor: q.has('cursor') ? null : 'opaque-next' });
  }));
  renderAt('/admin/strategy-gates');
  await waitFor(() => expect(screen.getByRole('button', { name: '下一页' })).toBeEnabled());
  expect(queries[0].get('stale')).toBe('false');
  fireEvent.click(screen.getByRole('button', { name: '下一页' }));
  await waitFor(() => expect(queries.at(-1)?.get('cursor')).toBe('opaque-next'));
  fireEvent.click(screen.getByRole('checkbox', { name: '仅看已作废审核' }));
  await waitFor(() => expect(queries.at(-1)?.get('stale')).toBe('true'));
  expect(queries.at(-1)?.has('cursor')).toBe(false);
  expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('卡片编号筛选'), { target: { value: uid(512) } });
  await waitFor(() => expect(queries.at(-1)?.get('card_id')).toBe(uid(512)));
  fireEvent.change(screen.getByLabelText('版本编号筛选'), { target: { value: uid(322) } });
  await waitFor(() => expect(queries.at(-1)?.get('version_id')).toBe(uid(322)));
});
it('生命周期必须先有 approved 报告，另行点击并发送 review_id', async () => {
  let body: unknown;
  server.use(
    http.get(`${API}/promotion-requests/:id`, () => HttpResponse.json({ ...EXAMPLE_PROMOTION_REPORT, decision: 'approved' })),
    http.post(`${API}/admin/strategies/:id/versions/:vid/lifecycle`, async ({ request }) => { body = await request.json(); return HttpResponse.json({ from: 'draft', to: 'simulating' }); }),
  );
  renderAt();
  await fillLifecycle();
  expect(body).toBeUndefined();
  fireEvent.click(screen.getByTestId('to-simulating'));
  await confirmMockPromotion('lifecycle');
  await waitFor(() => expect(body).toEqual({ to: 'simulating', reason: '本人已核对绑定版本', review_id: DEMO_REVIEW_ID, password: 'x'.repeat(10) }));
});
it('pending 和 stale 审核不可晋级，stale 不可批准', async () => {
  server.use(http.get(`${API}/promotion-requests/:id`, () => HttpResponse.json({ ...EXAMPLE_PROMOTION_REPORT, stale: true })));
  renderAt();
  await fillApproval();
  expect(screen.getByTestId('approve-g7')).toBeDisabled();
  expect(screen.getByTestId('to-simulating')).toBeDisabled();
  expect(screen.getByText('审核已作废，仅供只读查看；请查看最新版本报告。')).toBeInTheDocument();
});
for (const operation of ['decision', 'lifecycle']) {
  for (const [status, code, text] of [[409, 'PROMOTION_STALE', /审核绑定的版本或内容哈希已变化，审核作废/], [403, 'HUMAN_SESSION_REQUIRED', /请管理员本人重新登录后操作/]] as const) {
    it(`${operation} ${code} 明确提示且不重试`, async () => {
      let writes = 0;
      server.use(http.post(operation === 'decision' ? `${API}/admin/promotions/:id/decision` : `${API}/admin/strategies/:id/versions/:vid/lifecycle`, () => {
        writes++; return HttpResponse.json({ error: { code, message: code, details: { current_version_id: uid(323) } } }, { status });
      }));
      if (operation === 'lifecycle') server.use(http.get(`${API}/promotion-requests/:id`, () => HttpResponse.json({ ...EXAMPLE_PROMOTION_REPORT, decision: 'approved' })));
      renderAt();
      if (operation === 'decision') {
        await fillApproval();
        fireEvent.click(screen.getByRole('checkbox', { name: '本人已核实并确认 G6 警告' }));
        fireEvent.click(screen.getByTestId('approve-g7'));
        await confirmMockPromotion('decision');
      } else { await fillLifecycle(); fireEvent.click(screen.getByTestId('to-simulating')); await confirmMockPromotion('lifecycle'); }
      await screen.findByText(text);
      expect(writes).toBe(1);
      expect(screen.getByTestId(operation === 'decision' ? 'approve-g7' : 'to-simulating')).toBeDisabled();
    });
  }
}
it('示例接口拒绝未确认警告和缺审核晋级', async () => {
  await expect(apiPost(`/admin/promotions/${DEMO_REVIEW_ID}/decision`, { decision: 'approved', comment: '示例数据', ack_warn_gates: [], password: 'x'.repeat(10) })).rejects.toMatchObject({ code: 'PROMOTION_WARN_UNACKNOWLEDGED' });
  await expect(apiPost(`/admin/strategies/${uid(512)}/versions/${uid(322)}/lifecycle`, { to: 'simulating', reason: '示例数据', review_id: null, password: 'x'.repeat(10) })).rejects.toMatchObject({ code: 'PROMOTION_GATES_NOT_MET' });
});
