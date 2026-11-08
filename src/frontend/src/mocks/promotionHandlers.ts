/** 完全合成的示例数据；仅修改内存，不代表真实门禁或真实审批。 */
import { http, HttpResponse } from 'msw';
import type { AutomaticGateId, PromotionReport, PromotionSummary } from '../api/promotionTypes';
import { EXAMPLE_PROMOTION_REPORT } from './promotionFixtures';
import { currentUser } from './session';
import { errorBody } from './handlerUtils';
import { uid } from './fixtures';
const API = '/api/v1';
export const DEMO_REVIEW_ID = uid(940);
export const LEGACY_REVIEW_ID = uid(938);
/** 明显是假值，且仅示例模式有效；绝非真实管理员口令。 */
export const MOCK_WRONG_REAUTH = 'DEMO-WRONG';
function reauth(value: unknown) {
  return typeof value !== 'string' || value.length < 10 || value === MOCK_WRONG_REAUTH
    ? HttpResponse.json(errorBody('REAUTH_FAILED', '本次密码复核失败'), { status: 401 }) : null;
}
let reports: PromotionReport[];
let simulated = new Set<string>();
export function resetPromotions() {
  reports = [structuredClone(EXAMPLE_PROMOTION_REPORT), { ...structuredClone(EXAMPLE_PROMOTION_REPORT), review_id: uid(939), content_sha256: 'fedcba'.repeat(10) + 'fedc', stale: true, stale_reason: 'content_changed', decision: 'approved', reviewer_id: uid(3), decided_at: '2026-11-01T08:30:00+08:00' }, { ...structuredClone(EXAMPLE_PROMOTION_REPORT), review_id: LEGACY_REVIEW_ID, version_id: null, content_sha256: null, stale: true, stale_reason: 'legacy_unbound' }];
  simulated = new Set();
}
resetPromotions();
const denied = () => HttpResponse.json(errorBody('FORBIDDEN', '无审批权限'), { status: 403 });
const missing = () => HttpResponse.json(errorBody('NOT_FOUND', '未找到审核记录'), { status: 404 });
const invalid = () => HttpResponse.json(errorBody('VALIDATION_ERROR', '筛选或请求格式不正确'), { status: 400 });
const stale = () => HttpResponse.json(errorBody('PROMOTION_STALE', '审核绑定的版本或内容哈希已变化', { current_version_id: EXAMPLE_PROMOTION_REPORT.version_id }), { status: 409 });
function summary(r: PromotionReport): PromotionSummary {
  const { gate_results, fixture_runs: _fixtures, g6_report: _g6, ...binding } = r;
  void _fixtures; void _g6;
  return { ...binding, card_key: '门禁草稿（示例数据）', lifecycle: r.version_id !== null && simulated.has(r.version_id) ? 'simulating' : 'draft', g7: r.decision,
    gates: gate_results.filter((g) => g.gate !== 'G7').map((g) => ({ gate: g.gate as AutomaticGateId, result: g.result })) };
}
export const promotionHandlers = [
  http.get(`${API}/admin/promotions`, ({ request }) => {
    if (currentUser()?.role !== 'admin') return denied();
    const q = new URL(request.url).searchParams;
    const decisions = q.get('decision')?.split(',');
    if ((decisions && decisions.some((d) => !['pending', 'approved', 'rejected', 'changes_requested'].includes(d))) || (q.has('stale') && !['true', 'false'].includes(q.get('stale')!))) return invalid();
    const filters = ['decision', 'card_id', 'version_id', 'stale'].map((k) => `${k}=${q.get(k) ?? (k === 'stale' ? 'false' : '')}`).join('&');
    const items = reports.filter((r) => r.stale === (q.get('stale') === 'true') && (!decisions || decisions.includes(r.decision)) && (!q.get('card_id') || r.card_id === q.get('card_id')) && (!q.get('version_id') || r.version_id === q.get('version_id')));
    const cursor = q.get('cursor');
    let offset = 0;
    if (cursor) {
      const parts = cursor.split('|');
      if (parts[0] !== filters || !/^\d+$/.test(parts[1] ?? '') || Number(parts[1]) >= items.length) return HttpResponse.json(errorBody('INVALID_CURSOR', '游标无效'), { status: 400 });
      offset = Number(parts[1]);
    }
    const limit = Number(q.get('limit') ?? 50);
    if (!Number.isInteger(limit) || limit < 1 || limit > 200) return invalid();
    return HttpResponse.json({ items: items.slice(offset, offset + limit).map(summary), next_cursor: offset + limit < items.length ? `${filters}|${offset + limit}` : null });
  }),
  http.get(`${API}/promotion-requests/:id`, ({ params }) => {
    const r = reports.find((r) => r.review_id === params.id);
    return r ? HttpResponse.json(r) : missing();
  }),
  http.post(`${API}/admin/promotions/:id/decision`, async ({ params, request }) => {
    if (currentUser()?.role !== 'admin') return denied();
    const r = reports.find((r) => r.review_id === params.id);
    if (!r) return missing();
    if (r.stale) return stale();
    if (r.decision !== 'pending') return HttpResponse.json(errorBody('INVALID_STATE_TRANSITION', '审核已决定'), { status: 409 });
    const b = await request.json() as { decision: string; comment: string; ack_warn_gates: AutomaticGateId[]; password: unknown };
    const passwordError = reauth(b.password);
    if (passwordError) return passwordError;
    if (!['approved', 'rejected', 'changes_requested'].includes(b.decision) || typeof b.comment !== 'string' || !b.comment.trim() || b.comment.length > 500 || !Array.isArray(b.ack_warn_gates) || b.ack_warn_gates.some((g) => !['G1', 'G2', 'G3', 'G4', 'G5', 'G6'].includes(g))) return invalid();
    const fails = r.gate_results.filter((g) => g.gate !== 'G7' && g.result === 'fail').map((g) => g.gate);
    const warns = r.gate_results.filter((g) => g.gate !== 'G7' && g.result === 'warn' && !b.ack_warn_gates.includes(g.gate as AutomaticGateId)).map((g) => g.gate);
    if (b.decision === 'approved' && fails.length) return HttpResponse.json(errorBody('PROMOTION_GATES_NOT_MET', '存在未通过门禁', { gates: fails }), { status: 422 });
    if (b.decision === 'approved' && warns.length) return HttpResponse.json(errorBody('PROMOTION_WARN_UNACKNOWLEDGED', '警告门禁尚未确认', { gates: warns }), { status: 422 });
    r.decision = b.decision as PromotionReport['decision'];
    r.reviewer_id = currentUser()!.id;
    r.decided_at = new Date().toISOString();
    return HttpResponse.json(summary(r));
  }),
  http.post(`${API}/admin/strategies/:id/versions/:vid/lifecycle`, async ({ params, request }) => {
    if (currentUser()?.role !== 'admin') return denied();
    const b = await request.json() as { to: string; reason: string; review_id: string; password: unknown };
    const passwordError = reauth(b.password);
    if (passwordError) return passwordError;
    const r = reports.find((r) => r.review_id === b.review_id);
    if (r?.stale) return stale();
    if (params.id !== uid(512) || params.vid !== EXAMPLE_PROMOTION_REPORT.version_id) return missing();
    if (!r || !r.version_id || r.decision !== 'approved' || r.version_id !== params.vid || r.content_sha256 !== EXAMPLE_PROMOTION_REPORT.content_sha256) return HttpResponse.json(errorBody('PROMOTION_GATES_NOT_MET', '示例数据：需先批准绑定审核', { gates: ['G7'] }), { status: 422 });
    if (b.to !== 'simulating' || typeof b.reason !== 'string' || !b.reason.trim()) return invalid();
    if (r.version_id !== null && simulated.has(r.version_id)) return HttpResponse.json(errorBody('INVALID_STATE_TRANSITION', '示例版本已在模拟中'), { status: 409 });
    simulated.add(r.version_id);
    return HttpResponse.json({ from: 'draft', to: 'simulating' });
  }),
];
