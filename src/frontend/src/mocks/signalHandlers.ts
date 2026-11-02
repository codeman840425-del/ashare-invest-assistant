/**
 * T-F17：候选信号与不可执行原因（契约 v0.2.7 §7.6）的 mock。
 * 会话内可变状态（忽略信号、手动解除原因）放在覆盖表里，resetSignals() 清空；示例数据本身不改。
 */
import { http, HttpResponse } from 'msw';
import type { CandidateSignalEventCause, CandidateSignalState } from '../api/enums';
import type { CandidateSignal, NonExecutableReason } from '../api/types';
import { CANDIDATE_SIGNALS, NOW, REASONS, SUGGESTIONS } from './fixtures';
import { errorBody, notFound, page, validation } from './handlerUtils';

const API = '/api/v1';

/** 终止态：不能再忽略，原因随之作废（§6 状态机） */
export const TERMINAL_SIGNAL_STATES: readonly CandidateSignalState[] = ['confirmed', 'dismissed', 'expired', 'invalidated', 'superseded'];

const signalPatch = new Map<string, Partial<CandidateSignal>>();
const reasonPatch = new Map<string, Partial<NonExecutableReason>>();
export function resetSignals() {
  signalPatch.clear();
  reasonPatch.clear();
}
/** T-F18：生成 / 确认计划草案时改信号状态与关联草案（会话内，resetSignals 清空） */
export function patchSignal(id: string, p: Partial<CandidateSignal>) {
  signalPatch.set(id, { ...signalPatch.get(id), ...p });
}
export const signalsNow = (): CandidateSignal[] => CANDIDATE_SIGNALS.map((c) => ({ ...c, ...signalPatch.get(c.id) }));
export const reasonsNow = (): NonExecutableReason[] => REASONS.map((r) => ({ ...r, ...reasonPatch.get(r.id) }));

/**
 * 状态历史（示例，契约 v0.2.9 #6）：由信号与原因推出；cause 只用 candidate_signal_event_cause 的 6 个取值。
 * 创建事件（from=null）与生成草案（→drafted）的 cause 契约未写明，示例分别用 executability_check 与 user（报告待定项）。
 */
type MockEvent = { id: string; from: CandidateSignalState | null; to: CandidateSignalState; cause: CandidateSignalEventCause; at: string };
const SYSTEM_CAUSE: Partial<Record<CandidateSignalState, CandidateSignalEventCause>> = { expired: 'expiry', superseded: 'supersede', invalidated: 'invalidation' };
function eventsOf(cs: CandidateSignal): MockEvent[] {
  const rs = reasonsNow().filter((r) => r.signal_id === cs.id);
  const out: Omit<MockEvent, 'id'>[] = [{ from: null, to: 'open', cause: 'executability_check', at: cs.created_at }];
  const st: { cur: CandidateSignalState } = { cur: 'open' };
  const push = (to: CandidateSignalState, cause: CandidateSignalEventCause, at: string) => {
    if (to === st.cur) return;
    // 事件时间不早于创建时间（示例里有 valid_until / detected_at 早于 created_at 的数据）
    out.push({ from: st.cur, to, cause, at: at < cs.created_at ? cs.created_at : at });
    st.cur = to;
  };
  const sorted = [...rs].sort((a, b) => a.detected_at.localeCompare(b.detected_at));
  if (sorted.length) push('blocked', 'executability_check', sorted[0].detected_at);
  for (const r of sorted.filter((x) => x.released_at)) push('released', 'reason_released', r.released_at!);
  const base = CANDIDATE_SIGNALS.find((c) => c.id === cs.id)!;
  if (base.state === 'drafted' || base.state === 'expired' || base.state === 'superseded' || base.state === 'blocked') {
    const at = base.state === 'expired' || base.state === 'superseded' ? (cs.valid_until ?? cs.created_at) : cs.created_at;
    push(base.state, base.state === 'drafted' ? 'user' : base.state === 'blocked' ? 'executability_check' : SYSTEM_CAUSE[base.state]!, at);
  }
  if (cs.state !== st.cur) {
    const cause: CandidateSignalEventCause = SYSTEM_CAUSE[cs.state] ?? (cs.state === 'released' ? 'reason_released' : cs.state === 'blocked' || cs.state === 'open' ? 'executability_check' : 'user');
    push(cs.state, cause, NOW);
  }
  // 排序 at desc, id desc；id 示例按序号生成
  return out.map((e, i) => ({ ...e, id: `${cs.id}-ev${String(i).padStart(2, '0')}` })).sort((a, b) => b.at.localeCompare(a.at) || b.id.localeCompare(a.id));
}

export const signalHandlers = [
  http.get(`${API}/candidate-signals`, ({ request }) => {
    const url = new URL(request.url);
    const code = url.searchParams.get('security_code');
    const state = url.searchParams.get('state');
    const instance = url.searchParams.get('instance_id');
    const horizon = url.searchParams.get('horizon');
    const items = signalsNow()
      .filter((c) => (!code || c.security_code === code) && (!state || c.state === state) && (!instance || c.instance_id === instance) && (!horizon || c.horizon === horizon))
      .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id));
    return HttpResponse.json(page(items, url));
  }),
  http.get(`${API}/candidate-signals/:id`, ({ params }) => {
    const cs = signalsNow().find((c) => c.id === params.id);
    return cs ? HttpResponse.json(cs) : notFound('候选信号');
  }),
  http.get(`${API}/candidate-signals/:id/events`, ({ params, request }) => {
    const cs = signalsNow().find((c) => c.id === params.id);
    // 契约 v0.2.9 #6：§1.2 分页 {items, next_cursor}
    return cs ? HttpResponse.json(page(eventsOf(cs), new URL(request.url))) : notFound('候选信号');
  }),
  http.post(`${API}/candidate-signals/:id/dismiss`, async ({ params, request }) => {
    const cs = signalsNow().find((c) => c.id === params.id);
    if (!cs) return notFound('候选信号');
    const body = (await request.json().catch(() => null)) as { note?: unknown } | null;
    if (!body || (body.note !== null && body.note !== undefined && typeof body.note !== 'string')) return validation('note', 'note 须为字符串或 null');
    if (TERMINAL_SIGNAL_STATES.includes(cs.state)) {
      return HttpResponse.json(errorBody('INVALID_STATE_TRANSITION', `候选信号当前为 ${cs.state}，不能忽略`, { from: cs.state, to: 'dismissed', allowed: [] }), { status: 409 });
    }
    signalPatch.set(cs.id, { ...signalPatch.get(cs.id), state: 'dismissed' });
    // 所属信号终止 → 生效中的原因作废（§6：active → obsolete）
    for (const r of reasonsNow()) if (r.signal_id === cs.id && r.status === 'active') reasonPatch.set(r.id, { status: 'obsolete' });
    return HttpResponse.json(signalsNow().find((c) => c.id === cs.id));
  }),

  http.get(`${API}/non-executable-reasons`, ({ request }) => {
    const url = new URL(request.url);
    const status = url.searchParams.get('status');
    const signalId = url.searchParams.get('signal_id');
    const code = url.searchParams.get('code');
    const since = url.searchParams.get('released_since');
    const sinceMs = since ? Date.parse(since) : NaN;
    if (since && Number.isNaN(sinceMs)) return validation('released_since', 'released_since 须为 ISO 8601 时间');
    // v0.2.9 #12：status 默认 active；all = 不按状态过滤（含 obsolete）；带 signal_ids / suggestion_id 时同样默认 active
    const st = status ?? 'active';
    if (!['active', 'released', 'all'].includes(st)) return validation('status', 'status 取值 active|released|all');
    let base = reasonsNow().filter((r) => (st === 'all' || r.status === st) && (!signalId || r.signal_id === signalId) && (!code || r.code === code));
    // v0.2.7：released_since 只返回 released_at ≥ released_since，排序 released_at desc, id desc
    if (since) {
      base = base.filter((r) => r.released_at && Date.parse(r.released_at) >= sinceMs)
        .sort((a, b) => b.released_at!.localeCompare(a.released_at!) || b.id.localeCompare(a.id));
    }
    // v0.2.3 #17：signal_ids（≤ 100）或 suggestion_id 时不分页，返回 {items}
    const idsParam = url.searchParams.get('signal_ids');
    const suggestionId = url.searchParams.get('suggestion_id');
    if (idsParam !== null || suggestionId !== null) {
      let ids: string[];
      if (idsParam !== null) {
        ids = idsParam.split(',').map((x) => x.trim()).filter(Boolean);
        if (ids.length > 100) return validation('signal_ids', 'signal_ids 最多 100 个');
      } else {
        const sg = SUGGESTIONS.find((x) => x.id === suggestionId);
        if (!sg) return notFound('建议');
        ids = sg.candidate_signal_ids;
      }
      return HttpResponse.json({ items: base.filter((r) => ids.includes(r.signal_id)) });
    }
    return HttpResponse.json(page(base, url));
  }),
  http.get(`${API}/non-executable-reasons/:id`, ({ params }) => {
    const r = reasonsNow().find((x) => x.id === params.id);
    return r ? HttpResponse.json(r) : notFound('不可执行原因');
  }),
  http.post(`${API}/non-executable-reasons/:id/release`, async ({ params, request }) => {
    const r = reasonsNow().find((x) => x.id === params.id);
    if (!r) return notFound('不可执行原因');
    const body = (await request.json().catch(() => null)) as { confirm?: unknown; note?: unknown } | null;
    if (!body || body.confirm !== true) return validation('confirm', 'confirm 须为 true');
    if (body.note !== null && body.note !== undefined && typeof body.note !== 'string') return validation('note', 'note 须为字符串或 null');
    // v0.2.9 #9：名单类原因（BLOCKLISTED、USER_MUTED）machine_checkable=true，只能删除 /restrictions 解除
    if (r.release_condition.machine_checkable || r.code === 'BLOCKLISTED' || r.code === 'USER_MUTED') {
      return HttpResponse.json(errorBody('REASON_NOT_MANUALLY_RELEASABLE', '该原因由系统自动检查，不能手动解除'), { status: 409 });
    }
    if (r.status !== 'active') return HttpResponse.json(errorBody('INVALID_STATE_TRANSITION', `原因当前为 ${r.status}，不能再解除`), { status: 409 });
    reasonPatch.set(r.id, { status: 'released', released_at: NOW, released_by: 'user', release_evidence: { note: (body.note as string | null | undefined) ?? null } });
    // 信号的生效原因全部解除 → blocked 变为 released，系统随后重新检查（§6）
    const cs = signalsNow().find((c) => c.id === r.signal_id);
    if (cs && cs.state === 'blocked' && !reasonsNow().some((x) => x.signal_id === cs.id && x.status === 'active')) {
      signalPatch.set(cs.id, { ...signalPatch.get(cs.id), state: 'released' });
    }
    return HttpResponse.json(reasonsNow().find((x) => x.id === r.id));
  }),
];
