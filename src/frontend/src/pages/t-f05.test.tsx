/** T-F05（契约 v0.2.5、T-A06）：同意流程、风险测评、fit_ack 已删除；画像为普通选填表单；画像规则只提示 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { DISCLAIMER_TEXT } from '../components/RiskDisclosure';
import { server } from '../mocks/server';
import { mockLoginAs, setRegistrationMode, state } from '../mocks/session';
import { SUGGESTIONS, uid } from '../mocks/fixtures';

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
const PW = 'x'.repeat(12) + '1';

describe('T-F05 删除项', () => {
  it('/onboarding 已删除 → 404 页', async () => {
    renderAt('/onboarding');
    expect(await screen.findByTestId('not-found')).toBeInTheDocument();
  });
  it('导航里没有“风险测评”入口', async () => {
    renderAt('/terminal');
    await screen.findByTestId('terminal');
    expect(screen.queryByText('风险测评')).toBeNull();
  });
  it('Me 只有契约 v0.2.5 的六个字段', async () => {
    const me = await (await fetch('/api/v1/me')).json();
    expect(Object.keys(me).sort()).toEqual(['display_name', 'entitlements', 'id', 'role', 'status', 'username']);
  });
});

describe('注册页：只展示免责提示，没有勾选框', () => {
  it('免责提示与 disclaimer.md 原文一致；请求体不含 agreements', async () => {
    mockLoginAs(null);
    setRegistrationMode('open');
    let body: Record<string, unknown> | null = null;
    server.events.on('request:start', async ({ request }) => {
      if (request.method === 'POST' && request.url.endsWith('/auth/register')) body = await request.clone().json();
    });
    renderAt('/register');
    const box = await screen.findByTestId('reg-disclaimer');
    expect(within(box).getByTestId('reg-disclaimer-text').textContent).toBe(DISCLAIMER_TEXT);
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'tf05_user' } });
    fireEvent.change(screen.getByLabelText('显示名'), { target: { value: '示例' } });
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: PW } });
    fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: PW } });
    fireEvent.click(screen.getByRole('button', { name: /提交注册申请/ }));
    expect(await screen.findByTestId('register-done')).toBeInTheDocument();
    server.events.removeAllListeners();
    expect(body).not.toBeNull();
    expect(body!).not.toHaveProperty('agreements');
  });
  it('旧客户端仍发 agreements → 服务端忽略，照常 201', async () => {
    setRegistrationMode('open');
    const r = await fetch('/api/v1/auth/register', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ username: 'tf05_old', password: PW, display_name: '示例', invite_code: null, apply_note: null, agreements: ['terms'] }),
    });
    expect(r.status).toBe(201);
  });
});

describe('画像：普通选填表单（v0.2.5 #6）', () => {
  it('新用户不填精力 / 风险 / 经验也能保存，三项提交为 null', async () => {
    mockLoginAs('new_user');
    let body: Record<string, unknown> | null = null;
    server.events.on('request:start', async ({ request }) => {
      if (request.method === 'PUT' && request.url.endsWith('/me/profile')) body = await request.clone().json();
    });
    renderAt('/settings/profile');
    fireEvent.click(await screen.findByRole('button', { name: /保存为新版本/ }));
    await waitFor(() => expect(state.profiles.get(uid(4))?.version_no).toBe(1));
    server.events.removeAllListeners();
    expect(body).toMatchObject({ effort: null, risk_tolerance: null, experience: null });
    expect(body!).not.toHaveProperty('assessment_id');
    expect(screen.queryByText(/测评/)).toBeNull();
  });
});

describe('周期分类：画像规则只提示（classifier 1.2.0）', () => {
  it('自报新手：显示 SH0C / IT0C 提示，不出现对应封顶；卡片带免责提示', async () => {
    mockLoginAs('novice_user');
    const sg = SUGGESTIONS[0];
    renderAt(`/suggestions/${sg.id}`);
    const page = await screen.findByTestId('suggestion-detail');
    const hz = await within(page).findByTestId('horizon-panel');
    expect(await within(hz).findByTestId('hint-short-SH0C')).toHaveTextContent('短线需要盯盘与止损纪律，您自报的经验为新手');
    expect(within(hz).getByTestId('hint-intraday_t-IT0C')).toBeInTheDocument();
    expect(within(hz).queryByTestId('cap-short-SH0C')).toBeNull();
    expect(within(page).getByTestId('card-disclaimer').textContent).toBe(DISCLAIMER_TEXT);
  });
  it('其他用户：hints 为空，不显示提示', async () => {
    const sg = SUGGESTIONS[0];
    renderAt(`/suggestions/${sg.id}`);
    const hz = await screen.findByTestId('horizon-panel');
    await within(hz).findAllByText('支持');
    expect(within(hz).queryAllByTestId(/^hint-/)).toHaveLength(0);
  });
  it('MSW 不再对 403 做同意门槛：已登录用户可直接访问候选信号', async () => {
    mockLoginAs('new_user');
    expect((await fetch('/api/v1/suggestions')).status).toBe(200);
  });
});
