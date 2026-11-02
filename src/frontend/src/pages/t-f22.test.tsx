/** T-F22（契约 v0.2.6、T-A07 §5）：设置 → 数据证书；高风险模板启用开关旁的固定风险说明 */
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { QueryClient } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { CONTRACT_VERSION } from '../api/enums';
import { HIGH_RISK_STRATEGY_NOTE } from '../components/StrategyEnableSwitch';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { setMockLicence } from '../mocks/licenceStore';
import { STRATEGY_TEMPLATES } from '../mocks/strategyHandlers';
import { uid } from '../mocks/fixtures';

// 页面模块的冷加载放在等待窗口之外（评审 b23401a N8）
beforeAll(() => preloadRoutes(routes), 30_000);

let client: QueryClient;
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  client = makeQueryClient(true);
  render(
    <AppProviders client={client}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}

/** 运行时生成的虚构证书：只用少见字母，避免与页面文字偶然重合 */
const ALPHA = 'QXZJKVWY';
const fakeLicence = (prefix = '') => prefix + Array.from({ length: 28 }, () => ALPHA[Math.floor(Math.random() * ALPHA.length)]).join('');
/** 契约 §9：任何地方都找不到证书字符串及其任意 ≥ 4 位子串 */
function leaks(hay: string, licence: string) {
  for (let i = 0; i + 4 <= licence.length; i++) if (hay.includes(licence.slice(i, i + 4))) return licence.slice(i, i + 4);
  return null;
}
/** 收集本测试期间所有模拟响应体 */
function captureResponses() {
  const bodies: Promise<string>[] = [];
  const fn = ({ response }: { response: Response }) => void bodies.push(response.clone().text());
  server.events.on('response:mocked', fn);
  return async () => {
    server.events.removeListener('response:mocked', fn);
    return (await Promise.all(bodies)).join('\n');
  };
}
function captureRequests(path: string) {
  const out: { method: string; body: unknown }[] = [];
  const fn = async ({ request }: { request: Request }) => {
    if (new URL(request.url).pathname !== `/api/v1${path}`) return;
    const text = await request.clone().text();
    out.push({ method: request.method, body: text ? JSON.parse(text) : null });
  };
  server.events.on('request:start', fn);
  return out;
}
const typeLicence = (v: string) => fireEvent.change(screen.getByTestId('licence-input'), { target: { value: v } });

describe('T-F22 契约 v0.2.6 对齐', () => {
  it('CONTRACT_VERSION 为 v0.2.9（v0.2.9 起）', () => {
    expect(CONTRACT_VERSION).toBe('v0.2.9');
  });
});

describe('T-F22 设置 → 数据证书', () => {
  it('“更多”导航与用户菜单都有“数据证书”入口，路由可达', async () => {
    renderAt('/settings/data-licence');
    const page = await screen.findByTestId('licence-page');
    expect(within(page).getAllByText('可用').length).toBeGreaterThan(0);
    const { NAV_MORE } = await import('../app/nav');
    expect(NAV_MORE.some((n) => n.path === '/settings/data-licence' && n.label === '数据证书')).toBe(true);
  });

  it('未设置 → 提交证书：输入立即清空，DOM、响应、查询与变更缓存里都没有证书值或其 4 位片段', async () => {
    mockLoginAs('new_user');
    const done = captureResponses();
    const licence = fakeLicence();
    const reqs = captureRequests('/me/data-licence');
    renderAt('/settings/data-licence');
    const page = await screen.findByTestId('licence-page');
    expect(within(page).getAllByText('未设置').length).toBeGreaterThan(0);
    expect(await screen.findByTestId('licence-banner')).toHaveAttribute('data-status', 'not_set');
    const input = screen.getByTestId('licence-input') as HTMLInputElement;
    expect(input.type).toBe('password');
    expect(input.autocomplete).toBe('off');
    expect(input).toHaveAttribute('data-1p-ignore', 'true');
    expect(input).toHaveAttribute('data-lpignore', 'true');
    expect(screen.getByTestId('licence-no-save')).toBeInTheDocument();
    typeLicence(licence);
    fireEvent.click(screen.getByTestId('licence-save'));
    expect(await screen.findByTestId('licence-msg')).toHaveTextContent('正在验证');
    expect(input.value).toBe('');
    // 下一次读取时验证落定为可用，横幅消失
    await waitFor(() => expect(within(screen.getByTestId('licence-status')).getByText('可用')).toBeInTheDocument(), { timeout: 8000 });
    await waitFor(() => expect(screen.queryByTestId('licence-banner')).toBeNull(), { timeout: 4000 });
    const put = reqs.find((r) => r.method === 'PUT')!;
    expect(Object.keys(put.body as object).sort()).toEqual(['expires_on', 'has_quant_pro', 'licence', 'tier']);
    expect(leaks(document.documentElement.outerHTML, licence)).toBeNull();
    expect(leaks(await done(), licence)).toBeNull();
    expect(leaks(JSON.stringify(client.getQueryCache().getAll().map((q) => q.state.data)), licence)).toBeNull();
    expect(leaks(JSON.stringify(client.getMutationCache().getAll().map((m) => m.state.variables)), licence)).toBeNull();
  }, 20000);

  it('格式不符：客户端与服务端提示都不含输入值', async () => {
    mockLoginAs('new_user');
    const bad = `${fakeLicence()}/?`;
    renderAt('/settings/data-licence');
    await screen.findByTestId('licence-page');
    typeLicence(bad);
    fireEvent.click(screen.getByTestId('licence-save'));
    expect(await screen.findByText(/格式不符/)).toBeInTheDocument();
    expect((screen.getByTestId('licence-input') as HTMLInputElement).value).toBe('');
    expect(leaks(document.body.innerHTML, bad.slice(0, 28))).toBeNull();
    const r = await fetch('/api/v1/me/data-licence', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ licence: bad, tier: 'free', has_quant_pro: false, expires_on: null }) });
    expect(r.status).toBe(400);
    const body = await r.json();
    expect(body.error.code).toBe('VALIDATION_ERROR');
    expect(body.error.details.fields[0].field).toBe('licence');
    expect(leaks(JSON.stringify(body), bad.slice(0, 28))).toBeNull();
  });

  it('同一证书已绑定其他账号 → 409 DATA_LICENCE_IN_USE；前者删除后可设置', async () => {
    const licence = fakeLicence();
    const put = () => fetch('/api/v1/me/data-licence', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ licence, tier: 'monthly', has_quant_pro: false, expires_on: null }) });
    mockLoginAs('new_user');
    expect((await put()).status).toBe(202);
    mockLoginAs('demo_user');
    const r = await put();
    expect(r.status).toBe(409);
    const text = await r.text();
    expect(JSON.parse(text).error.code).toBe('DATA_LICENCE_IN_USE');
    expect(leaks(text, licence)).toBeNull();
    mockLoginAs('new_user');
    expect((await fetch('/api/v1/me/data-licence', { method: 'DELETE' })).status).toBe(204);
    expect((await fetch('/api/v1/me/data-licence', { method: 'DELETE' })).status).toBe(204);
    mockLoginAs('demo_user');
    expect((await put()).status).toBe(202);
  });

  it('未设置时 PATCH / 测试证书 → 409 DATA_LICENCE_NOT_SET；GET 只有契约字段，无证书类键', async () => {
    mockLoginAs('new_user');
    const p = await fetch('/api/v1/me/data-licence', { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ tier: 'free' }) });
    expect(p.status).toBe(409);
    expect((await p.json()).error.code).toBe('DATA_LICENCE_NOT_SET');
    const t = await fetch('/api/v1/me/data-licence/test', { method: 'POST' });
    expect((await t.json()).error.code).toBe('DATA_LICENCE_NOT_SET');
    mockLoginAs('demo_user');
    const s = await (await fetch('/api/v1/me/data-licence')).json();
    expect(Object.keys(s).sort()).toEqual([
      'days_to_expiry', 'expires_on', 'has_quant_pro', 'last_error_at', 'last_error_code', 'last_verified_at', 'paused_until', 'set_at', 'status', 'tier',
    ]);
  });

  it('已设置：留空证书只 PATCH 元数据；测试证书 202；删除后回到未设置', async () => {
    const reqs = captureRequests('/me/data-licence');
    renderAt('/settings/data-licence');
    await screen.findByTestId('licence-page');
    fireEvent.change(screen.getByTestId('licence-expires'), { target: { value: '2027-06-30' } });
    fireEvent.click(screen.getByTestId('licence-save'));
    expect(await screen.findByText('已更新档位与到期日')).toBeInTheDocument();
    const patch = reqs.find((r) => r.method === 'PATCH')!;
    expect(patch.body).not.toHaveProperty('licence');
    expect(patch.body).toMatchObject({ expires_on: '2027-06-30' });
    fireEvent.click(screen.getByTestId('licence-test'));
    expect(await screen.findByText(/已提交测试/)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('licence-delete'));
    fireEvent.click(await screen.findByRole('button', { name: /^删\s?除$/ }));
    expect(await screen.findByText('证书已删除')).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByTestId('licence-status')).getByText('未设置')).toBeInTheDocument());
  });

  it('证书不可用（invalid）→ 全站横幅；错误码只显示说明', async () => {
    setMockLicence(uid(2), { status: 'invalid', last_error_code: '102', last_error_at: '2026-11-02T09:30:00+08:00' });
    renderAt('/settings/data-licence');
    const banner = await screen.findByTestId('licence-banner');
    expect(banner).toHaveAttribute('data-status', 'invalid');
    expect(banner).toHaveTextContent('你的数据证书不可用');
    expect(await screen.findByTestId('licence-error')).toHaveTextContent('证书无效或已失效（102）');
  });

  it('提交后验证失败的虚构证书落定为 invalid', async () => {
    mockLoginAs('new_user');
    const licence = fakeLicence('X-INVALID-');
    renderAt('/settings/data-licence');
    await screen.findByTestId('licence-page');
    typeLicence(licence);
    fireEvent.click(screen.getByTestId('licence-save'));
    await waitFor(() => expect(within(screen.getByTestId('licence-status')).getByText('无效')).toBeInTheDocument(), { timeout: 8000 });
    expect(leaks(document.documentElement.outerHTML, licence.slice(10))).toBeNull();
  }, 15000);
});

describe('T-F22 高风险模板的启用开关', () => {
  it('风险说明与 plan 2.5.0A ⑫（T-A07 §4 第 4 条默认文案）逐字一致', () => {
    const plan = readFileSync(resolve(__dirname, '../../../../docs/plan.md'), 'utf8');
    const row = plan.split('\n').find((l) => l.startsWith('| ⑫ `risk_level`'))!;
    const quoted = row.slice(row.indexOf('启用开关旁固定展示风险说明')).match(/“([^”]+)”/)![1];
    expect(HIGH_RISK_STRATEGY_NOTE).toBe(quoted);
    // 任务单原文（仓库外，存在时一并比对）
    const ta07 = resolve(__dirname, '../../../../../team/reports/T-A07.md');
    if (existsSync(ta07)) expect(readFileSync(ta07, 'utf8')).toContain(`“${HIGH_RISK_STRATEGY_NOTE}”`);
  });

  it('按 risk_level 字段判断：只有 high 的模板显示说明（开、关两种状态都显示），不按 key 硬编码', async () => {
    renderAt('/strategies');
    await screen.findByTestId('strategies-page');
    const high = STRATEGY_TEMPLATES.filter((t) => t.risk_level === 'high');
    expect(high.map((t) => t.key)).toContain('st_strong_momo');
    for (const t of STRATEGY_TEMPLATES) {
      const cell = await screen.findByTestId(`enable-${t.key}`);
      const note = within(cell).queryByTestId('high-risk-note');
      if (t.risk_level === 'high') expect(note).toHaveTextContent(HIGH_RISK_STRATEGY_NOTE);
      else expect(note).toBeNull();
    }
    // 已启用的普通模板（如示例趋势）旁同样没有说明，未启用的高风险模板旁有
    expect(within(screen.getByTestId('enable-st_strong_momo')).getByRole('switch')).not.toBeChecked();
  });

  it('把字段改成 high 的任意模板同样显示说明（组件只认字段）', async () => {
    const t = STRATEGY_TEMPLATES.find((x) => x.key === 'st_pullback_ma')!;
    const prev = t.risk_level;
    t.risk_level = 'high';
    try {
      renderAt('/strategies');
      const cell = await screen.findByTestId('enable-st_pullback_ma');
      expect(within(cell).getByTestId('high-risk-note')).toHaveTextContent(HIGH_RISK_STRATEGY_NOTE);
    } finally {
      t.risk_level = prev;
    }
  });

  it('启用高风险模板：不弹窗、不发任何确认字段，201 后开关为开、说明仍在', async () => {
    const reqs = captureRequests('/strategy-instances');
    renderAt('/strategies');
    const cell = await screen.findByTestId('enable-st_strong_momo');
    await act(async () => fireEvent.click(within(cell).getByRole('switch')));
    await waitFor(() => expect(within(screen.getByTestId('enable-st_strong_momo')).getByRole('switch')).toBeChecked());
    expect(screen.queryByRole('dialog')).toBeNull();
    const post = reqs.find((r) => r.method === 'POST')!;
    expect(Object.keys(post.body as object).sort()).toEqual(['account_id', 'budget_amount', 'horizon', 'param_overrides', 'scope', 'security_code', 'strategy_version_id']);
    expect(post.body).toMatchObject({ strategy_version_id: uid(321), scope: 'account', horizon: 'short' });
    expect(within(screen.getByTestId('enable-st_strong_momo')).getByTestId('high-risk-note')).toBeInTheDocument();
    // 演示用户画像不含短线 → warnings 正常显示，不阻断
    expect(await screen.findByTestId('instance-warnings')).toHaveTextContent('画像偏好周期不含短线');
  });

  it('停用 = 暂停实例；再启用 = 恢复', async () => {
    const reqs = captureRequests(`/strategy-instances/${uid(200)}/pause`);
    renderAt('/strategies');
    const cell = await screen.findByTestId('enable-demo_trend');
    expect(within(cell).getByRole('switch')).toBeChecked();
    await act(async () => fireEvent.click(within(cell).getByRole('switch')));
    await waitFor(() => expect(within(screen.getByTestId('enable-demo_trend')).getByRole('switch')).not.toBeChecked());
    expect(reqs).toHaveLength(1);
  });
});
