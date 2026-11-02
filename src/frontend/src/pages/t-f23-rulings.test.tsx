/**
 * T-F23 裁定跟进：reports/frontend-pending-rulings.md 中已裁定项（契约 v0.2.9 #30 ①–⑤、§7.7B、验收 1–8；#26 ⑤）。
 * 全部数据为 MSW 示例数据。
 */
import { fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { ApiError } from '../api/client';
import { ENUMS } from '../api/enums';
import { useCreateCandidateVersion } from '../api/candidateQueries';
import type { Alert, Plan, PlanSummary } from '../api/planAlertTypes';
import type { PlanDraft } from '../api/planTypes';
import { lotRuleOf, lotWarning } from '../lib/planDraft';
import { CANDIDATE_SIGNALS, PORTFOLIO, REASONS, uid } from '../mocks/fixtures';
import { CHECKLIST, draftsNow } from '../mocks/planHandlers';
import { CSRF_WHITELIST } from '../mocks/accountHandlers';
import { mockLoginAs, setRegistrationMode } from '../mocks/session';
import { server } from '../mocks/server';
import { UNCLASSIFIED_SECTOR } from './portfolio/PortfolioPage';
import { CONFLICT_EVIDENCE_KEY } from './signals/CandidateSignalDetailPage';
import { apiFetch } from '../test/apiFetch';

beforeAll(() => preloadRoutes(routes), 30_000);
beforeEach(() => mockLoginAs('demo_user'));

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';
type Err = { error: { code: string; details: Record<string, unknown> | null } };
type Page<T> = { items: T[]; next_cursor: string | null };
const json = (method: string, path: string, body?: unknown, headers: Record<string, string> = {}) =>
  apiFetch(`${API}${path}`, { method, headers: { 'content-type': 'application/json', ...headers }, body: body === undefined ? undefined : JSON.stringify(body) });
const getJ = async <T,>(path: string) => { const r = await apiFetch(`${API}${path}`); return { status: r.status, body: (await r.json()) as T }; };
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}
const PLAN_TRIGGERED = uid(7301);
const PLAN_ACTIVE = uid(7303);
const PLAN_DONE = uid(7304);
const ALERT_PLAN_COND = uid(7199);
const ALERT_DISMISSED = uid(7105);
const PLAN_BODY = { security_code: '000002.SZ', action: 'buy', rationale: '示例：计划条件说明', conditions: [{ kind: 'trigger', type: 'price_below', params: { price: '9.50' }, description: '示例：价格回落到 9.50 以下' }] };

describe('#30 ③ STRATEGY_CONFLICT evidence 保留键 signal.conflict_signal_id', () => {
  it('mock：每个对方信号一条 evidence，值为对方信号 id；验收 4 的示例为 2 条', () => {
    expect(CONFLICT_EVIDENCE_KEY).toBe('signal.conflict_signal_id');
    const rs = REASONS.filter((r) => r.code === 'STRATEGY_CONFLICT');
    expect(rs.length).toBeGreaterThan(0);
    for (const r of rs) {
      const ev = r.evidence.filter((e) => e.key === CONFLICT_EVIDENCE_KEY);
      expect(ev.length).toBeGreaterThan(0);
      for (const e of ev) expect(CANDIDATE_SIGNALS.some((c) => c.id === e.value)).toBe(true);
    }
    // 验收 4：示例中至少有一个原因带 2 条以上（每个对方信号一条）
    expect(Math.max(...rs.map((r) => r.evidence.filter((e) => e.key === CONFLICT_EVIDENCE_KEY).length))).toBeGreaterThanOrEqual(2);
  });
  it('详情页按 evidence 中的 id 列出对方信号卡片', async () => {
    const r = REASONS.find((x) => x.code === 'STRATEGY_CONFLICT' && x.evidence.filter((e) => e.key === CONFLICT_EVIDENCE_KEY).length >= 2)!;
    renderAt(`/candidate-signals/${r.signal_id}`);
    const box = await screen.findByTestId('signal-conflicts', {}, { timeout: 5000 });
    for (const e of r.evidence.filter((x) => x.key === CONFLICT_EVIDENCE_KEY)) expect(within(box).getByTestId(`conflict-card-${String(e.value)}`)).toBeInTheDocument();
  });
  it('evidence 指向的信号不在当前列表时列出链接，不按方向推测', async () => {
    const ghost = uid(1999);
    const base = REASONS.find((x) => x.code === 'STRATEGY_CONFLICT')!;
    server.use(http.get(`${API}/non-executable-reasons`, () => HttpResponse.json({ items: [{ ...base, status: 'active', evidence: [{ id: 'EC1', key: CONFLICT_EVIDENCE_KEY, value: ghost, unit: null, provider: 'system', endpoint: null, data_as_of: null, fetched_at: '2026-11-02T09:30:00+08:00', epistemic_type: 'fact' }] }], next_cursor: null })));
    const sig = REASONS.find((x) => x.code === 'STRATEGY_CONFLICT')!.signal_id;
    renderAt(`/candidate-signals/${sig}`);
    const miss = await screen.findByTestId('conflict-missing');
    expect(miss).toHaveTextContent(ghost.slice(-8));
  });
});

describe('#30 ③ POST /plan-drafts 400 先于 409；lot_rule 在 fields[]；卖出零股公式', () => {
  const BUY = uid(1000);
  const REDUCE = uid(1003);
  it('方向不同的两个信号 → 400（不是 409）', async () => {
    const r = await json('POST', '/plan-drafts', { signal_ids: [BUY, REDUCE] });
    expect(r.status).toBe(400);
    expect(((await r.json()) as Err).error.details).toEqual({ fields: [{ field: 'signal_ids', issue: expect.any(String) }] });
  });
  it('同向但带 STRATEGY_CONFLICT（blocked）→ 409 SIGNAL_NOT_EXECUTABLE', async () => {
    const r = await json('POST', '/plan-drafts', { signal_ids: [BUY] });
    expect(r.status).toBe(409);
    expect(((await r.json()) as Err).error.code).toBe('SIGNAL_NOT_EXECUTABLE');
  });
  it('确认时不合手数 → 400，details.fields[0] 含 issue=lot_rule、min_buy、step；前端只从 fields[] 读', async () => {
    const PENDING = uid(1012);
    const d = draftsNow().find((x) => x.id === PENDING)!;
    const answers = CHECKLIST.filter((c) => c.required).map((c) => ({ id: c.id, answer: 'yes' }));
    const r = await json('POST', `/plan-drafts/${PENDING}/confirm`, { checklist_answers: answers, risk_ack: true, chosen_qty: '150', chosen_price: d.price_range.low, deviation_ack: true });
    expect(r.status).toBe(400);
    const b = (await r.json()) as Err;
    const f0 = (b.error.details!.fields as Record<string, unknown>[])[0];
    expect(f0).toMatchObject({ field: 'chosen_qty', issue: 'lot_rule', min_buy: '100', step: '100' });
    expect(b.error.details).not.toHaveProperty('min_buy');
    expect(lotRuleOf(new ApiError(400, b.error.code, 'x', b.error.details, null))).toEqual({ min_buy: '100', step: '100' });
  });
  it('科创板可卖 350 股：卖 150 提示，卖 250、350 不提示；卖 400 超过可卖', () => {
    const base = draftsNow()[0];
    const star: PlanDraft = { ...base, security_code: '688001.SH', action: 'sell', qty_range: { ...base.qty_range, lot: '1' }, user_context_snapshot: { ...base.user_context_snapshot, sellable_qty: '350' } };
    expect(lotWarning(star, '150')).toMatch(/科创板卖出数量须不少于 200 股/);
    expect(lotWarning(star, '250')).toBeNull();
    expect(lotWarning(star, '350')).toBeNull();
    expect(lotWarning(star, '400')).toMatch(/不能超过可卖数量 350/);
    // 可卖余量不足 200 股时只能一次全部卖出
    const tail: PlanDraft = { ...star, user_context_snapshot: { ...star.user_context_snapshot, sellable_qty: '120' } };
    expect(lotWarning(tail, '120')).toBeNull();
    expect(lotWarning(tail, '100')).toMatch(/一次卖出全部可卖 120 股/);
  });
});

describe('#30 ③ 没有行业归属的持仓计入“未分类”', () => {
  it('mock exposure.sector 含“未分类”；持仓页单独标注、说明不参与行业集中度', async () => {
    expect(PORTFOLIO.exposure.sector.some((x) => x.name === UNCLASSIFIED_SECTOR)).toBe(true);
    renderAt('/portfolio');
    const u = await screen.findByTestId('sector-unclassified');
    expect(u).toHaveTextContent('未分类');
    fireEvent.mouseEnter(u);
    expect(await screen.findByText(/不参与行业集中度判断/)).toBeInTheDocument();
  });
});

describe('研究候选改版带 Idempotency-Key', () => {
  it('POST /candidates/{id}/versions 带 Idempotency-Key；重试复用同一个键', async () => {
    const keys: (string | null)[] = [];
    let n = 0;
    server.use(http.post(`${API}/candidates/:id/versions`, ({ request }) => {
      keys.push(request.headers.get('Idempotency-Key'));
      n += 1;
      return n === 1 ? HttpResponse.error() : HttpResponse.json({ id: 'x' }, { status: 201 });
    }));
    const qc = makeQueryClient(true);
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
    const { result } = renderHook(() => useCreateCandidateVersion(uid(8001)), { wrapper });
    const body = { base_version_no: 1, thesis: '示例', conditions_to_hold: [], decision: null, decision_reason: null };
    await result.current.mutateAsync(body).catch(() => null);
    await result.current.mutateAsync(body);
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
  });
});

describe('#30 ④⑤ CSRF 白名单、Origin 校验与判定顺序（mock）', () => {
  it('白名单只有 POST /auth/login、POST /auth/register', () => {
    expect([...CSRF_WHITELIST]).toEqual(['POST /auth/login', 'POST /auth/register']);
  });
  it('未登录：login 不带 X-CSRF-Token 照常处理；带外站 Origin → 403 CSRF_FAILED', async () => {
    mockLoginAs(null);
    const ok = await fetch(`${API}/auth/login`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ username: 'demo_user', password: 'x'.repeat(12) }) });
    expect(ok.status).not.toBe(403);
    expect(ok.status).not.toBe(401);
    mockLoginAs(null);
    const bad = await fetch(`${API}/auth/login`, { method: 'POST', headers: { 'content-type': 'application/json', Origin: 'https://evil.example' }, body: JSON.stringify({ username: 'demo_user', password: 'x'.repeat(12) }) });
    expect(bad.status).toBe(403);
    expect(((await bad.json()) as Err).error.code).toBe('CSRF_FAILED');
  });
  it('注册关闭时 503 先于 Origin 校验', async () => {
    mockLoginAs(null);
    setRegistrationMode('closed');
    const r = await fetch(`${API}/auth/register`, { method: 'POST', headers: { 'content-type': 'application/json', Origin: 'https://evil.example' }, body: JSON.stringify({}) });
    expect(r.status).toBe(503);
  });
  it.each([
    ['POST', '/auth/logout'],
    ['POST', '/auth/password'],
    ['POST', '/plans'],
    ['PATCH', `/alerts/${ALERT_PLAN_COND}`],
    ['PUT', '/me/data-licence'],
  ])('无会话的写请求 %s %s → 401 AUTH_REQUIRED（含非法 JSON：请求体解析不先于认证）', async (method, path) => {
    mockLoginAs(null);
    for (const body of ['{}', '{not json']) {
      const r = await fetch(`${API}${path}`, { method, headers: { 'content-type': 'application/json' }, body });
      expect(r.status).toBe(401);
      expect(((await r.json()) as Err).error.code).toBe('AUTH_REQUIRED');
    }
  });
  it('已登录但不带 X-CSRF-Token：logout / password / 非法 JSON → 403 CSRF_FAILED', async () => {
    for (const [path, body] of [['/auth/logout', '{}'], ['/auth/password', '{}'], ['/plans', '{not json']]) {
      const r = await fetch(`${API}${path}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body });
      expect(r.status).toBe(403);
      expect(((await r.json()) as Err).error.code).toBe('CSRF_FAILED');
    }
  });
  it('非管理员访问 /admin/* → 404', async () => {
    const r = await apiFetch(`${API}/admin/users`);
    expect(r.status).toBe(404);
  });
  it('请求体超过上限 → 413，先于认证', async () => {
    mockLoginAs(null);
    const r = await fetch(`${API}/auth/logout`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: 'x'.repeat(25 * 1024 * 1024 + 16) });
    expect(r.status).toBe(413);
  }, 30_000);
});

describe('/auth/password mock（§7.1）', () => {
  it('204 + 轮换 csrf_token；旧密码错误 → 400 field=old_password；新密码不合规 → 400', async () => {
    const before = document.cookie;
    const ok = await json('POST', '/auth/password', { old_password: 'x'.repeat(12), new_password: `${'x'.repeat(10)}9` });
    expect(ok.status).toBe(204);
    expect(document.cookie).not.toBe(before);
    const bad = await json('POST', '/auth/password', { old_password: 'x', new_password: `${'x'.repeat(10)}9` });
    expect(bad.status).toBe(400);
    expect(((await bad.json()) as Err).error.details).toMatchObject({ field: 'old_password' });
    const weak = await json('POST', '/auth/password', { old_password: 'x'.repeat(12), new_password: 'x'.repeat(12) });
    expect(weak.status).toBe(400);
  });
});

describe('403 CSRF_FAILED → 顶部提示刷新页面', () => {
  it('任一请求得到 403 CSRF_FAILED 时显示提示与“刷新页面”按钮，可关闭', async () => {
    server.use(http.get(`${API}/plans`, () => HttpResponse.json({ error: { code: 'CSRF_FAILED', message: 'x', details: null, request_id: 'r' } }, { status: 403 })));
    renderAt('/plans');
    const bar = await screen.findByTestId('csrf-refresh');
    expect(bar).toHaveTextContent('请刷新页面');
    expect(within(bar).getByTestId('csrf-refresh-btn')).toBeInTheDocument();
  });
});

describe('#26 ⑤ 管理员暂停 / 恢复证书 → 通知证书所有者', () => {
  it('状态变化才发；只发给所有者；标题固定、target none、正文不含理由', async () => {
    const owner = uid(2);
    mockLoginAs('admin');
    const reason = '示例理由-不应出现在通知正文';
    expect((await json('POST', `/admin/data-licences/${owner}/pause`, { reason })).status).toBe(204);
    expect((await json('POST', `/admin/data-licences/${owner}/pause`, { reason })).status).toBe(204);
    const adminView = await getJ<Page<{ title: string }>>('/notifications?limit=100');
    expect(adminView.body.items.some((n) => n.title.startsWith('数据证书已被管理员'))).toBe(false);
    mockLoginAs('demo_user');
    const mine = await getJ<Page<{ title: string; body: string; kind: string; target: { type: string } }>>('/notifications?limit=100');
    const paused = mine.body.items.filter((n) => n.title === '数据证书已被管理员暂停');
    expect(paused).toHaveLength(1);
    expect(paused[0]).toMatchObject({ kind: 'data_licence', target: { type: 'none' } });
    expect(paused[0].body).not.toContain(reason);
    mockLoginAs('admin');
    expect((await json('POST', `/admin/data-licences/${owner}/resume`, { reason })).status).toBe(204);
    mockLoginAs('demo_user');
    const after = await getJ<Page<{ title: string }>>('/notifications?limit=100');
    expect(after.body.items.filter((n) => n.title === '数据证书已被管理员恢复')).toHaveLength(1);
  });
});

describe('§7.7B /plans（验收 6）', () => {
  it('默认列表只含 active、triggered；status=all 含已完成', async () => {
    const d = await getJ<Page<PlanSummary>>('/plans');
    expect(d.body.items.length).toBeGreaterThan(0);
    expect(d.body.items.every((p) => p.status === 'active' || p.status === 'triggered')).toBe(true);
    const all = await getJ<Page<PlanSummary>>('/plans?status=all');
    expect(all.body.items.some((p) => p.id === PLAN_DONE)).toBe(true);
  });
  it('candidate_id → 400 not_supported；指数 → 400 not_allowed', async () => {
    const r = await json('POST', '/plans', { ...PLAN_BODY, candidate_id: uid(8001) });
    expect(r.status).toBe(400);
    expect(((await r.json()) as Err).error.details).toEqual({ fields: [{ field: 'candidate_id', issue: 'not_supported' }] });
    const idx = await json('POST', '/plans', { ...PLAN_BODY, security_code: '000001.SH' });
    expect(idx.status).toBe(400);
  });
  it('重复（同证券、同动作、未结束）→ 409 CONFLICT{existing_id}；Idempotency-Key 重放返回同一结果', async () => {
    const key = { 'Idempotency-Key': 'k-demo-1' };
    const a = await json('POST', '/plans', PLAN_BODY, key);
    expect(a.status).toBe(201);
    const pa = (await a.json()) as Plan;
    const again = await json('POST', '/plans', PLAN_BODY, key);
    expect(again.status).toBe(201);
    expect(((await again.json()) as Plan).id).toBe(pa.id);
    const dup = await json('POST', '/plans', PLAN_BODY);
    expect(dup.status).toBe(409);
    expect(((await dup.json()) as Err).error).toMatchObject({ code: 'CONFLICT', details: { existing_id: pa.id } });
  });
  it('triggered 新建版本 → active；版本号不对 → VERSION_CONFLICT', async () => {
    const p = (await getJ<Plan>(`/plans/${PLAN_TRIGGERED}`)).body;
    expect(p.status).toBe('triggered');
    const body = { base_version_no: p.current_version_no, change_reason: '示例：调整计划条件', action: p.action, rationale: '示例', conditions: [] };
    const stale = await json('POST', `/plans/${PLAN_TRIGGERED}/versions`, { ...body, base_version_no: p.current_version_no - 1 });
    expect(stale.status).toBe(409);
    expect(((await stale.json()) as Err).error.code).toBe('VERSION_CONFLICT');
    const r = await json('POST', `/plans/${PLAN_TRIGGERED}/versions`, body);
    expect(r.status).toBe(201);
    expect((await r.json()) as Plan).toMatchObject({ status: 'active', current_version_no: p.current_version_no + 1 });
  });
  it('关闭已结束的计划、给已结束的计划建版本 → 409 INVALID_STATE_TRANSITION allowed=[]', async () => {
    expect((await json('POST', `/plans/${PLAN_ACTIVE}/close`, { status: 'cancelled' })).status).toBe(200);
    const again = await json('POST', `/plans/${PLAN_ACTIVE}/close`, { status: 'done' });
    expect(again.status).toBe(409);
    expect(((await again.json()) as Err).error).toMatchObject({ code: 'INVALID_STATE_TRANSITION', details: { allowed: [] } });
    const v = await json('POST', `/plans/${PLAN_ACTIVE}/versions`, { base_version_no: 1, change_reason: '示例', action: 'reduce', rationale: '示例' });
    expect(v.status).toBe(409);
    expect(((await v.json()) as Err).error.details).toMatchObject({ allowed: [] });
  });
  it.each(['PUT', 'PATCH', 'DELETE'])('%s /plans/{id} → 405', async (m) => {
    expect((await json(m, `/plans/${PLAN_ACTIVE}`, {})).status).toBe(405);
  });
});

describe('§7.7B /alerts（验收 7）', () => {
  it('默认只含 new、read；含 plan_condition 提醒；/today 的 alerts 不含它', async () => {
    const d = await getJ<Page<Alert>>('/alerts');
    expect(d.body.items.every((a) => a.status === 'new' || a.status === 'read')).toBe(true);
    expect(d.body.items.some((a) => a.id === ALERT_PLAN_COND && a.origin === 'plan_condition')).toBe(true);
    expect(d.body.items.some((a) => a.id === ALERT_DISMISSED)).toBe(false);
    const today = await getJ<{ alerts: { items: { id: string }[] } | { id: string }[] }>('/today');
    const ids = JSON.stringify(today.body.alerts);
    expect(ids).not.toContain(ALERT_PLAN_COND);
  });
  it('dismissed → read 409 allowed=[]；同状态 PATCH → 200；POST /alerts → 405', async () => {
    const r = await json('PATCH', `/alerts/${ALERT_DISMISSED}`, { status: 'read' });
    expect(r.status).toBe(409);
    expect(((await r.json()) as Err).error.details).toMatchObject({ allowed: [] });
    expect((await json('PATCH', `/alerts/${ALERT_DISMISSED}`, { status: 'dismissed' })).status).toBe(200);
    expect((await json('POST', '/alerts', {})).status).toBe(405);
  });
});

describe('枚举（验收 8；/meta/enums 由后端提供，mock 不拦截）', () => {
  it('前端枚举含 plan_status、plan_condition_type', async () => {
    expect(ENUMS.plan_status).toEqual(['active', 'triggered', 'done', 'cancelled']);
    expect(ENUMS.plan_condition_type.length).toBeGreaterThan(0);
    expect(ENUMS.plan_condition_type).toEqual(expect.arrayContaining(['price_above', 'price_below', 'pct_change', 'date', 'custom']));
  });
});

describe('计划页与提醒页（UI）', () => {
  it('/plans 列表 → 详情：待处理条件、当前版本、版本历史；关闭后显示终态说明', async () => {
    renderAt('/plans');
    fireEvent.click(await screen.findByTestId(`plan-link-${PLAN_TRIGGERED}`));
    expect(await screen.findByTestId('plan-pending')).toBeInTheDocument();
    expect(screen.getByTestId('plan-current')).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByTestId('plan-version-row').length).toBeGreaterThan(1));
  });
  it('已结束的计划：修改、关闭按钮不可用，并说明原因', async () => {
    renderAt(`/plans/${PLAN_DONE}`);
    expect(await screen.findByTestId('plan-terminal-note')).toBeInTheDocument();
    expect(screen.getByTestId('plan-edit-btn')).toBeDisabled();
    expect(screen.getByTestId('plan-close-btn')).toBeDisabled();
  });
  it('/alerts 列表默认不含已忽略；详情打开不改状态，显式“标为已读”才 PATCH', async () => {
    renderAt('/alerts');
    expect(await screen.findByTestId(`alert-link-${ALERT_PLAN_COND}`)).toBeInTheDocument();
    expect(screen.queryByTestId(`alert-link-${ALERT_DISMISSED}`)).toBeNull();
    fireEvent.click(screen.getByTestId(`alert-link-${ALERT_PLAN_COND}`));
    const st = await screen.findByTestId('alert-detail-status');
    expect(st).toHaveTextContent('未读');
    expect(screen.getByTestId('alert-plans')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('alert-to-read'));
    await waitFor(() => expect(screen.getByTestId('alert-detail-status')).toHaveTextContent('已读'));
  });
});
