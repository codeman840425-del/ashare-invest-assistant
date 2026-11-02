/**
 * T-F23 研究候选（契约 v0.2.9 §7.7A，T-A11）的 MSW 处理器与会话内可变状态。
 * 示例数据全部虚构；resetCandidates() 在每个测试后恢复初始状态。
 * 校验顺序按 §7.7A：请求体 → 证券 → 来源建议 → 重复；新建版本：请求体 → 本人 → 终态 → 乐观锁。
 */
import { http, HttpResponse } from 'msw';
import { ENUMS } from '../api/enums';
import type { CandidateDecision, ResearchCandidateStatus } from '../api/enums';
import type {
  CandidateCondition, CandidateConditionInput, CandidateFact, CandidateVersion, FitAssessment, ResearchCandidate, ResearchCandidateSummary,
} from '../api/candidateTypes';
import type { Evidence, Gap, TextWithEvidence } from '../api/types';
import { SECURITY_RISK_FLAG, LISTING_STATUS } from '../i18n/labels';
import { LICENCE_UNAVAILABLE } from '../i18n/licenceLabels';
import { errorBody, notFound, page, validation } from './handlerUtils';
import { NOW, PORTFOLIO, SUGGESTIONS, suggestionOf, uid } from './fixtures';
import { securityProfile } from './marketFixtures';
import { currentUser, state as session } from './session';
import { licenceState } from './licenceStore';

const API = '/api/v1';
const DEMO_UID = uid(2);

interface Stored { owner: string; head: Omit<ResearchCandidate, 'current_version' | 'version_count'>; versions: CandidateVersion[] }
interface Idem { body: string; status: number; json: unknown }

let store: Stored[] = [];
let idem = new Map<string, Idem>();
let seq = 0;

type Field = { field: string; issue: string };
const fieldsError = (fields: Field[]) => HttpResponse.json(errorBody('VALIDATION_ERROR', '参数校验失败', { fields }), { status: 400 });
const conflict = (code: string, message: string, details: Record<string, unknown>) => HttpResponse.json(errorBody(code, message, details), { status: 409 });

const pad = (n: number) => String(n).padStart(2, '0');
/** 示例时间：从 10:40 起每次写入加 1 分钟（北京时间） */
function nextTime(): string {
  seq += 1;
  const m = 40 + seq;
  return `2026-11-02T${pad(10 + Math.floor(m / 60))}:${pad(m % 60)}:00+08:00`;
}
const candId = (n: number) => `c0a1e000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const verId = (n: number) => `c0a1e000-0000-4000-9000-${String(n).padStart(12, '0')}`;

const decisionStatus: Record<CandidateDecision, ResearchCandidateStatus> = { continue: 'researching', watch: 'watching', drop: 'dropped' };
const TERMINAL: ResearchCandidateStatus[] = ['dropped', 'planned'];
const ACTIVE: ResearchCandidateStatus[] = ['researching', 'watching'];

/** 系统生成：建议来源照抄各策略结论的 reasons / counter_evidence 与 risk_flags；其余只列证券风险因子 */
function systemContent(code: string, suggestionId: string | null): { reasons: CandidateFact[]; counter: CandidateFact[]; evidence: Evidence[] } {
  // 多个策略可能给出同一条理由 / 反证：按文字与表达式去重
  const uniq = (xs: CandidateFact[]) => xs.filter((x, i) => xs.findIndex((y) => y.text === x.text && y.expr === x.expr) === i);
  const fact = (t: TextWithEvidence): CandidateFact => ({ text: t.text, expr: t.expr, evidence_ids: [...t.evidence_ids], epistemic_type: 'fact', source_kind: 'system_calc' });
  if (suggestionId) {
    const sg = SUGGESTIONS.find((s) => s.id === suggestionId)!;
    const reasons = uniq(sg.strategies.flatMap((s) => s.reasons).map(fact));
    const counter = uniq([
      ...sg.strategies.flatMap((s) => s.counter_evidence).map(fact),
      ...sg.risk_flags.map((f): CandidateFact => ({ text: f.message, expr: null, evidence_ids: [...f.evidence_ids], epistemic_type: 'fact', source_kind: 'system_calc' })),
    ]);
    const used = new Set([...reasons, ...counter].flatMap((x) => x.evidence_ids));
    return { reasons, counter, evidence: sg.evidence.filter((e) => used.has(e.id)).map((e) => ({ ...e })) };
  }
  const p = securityProfile(code)!;
  const counter: CandidateFact[] = [];
  const risk = (text: string): CandidateFact => ({ text, expr: null, evidence_ids: [], epistemic_type: 'fact', source_kind: 'market_data' });
  if (p.risk_flag) counter.push(risk(`证券带风险标记：${SECURITY_RISK_FLAG[p.risk_flag]}（示例）`));
  if (p.suspended) counter.push(risk('该证券当前停牌（示例）'));
  if (p.listing_status === 'delisting_period') counter.push(risk(`证券处于${LISTING_STATUS.delisting_period}（示例）`));
  return { reasons: [], counter, evidence: [] };
}

/** 只读本人画像与本人持仓（示例：持仓只属于 demo_user）；画像类提示 hints 本 mock 不复刻 /horizon-assessments 规则，恒为 [] */
function fitOf(owner: string, code: string): FitAssessment {
  const profile = session.profiles.get(owner);
  const holdings = owner === DEMO_UID;
  const pos = holdings ? PORTFOLIO.positions.find((p) => p.security_code === code) : undefined;
  const warnings: TextWithEvidence[] = pos && profile?.max_single_position_pct
    ? [{ text: `你已持有该证券，仓位占比 ${pos.weight_pct}%，对照你的单票上限 ${profile.max_single_position_pct}%（RC2，示例）`, expr: null, evidence_ids: [] }]
    : [];
  return { profile_filled: !!profile, holdings_available: holdings, hints: [], warnings };
}

/** 数据时间取版本创建时刻（不晚于示例“现在”），回看旧版本不显示之后的数据时间 */
function dataBlock(owner: string, at: string): { data_status: 'fresh' | 'stale'; data_as_of: string; gaps: Gap[] } {
  const asOf = at < NOW ? at : NOW;
  if (LICENCE_UNAVAILABLE.includes(licenceState(owner))) {
    return { data_status: 'stale', data_as_of: asOf, gaps: [{ key: 'candidate', reason: 'data_licence_unavailable', message: '你的数据证书不可用，内容按缓存生成（示例）' }] };
  }
  return { data_status: 'fresh', data_as_of: asOf, gaps: [] };
}

const toConditions = (xs: CandidateConditionInput[]): CandidateCondition[] => xs.map((c) => ({
  text: c.text.trim(), verify_by: c.verify_by || null, verify_method: c.verify_method?.trim() || null, confidence: c.confidence ?? null, epistemic_type: 'hypothesis',
}));

function makeVersion(s: Stored, vn: number, at: string, thesis: string | null, conds: CandidateConditionInput[], decision: CandidateDecision | null, reason: string | null): CandidateVersion {
  const sys = systemContent(s.head.security_code, s.head.suggestion_id);
  return {
    id: verId(Number(s.head.id.slice(-12)) * 100 + vn), candidate_id: s.head.id, version_no: vn, security_code: s.head.security_code, name: s.head.name,
    thesis, reasons: sys.reasons, conditions_to_hold: toConditions(conds), counter_evidence: sys.counter, fit_assessment: fitOf(s.owner, s.head.security_code),
    decision, decision_reason: reason, snapshot_id: `snap-cand-${s.head.id.slice(-4)}-v${vn}`, evidence: sys.evidence, ...dataBlock(s.owner, at), created_at: at,
  };
}

const full = (s: Stored): ResearchCandidate => ({ ...s.head, version_count: s.versions.length, current_version: s.versions[s.versions.length - 1] });
const summary = (s: Stored): ResearchCandidateSummary => {
  const v = s.versions[s.versions.length - 1];
  return {
    id: s.head.id, security_code: s.head.security_code, name: s.head.name, origin: s.head.origin, status: s.head.status, suggestion_id: s.head.suggestion_id,
    current_version_no: v.version_no, decision: v.decision, last_version_at: v.created_at, created_at: s.head.created_at,
  };
};

function seed(n: number, owner: string, code: string, origin: Stored['head']['origin'], created: string): Stored {
  const p = securityProfile(code)!;
  const s: Stored = {
    owner,
    head: {
      id: candId(n), security_code: code, name: p.name, security_type: p.type, origin, strategy_run_id: null,
      suggestion_id: origin === 'suggestion' ? suggestionOf(code)!.id : null, status: 'researching', plan_ids: [], created_at: created,
    },
    versions: [],
  };
  return s;
}

export function resetCandidates() {
  seq = 0;
  idem = new Map();
  const a = seed(1, DEMO_UID, '600000.SH', 'suggestion', '2026-10-28T20:10:00+08:00');
  a.versions.push(makeVersion(a, 1, a.head.created_at, '示例：关注净息差企稳后的估值修复（示例）', [
    { text: '三季报净息差环比不再下降（示例）', verify_by: '2026-11-15', verify_method: null, confidence: 'medium' },
  ], null, null));
  a.versions.push(makeVersion(a, 2, '2026-10-30T21:05:00+08:00', '示例：关注净息差企稳后的估值修复（示例）', [
    { text: '三季报净息差环比不再下降（示例）', verify_by: '2026-11-15', verify_method: null, confidence: 'medium' },
    { text: '分红方案维持往年比例（示例）', verify_by: null, verify_method: '查看年报分红预案（示例）', confidence: 'low' },
  ], 'watch', '等待三季报数据再判断（示例）'));
  a.head.status = 'watching';
  const b = seed(2, DEMO_UID, '830001.BJ', 'from_stock', '2026-10-31T19:30:00+08:00');
  b.versions.push(makeVersion(b, 1, b.head.created_at, null, [], null, null));
  const c = seed(3, DEMO_UID, '600002.SH', 'manual', '2026-10-20T20:00:00+08:00');
  c.versions.push(makeVersion(c, 1, c.head.created_at, '示例：集采后的盈利恢复（示例）', [], null, null));
  c.versions.push(makeVersion(c, 2, '2026-10-26T20:00:00+08:00', '示例：集采后的盈利恢复（示例）', [], 'drop', '研究后认为假设不成立（示例）'));
  c.head.status = 'dropped';
  // 他人的候选：本人任何接口都看不到（404 / 列表不含）
  const d = seed(4, uid(3), '000001.SZ', 'manual', '2026-10-29T10:00:00+08:00');
  d.versions.push(makeVersion(d, 1, d.head.created_at, '他人的研究内容（示例）', [], null, null));
  // 已计划（planned）示例：契约 §7.7A 本版实际不会出现 planned，此条只为演示前端显示，属于管理员示例账户，不影响 demo_user 数据
  const e = seed(5, uid(3), '300001.SZ', 'manual', '2026-10-22T20:00:00+08:00');
  e.versions.push(makeVersion(e, 1, e.head.created_at, '示例：订单回暖后的产能利用率（示例）', [], null, null));
  e.head.status = 'planned';
  store = [a, b, c, d, e];
}
resetCandidates();

/** 测试与截图用：读当前状态 */
export const candidatesNow = () => store;

const mine = (id: string) => {
  const u = currentUser();
  return store.find((s) => s.head.id === id && !!u && s.owner === u.id);
};

const isObj = (x: unknown): x is Record<string, unknown> => typeof x === 'object' && x !== null && !Array.isArray(x);
const strOrNull = (x: unknown) => x === null || x === undefined || typeof x === 'string';
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** thesis：去首尾空白后 1–2000 字，空串按 null */
function checkThesis(raw: unknown, fields: Field[]): string | null {
  if (!strOrNull(raw)) { fields.push({ field: 'thesis', issue: 'invalid' }); return null; }
  const t = typeof raw === 'string' ? raw.trim() : '';
  if (t.length > 2000) fields.push({ field: 'thesis', issue: 'too_long' });
  return t || null;
}
function checkConditions(raw: unknown, fields: Field[]): CandidateConditionInput[] {
  if (raw === undefined || raw === null) return [];
  if (!Array.isArray(raw)) { fields.push({ field: 'conditions_to_hold', issue: 'invalid' }); return []; }
  if (raw.length > 10) fields.push({ field: 'conditions_to_hold', issue: 'too_many' });
  raw.forEach((c: unknown, i) => {
    const f = `conditions_to_hold[${i}]`;
    if (!isObj(c)) { fields.push({ field: f, issue: 'invalid' }); return; }
    const text = typeof c.text === 'string' ? c.text.trim() : '';
    if (!text) fields.push({ field: `${f}.text`, issue: 'required' });
    else if (text.length > 200) fields.push({ field: `${f}.text`, issue: 'too_long' });
    if (!strOrNull(c.verify_by) || (typeof c.verify_by === 'string' && c.verify_by !== '' && !DATE.test(c.verify_by))) fields.push({ field: `${f}.verify_by`, issue: 'invalid' });
    const vm = typeof c.verify_method === 'string' ? c.verify_method.trim() : '';
    if (vm.length > 200) fields.push({ field: `${f}.verify_method`, issue: 'too_long' });
    if (c.confidence !== null && c.confidence !== undefined && !(ENUMS.confidence_level as readonly unknown[]).includes(c.confidence)) fields.push({ field: `${f}.confidence`, issue: 'invalid' });
    if (!c.verify_by && !vm) fields.push({ field: f, issue: 'verification_required' });
  });
  return raw as CandidateConditionInput[];
}

/** Idempotency-Key：同键同体重放返回第一次的结果；同键异体 409 IDEMPOTENCY_CONFLICT */
function replay(scope: string, key: string | null, text: string) {
  if (!key) return null;
  const hit = idem.get(`${scope}|${key}`);
  if (!hit) return null;
  if (hit.body !== text) return conflict('IDEMPOTENCY_CONFLICT', '同一 Idempotency-Key 的请求体不同', {});
  return HttpResponse.json(hit.json as Record<string, unknown>, { status: hit.status });
}
function remember(scope: string, key: string | null, text: string, json: ResearchCandidate) {
  if (key) idem.set(`${scope}|${key}`, { body: text, status: 201, json });
  return HttpResponse.json(json, { status: 201 });
}

export const candidateHandlers = [
  http.get(`${API}/candidates`, ({ request }) => {
    const url = new URL(request.url);
    const u = currentUser();
    const raw = url.searchParams.get('status');
    let statuses: string[] | null = ['researching', 'watching', 'planned'];
    if (raw === 'all') statuses = null;
    else if (raw) {
      statuses = raw.split(',').map((x) => x.trim()).filter(Boolean);
      if (!statuses.length || statuses.some((x) => !(ENUMS.research_candidate_status as readonly string[]).includes(x))) return validation('status', 'invalid');
    }
    const origin = url.searchParams.get('origin');
    if (origin && !(ENUMS.research_candidate_origin as readonly string[]).includes(origin)) return validation('origin', 'invalid');
    const code = url.searchParams.get('security_code');
    const sid = url.searchParams.get('suggestion_id');
    const items = store
      .filter((s) => !!u && s.owner === u.id)
      .filter((s) => (!statuses || statuses.includes(s.head.status)) && (!origin || s.head.origin === origin) && (!code || s.head.security_code === code) && (!sid || s.head.suggestion_id === sid))
      .sort((x, y) => y.head.created_at.localeCompare(x.head.created_at) || y.head.id.localeCompare(x.head.id))
      .map(summary);
    return HttpResponse.json(page(items, url));
  }),

  http.post(`${API}/candidates`, async ({ request }) => {
    const u = currentUser()!;
    const key = request.headers.get('Idempotency-Key');
    const text = await request.text();
    const again = replay(`${u.id}|create`, key, text);
    if (again) return again;
    let b: Record<string, unknown>;
    try { b = JSON.parse(text) as Record<string, unknown>; } catch { return validation('body', 'invalid'); }
    if (!isObj(b)) return validation('body', 'invalid');
    // ① 请求体
    const fields: Field[] = [];
    const origin = b.origin;
    if (origin === 'strategy_screen') fields.push({ field: 'origin', issue: 'not_supported' });
    else if (!['manual', 'from_stock', 'suggestion'].includes(origin as string)) fields.push({ field: 'origin', issue: 'invalid' });
    const code = typeof b.security_code === 'string' && b.security_code.trim() ? b.security_code.trim().toUpperCase() : null;
    const sid = typeof b.suggestion_id === 'string' && b.suggestion_id ? b.suggestion_id : null;
    if (origin === 'manual' || origin === 'from_stock') {
      if (!code) fields.push({ field: 'security_code', issue: 'required' });
      if (b.suggestion_id !== null && b.suggestion_id !== undefined) fields.push({ field: 'suggestion_id', issue: 'not_allowed' });
    }
    if (origin === 'suggestion' && !sid) fields.push({ field: 'suggestion_id', issue: 'required' });
    const thesis = checkThesis(b.thesis, fields);
    const conds = checkConditions(b.conditions_to_hold, fields);
    // 示例：只有 demo_user 有建议；他人的与不存在的响应相同
    const sg = origin === 'suggestion' && sid && u.id === DEMO_UID ? SUGGESTIONS.find((s) => s.id === sid) : undefined;
    if (origin === 'suggestion' && sg && code && code !== sg.security_code) fields.push({ field: 'security_code', issue: 'mismatch' });
    if (fields.length) return fieldsError(fields);
    // ② 证券（suggestion 来源且未带代码时取建议的证券；建议不存在时留到 ③）
    const target = code ?? sg?.security_code ?? null;
    if (target) {
      const p = securityProfile(target);
      if (!p) return validation('security_code', 'unknown_security');
      if (p.type === 'etf' || p.type === 'index') return validation('security_code', 'security_type_not_supported');
    }
    // ③ 来源建议
    if (origin === 'suggestion' && !sg) return validation('suggestion_id', 'not_found');
    // ④ 重复
    const dup = store.find((s) => s.owner === u.id && s.head.security_code === target && ACTIVE.includes(s.head.status));
    if (dup) return conflict('CONFLICT', '该证券已有进行中的研究候选（示例）', { field: 'security_code', existing_id: dup.head.id });
    const p = securityProfile(target!)!;
    const n = store.length + 1;
    const s: Stored = {
      owner: u.id,
      head: {
        id: candId(n), security_code: target!, name: p.name, security_type: p.type, origin: origin as Stored['head']['origin'], strategy_run_id: null,
        suggestion_id: origin === 'suggestion' ? sg!.id : null, status: 'researching', plan_ids: [], created_at: nextTime(),
      },
      versions: [],
    };
    s.versions.push(makeVersion(s, 1, s.head.created_at, thesis, conds, null, null));
    store.push(s);
    return remember(`${u.id}|create`, key, text, full(s));
  }),

  http.get(`${API}/candidates/:id`, ({ params }) => {
    const s = mine(String(params.id));
    return s ? HttpResponse.json(full(s)) : notFound('研究候选');
  }),
  http.get(`${API}/candidates/:id/versions`, ({ params, request }) => {
    const s = mine(String(params.id));
    if (!s) return notFound('研究候选');
    return HttpResponse.json(page([...s.versions].sort((a, b) => b.version_no - a.version_no), new URL(request.url)));
  }),
  http.get(`${API}/candidates/:id/versions/:n`, ({ params }) => {
    const s = mine(String(params.id));
    const v = s?.versions.find((x) => String(x.version_no) === params.n);
    return v ? HttpResponse.json(v) : notFound(s ? '版本' : '研究候选');
  }),

  http.post(`${API}/candidates/:id/versions`, async ({ params, request }) => {
    const u = currentUser()!;
    const key = request.headers.get('Idempotency-Key');
    const text = await request.text();
    const again = replay(`${u.id}|ver|${String(params.id)}`, key, text);
    if (again) return again;
    let b: Record<string, unknown>;
    try { b = JSON.parse(text) as Record<string, unknown>; } catch { return validation('body', 'invalid'); }
    if (!isObj(b)) return validation('body', 'invalid');
    // ① 请求体
    const fields: Field[] = [];
    if (!Number.isInteger(b.base_version_no)) fields.push({ field: 'base_version_no', issue: 'required' });
    const decision = b.decision ?? null;
    if (decision !== null && !(ENUMS.candidate_decision as readonly unknown[]).includes(decision)) fields.push({ field: 'decision', issue: 'invalid' });
    const reasonRaw = b.decision_reason ?? null;
    const reason = typeof reasonRaw === 'string' ? reasonRaw.trim() : null;
    if (decision !== null) {
      if (!reason) fields.push({ field: 'decision_reason', issue: 'required' });
      else if (reason.length > 200) fields.push({ field: 'decision_reason', issue: 'too_long' });
    } else if (reasonRaw !== null) fields.push({ field: 'decision_reason', issue: 'not_allowed' });
    const thesis = checkThesis(b.thesis, fields);
    const conds = checkConditions(b.conditions_to_hold, fields);
    if (fields.length) return fieldsError(fields);
    // ② 本人
    const s = mine(String(params.id));
    if (!s) return notFound('研究候选');
    // ③ 终态
    const from = s.head.status;
    const to = decision ? decisionStatus[decision as CandidateDecision] : from;
    if (TERMINAL.includes(from)) return conflict('INVALID_STATE_TRANSITION', '研究候选已结束，不能再新建版本', { from, to, allowed: [] });
    // ④ 乐观锁
    const cur = s.versions[s.versions.length - 1].version_no;
    if (b.base_version_no !== cur) return conflict('VERSION_CONFLICT', '已有更新的版本', { current_version_no: cur });
    s.versions.push(makeVersion(s, cur + 1, nextTime(), thesis, conds, (decision as CandidateDecision | null), decision ? reason : null));
    s.head.status = to;
    return remember(`${u.id}|ver|${s.head.id}`, key, text, full(s));
  }),
];
