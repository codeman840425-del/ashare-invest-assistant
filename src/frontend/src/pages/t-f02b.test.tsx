/** T-F02b：评审 T-F01 / T-F02 修复项（MSW 示例数据） */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { apiPost, setCsrfToken } from '../api/client';
import type { Trade } from '../api/accountTypes';
import { OVERRIDE_CHOICES, RESOLUTION_CHOICE, voidReasonText } from '../i18n/importLabels';
import { uid } from '../mocks/fixtures';
import { server } from '../mocks/server';
import { RESOLUTION_CHOICES, SECOND_ACCOUNT_ID } from '../mocks/session';

// 页面模块的冷加载放在等待窗口之外（评审 b23401a N8）
beforeAll(() => preloadRoutes(routes), 30_000);

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

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

describe('P2 通知深链参数', () => {
  it('/portfolio/import?batch=<id> 跳到批次页', async () => {
    const router = renderAt(`/portfolio/import?batch=${uid(820)}`);
    await waitFor(() => expect(router.state.location.pathname).toBe(`/portfolio/import/${uid(820)}`));
    expect(await screen.findByTestId('import-batch')).toBeInTheDocument();
  });
  it('/portfolio?account_id= 选中对应账户，持仓按该账户请求（v0.2.4 #14）', async () => {
    const seen: (string | null)[] = [];
    server.events.on('request:start', ({ request }) => {
      const u = new URL(request.url);
      if (u.pathname === '/api/v1/portfolio') seen.push(u.searchParams.get('account_id'));
    });
    renderAt(`/portfolio?account_id=${SECOND_ACCOUNT_ID}`);
    expect(await screen.findByTestId('positions-tab')).toBeInTheDocument();
    await waitFor(() => expect(seen).toContain(SECOND_ACCOUNT_ID));
    fireEvent.click(within(screen.getByTestId('portfolio-scope')).getByText('合并全部账户'));
    await waitFor(() => expect(seen).toContain(null));
    server.events.removeAllListeners();
  });
});

describe('成交：作废、更正与幂等（v0.2.4 #12；评审 s1、m8）', () => {
  it('作废必须填原因；作废后显示原因', async () => {
    renderAt('/portfolio?tab=trades');
    fireEvent.click(await screen.findByTestId(`void-${uid(901)}`));
    const dialog = await screen.findByRole('dialog');
    const ok = within(dialog).getByRole('button', { name: /作\s*废/ });
    expect(ok).toBeDisabled();
    fireEvent.change(within(dialog).getByTestId('void-reason'), { target: { value: '录入重复（示例）' } });
    expect(ok).toBeEnabled();
    fireEvent.click(ok);
    expect(await screen.findByTestId(`voided-${uid(901)}`)).toBeInTheDocument();
    expect(screen.getByText('已作废：录入重复（示例）')).toBeInTheDocument();
  });
  it('导入批次撤销产生的作废显示为批次撤销', () => {
    expect(voidReasonText({ void_reason: `batch_reverted:${uid(819)}` })).toContain('所属导入批次已撤销');
    expect(voidReasonText({ void_reason: null })).toContain('已作废');
  });
  it('同一 Idempotency-Key 重放返回同一条成交；已作废再作废 → 409', async () => {
    setCsrfToken('mock-csrf');
    const body = { account_id: uid(1), trade_date: '2026-10-28', trade_time: null, security_code: '600000.SH', side: 'buy', qty: '100', price: '9.80', fee_total: null };
    const a = await apiPost<Trade>('/trades', body, { idempotencyKey: 'idem-demo-1' });
    const b = await apiPost<Trade>('/trades', body, { idempotencyKey: 'idem-demo-1' });
    expect(b.id).toBe(a.id);
    expect(a).toMatchObject({ net_amount: null, void_reason: null, voided_at: null, corrects_trade_id: null });
    const v = await apiPost<Trade>(`/trades/${a.id}/void`, { reason: '示例' });
    expect(v.voided).toBe(true);
    await expect(apiPost(`/trades/${a.id}/void`, { reason: '示例' })).rejects.toMatchObject({ status: 409 });
  });
  it('更正记录必须带原因，保存后原记录作废', async () => {
    setCsrfToken('mock-csrf');
    const body = { account_id: uid(1), trade_date: '2026-10-28', trade_time: null, security_code: '600002.SH', side: 'buy', qty: '400', price: '17.95', fee_total: null, corrects_trade_id: uid(901) };
    await expect(apiPost('/trades', body)).rejects.toMatchObject({ status: 400 });
    const t = await apiPost<Trade>('/trades', { ...body, reason: '价格录错（示例）' });
    expect(t.corrects_trade_id).toBe(uid(901));
  });
});

describe('导入（评审 m7、§4.1 处理选项表）', () => {
  it('超过 5 MB 的文件在前端直接拦下', async () => {
    renderAt('/portfolio/import');
    const input = (await screen.findByText(/拖到这里/)).closest('.ant-upload')!.querySelector('input[type=file]') as HTMLInputElement;
    const big = new File(['x'], 'big.txt', { type: 'text/plain' });
    Object.defineProperty(big, 'size', { value: 5 * 1024 * 1024 + 1 });
    fireEvent.change(input, { target: { files: [big] } });
    expect(await screen.findByTestId('upload-too-big')).toHaveTextContent('5 MB');
  });
  it('v0.2.4 #11：每个需处理的码都有中文选项；需填理由的三项', () => {
    for (const choices of Object.values(RESOLUTION_CHOICES)) for (const c of choices) expect(RESOLUTION_CHOICE[c as keyof typeof RESOLUTION_CHOICE]).toBeTruthy();
    expect(RESOLUTION_CHOICES.IMPORT_ACCOUNT_MISMATCH).toEqual(['confirm_new_holder_code']);
    expect([...OVERRIDE_CHOICES].sort()).toEqual(['confirm_new_holder_code', 'force_import', 'keep_import_void_manual']);
  });
});
