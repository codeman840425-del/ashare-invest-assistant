/** T-F18 计划草案（契约 v0.2.8 §7.7） */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { ApiError } from '../api/client';
import { errorText } from '../api/errorPolicy';
import type { PlanDraft } from '../api/planTypes';
import { deviationFields, lotWarning, missingRequired, parseStatuses, priceError, qtyError } from '../lib/planDraft';
import { uid } from '../mocks/fixtures';
import { CHECKLIST, draftsNow } from '../mocks/planHandlers';
import { server } from '../mocks/server';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';
const post = (path: string, body: unknown) => fetch(`${API}${path}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

// 示例：uid 1012 待确认（买入 300001.SZ，来自信号 1011）、1022 待确认（做T先卖 002001.SZ）、7701 条件已变、7702 已过期、7703 已放弃
const PENDING = uid(1012);
const STALE = uid(7701);
const SIG_DRAFTED = uid(1011);
const SIG_BLOCKED = uid(1000);
const draftOf = (id: string) => draftsNow().find((d) => d.id === id)!;
const ALL_YES = CHECKLIST.filter((c) => c.required).map((c) => ({ id: c.id, answer: 'yes' }));
const okBody = (d: PlanDraft) => ({ checklist_answers: ALL_YES, risk_ack: true, chosen_qty: d.qty_range.min, chosen_price: d.price_range.low, deviation_ack: false });

describe('纯函数', () => {
  const d = () => draftOf(PENDING);
  it('status 参数多值解析，丢弃非法值', () => {
    expect(parseStatuses('pending,stale,bogus')).toEqual(['pending', 'stale']);
    expect(parseStatuses(null)).toEqual([]);
  });
  it('数量 / 价格校验与偏离字段', () => {
    expect(qtyError('')).toBe('请填写数量');
    expect(qtyError('1.5')).toBe('数量须为正整数');
    expect(priceError('1.2345')).toMatch(/3 位小数/);
    expect(deviationFields(d(), d().qty_range.min, d().price_range.low)).toEqual([]);
    const over = String(Number(d().qty_range.max) + 100);
    expect(deviationFields(d(), over, '0.01')).toEqual(['chosen_qty', 'chosen_price']);
    expect(deviationFields(d(), 'abc', d().price_range.high)).toEqual([]);
  });
  it('买入非整手提示；减仓不提示', () => {
    expect(lotWarning(d(), '150')).toMatch(/整数倍/);
    expect(lotWarning(d(), '200')).toBeNull();
    expect(lotWarning(draftOf(uid(1022)), '150')).toBeNull();
  });
  it('必答未作答', () => {
    expect(missingRequired(d(), {})).toEqual(['q_counter', 'q_fit', 'q_broker']);
    expect(missingRequired(d(), { q_counter: 'no', q_fit: 'unsure', q_broker: 'yes' })).toEqual([]);
  });
  it('错误码文案', () => {
    expect(errorText(new ApiError(409, 'PLAN_DRAFT_STALE', 'x', null, null))).toMatch(/重新生成/);
    expect(errorText(new ApiError(422, 'CHECKLIST_INCOMPLETE', 'x', null, null))).toMatch(/必答/);
    expect(errorText(new ApiError(409, 'SIGNAL_NOT_EXECUTABLE', 'x', null, null))).toMatch(/不可执行原因/);
  });
});

describe('mock 与契约 §7.7 一致', () => {
  it('列表：status 多值、signal_id 筛选，按 created_at 倒序', async () => {
    const r = await (await fetch(`${API}/plan-drafts?status=pending,stale`)).json();
    expect(r.items.map((x: PlanDraft) => x.status)).toEqual(['pending', 'stale', 'pending']);
    expect(r.next_cursor).toBeNull();
    const all = await (await fetch(`${API}/plan-drafts`)).json();
    expect(all.items).toHaveLength(5);
    const bySig = await (await fetch(`${API}/plan-drafts?signal_id=${SIG_DRAFTED}`)).json();
    expect(bySig.items.every((x: PlanDraft) => x.signal_ids.includes(SIG_DRAFTED))).toBe(true);
  });
  it('草案字段：金额为字符串，含清单、快照与费用认知类型', () => {
    const d = draftOf(PENDING);
    for (const v of [d.max_loss_amount, d.max_loss_pct, d.fee_estimate.amount, d.user_context_snapshot.cash, d.qty_range.min, d.price_range.low]) expect(typeof v).toBe('string');
    expect(d.fee_estimate.epistemic_type).toBe('estimate');
    expect(d.judgment_checklist.some((c) => c.required)).toBe(true);
  });
  it('生成：参数、状态、成功后信号关联新草案', async () => {
    expect((await post('/plan-drafts', { signal_ids: [] })).status).toBe(400);
    const blocked = await post('/plan-drafts', { signal_ids: [SIG_BLOCKED] });
    expect([blocked.status, (await blocked.json()).error.code]).toEqual([409, 'INVALID_STATE_TRANSITION']);
    const ok = await post('/plan-drafts', { signal_ids: [SIG_DRAFTED] });
    expect(ok.status).toBe(201);
    const d = (await ok.json()) as PlanDraft;
    expect([d.status, d.signal_ids]).toEqual(['pending', [SIG_DRAFTED]]);
    const cs = await (await fetch(`${API}/candidate-signals/${SIG_DRAFTED}`)).json();
    expect(cs.plan_draft_ids).toContain(d.id);
  });
  it('确认：清单 → 风险 → 偏离 → 成功；重复确认与失效草案报错', async () => {
    const d = draftOf(PENDING);
    const c = (body: unknown, id = PENDING) => post(`/plan-drafts/${id}/confirm`, body);
    let r = await c({ ...okBody(d), checklist_answers: ALL_YES.slice(1) });
    expect([r.status, (await r.json()).error.details]).toEqual([422, { missing: ['q_counter'] }]);
    r = await c({ ...okBody(d), risk_ack: false });
    expect((await r.json()).error.code).toBe('RISK_ACK_REQUIRED');
    r = await c({ ...okBody(d), chosen_qty: String(Number(d.qty_range.max) + 100) });
    expect([r.status, (await r.json()).error.details]).toEqual([422, { fields: ['chosen_qty'] }]);
    r = await c(okBody(draftOf(STALE)), STALE);
    expect([r.status, (await r.json()).error.code]).toEqual([409, 'PLAN_DRAFT_STALE']);
    r = await c({ ...okBody(d), chosen_qty: String(Number(d.qty_range.max) + 100), deviation_ack: true });
    expect(r.status).toBe(201);
    expect((await r.json()).plan_version_no).toBe(1);
    expect(draftOf(PENDING).status).toBe('confirmed');
    r = await c(okBody(d));
    expect([r.status, (await r.json()).error.code]).toEqual([409, 'INVALID_STATE_TRANSITION']);
  });
  it('放弃：pending → discarded；非 pending 报 409', async () => {
    const r = await post(`/plan-drafts/${PENDING}/discard`, { note: null });
    expect((await r.json()).status).toBe('discarded');
    expect((await post(`/plan-drafts/${STALE}/discard`, { note: null })).status).toBe(409);
  });
  it('/today 待确认草案取自草案当前状态（pending + stale）', async () => {
    const t = await (await fetch(`${API}/today`)).json();
    expect(t.pending_plan_drafts.items.map((x: { id: string }) => x.id).sort()).toEqual([PENDING, uid(1022), STALE].sort());
  });
});

describe('页面', () => {
  it('/plan-drafts?status=pending,stale 由真实页面接住，保留参数', async () => {
    const router = renderAt('/plan-drafts?status=pending,stale');
    await waitFor(() => expect(screen.getAllByTestId(/^draft-link-/)).toHaveLength(3));
    expect(screen.queryByTestId('placeholder')).toBeNull();
    expect(router.state.location.search).toBe('?status=pending,stale');
    expect(screen.getByTestId('card-disclaimer')).toBeInTheDocument();
  });

  it('确认：必答 + 风险确认后才能提交；偏离需再确认；二次确认后跳到计划页', async () => {
    const router = renderAt(`/plan-drafts/${PENDING}`);
    const btn = await screen.findByTestId('confirm-btn');
    expect(btn).toBeDisabled();
    expect(screen.getByTestId('confirm-blockers')).toHaveTextContent('3 项必答');
    for (const id of ['q_counter', 'q_fit', 'q_broker']) fireEvent.click(within(screen.getByTestId(`check-${id}`)).getByText('是'));
    fireEvent.click(screen.getByText(/我已了解：草案由规则自动生成/));
    await waitFor(() => expect(screen.getByTestId('confirm-btn')).toBeEnabled());
    const max = Number(draftOf(PENDING).qty_range.max);
    fireEvent.change(screen.getByTestId('chosen-qty'), { target: { value: String(max + 100) } });
    expect(await screen.findByTestId('deviation-alert')).toHaveTextContent('数量超出草案区间');
    expect(screen.getByTestId('confirm-btn')).toBeDisabled();
    fireEvent.click(screen.getByText(/我确认按偏离草案区间/));
    await waitFor(() => expect(screen.getByTestId('confirm-btn')).toBeEnabled());
    fireEvent.click(screen.getByTestId('confirm-btn'));
    expect(await screen.findByTestId('review-summary')).toHaveTextContent(String(max + 100));
    fireEvent.click(screen.getByTestId('review-ok'));
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/plans\//));
    expect(await screen.findByTestId('placeholder')).toBeInTheDocument();
    expect(draftOf(PENDING).status).toBe('confirmed');
  });

  it('“否 / 不确定”给出提示但不拦截', async () => {
    renderAt(`/plan-drafts/${PENDING}`);
    await screen.findByTestId('confirm-btn');
    fireEvent.click(within(screen.getByTestId('check-q_fit')).getByText('不确定'));
    expect(await screen.findByTestId('doubt-alert')).toHaveTextContent('1 项');
  });

  it('条件已变：不能确认，重新生成后跳到新草案，旧草案不变', async () => {
    const router = renderAt(`/plan-drafts/${STALE}`);
    expect(await screen.findByTestId('draft-stale')).toHaveTextContent('已失效');
    expect(screen.queryByTestId('confirm-form')).toBeNull();
    fireEvent.click(screen.getByTestId('regen-btn'));
    await waitFor(() => expect(router.state.location.pathname).not.toBe(`/plan-drafts/${STALE}`));
    const newId = router.state.location.pathname.split('/').pop()!;
    expect(draftOf(newId).status).toBe('pending');
    expect(draftOf(newId).signal_ids).toEqual(draftOf(STALE).signal_ids);
    expect(draftOf(STALE).status).toBe('stale');
    expect(await screen.findByTestId('confirm-form')).toBeInTheDocument();
  });

  it('放弃草案', async () => {
    renderAt(`/plan-drafts/${PENDING}`);
    fireEvent.click(await screen.findByTestId('discard-btn'));
    fireEvent.change(await screen.findByTestId('discard-note'), { target: { value: '示例：先观望' } });
    fireEvent.click(screen.getByTestId('discard-ok'));
    expect(await screen.findByTestId('draft-discarded')).toBeInTheDocument();
    expect(screen.getByTestId('draft-status')).toHaveTextContent('已放弃');
  });

  it('候选信号详情：可拟定状态下“拟定计划草案”可用，带 Idempotency-Key，生成后跳到草案', async () => {
    const keys: (string | null)[] = [];
    const onStart = ({ request }: { request: Request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname === `${API}/plan-drafts`) keys.push(request.headers.get('Idempotency-Key'));
    };
    server.events.on('request:start', onStart);
    try {
      const router = renderAt(`/candidate-signals/${SIG_DRAFTED}`);
      const btn = await screen.findByTestId('draft-btn');
      await waitFor(() => expect(btn).toBeEnabled());
      fireEvent.click(btn);
      await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/plan-drafts\//));
      expect(keys).toHaveLength(1);
      expect(keys[0]).toBeTruthy();
      expect(await screen.findByTestId('confirm-form')).toBeInTheDocument();
    } finally {
      server.events.removeListener('request:start', onStart);
    }
  });

  it('候选信号详情：被拦截的信号不能拟定', async () => {
    renderAt(`/candidate-signals/${SIG_BLOCKED}`);
    expect(await screen.findByTestId('draft-btn')).toBeDisabled();
  });
});
