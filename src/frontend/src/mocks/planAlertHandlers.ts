/**
 * T-F23 裁定跟进：操作计划与提醒（契约 v0.2.9 §7.7B，#30）的 MSW 处理器与会话内可变状态。
 * 示例数据全部虚构（标题、条件文字均为示例）；只陈述“发生了什么”，不含动作建议；不下单。
 * PUT/PATCH/DELETE /plans/{id}、POST /alerts 等不在这里声明，由 handlers.ts 兜底统一返回 405 + Allow。
 */
import { http, HttpResponse } from 'msw';
import { ENUMS } from '../api/enums';
import type { Action, AlertStatus, PlanConditionType, PlanStatus } from '../api/enums';
import type {
  Alert, Plan, PlanCondition, PlanConditionInput, PlanConditionParams, PlanPendingTrigger, PlanSummary, PlanVersion,
} from '../api/planAlertTypes';
import { ALERT_NEXT, WRITABLE_CONDITION_TYPES, isTerminalPlan } from '../api/planAlertTypes';
import type { Evidence, Stops } from '../api/types';
import { errorBody, notFound, page, validation } from './handlerUtils';
import { ACCOUNT_ID, uid } from './fixtures';
import { securityProfile } from './marketFixtures';
import { currentUser } from './session';
import { TODAY_EVIDENCE, todayAlerts } from './todayFixtures';

const API = '/api/v1';
const DEMO_UID = uid(2);

interface StoredPlan { owner: string; head: PlanSummary; versions: PlanVersion[]; pending: PlanPendingTrigger[]; evidence: Evidence[] }
interface StoredAlert { owner: string; alert: Alert }
interface Idem { body: string; status: number; json: unknown }

let plans: StoredPlan[] = [];
let alerts: StoredAlert[] = [];
let idem = new Map<string, Idem>();
let seq = 0;

type Field = { field: string; issue: string };
const fieldsError = (fields: Field[]) => HttpResponse.json(errorBody('VALIDATION_ERROR', '参数校验失败', { fields }), { status: 400 });
const conflict = (code: string, message: string, details: Record<string, unknown>) => HttpResponse.json(errorBody(code, message, details), { status: 409 });
const pad = (n: number) => String(n).padStart(2, '0');
/** 示例时间：从 10:50 起每次写入加 1 分钟（北京时间） */
function nextTime(): string {
  seq += 1;
  const m = 50 + seq;
  return `2026-11-02T${pad(10 + Math.floor(m / 60))}:${pad(m % 60)}:00+08:00`;
}
const evOf = (ids: string[]) => TODAY_EVIDENCE.filter((e) => ids.includes(e.id));
const cond = (n: number, kind: PlanCondition['kind'], type: PlanConditionType, params: PlanConditionParams, description: string): PlanCondition =>
  ({ id: uid(n), kind, type, params, description, epistemic_type: 'hypothesis' });
const STOPS = (stop_loss: string | null, take_profit: string | null, time_stop_days: number | null): Stops => ({ stop_loss, take_profit, time_stop_days });

function version(planId: string, no: number, action: Action, at: string, conditions: PlanCondition[], extra: Partial<PlanVersion> = {}): PlanVersion {
  return {
    plan_id: planId, version_no: no, action, qty: null, price: null, size_pct_of_assets: null, max_loss_amount: null, stops: null,
    rationale: '示例：计划依据（用户自填，示例文字）', risks: null, review_date: null, conditions, change_reason: no === 1 ? null : '示例：调整计划条件',
    checklist_answers: [], snapshot_id: null, created_at: at, ...extra,
  };
}

/** 示例计划（demo_user 名下）：1 个已触发（来自草案）、1 个已触发（失效条件，手工）、1 个进行中、1 个已完成 */
function seedPlans(): StoredPlan[] {
  const p1 = uid(7301), p2 = uid(7302), p3 = uid(7303), p4 = uid(7304);
  const head = (id: string, code: string, origin: PlanSummary['origin'], status: PlanStatus, action: Action, cur: number, created: string, triggered: string | null): PlanSummary => ({
    id, security_code: code, name: securityProfile(code)?.name ?? code, account_id: ACCOUNT_ID, origin, status, action, current_version_no: cur,
    plan_draft_id: origin === 'plan_draft' ? uid(7801) : null, candidate_id: null, triggered_at: triggered, created_at: created, updated_at: triggered ?? created,
  });
  return [
    {
      owner: DEMO_UID,
      head: head(p1, '000001.SZ', 'plan_draft', 'triggered', 'buy', 2, '2026-10-28T15:10:00+08:00', '2026-11-02T10:29:00+08:00'),
      versions: [
        version(p1, 2, 'buy', '2026-10-30T20:00:00+08:00', [
          cond(7311, 'trigger', 'price_below', { price: '23.20' }, '不复权最新价 ≤ 23.20（示例计划条件）'),
          cond(7313, 'invalidation', 'date', { on: '2026-11-20' }, '日期2026-11-20，非交易日顺延至其后首个交易日09:00（北京时间；示例计划条件）'),
        ], { qty: '200', price: '23.20', stops: STOPS('21.80', null, 20), review_date: '2026-11-20', change_reason: '示例：放宽计划条件价格',
          checklist_answers: [{ id: 'c1', question: '是否已核对可用资金？（示例）', answer: 'yes', note: null }] }),
        version(p1, 1, 'buy', '2026-10-28T15:10:00+08:00', [
          cond(7310, 'trigger', 'price_below', { price: '22.80' }, '不复权最新价 ≤ 22.80（示例计划条件）'),
        ], { qty: '200', price: '22.80', checklist_answers: [{ id: 'c1', question: '是否已核对可用资金？（示例）', answer: 'yes', note: null }] }),
      ],
      pending: [{ condition_id: uid(7311), condition_kind: 'trigger', condition_text: '不复权最新价 ≤ 23.20（计划条件已满足）', triggered_at: '2026-11-02T10:29:00+08:00', alert_id: null, evidence_ids: ['TE4'] }],
      evidence: evOf(['TE4']),
    },
    {
      owner: DEMO_UID,
      head: head(p2, '002001.SZ', 'manual', 'triggered', 'buy', 1, '2026-10-27T21:00:00+08:00', '2026-11-02T10:05:00+08:00'),
      versions: [version(p2, 1, 'buy', '2026-10-27T21:00:00+08:00', [
        cond(7314, 'trigger', 'pct_change', { pct: '-3.00' }, '当日跌幅达到 3%（示例计划条件）'),
        cond(7312, 'invalidation', 'price_below', { price: '12.50' }, '不复权最新价 ≤ 12.50 时该计划失效（示例）'),
      ], { risks: '示例：行业数据披露延迟' })],
      pending: [{ condition_id: uid(7312), condition_kind: 'invalidation', condition_text: '不复权最新价 ≤ 12.50 时该计划失效（失效条件已满足）', triggered_at: '2026-11-02T10:05:00+08:00', alert_id: uid(7199), evidence_ids: ['TE5'] }],
      evidence: evOf(['TE5']),
    },
    {
      owner: DEMO_UID,
      head: head(p3, '600000.SH', 'manual', 'active', 'reduce', 1, '2026-10-30T19:00:00+08:00', null),
      versions: [version(p3, 1, 'reduce', '2026-10-30T19:00:00+08:00', [
        cond(7315, 'trigger', 'price_above', { price: '11.00' }, '不复权最新价 ≥ 11.00（示例计划条件）'),
        cond(7316, 'trigger', 'custom', {}, '业绩预告披露后复核（示例，只作文字记录）'),
      ], { qty: '500', review_date: '2026-11-15' })],
      pending: [],
      evidence: [],
    },
    {
      owner: DEMO_UID,
      head: { ...head(p4, '300001.SZ', 'manual', 'done', 'buy', 1, '2026-10-20T20:00:00+08:00', null), updated_at: '2026-10-29T20:00:00+08:00' },
      versions: [version(p4, 1, 'buy', '2026-10-20T20:00:00+08:00', [])],
      pending: [],
      evidence: [],
    },
  ];
}

/** 示例提醒：/today 的 3 条 + 1 条 origin=plan_condition（只在 /alerts）+ 1 条已忽略（默认不显示） */
function seedAlerts(): StoredAlert[] {
  const base = todayAlerts().map((a): Alert => ({
    ...a, checklist: ['核对公告原文与发布时间（示例）', '确认是否影响相关计划条件（示例）'], snapshot_id: null, handled_at: a.status === 'read' ? '2026-11-02T10:31:00+08:00' : null,
    evidence: evOf(a.evidence_ids),
  }));
  const extra: Alert[] = [
    {
      id: uid(7199), rule_id: uid(7198), origin: 'plan_condition', severity: 'important', status: 'new', security_code: '002001.SZ', name: securityProfile('002001.SZ')?.name ?? '002001.SZ',
      title: '计划失效条件已满足：不复权最新价 ≤ 12.50（示例）', triggered_at: '2026-11-02T10:05:00+08:00', data_as_of: '2026-11-02T10:28:00+08:00',
      affected_plans: [{ plan_id: uid(7302), plan_version_no: 1, condition_id: uid(7312) }], evidence_ids: ['TE5'],
      checklist: ['核对行情数据时间（示例）'], snapshot_id: null, handled_at: null, evidence: evOf(['TE5']),
    },
    {
      id: uid(7105), rule_id: uid(7155), origin: 'user_custom', severity: 'info', status: 'dismissed', security_code: '600000.SH', name: securityProfile('600000.SH')?.name ?? '600000.SH',
      title: '示例银行价格到达自定义提醒价 9.80（示例）', triggered_at: '2026-10-30T14:00:00+08:00', data_as_of: '2026-10-30T14:00:00+08:00',
      affected_plans: [], evidence_ids: ['TE1'], checklist: [], snapshot_id: null, handled_at: '2026-10-30T15:00:00+08:00', evidence: evOf(['TE1']),
    },
  ];
  return [...base, ...extra].map((alert) => ({ owner: DEMO_UID, alert }));
}

export function resetPlansAlerts() {
  plans = seedPlans();
  alerts = seedAlerts();
  idem = new Map();
  seq = 0;
}
resetPlansAlerts();

const planOf = (s: StoredPlan): Plan => ({
  ...s.head, current_version: s.versions.find((v) => v.version_no === s.head.current_version_no)!, version_count: s.versions.length,
  pending_triggers: s.pending, evidence: s.evidence,
});
const mine = (id: string) => {
  const u = currentUser();
  return plans.find((p) => p.head.id === id && !!u && p.owner === u.id) ?? null;
};
const myAlert = (id: string) => {
  const u = currentUser();
  return alerts.find((a) => a.alert.id === id && !!u && a.owner === u.id) ?? null;
};

/** 计划草案确认（T-F18 mock）生成的计划也放进这里，详情页能打开 */
export function addPlanFromDraft(input: { id: string; security_code: string; name: string; account_id: string | null; action: Action; qty: string | null; price: string | null; plan_draft_id: string; answers: PlanVersion['checklist_answers'] }) {
  const u = currentUser();
  if (!u) return;
  const at = nextTime();
  plans.push({
    owner: u.id,
    head: { id: input.id, security_code: input.security_code, name: input.name, account_id: input.account_id, origin: 'plan_draft', status: 'active', action: input.action,
      current_version_no: 1, plan_draft_id: input.plan_draft_id, candidate_id: null, triggered_at: null, created_at: at, updated_at: at },
    versions: [version(input.id, 1, input.action, at, [], { qty: input.qty, price: input.price, checklist_answers: input.answers, rationale: '示例：由计划草案确认生成' })],
    pending: [], evidence: [],
  });
}

const isObj = (x: unknown): x is Record<string, unknown> => !!x && typeof x === 'object' && !Array.isArray(x);
const isDec = (x: unknown) => typeof x === 'string' && /^-?\d+(\.\d+)?$/.test(x);
const isDate = (x: unknown) => typeof x === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(x);
const optDec = (b: Record<string, unknown>, k: string, fields: Field[]) => {
  const v = b[k];
  if (v === undefined || v === null) return null;
  if (!isDec(v)) fields.push({ field: k, issue: 'invalid' });
  return v as string;
};

function paramsOk(type: PlanConditionType, p: unknown): boolean {
  if (!isObj(p)) return false;
  const keys = Object.keys(p);
  if (type === 'price_above' || type === 'price_below') return keys.length === 1 && isDec(p.price) && Number(p.price) > 0;
  if (type === 'pct_change') return keys.length === 1 && isDec(p.pct) && /[1-9]/.test(String(p.pct));
  if (type === 'date') {
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(Date.now());
    return keys.length === 1 && isDate(p.on) && String(p.on) >= today;
  }
  return keys.length === 0;
}

/** 请求体中 POST /plans 与新建版本共用的部分（整体替换：省略视为 null 或 []） */
function parseCommon(b: Record<string, unknown>, fields: Field[]) {
  const action = b.action;
  if (typeof action !== 'string' || !(ENUMS.action as readonly string[]).includes(action)) fields.push({ field: 'action', issue: 'invalid' });
  const rationale = b.rationale;
  if (typeof rationale !== 'string' || !rationale.trim() || rationale.length > 2000) fields.push({ field: 'rationale', issue: 'invalid' });
  const risks = b.risks ?? null;
  if (risks !== null && (typeof risks !== 'string' || risks.length > 2000)) fields.push({ field: 'risks', issue: 'invalid' });
  const review = b.review_date ?? null;
  if (review !== null && !isDate(review)) fields.push({ field: 'review_date', issue: 'invalid' });
  const qty = optDec(b, 'qty', fields);
  const price = optDec(b, 'price', fields);
  const size = optDec(b, 'size_pct_of_assets', fields);
  const maxLoss = optDec(b, 'max_loss_amount', fields);
  let stops: Stops | null = null;
  if (b.stops !== undefined && b.stops !== null) {
    const s = b.stops;
    if (!isObj(s)) fields.push({ field: 'stops', issue: 'invalid' });
    else stops = { stop_loss: (s.stop_loss as string | null) ?? null, take_profit: (s.take_profit as string | null) ?? null, time_stop_days: (s.time_stop_days as number | null) ?? null };
  }
  const raw = b.conditions ?? [];
  const conds: PlanConditionInput[] = [];
  if (!Array.isArray(raw) || raw.length > 20) fields.push({ field: 'conditions', issue: 'invalid' });
  else {
    raw.forEach((c: unknown, i) => {
      const f = `conditions[${i}]`;
      if (!isObj(c)) { fields.push({ field: f, issue: 'invalid' }); return; }
      if (typeof c.kind !== 'string' || !(ENUMS.plan_condition_kind as readonly string[]).includes(c.kind)) fields.push({ field: `${f}.kind`, issue: 'invalid' });
      const t = c.type;
      if (typeof t !== 'string' || !(ENUMS.plan_condition_type as readonly string[]).includes(t)) fields.push({ field: `${f}.type`, issue: 'invalid' });
      else if (!WRITABLE_CONDITION_TYPES.includes(t as PlanConditionType)) fields.push({ field: `${f}.type`, issue: 'not_supported' });
      else if (!paramsOk(t as PlanConditionType, c.params)) fields.push({ field: `${f}.params`, issue: 'invalid' });
      if (typeof c.description !== 'string' || !c.description.trim() || c.description.length > 200) fields.push({ field: `${f}.description`, issue: 'invalid' });
      conds.push(c as unknown as PlanConditionInput);
    });
  }
  return {
    action: action as Action, rationale: rationale as string, risks: risks as string | null, review_date: review as string | null,
    qty, price, size_pct_of_assets: size, max_loss_amount: maxLoss, stops, conds,
  };
}

const toConditions = (xs: PlanConditionInput[]): PlanCondition[] => xs.map((c) => {
  seq += 1;
  return { id: uid(7400 + seq), kind: c.kind, type: c.type, params: c.params, description: c.description, epistemic_type: 'hypothesis' };
});

/** Idempotency-Key：同键同体重放返回第一次的结果；同键异体 409 IDEMPOTENCY_CONFLICT */
function replay(scope: string, key: string | null, text: string) {
  if (!key) return null;
  const hit = idem.get(`${scope}|${key}`);
  if (!hit) return null;
  if (hit.body !== text) return conflict('IDEMPOTENCY_CONFLICT', '同一 Idempotency-Key 的请求体不同', {});
  return HttpResponse.json(hit.json as Record<string, unknown>, { status: hit.status });
}
function remember(scope: string, key: string | null, text: string, json: Plan) {
  if (key) idem.set(`${scope}|${key}`, { body: text, status: 201, json });
  return HttpResponse.json(json, { status: 201 });
}

function parseStatuses<T extends string>(raw: string | null, all: readonly string[], dflt: T[]): T[] | null | 'bad' {
  if (raw === 'all') return null;
  if (!raw) return dflt;
  const xs = raw.split(',').map((x) => x.trim()).filter(Boolean);
  if (!xs.length || xs.some((x) => !all.includes(x))) return 'bad';
  return xs as T[];
}

export const planAlertHandlers = [
  // ---- /plans ----
  http.get(`${API}/plans`, ({ request }) => {
    const url = new URL(request.url);
    const u = currentUser();
    const st = parseStatuses<PlanStatus>(url.searchParams.get('status'), ENUMS.plan_status, ['active', 'triggered']);
    if (st === 'bad') return validation('status', 'invalid');
    const origin = url.searchParams.get('origin');
    if (origin && !(ENUMS.plan_origin as readonly string[]).includes(origin)) return validation('origin', 'invalid');
    const code = url.searchParams.get('security_code');
    const acc = url.searchParams.get('account_id');
    const items = plans
      .filter((p) => !!u && p.owner === u.id)
      .filter((p) => (!st || st.includes(p.head.status)) && (!origin || p.head.origin === origin) && (!code || p.head.security_code === code) && (!acc || p.head.account_id === acc))
      .sort((x, y) => y.head.created_at.localeCompare(x.head.created_at) || y.head.id.localeCompare(x.head.id))
      .map((p) => p.head);
    return HttpResponse.json(page(items, url));
  }),

  http.post(`${API}/plans`, async ({ request }) => {
    const u = currentUser()!;
    const key = request.headers.get('Idempotency-Key');
    const text = await request.text();
    const again = replay(`${u.id}|create`, key, text);
    if (again) return again;
    let b: unknown;
    try { b = JSON.parse(text); } catch { return validation('body', 'invalid'); }
    if (!isObj(b)) return validation('body', 'invalid');
    const fields: Field[] = [];
    const code = typeof b.security_code === 'string' ? b.security_code.trim().toUpperCase() : '';
    const prof = code ? securityProfile(code) : null;
    if (!prof) fields.push({ field: 'security_code', issue: 'unknown_security' });
    else if (prof.type === 'index') fields.push({ field: 'security_code', issue: 'not_allowed' });
    const acc = b.account_id ?? null;
    if (acc !== null && typeof acc !== 'string') fields.push({ field: 'account_id', issue: 'invalid' });
    if (b.candidate_id !== undefined && b.candidate_id !== null) fields.push({ field: 'candidate_id', issue: 'not_supported' });
    const c = parseCommon(b, fields);
    if (fields.length) return fieldsError(fields);
    const dup = plans.find((p) => p.owner === u.id && p.head.security_code === code && p.head.action === c.action && !isTerminalPlan(p.head.status));
    if (dup) return conflict('CONFLICT', '同一证券已有相同动作的进行中计划', { field: 'security_code', existing_id: dup.head.id });
    seq += 1;
    const id = uid(7500 + seq);
    const at = nextTime();
    const s: StoredPlan = {
      owner: u.id,
      head: { id, security_code: code, name: prof!.name, account_id: acc as string | null, origin: 'manual', status: 'active', action: c.action, current_version_no: 1,
        plan_draft_id: null, candidate_id: null, triggered_at: null, created_at: at, updated_at: at },
      versions: [version(id, 1, c.action, at, toConditions(c.conds), {
        qty: c.qty, price: c.price, size_pct_of_assets: c.size_pct_of_assets, max_loss_amount: c.max_loss_amount, stops: c.stops,
        rationale: c.rationale, risks: c.risks, review_date: c.review_date, change_reason: null,
      })],
      pending: [], evidence: [],
    };
    plans.push(s);
    return remember(`${u.id}|create`, key, text, planOf(s));
  }),

  http.get(`${API}/plans/:id`, ({ params }) => {
    const s = mine(String(params.id));
    return s ? HttpResponse.json(planOf(s)) : notFound('计划');
  }),

  http.get(`${API}/plans/:id/versions`, ({ params, request }) => {
    const s = mine(String(params.id));
    if (!s) return notFound('计划');
    return HttpResponse.json(page([...s.versions].sort((x, y) => y.version_no - x.version_no), new URL(request.url)));
  }),

  http.get(`${API}/plans/:id/versions/:n`, ({ params }) => {
    const s = mine(String(params.id));
    const v = s?.versions.find((x) => String(x.version_no) === String(params.n));
    return v ? HttpResponse.json(v) : notFound('计划版本');
  }),

  http.post(`${API}/plans/:id/versions`, async ({ params, request }) => {
    const u = currentUser()!;
    const id = String(params.id);
    const key = request.headers.get('Idempotency-Key');
    const text = await request.text();
    const again = replay(`${u.id}|version|${id}`, key, text);
    if (again) return again;
    let b: unknown;
    try { b = JSON.parse(text); } catch { return validation('body', 'invalid'); }
    if (!isObj(b)) return validation('body', 'invalid');
    // ① 400
    const fields: Field[] = [];
    if (!Number.isInteger(b.base_version_no) || (b.base_version_no as number) < 1) fields.push({ field: 'base_version_no', issue: 'invalid' });
    if (typeof b.change_reason !== 'string' || !b.change_reason.trim() || b.change_reason.length > 200) fields.push({ field: 'change_reason', issue: 'invalid' });
    if (b.candidate_id !== undefined && b.candidate_id !== null) fields.push({ field: 'candidate_id', issue: 'not_supported' });
    const c = parseCommon(b, fields);
    const s = mine(id);
    // 不可改字段：带不同值 → not_allowed（需要找到计划才能比较；找不到时落到 404）
    if (s) {
      for (const k of ['security_code', 'account_id', 'origin'] as const) {
        if (k in b && b[k] !== s.head[k]) fields.push({ field: k, issue: 'not_allowed' });
      }
    }
    if (fields.length) return fieldsError(fields);
    // ② 404 → ③ 终态 → ④ 乐观锁
    if (!s) return notFound('计划');
    if (isTerminalPlan(s.head.status)) return conflict('INVALID_STATE_TRANSITION', '计划已结束，不能再修改', { from: s.head.status, to: s.head.status, allowed: [] });
    if (b.base_version_no !== s.head.current_version_no) return conflict('VERSION_CONFLICT', '计划已被修改，请刷新后重试', { current_version_no: s.head.current_version_no });
    const at = nextTime();
    const no = s.head.current_version_no + 1;
    s.versions.unshift(version(id, no, c.action, at, toConditions(c.conds), {
      qty: c.qty, price: c.price, size_pct_of_assets: c.size_pct_of_assets, max_loss_amount: c.max_loss_amount, stops: c.stops,
      rationale: c.rationale, risks: c.risks, review_date: c.review_date, change_reason: (b.change_reason as string).trim(),
    }));
    // triggered 时新建版本 → active，pending_triggers 清空（新版本的条件重新布防）
    s.head = { ...s.head, action: c.action, current_version_no: no, status: 'active', triggered_at: null, updated_at: at };
    s.pending = [];
    s.evidence = [];
    return remember(`${u.id}|version|${id}`, key, text, planOf(s));
  }),

  http.post(`${API}/plans/:id/close`, async ({ params, request }) => {
    let b: unknown;
    try { b = await request.json(); } catch { return validation('body', 'invalid'); }
    const fields: Field[] = [];
    if (!isObj(b) || (b.status !== 'done' && b.status !== 'cancelled')) fields.push({ field: 'status', issue: 'invalid' });
    const note = isObj(b) ? (b.note ?? null) : null;
    if (note !== null && (typeof note !== 'string' || note.length > 200)) fields.push({ field: 'note', issue: 'invalid' });
    if (fields.length) return fieldsError(fields);
    const s = mine(String(params.id));
    if (!s) return notFound('计划');
    const to = (b as { status: PlanStatus }).status;
    if (isTerminalPlan(s.head.status)) return conflict('INVALID_STATE_TRANSITION', '计划已结束', { from: s.head.status, to, allowed: [] });
    s.head = { ...s.head, status: to, updated_at: nextTime() };
    s.pending = [];
    return HttpResponse.json(planOf(s));
  }),

  // ---- /alerts ----
  http.get(`${API}/alerts`, ({ request }) => {
    const url = new URL(request.url);
    const u = currentUser();
    const st = parseStatuses<AlertStatus>(url.searchParams.get('status'), ENUMS.alert_status, ['new', 'read']);
    if (st === 'bad') return validation('status', 'invalid');
    const origin = url.searchParams.get('origin');
    if (origin && !(ENUMS.alert_origin as readonly string[]).includes(origin)) return validation('origin', 'invalid');
    const sev = url.searchParams.get('severity');
    if (sev && !(ENUMS.severity as readonly string[]).includes(sev)) return validation('severity', 'invalid');
    const code = url.searchParams.get('security_code');
    const planId = url.searchParams.get('plan_id');
    const items = alerts
      .filter((a) => !!u && a.owner === u.id)
      .map((a) => a.alert)
      .filter((a) => (!st || st.includes(a.status)) && (!origin || a.origin === origin) && (!sev || a.severity === sev) && (!code || a.security_code === code)
        // 契约未给 Alert 单独的 plan_id 字段：按 affected_plans[].plan_id 过滤（见报告“缺失的契约项”）
        && (!planId || a.affected_plans.some((p) => p.plan_id === planId)))
      .sort((x, y) => y.triggered_at.localeCompare(x.triggered_at) || y.id.localeCompare(x.id));
    return HttpResponse.json(page(items, url));
  }),

  http.get(`${API}/alerts/:id`, ({ params }) => {
    const a = myAlert(String(params.id));
    return a ? HttpResponse.json(a.alert) : notFound('提醒');
  }),

  http.patch(`${API}/alerts/:id`, async ({ params, request }) => {
    let b: unknown;
    try { b = await request.json(); } catch { return validation('body', 'invalid'); }
    const to = isObj(b) ? b.status : undefined;
    if (typeof to !== 'string' || !(ENUMS.alert_status as readonly string[]).includes(to)) return validation('status', 'invalid');
    const a = myAlert(String(params.id));
    if (!a) return notFound('提醒');
    const from = a.alert.status;
    if (to === from) return HttpResponse.json(a.alert);
    const allowed = ALERT_NEXT[from];
    if (!(allowed as string[]).includes(to)) return conflict('INVALID_STATE_TRANSITION', '提醒状态不能这样变更', { from, to, allowed });
    a.alert = { ...a.alert, status: to as AlertStatus, handled_at: nextTime() };
    return HttpResponse.json(a.alert);
  }),
];
