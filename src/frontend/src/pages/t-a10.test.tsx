/** T-A10 前端同步契约 v0.2.9（#1–#14、#26 中涉及前端的部分） */
import { render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { ApiError } from '../api/client';
import { CONTRACT_VERSION, ENUMS } from '../api/enums';
import type { NonExecutableReason, Portfolio } from '../api/types';
import { lotRuleOf, lotWarning } from '../lib/planDraft';
import { CANDIDATE_SIGNALS, PORTFOLIO, REASONS, uid } from '../mocks/fixtures';
import { CHECKLIST, draftsNow, lotRule } from '../mocks/planHandlers';
import { adminLicenceLog } from '../mocks/licenceStore';
import { mockLoginAs } from '../mocks/session';
import { server } from '../mocks/server';
import { STRATEGY_TEMPLATES } from '../mocks/strategyHandlers';

beforeAll(() => preloadRoutes(routes), 30_000);

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';
const get = async <T,>(path: string) => { const r = await fetch(`${API}${path}`); return { status: r.status, body: (await r.json()) as T }; };
const post = (path: string, body: unknown) => fetch(`${API}${path}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}
type Err = { error: { code: string; details: Record<string, unknown> } };
const BUY = uid(1000);
const REDUCE = uid(1003);
const SELL_T1 = uid(1016);
const PENDING = uid(1012);
const SELL_DRAFT = uid(1022);

describe('版本与枚举（/meta/enums）', () => {
  it('CONTRACT_VERSION = v0.2.9，新增 4 个枚举键', () => {
    expect(CONTRACT_VERSION).toBe('v0.2.9');
    expect(ENUMS.candidate_signal_event_cause).toEqual(['executability_check', 'reason_released', 'user', 'expiry', 'invalidation', 'supersede']);
    for (const k of ['research_candidate_status', 'research_candidate_origin', 'candidate_decision'] as const) expect(ENUMS[k].length).toBeGreaterThan(0);
  });
});

describe('#1–#3 持仓：无行情行 null、estimated、security_type', () => {
  it('mock：可转债行 pnl/pnl_pct/market_value 为 null（不是 0），estimated=true，security_type=null；顶层 partial', () => {
    const cb = PORTFOLIO.positions.find((p) => p.estimated)!;
    expect(cb).toMatchObject({ security_type: null, market_value: null, pnl: null, pnl_pct: null, estimated: true });
    expect(Number(cb.weight_pct)).toBeGreaterThan(0);
    expect(PORTFOLIO.positions.filter((p) => !p.estimated).every((p) => p.pnl !== null && p.security_type !== null)).toBe(true);
    expect(PORTFOLIO.data_status).toBe('partial');
  });
  it('估算标记看 estimated 字段，不看代码前缀', async () => {
    const stock = PORTFOLIO.positions.find((p) => !p.estimated)!;
    const cb = PORTFOLIO.positions.find((p) => p.estimated)!;
    const body: Portfolio = {
      ...PORTFOLIO,
      positions: PORTFOLIO.positions.map((p) =>
        p.security_code === stock.security_code ? { ...p, estimated: true, market_value: null, pnl: null, pnl_pct: null }
          : p.security_code === cb.security_code ? { ...p, estimated: false, security_type: 'stock', market_value: '1.00', pnl: '0.00', pnl_pct: '0.00' } : p),
    };
    server.use(http.get(`${API}/portfolio`, () => HttpResponse.json(body)));
    renderAt('/portfolio');
    expect(await screen.findByTestId(`cb-tag-${stock.security_code}`, undefined, { timeout: 5000 })).toHaveTextContent('无行情');
    expect(screen.getByTestId(`cb-tag-${stock.security_code}`)).not.toHaveTextContent('可转债');
    expect(screen.queryByTestId(`cb-tag-${cb.security_code}`)).toBeNull();
    // 示例数据横幅的契约版本跟随 CONTRACT_VERSION
    expect(screen.getByText(/按契约 v0\.2\.9 结构/)).toBeInTheDocument();
  });
});

describe('#6 候选信号事件：分页包装、6 个 cause、不返回 detail', () => {
  it('{items, next_cursor}，at desc；cause 只取枚举值；无 plan_confirmed 与 detail', async () => {
    for (const cs of CANDIDATE_SIGNALS) {
      const { status, body } = await get<{ items: Record<string, unknown>[]; next_cursor: string | null }>(`/candidate-signals/${cs.id}/events`);
      expect(status).toBe(200);
      expect(Array.isArray(body.items)).toBe(true);
      for (const e of body.items) {
        expect(ENUMS.candidate_signal_event_cause).toContain(e.cause);
        expect(e).not.toHaveProperty('detail');
        expect(typeof e.id).toBe('string');
      }
      const ats = body.items.map((e) => String(e.at));
      expect([...ats].sort().reverse()).toEqual(ats);
      expect(body.items.filter((e) => e.from === null)).toEqual([body.items.at(-1)]);
    }
  });
  it('详情页按页加载状态历史（加载更多）', async () => {
    const items = Array.from({ length: 3 }, (_, i) => ({ id: `ev-${i}`, from: i === 2 ? null : 'open', to: i === 2 ? 'open' : 'blocked', cause: 'executability_check', at: `2026-11-02T09:0${5 - i}:00+08:00` }));
    server.use(http.get(`${API}/candidate-signals/:id/events`, ({ request }) => {
      const c = new URL(request.url).searchParams.get('cursor');
      return HttpResponse.json(c ? { items: items.slice(2), next_cursor: null } : { items: items.slice(0, 2), next_cursor: 'p2' });
    }));
    renderAt(`/candidate-signals/${BUY}`);
    const pager = await screen.findByTestId('signal-events-pager', undefined, { timeout: 5000 });
    within(pager).getByRole('button').click();
    expect(await screen.findByTestId('signal-events-pager-end')).toHaveTextContent('3');
  });
});

describe('#7 列表冲突按 STRATEGY_CONFLICT 原因判断', () => {
  it('去掉冲突原因后列表不再标“方向冲突”', async () => {
    server.use(http.get(`${API}/non-executable-reasons`, () => HttpResponse.json({ items: [] })));
    renderAt('/candidate-signals');
    expect(await screen.findByTestId(`sig-link-${BUY}`, undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.queryByTestId(`conflict-${BUY}`)).toBeNull();
  });
  it('带 signal_ids 的请求带 code=STRATEGY_CONFLICT，每批 ≤ 100', async () => {
    const seen: URL[] = [];
    server.events.on('request:start', ({ request }) => { const u = new URL(request.url); if (u.pathname === `${API}/non-executable-reasons`) seen.push(u); });
    renderAt('/candidate-signals');
    await screen.findByTestId(`conflict-${BUY}`, undefined, { timeout: 5000 });
    server.events.removeAllListeners('request:start');
    const batch = seen.find((u) => u.searchParams.get('signal_ids'))!;
    expect(batch.searchParams.get('code')).toBe('STRATEGY_CONFLICT');
    expect(batch.searchParams.get('signal_ids')!.split(',').length).toBeLessThanOrEqual(100);
  });
});

describe('#8 / #12 不可执行原因：带证券、status 默认 active', () => {
  it('元素带 security_code、name，与所属信号一致', async () => {
    const { body } = await get<{ items: NonExecutableReason[] }>('/non-executable-reasons?status=all&limit=200');
    expect(body.items.length).toBeGreaterThan(0);
    for (const r of body.items) {
      const cs = CANDIDATE_SIGNALS.find((c) => c.id === r.signal_id)!;
      expect(r.security_code).toBe(cs.security_code);
      expect(r.name).toBe(cs.name);
    }
  });
  it('默认只返回 active；status=all 含已解除；带 signal_ids 同样默认 active；非法值 400', async () => {
    const ids = [...new Set(REASONS.map((r) => r.signal_id))].join(',');
    const def = await get<{ items: NonExecutableReason[] }>(`/non-executable-reasons?signal_ids=${ids}`);
    const all = await get<{ items: NonExecutableReason[] }>(`/non-executable-reasons?signal_ids=${ids}&status=all`);
    expect(def.body.items.every((r) => r.status === 'active')).toBe(true);
    expect(all.body.items.some((r) => r.status === 'released')).toBe(true);
    expect(all.body.items.length).toBe(REASONS.length);
    expect((await get('/non-executable-reasons?status=bogus')).status).toBe(400);
  });
  it('信号详情的“自动重评状态”请求带 status=all', async () => {
    const seen: URL[] = [];
    server.events.on('request:start', ({ request }) => { const u = new URL(request.url); if (u.pathname === `${API}/non-executable-reasons`) seen.push(u); });
    renderAt(`/candidate-signals/${BUY}`);
    await screen.findByTestId('signal-reasons', undefined, { timeout: 5000 });
    await waitFor(() => expect(seen.some((u) => u.searchParams.get('signal_ids') === BUY && u.searchParams.get('status') === 'all')).toBe(true));
    server.events.removeAllListeners('request:start');
  });
});

describe('#9 名单类原因不能手动解除', () => {
  const extra: NonExecutableReason[] = [];
  afterEach(() => { for (const r of extra.splice(0)) REASONS.splice(REASONS.indexOf(r), 1); });
  it('BLOCKLISTED / USER_MUTED → 409 REASON_NOT_MANUALLY_RELEASABLE（即使示例里 machine_checkable 写成 false）', async () => {
    const base = REASONS.find((r) => r.status === 'active' && !r.release_condition.machine_checkable)!;
    for (const [i, code] of (['BLOCKLISTED', 'USER_MUTED'] as const).entries()) {
      const r: NonExecutableReason = { ...base, id: uid(19990 + i), code };
      REASONS.push(r); extra.push(r);
      const res = await post(`/non-executable-reasons/${r.id}/release`, { confirm: true, note: null });
      expect(res.status).toBe(409);
      expect(((await res.json()) as Err).error.code).toBe('REASON_NOT_MANUALLY_RELEASABLE');
    }
  });
});

describe('#10 跟踪统计 scope', () => {
  it('默认 mine；site 可用；其他值 400 scope', async () => {
    const t = STRATEGY_TEMPLATES[0];
    const base = `/strategies/${t.id}/versions/${t.current_version.id}/tracking`;
    expect((await get(base)).status).toBe(200);
    expect((await get(`${base}?scope=site`)).status).toBe(200);
    const bad = await get<Err>(`${base}?scope=all`);
    expect(bad.status).toBe(400);
    expect(bad.body.error.details).toEqual({ fields: [{ field: 'scope', issue: expect.any(String) }] });
  });
});

describe('#11 放弃草案请求体 {}', () => {
  it('旧客户端带来的 note 被忽略，不报 400', async () => {
    const r = await post(`/plan-drafts/${PENDING}/discard`, { note: '示例' });
    expect(r.status).toBe(200);
    expect(draftsNow().find((d) => d.id === PENDING)!.status).toBe('discarded');
  });
});

describe('#13 多信号生成草案', () => {
  it('方向相反且带 STRATEGY_CONFLICT → 409 SIGNAL_NOT_EXECUTABLE{reason_ids}', async () => {
    const r = await post('/plan-drafts', { signal_ids: [BUY, REDUCE] });
    expect(r.status).toBe(409);
    const b = (await r.json()) as Err;
    expect(b.error.code).toBe('SIGNAL_NOT_EXECUTABLE');
    expect((b.error.details.reason_ids as string[]).length).toBeGreaterThan(0);
  });
  it('不同证券 → 400 VALIDATION_ERROR signal_ids', async () => {
    const a = CANDIDATE_SIGNALS.find((c) => c.id === BUY)!;
    const other = CANDIDATE_SIGNALS.find((c) => c.security_code !== a.security_code)!;
    const r = await post('/plan-drafts', { signal_ids: [BUY, other.id] });
    expect(r.status).toBe(400);
    expect(((await r.json()) as Err).error.details).toEqual({ fields: [{ field: 'signal_ids', issue: expect.any(String) }] });
    expect(SELL_T1).toBeTruthy();
  });
});

describe('#14 整手规则', () => {
  it('示例规则：科创板起买 200、递增 1；其他 100/100', () => {
    expect(lotRule('688001.SH')).toEqual({ min_buy: 200, step: 1 });
    expect(lotRule('600000.SH')).toEqual({ min_buy: 100, step: 100 });
  });
  it('确认时不符合整手 → 400 lot_rule{min_buy, step}，deviation_ack 不能绕过；前端能读出', async () => {
    const d = draftsNow().find((x) => x.id === PENDING)!;
    const answers = CHECKLIST.filter((c) => c.required).map((c) => ({ id: c.id, answer: 'yes' }));
    const r = await post(`/plan-drafts/${PENDING}/confirm`, { checklist_answers: answers, risk_ack: true, chosen_qty: '150', chosen_price: d.price_range.low, deviation_ack: true });
    expect(r.status).toBe(400);
    const b = (await r.json()) as Err;
    expect(b.error.details).toEqual({ fields: [{ field: 'chosen_qty', issue: 'lot_rule', min_buy: '100', step: '100' }] });
    expect(lotRuleOf(new ApiError(400, b.error.code, 'x', b.error.details, null))).toEqual({ min_buy: '100', step: '100' });
    // 契约写法 {field, issue, min_buy, step} 放在 details 顶层时同样能读出（待定项：二者哪种为准）
    expect(lotRuleOf(new ApiError(400, 'VALIDATION_ERROR', 'x', { field: 'chosen_qty', issue: 'lot_rule', min_buy: 200, step: 1 }, null))).toEqual({ min_buy: '200', step: '1' });
  });
  it('卖出一侧：超过可卖数量提示，不提示递增', () => {
    const d = draftsNow().find((x) => x.id === SELL_DRAFT)!;
    const sellable = Number(d.user_context_snapshot.sellable_qty);
    expect(lotWarning(d, String(sellable + 100))).toMatch(/不能超过可卖数量/);
    expect(lotWarning(d, String(sellable))).toBeNull();
  });
});

describe('#26① 管理端 resume 幂等', () => {
  it('未被暂停时 resume → 204，不写审计', async () => {
    mockLoginAs('admin');
    const n = adminLicenceLog.length;
    const r = await post(`/admin/data-licences/${uid(13)}/resume`, { reason: '示例：核对' });
    expect(r.status).toBe(204);
    expect(adminLicenceLog.length).toBe(n);
  });
});
