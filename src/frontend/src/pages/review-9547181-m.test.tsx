/** 评审 9547181 m 级：证书 PUT 冷却规则（契约 #13 及 v0.2.8 补充）、202 提示文案、PUT/PATCH 503、过期文案、/test 判断顺序 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import type { DataLicenceStatus } from '../api/licenceTypes';
import { expiryLeftText } from '../i18n/licenceLabels';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { LICENCE_RATE, setMockLicence, setMockLicenceSettingsEnabled } from '../mocks/licenceStore';
import { uid } from '../mocks/fixtures';
import { apiFetch } from '../test/apiFetch';

// 页面模块的冷加载放在等待窗口之外（评审 b23401a N8）
beforeAll(() => preloadRoutes(routes), 30_000);

const API = '/api/v1';
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}
/** 运行时生成的虚构证书（只用少见字母） */
const ALPHA = 'QXZJKVWY';
const fakeLicence = () => Array.from({ length: 28 }, () => ALPHA[Math.floor(Math.random() * ALPHA.length)]).join('');
const FUTURE = '2026-11-03T00:01:00+08:00';
const PAST = '2026-11-01T00:01:00+08:00';
async function put(licence: string, tier = 'free') {
  const r = await apiFetch(`${API}/me/data-licence`, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ licence, tier, has_quant_pro: false, expires_on: null }) });
  return { status: r.status, body: (await r.json()) as DataLicenceStatus & { error?: { code: string } } };
}
const ACTIVE_NO_PAUSE: DataLicenceStatus = {
  status: 'active', tier: 'diamond', has_quant_pro: false, expires_on: null, days_to_expiry: null, set_at: null,
  last_verified_at: null, last_error_code: null, last_error_at: null, paused_until: null,
};
const del = () => apiFetch(`${API}/me/data-licence`, { method: 'DELETE' });
const getStatus = async () => (await (await apiFetch(`${API}/me/data-licence`)).json()) as DataLicenceStatus;

describe('m1：重复 PUT 同一证书（契约 #13）', () => {
  it('quota_exceeded 时重提同一证书 → 202，保持状态与 paused_until，只更新档位', async () => {
    const L = fakeLicence();
    expect((await put(L)).status).toBe(202);
    setMockLicence(uid(2), { status: 'quota_exceeded', paused_until: FUTURE, last_error_code: '101' });
    const r = await put(L, 'annual');
    expect(r.status).toBe(202);
    expect(r.body).toMatchObject({ status: 'quota_exceeded', paused_until: FUTURE, tier: 'annual', last_error_code: '101' });
    expect((await getStatus()).status).toBe('quota_exceeded');
  });
  it('active 且 paused_until 未到期 → 保持 active 与 paused_until，不验证', async () => {
    const L = fakeLicence();
    await put(L);
    setMockLicence(uid(2), { status: 'active', paused_until: FUTURE });
    const r = await put(L);
    expect(r.body).toMatchObject({ status: 'active', paused_until: FUTURE });
    expect((await getStatus()).status).toBe('active');
  });
  it('active、paused_until 已到期或为空 → 照常转为 pending_verification', async () => {
    const L = fakeLicence();
    await put(L);
    setMockLicence(uid(2), { status: 'active', paused_until: PAST });
    expect((await put(L)).body.status).toBe('pending_verification');
    setMockLicence(uid(2), { status: 'active', paused_until: null });
    expect((await put(L)).body.status).toBe('pending_verification');
  });
  it('冷却中换成不同证书 → 照常验证，冷却状态不带过去', async () => {
    await put(fakeLicence());
    setMockLicence(uid(2), { status: 'ip_limited', paused_until: FUTURE });
    const r = await put(fakeLicence());
    expect(r.body).toMatchObject({ status: 'pending_verification', paused_until: null });
  });
});

describe('m1：删除后重新提交不能跳过冷却（v0.2.8 #13 补充）', () => {
  it('quota_exceeded 时 DELETE，到期前重提同一证书 → 恢复删除前的 status 与 paused_until，不验证', async () => {
    const L = fakeLicence();
    await put(L);
    setMockLicence(uid(2), { status: 'quota_exceeded', paused_until: FUTURE, last_error_code: '101', last_error_at: '2026-11-02T09:41:00+08:00' });
    expect((await del()).status).toBe(204);
    expect((await getStatus()).status).toBe('not_set');
    const r = await put(L);
    expect(r.status).toBe(202);
    expect(r.body).toMatchObject({ status: 'quota_exceeded', paused_until: FUTURE, last_error_code: '101' });
    expect((await getStatus()).status).toBe('quota_exceeded');
    expect(JSON.stringify(r.body)).not.toMatch(/digest|fingerprint|seed-/);
  });
  it('active 带未到期 paused_until 时删除后重提同一证书 → 恢复 active 与 paused_until', async () => {
    const L = fakeLicence();
    await put(L);
    setMockLicence(uid(2), { status: 'active', paused_until: FUTURE });
    await del();
    expect((await put(L)).body).toMatchObject({ status: 'active', paused_until: FUTURE });
  });
  it('删除后换不同证书 → 照常验证；记录取出即作废，再删再提原证书也照常验证', async () => {
    const L = fakeLicence();
    await put(L);
    setMockLicence(uid(2), { status: 'ip_limited', paused_until: FUTURE });
    await del();
    expect((await put(fakeLicence())).body.status).toBe('pending_verification');
    await del();
    expect((await put(L)).body.status).toBe('pending_verification');
  });
  it('不在冷却时删除（或 paused_until 已到期）→ 重提照常验证', async () => {
    const L = fakeLicence();
    await put(L);
    setMockLicence(uid(2), { status: 'active', paused_until: PAST });
    await del();
    expect((await put(L)).body.status).toBe('pending_verification');
  });
  it('管理员暂停优先：冷却中删除、暂停后重提 → 仍为 paused_by_admin', async () => {
    const L = fakeLicence();
    await put(L);
    setMockLicence(uid(2), { status: 'quota_exceeded', paused_until: FUTURE });
    await del();
    setMockLicence(uid(2), { status: 'paused_by_admin' });
    await del();
    expect((await put(L)).body.status).toBe('paused_by_admin');
  });
});

describe('m2：保存成功后的提示只在冷却时提“冷却到期前”', () => {
  const submit = async (L: string) => {
    fireEvent.change(await screen.findByTestId('licence-input'), { target: { value: L } });
    fireEvent.click(screen.getByTestId('licence-save'));
    return screen.findByTestId('licence-msg');
  };
  it('冷却中重提同一证书 → 提示冷却', async () => {
    const L = fakeLicence();
    await put(L);
    setMockLicence(uid(2), { status: 'quota_exceeded', paused_until: FUTURE });
    renderAt('/settings/data-licence');
    expect(await submit(L)).toHaveTextContent('冷却到期前不会重新验证');
  });
  it('202 返回 active 且无 paused_until → 只说明当前状态，不提冷却', async () => {
    server.use(http.put(`${API}/me/data-licence`, () => HttpResponse.json({ ...ACTIVE_NO_PAUSE }, { status: 202 })));
    renderAt('/settings/data-licence');
    const msg = await submit(fakeLicence());
    expect(msg).toHaveTextContent('当前状态“可用”');
    expect(msg).not.toHaveTextContent('冷却');
  });
  it('新证书 → “已提交，正在验证”', async () => {
    renderAt('/settings/data-licence');
    expect(await submit(fakeLicence())).toHaveTextContent('已提交，正在验证');
  });
});

describe('m3：PUT 与 PATCH 收到 503 MAINTENANCE', () => {
  it('PUT 503 → 显示“设置暂未开放”，保存与测试禁用，删除可用；证书输入已清空', async () => {
    setMockLicenceSettingsEnabled(false);
    renderAt('/settings/data-licence');
    fireEvent.change(await screen.findByTestId('licence-input'), { target: { value: fakeLicence() } });
    fireEvent.click(screen.getByTestId('licence-save'));
    expect(await screen.findByTestId('licence-closed')).toHaveTextContent('设置暂未开放');
    await waitFor(() => expect(screen.getByTestId('licence-save')).toBeDisabled());
    expect(screen.getByTestId('licence-test')).toBeDisabled();
    expect(screen.getByText('删除证书').closest('button')).not.toBeDisabled();
    expect((screen.getByTestId('licence-input') as HTMLInputElement).value).toBe('');
    expect(screen.queryByTestId('licence-msg')).toBeNull();
  });
  it('PATCH 503（只改档位）→ 同样显示“设置暂未开放”并禁用提交', async () => {
    setMockLicenceSettingsEnabled(false);
    renderAt('/settings/data-licence');
    await screen.findByTestId('licence-input');
    fireEvent.click(screen.getByTestId('licence-save'));
    expect(await screen.findByTestId('licence-closed')).toHaveTextContent('设置暂未开放');
    await waitFor(() => expect(screen.getByTestId('licence-save')).toBeDisabled());
    expect(screen.queryByText('已更新档位与到期日')).toBeNull();
  });
  it('接口顺序：请求体格式错误先于 503；PATCH 503 先于 409 DATA_LICENCE_NOT_SET', async () => {
    setMockLicenceSettingsEnabled(false);
    expect((await put('短')).status).toBe(400);
    expect((await put(fakeLicence())).status).toBe(503);
    const bad = await apiFetch(`${API}/me/data-licence`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ tier: 'nope' }) });
    expect(bad.status).toBe(400);
    await del();
    const r = await apiFetch(`${API}/me/data-licence`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ tier: 'free' }) });
    expect(r.status).toBe(503);
  });
});

describe('m4：/test 判断顺序与后端一致（暂停 409 先于限速）', () => {
  it('暂停期间即使测试次数已用完也返回 409 DATA_LICENCE_UNAVAILABLE', async () => {
    for (let i = 0; i < LICENCE_RATE.test; i++) await apiFetch(`${API}/me/data-licence/test`, { method: 'POST' });
    expect((await apiFetch(`${API}/me/data-licence/test`, { method: 'POST' })).status).toBe(429);
    setMockLicence(uid(2), { status: 'paused_by_admin' });
    const r = await apiFetch(`${API}/me/data-licence/test`, { method: 'POST' });
    expect(r.status).toBe(409);
    expect(((await r.json()) as { error: { code: string } }).error.code).toBe('DATA_LICENCE_UNAVAILABLE');
  });
  it('未设置时返回 409 DATA_LICENCE_NOT_SET，且不消耗测试次数', async () => {
    await del();
    for (let i = 0; i < LICENCE_RATE.test + 1; i++) expect((await apiFetch(`${API}/me/data-licence/test`, { method: 'POST' })).status).toBe(409);
    await put(fakeLicence());
    expect((await apiFetch(`${API}/me/data-licence/test`, { method: 'POST' })).status).toBe(202);
  });
});

describe('m5：过期后显示“已过期”，不显示“剩 -N 天”', () => {
  it('文案函数', () => {
    expect(expiryLeftText(null)).toBeNull();
    expect(expiryLeftText(-3)).toBe('已过期');
    expect(expiryLeftText(0)).toBe('今天到期');
    expect(expiryLeftText(5)).toBe('剩 5 天');
  });
  it('设置页', async () => {
    setMockLicence(uid(2), { expires_on: '2026-10-01', days_to_expiry: -32 });
    renderAt('/settings/data-licence');
    const box = await screen.findByTestId('licence-status');
    await waitFor(() => expect(box).toHaveTextContent('2026-10-01（已过期）'));
    expect(box.textContent).not.toMatch(/剩 -/);
  });
  it('管理端采集表与证书列表', async () => {
    mockLoginAs('admin');
    setMockLicence(uid(13), { expires_on: '2026-10-01', days_to_expiry: -32 });
    renderAt('/admin/ingest');
    const table = await screen.findByTestId('admin-ingest');
    await waitFor(() => expect(within(table).getByText('2026-10-01（已过期）')).toBeInTheDocument());
    expect(table.textContent).not.toMatch(/剩 -/);
  });
  it('管理端证书列表', async () => {
    mockLoginAs('admin');
    setMockLicence(uid(13), { expires_on: '2026-10-01', days_to_expiry: -32 });
    renderAt('/admin/data-licences');
    await waitFor(() => expect(screen.getByText('2026-10-01（已过期）')).toBeInTheDocument());
    expect(document.body.textContent).not.toMatch(/剩 -/);
  });
});
