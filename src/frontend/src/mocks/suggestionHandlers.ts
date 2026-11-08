import { withExampleSuggestionExplanation } from './explanationFixtures';
import { currentUser } from './session';
import { exampleTracking } from './phase2Fixtures';
/**
 * 候选信号卡（建议）补全的 mock（T-F12，契约 §5.2、§7 /suggestions*）：
 * - 列表 / 详情改为读会话内状态：手动刷新会生成新卡，旧卡变为 superseded（取代链）
 * - POST /suggestions/refresh（契约 #36）：同步返回 200 {suggestion, changed, superseded_id, data_as_of}；
 *   有当前卡 → 生成新卡并取代旧卡（changed=true、superseded_id=旧卡 id）；该证券没有任何卡 → {suggestion: null, changed: false}；
 *   同一证券 30 秒内再次刷新 → 409 SUGGESTION_REFRESH_TOO_FREQUENT{retry_after_s}（间隔为示例值）
 * - POST /suggestions/{id}/actions：只收 viewed / dismissed / acted_trade_linked，记录到 actionLog，204（响应体契约未定）
 * - GET /suggestions/{id}/tracking：§7.11.3 的逐条结果、价格依据、缺口；旧 Stat 不放大样本
 * - GET /suggestions/{id}/chain：契约未给响应结构，mock 不实现（前端也不请求）
 * 全部为示例数据，不发外网请求。
 */
import { http, HttpResponse } from 'msw';
import { ENUMS } from '../api/enums';
import type { Suggestion, SuggestionListItem } from '../api/types';
import { errorBody, notFound, page, validation } from './handlerUtils';
import { SUGGESTIONS, summarize, uid } from './fixtures';
import { pushStreamEvent } from './streamHandlers';

const API = '/api/v1';
export const REFRESH_MIN_INTERVAL_S = 30;

/** 示例：600000.SH 当前卡的 supersedes_id 指向这张已被取代的旧卡 */
function seedSuperseded(): Suggestion[] {
  const cur = SUGGESTIONS.find((s) => s.supersedes_id === uid(99));
  if (!cur) return [];
  return [{
    ...cur, id: uid(99), status: 'superseded', supersedes_id: null, superseded_by_id: cur.id,
    created_at: '2026-11-02T09:31:00+08:00',
    explanation: { ...cur.explanation, text: `${cur.name}：盘中事件前的上一张候选信号卡（示例数据）`, llm_call_id: null },
  }];
}

let cards: Suggestion[] = [];
let lastRefresh = new Map<string, number>();
let seq = 0;
export const actionLog: { suggestion_id: string; kind: string; trade_id: string | null; note: string | null }[] = [];

export function resetSuggestions() {
  cards = [...SUGGESTIONS.map(withExampleSuggestionExplanation), ...seedSuperseded()];
  lastRefresh = new Map();
  seq = 0;
  actionLog.length = 0;
}
resetSuggestions();

export const suggestionsNow = () => cards;
const listItem = (sg: Suggestion): SuggestionListItem => ({ ...summarize(sg), security_code: sg.security_code, name: sg.name });

export const suggestionHandlers = [
  http.get(`${API}/suggestions`, ({ request }) => {
    const url = new URL(request.url);
    const code = url.searchParams.get('security_code');
    const status = url.searchParams.get('status') ?? 'active';
    if (!(ENUMS.suggestion_status as readonly string[]).includes(status)) return validation('status', 'status 取值见 suggestion_status');
    const items = cards.filter((s) => (!code || s.security_code === code) && s.status === status).map(listItem);
    return HttpResponse.json(page(items, url));
  }),
  http.post(`${API}/suggestions/refresh`, async ({ request }) => {
    const body = (await request.json().catch(() => null)) as { security_code?: unknown } | null;
    const code = typeof body?.security_code === 'string' ? body.security_code : '';
    if (!code) return validation('security_code', 'security_code 必填');
    const now = Date.now();
    const last = lastRefresh.get(code);
    if (last !== undefined && now - last < REFRESH_MIN_INTERVAL_S * 1000) {
      const retry_after_s = Math.ceil((REFRESH_MIN_INTERVAL_S * 1000 - (now - last)) / 1000);
      return HttpResponse.json(errorBody('SUGGESTION_REFRESH_TOO_FREQUENT', '刷新过于频繁', { retry_after_s }), { status: 409 });
    }
    lastRefresh.set(code, now);
    const cur = cards.find((s) => s.security_code === code && s.status === 'active');
    // #36：当前没有任何建议 → suggestion=null、changed=false（示例数据不新建）
    if (!cur) return HttpResponse.json({ suggestion: null, changed: false, superseded_id: null, data_as_of: new Date(now).toISOString() });
    seq += 1;
    const next: Suggestion = {
      ...cur, id: uid(1200 + seq), status: 'active', origin: 'manual_refresh', supersedes_id: cur.id, superseded_by_id: null,
      created_at: new Date(now).toISOString(),
      explanation: { source: 'template', text: `${cur.name}：手动刷新后按缓存数据重算的候选信号卡（示例数据）`, llm_call_id: null, prompt_version: null, validation_status: 'fallback', paragraphs: [{ text: `${cur.name}：手动刷新后按缓存数据重算的候选信号卡（示例数据）`, expr: null, evidence_ids: [] }] },
    };
    cards = cards.map((s) => (s.id === cur.id ? { ...s, status: 'superseded', superseded_by_id: next.id } : s));
    cards.push(next);
    pushStreamEvent('suggestion', { id: next.id, security_code: next.security_code, name: next.name, supersedes_id: cur.id, summary: summarize(next) });
    return HttpResponse.json({ suggestion: next, changed: true, superseded_id: cur.id, data_as_of: next.data_as_of });
  }),
  http.get(`${API}/suggestions/:id/tracking`, ({ params }) => {
    // 本批合成建议仅归示例用户本人；其他会话与不存在的建议同为404。
    const sg = currentUser()?.username === 'demo_user' ? cards.find((s) => s.id === params.id) : undefined;
    return sg ? HttpResponse.json(exampleTracking(sg)) : notFound('建议');
  }),
  http.post(`${API}/suggestions/:id/actions`, async ({ params, request }) => {
    const sg = cards.find((s) => s.id === params.id);
    if (!sg) return notFound('建议');
    const body = (await request.json().catch(() => null)) as { kind?: unknown; trade_id?: unknown; note?: unknown } | null;
    const kind = body?.kind;
    if (kind !== 'viewed' && kind !== 'dismissed' && kind !== 'acted_trade_linked') return validation('kind', 'kind 取值为 viewed|dismissed|acted_trade_linked');
    const tradeId = body?.trade_id ?? null;
    if (kind === 'acted_trade_linked' ? typeof tradeId !== 'string' : tradeId !== null) return validation('trade_id', 'trade_id 仅在 acted_trade_linked 时填写');
    const note = body?.note ?? null;
    if (note !== null && typeof note !== 'string') return validation('note', 'note 须为文本或 null');
    actionLog.push({ suggestion_id: sg.id, kind, trade_id: tradeId as string | null, note });
    return new HttpResponse(null, { status: 204 });
  }),
  http.get(`${API}/suggestions/:id`, ({ params }) => {
    const sg = cards.find((s) => s.id === params.id);
    return sg ? HttpResponse.json(sg) : notFound('建议');
  }),
];
