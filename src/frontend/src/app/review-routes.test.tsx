/** T-F01 评审 M2（全局 401/CONSENT 跳转）与 M4（管理后台只对 admin 可见） */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { AppProviders } from './AppProviders';
import { makeQueryClient } from './queryClient';
import { routes } from './routes';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders client={makeQueryClient(true)}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}
const asAdmin = () => mockLoginAs('admin');
const err = (status: number, code: string) => () => HttpResponse.json({ error: { code, message: 'x', details: null, request_id: 'r' } }, { status });

describe('M2 全局错误处理', () => {
  it('任意请求 401 AUTH_REQUIRED → 跳转 /login?next=当前路径', async () => {
    server.use(http.get('/api/v1/terminal', err(401, 'AUTH_REQUIRED')));
    const router = renderAt('/terminal?scope=all');
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));
    expect(new URLSearchParams(router.state.location.search).get('next')).toBe('/terminal?scope=all');
  });
  it('403 CONSENT_REQUIRED → 跳转 /onboarding?next=', async () => {
    server.use(http.get('/api/v1/suggestions', err(403, 'CONSENT_REQUIRED')));
    const router = renderAt('/suggestions');
    await waitFor(() => expect(router.state.location.pathname).toBe('/onboarding'));
    expect(new URLSearchParams(router.state.location.search).get('next')).toBe('/suggestions');
  });
  it('ErrorBox 按码显示中文文案并带 data-code', async () => {
    server.use(http.get('/api/v1/suggestions', err(503, 'FRESH_DATA_REQUIRED')));
    renderAt('/suggestions');
    const box = await screen.findByText(/行情数据暂未更新/);
    expect(box.closest('[data-code]')).toHaveAttribute('data-code', 'FRESH_DATA_REQUIRED');
  });
});

describe('M4 管理后台入口', () => {
  it('普通用户：/admin/users 显示 404，更多菜单无“管理后台”', async () => {
    renderAt('/admin/users');
    expect(await screen.findByTestId('not-found')).toBeInTheDocument();
    fireEvent.mouseEnter(screen.getByText(/更多/));
    await screen.findByText('市场概览');
    expect(screen.queryByText('用户审核（管理）')).toBeNull();
  });
  it('管理员：/admin/users 为用户审核页，更多菜单含管理入口', async () => {
    asAdmin();
    renderAt('/admin/users');
    expect(await screen.findByTestId('admin-users')).toBeInTheDocument();
    fireEvent.mouseEnter(screen.getByText(/更多/));
    expect(await screen.findByText('用户审核（管理）')).toBeInTheDocument();
  });
});
