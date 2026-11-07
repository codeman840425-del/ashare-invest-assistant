/**
 * T-F18：计划草案（契约 v0.2.9 §7.7）的 mock。
 * 示例草案由已拟定草案的候选信号推出（数量、价格区间按示例持仓与资金估算，标“示例”）；
 * 会话内新建 / 确认 / 放弃写在 drafts 里，resetPlanDrafts()（resetMockState 调用）恢复初始状态。
 */
import { http, HttpResponse } from 'msw';
import type { CandidateSignal } from '../api/types';
import type { ChecklistItem, PlanDraft, PlanDraftConfirm } from '../api/planTypes';
import type { CandidateSignalState, PlanDraftStatus } from '../api/enums';
import { CANDIDATE_SIGNALS, NOW, PORTFOLIO, QUOTES, sectorOf, uid } from './fixtures';
import { errorBody, notFound, page, validation } from './handlerUtils';
import { addPlanFromDraft } from './planAlertHandlers';
import { patchSignal, reasonsNow, signalsNow, TERMINAL_SIGNAL_STATES } from './signalHandlers';

/** 契约 §4：allowed = 用户从 from 出发、经接口可到达的状态（按枚举顺序）；终态为 [] */
/** 评审 b23401a N7：blocked 可经手动解除原因（§6.0 POST /release）变为 released，所以是 ['released','dismissed'] */
export const signalAllowed = (st: CandidateSignalState): CandidateSignalState[] =>
  TERMINAL_SIGNAL_STATES.includes(st) ? [] : st === 'drafted' ? ['confirmed', 'dismissed'] : st === 'blocked' ? ['released', 'dismissed'] : ['dismissed'];

const API = '/api/v1';
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const fail = (status: number, code: string, message: string, details: Record<string, unknown> | null = null) =>
  HttpResponse.json(errorBody(code, message, details), { status });

export const CHECKLIST: ChecklistItem[] = [
  { id: 'q_counter', question: '我已阅读该规则信号的反证与失效条件', required: true },
  { id: 'q_fit', question: '这笔操作符合我自己的仓位与风险承受安排', required: true },
  { id: 'q_broker', question: '下单前我会在券商端核对实时价格、可用资金或可卖数量', required: true },
  { id: 'q_other', question: '有本工具未覆盖的信息（公告、个人资金安排等）影响我的判断', required: false },
];

const f2 = (n: number) => n.toFixed(2);
const SELL_SIDE = new Set(['sell', 'reduce']);
const BUY_SIDE = new Set(['buy', 'add']);
/** 示例整手规则（契约 v0.2.9 #14；实际取自草案 market_rule_version_id）：科创板起买 200、递增 1；主板、创业板、ETF 100/100 */
export const isStar = (code: string) => /^68[89]\d{3}\.SH$/.test(code);
export const lotRule = (code: string) => (isStar(code) ? { min_buy: 200, step: 1 } : { min_buy: 100, step: 100 });
/** 卖出一侧的“一手”（零股判断用；科创板按 200 处理，以交易所规则为准） */
const sellLot = (code: string) => (isStar(code) ? 200 : 100);

/** 由候选信号推出一份示例草案 */
function buildDraft(cs: CandidateSignal, id: string, status: PlanDraftStatus, created_at: string, valid_until: string | null): PlanDraft {
  const q = QUOTES.find((x) => x.security_code === cs.security_code);
  const px = Number(q?.price ?? 10);
  const pos = PORTFOLIO.positions.find((p) => p.security_code === cs.security_code);
  const holding = Number(pos?.qty ?? 0);
  const sellable = Number(pos?.sellable_qty ?? 0);
  const cash = Number(PORTFOLIO.cash);
  const total = Number(PORTFOLIO.total_assets);
  const rule = lotRule(cs.security_code);
  const lot = rule.step;
  const sellSide = SELL_SIDE.has(cs.proposed_action) || cs.t_leg === 'sell_first';
  const low = px * 0.99;
  const high = px * 1.01;
  const sl = sellLot(cs.security_code);
  let min = sellSide ? sl : rule.min_buy;
  let max: number;
  if (!sellSide) max = Math.max(rule.min_buy, Math.floor(Math.min(cash, total * 0.1) / high / lot) * lot);
  else if (cs.proposed_action === 'sell') min = max = Math.max(sellable, sl);
  else max = Math.max(sl, Math.floor(sellable / 2 / sl) * sl);
  if (min > max) min = max;
  const stop = cs.stops.stop_loss ? Number(cs.stops.stop_loss) : null;
  const loss = sellSide ? max * (high - low) : max * (stop !== null && stop < high ? high - stop : high * 0.08);
  const notional = max * high;
  const fee = Math.max(5, notional * 0.00025) + notional * 0.00001 + (sellSide ? notional * 0.0005 : 0);
  const sector = sectorOf(cs.security_code);
  const sectorPct = PORTFOLIO.exposure.sector.find((x) => x.name === sector)?.pct ?? '0.00';
  return {
    id, status, signal_ids: [cs.id], security_code: cs.security_code, name: cs.name, action: cs.proposed_action,
    qty_range: { min: String(min), max: String(max), lot: String(lot) },
    price_range: { low: f2(low), high: f2(high) },
    stops: cs.stops,
    max_loss_amount: f2(loss), max_loss_pct: f2((loss / total) * 100),
    fee_estimate: { amount: f2(fee), epistemic_type: 'estimate' },
    user_context_snapshot: { holding_qty: String(holding), sellable_qty: String(sellable), cash: f2(cash), sector_pct: sectorPct },
    risk_flags: cs.risk_flags,
    judgment_checklist: CHECKLIST,
    valid_until, market_rule_version_id: uid(7690), created_at,
  };
}

const sig = (n: number) => CANDIDATE_SIGNALS.find((c) => c.id === uid(n))!;
const VALID = '2026-11-02T15:00:00+08:00';
function initial(): PlanDraft[] {
  return [
    buildDraft(sig(1011), uid(1012), 'pending', '2026-11-02T10:12:30+08:00', VALID),
    buildDraft(sig(1021), uid(1022), 'pending', '2026-11-02T09:31:00+08:00', VALID),
    // 早先为同一信号生成、之后行情变化而失效的草案：演示“重新生成”
    buildDraft(sig(1011), uid(7701), 'stale', '2026-11-02T09:45:00+08:00', VALID),
    buildDraft(sig(1011), uid(7702), 'expired', '2026-10-30T10:05:00+08:00', '2026-10-30T15:00:00+08:00'),
    buildDraft(sig(1021), uid(7703), 'discarded', '2026-10-30T09:40:00+08:00', '2026-10-30T15:00:00+08:00'),
  ];
}

let drafts: PlanDraft[] = initial();
let seq = 0;
export function resetPlanDrafts() {
  drafts = initial();
  seq = 0;
}
export const draftsNow = (): PlanDraft[] => drafts;
/** 测试辅助：改某份草案的状态（例如把待确认改成 stale） */
export function mockSetDraftStatus(id: string, status: PlanDraftStatus) {
  drafts = drafts.map((d) => (d.id === id ? { ...d, status } : d));
}

const EXPLAINABLE_ROLES = new Set(['entry', 'exit', 'weakening']);

export const planHandlers = [
  http.get(`${API}/plan-drafts`, ({ request }) => {
    const url = new URL(request.url);
    const statuses = (url.searchParams.get('status') ?? '').split(',').filter(Boolean);
    const code = url.searchParams.get('security_code');
    const sid = url.searchParams.get('signal_id');
    const items = drafts
      .filter((d) => (!statuses.length || statuses.includes(d.status)) && (!code || d.security_code === code) && (!sid || d.signal_ids.includes(sid)))
      .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id));
    return HttpResponse.json(page(items, url));
  }),

  http.get(`${API}/plan-drafts/:id`, ({ params }) => {
    const d = drafts.find((x) => x.id === params.id);
    return d ? HttpResponse.json(d) : notFound('计划草案');
  }),

  http.post(`${API}/plan-drafts`, async ({ request }) => {
    // 契约 v0.2.9 #37（§7.7 完整判定顺序）：每一步对全部信号检查完再进入下一步，返回第一个不通过的步骤
    const body = (await request.json().catch(() => null)) as { signal_ids?: unknown } | null;
    const raw = body?.signal_ids;
    // ① 格式：非空 uuid 数组
    if (!Array.isArray(raw) || !raw.length || !raw.every((x) => typeof x === 'string' && UUID_RE.test(x))) {
      return validation('signal_ids', 'signal_ids 须为非空 uuid 数组');
    }
    const ids = raw as string[];
    const all = signalsNow();
    const list = ids.map((id) => all.find((c) => c.id === id));
    // ② 不存在或不属于本人 → 400 not_found（不返回 404，不区分两种情况）
    if (list.some((c) => !c)) {
      return HttpResponse.json(errorBody('VALIDATION_ERROR', '候选信号不存在', { fields: [{ field: 'signal_ids', issue: 'not_found' }] }), { status: 400 });
    }
    const css = list as CandidateSignal[];
    // ③ 同一证券、同一 proposed_action、同一 t_leg
    const same = (k: (c: CandidateSignal) => unknown) => new Set(css.map(k)).size === 1;
    if (!same((c) => c.security_code) || !same((c) => c.proposed_action) || !same((c) => c.t_leg)) {
      return validation('signal_ids', '多个信号须属于同一证券、同一动作（有 t_leg 时 t_leg 也相同）');
    }
    // ④ simulating 模板
    const sim = css.find((c) => c.lifecycle === 'simulating');
    if (sim) return fail(409, 'STRATEGY_VERSION_NOT_RUNNABLE', '模拟期策略不能拟定计划草案', { lifecycle: sim.lifecycle });
    // ⑤ 终态 → INVALID_STATE_TRANSITION，allowed=[]
    const term = css.find((c) => TERMINAL_SIGNAL_STATES.includes(c.state));
    if (term) return fail(409, 'INVALID_STATE_TRANSITION', `候选信号状态为 ${term.state}，不能拟定计划草案`, { from: term.state, to: 'drafted', allowed: [] });
    // ⑥ blocked 或仍有 active 原因（不论原因码）→ SIGNAL_NOT_EXECUTABLE，reason_ids 去重后按 id 升序
    const activeR = reasonsNow().filter((r) => ids.includes(r.signal_id) && r.status === 'active');
    if (activeR.length || css.some((c) => c.state === 'blocked')) {
      const reasonIds = [...new Set(activeR.map((r) => r.id))].sort();
      return fail(409, 'SIGNAL_NOT_EXECUTABLE', '信号存在未解除的不可执行原因', { reason_ids: reasonIds });
    }
    // ⑦ 没有可解释的规则引用 → 422；open、released、drafted 均可拟定（drafted 即重新生成）
    const unexplained = css.find((c) => !c.rule_refs.some((r) => EXPLAINABLE_ROLES.has(r.role) && r.passed === true));
    if (unexplained) return fail(422, 'PLAN_REQUIRES_EXPLAINABLE_SIGNAL', '信号缺少可解释的规则依据');
    seq += 1;
    const d = buildDraft(css[0], uid(7800 + seq), 'pending', NOW, VALID);
    d.signal_ids = ids;
    drafts = [d, ...drafts];
    for (const c of css) patchSignal(c.id, { state: 'drafted', plan_draft_ids: [...c.plan_draft_ids, d.id] });
    return HttpResponse.json(d, { status: 201 });
  }),

  http.post(`${API}/plan-drafts/:id/confirm`, async ({ params, request }) => {
    const d = drafts.find((x) => x.id === params.id);
    if (!d) return notFound('计划草案');
    if (d.status === 'stale' || d.status === 'expired') return fail(409, 'PLAN_DRAFT_STALE', '草案已失效，请重新生成', { status: d.status });
    if (d.status !== 'pending') return fail(409, 'INVALID_STATE_TRANSITION', `草案状态为 ${d.status}，不能确认`, { from: d.status, to: 'confirmed', allowed: [] });
    const b = (await request.json().catch(() => ({}))) as Partial<PlanDraftConfirm>;
    const answers = Array.isArray(b.checklist_answers) ? b.checklist_answers : [];
    const missing = d.judgment_checklist.filter((c) => c.required && !answers.some((a) => a.id === c.id && ['yes', 'no', 'unsure'].includes(a.answer))).map((c) => c.id);
    if (missing.length) return fail(422, 'CHECKLIST_INCOMPLETE', '判断清单有必答项未作答', { missing });
    if (b.risk_ack !== true) return fail(422, 'RISK_ACK_REQUIRED', '请确认已了解风险');
    const qty = Number(b.chosen_qty);
    const price = Number(b.chosen_price);
    if (!Number.isFinite(qty) || qty <= 0) return validation('chosen_qty', '数量须为正数');
    if (!Number.isFinite(price) || price <= 0) return validation('chosen_price', '价格须为正数');
    const fields: string[] = [];
    if (qty < Number(d.qty_range.min) || qty > Number(d.qty_range.max)) fields.push('chosen_qty');
    if (price < Number(d.price_range.low) || price > Number(d.price_range.high)) fields.push('chosen_price');
    // v0.2.9 #14：整手校验，deviation_ack 不能绕过
    const rule = lotRule(d.security_code);
    const sellable = Number(d.user_context_snapshot.sellable_qty);
    const lotBad = BUY_SIDE.has(d.action)
      ? qty < rule.min_buy || qty % rule.step !== 0 || !Number.isInteger(qty)
      : SELL_SIDE.has(d.action)
        // v0.2.9 #30 ③ 卖出零股公式：卖全部可卖余量，或 数量 ≥ min_buy 且 (数量 − min_buy) 是 step 的整数倍
        ? qty > sellable || (qty !== sellable && (qty < rule.min_buy || (qty - rule.min_buy) % rule.step !== 0 || !Number.isInteger(qty)))
        : false;
    if (lotBad) {
      return fail(400, 'VALIDATION_ERROR', '数量不符合整手规则', {
        fields: [{ field: 'chosen_qty', issue: 'lot_rule', min_buy: String(rule.min_buy), step: String(rule.step) }],
      });
    }
    if (fields.length && b.deviation_ack !== true) return fail(422, 'DEVIATION_ACK_REQUIRED', '数量或价格超出草案区间，需要确认', { fields });
    seq += 1;
    drafts = drafts.map((x) => (x.id === d.id ? { ...x, status: 'confirmed' } : x));
    for (const id of d.signal_ids) patchSignal(id, { state: 'confirmed' });
    const planId = uid(7900 + seq);
    // T-F23 裁定跟进：确认生成的计划进入 /plans 示例存储，计划详情页可打开（§7.7B origin=plan_draft）
    addPlanFromDraft({
      id: planId, security_code: d.security_code, name: d.name, account_id: null, action: d.action, qty: String(qty), price: String(price), plan_draft_id: d.id,
      answers: answers.map((a) => ({ id: a.id, question: d.judgment_checklist.find((c) => c.id === a.id)?.question ?? a.id, answer: a.answer, note: a.note ?? null })),
    });
    return HttpResponse.json({ plan_id: planId, plan_version_no: 1 }, { status: 201 });
  }),

  http.post(`${API}/plan-drafts/:id/discard`, async ({ params, request }) => {
    const d = drafts.find((x) => x.id === params.id);
    if (!d) return notFound('计划草案');
    if (d.status !== 'pending') return fail(409, 'INVALID_STATE_TRANSITION', `草案状态为 ${d.status}，不能放弃`, { from: d.status, to: 'discarded', allowed: [] });
    await request.json().catch(() => null); // v0.2.9 #11：请求体 {}；旧客户端带来的 note 一律忽略，不报 400、不保存
    const next: PlanDraft = { ...d, status: 'discarded' };
    drafts = drafts.map((x) => (x.id === d.id ? next : x));
    return HttpResponse.json(next);
  }),
];
