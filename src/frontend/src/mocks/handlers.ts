/**
 * MSW 处理器：按契约 v0.2.2 §7 的路径与响应结构返回示例数据。只拦截同源 `/api/v1/*`。
 * 未实现的端点统一返回 404 + 契约错误信封（code=NOT_FOUND），便于发现漏接。
 */
import { http, HttpResponse, delay } from 'msw';
import type { ApiErrorBody, Notification, Paged, TerminalScope } from '../api/types';
import {
  CANDIDATE_SIGNALS, DAILY_REPORTS, HORIZON_ASSESSMENTS, DAILY_REPORT_LIST, HEALTH_READY, ME, NOTIFICATIONS, NOW, PORTFOLIO, QUOTES, REASONS,
  SIGNAL_EVENTS, SUGGESTIONS, SUGGESTION_LIST, TERMINAL_ACCOUNT, TERMINAL_ROWS, WATCHLIST, dailyBars, intradayBars,
} from './fixtures';

const API = '/api/v1';
let reqSeq = 0;

export function errorBody(code: string, message: string, details: Record<string, unknown> | null = null): ApiErrorBody {
  reqSeq += 1;
  return { error: { code, message, details, request_id: `mock-${String(reqSeq).padStart(6, '0')}` } };
}
const notFound = (what: string) => HttpResponse.json(errorBody('NOT_FOUND', `${what} 不存在（示例数据）`), { status: 404 });
const validation = (field: string, msg: string) => HttpResponse.json(errorBody('VALIDATION_ERROR', msg, { field }), { status: 422 });

function page<T>(items: T[], url: URL): Paged<T> {
  const limit = Math.min(Math.max(Number(url.searchParams.get('limit') ?? 50) || 50, 1), 200);
  const start = Number(url.searchParams.get('cursor') ?? 0) || 0;
  const slice = items.slice(start, start + limit);
  return { items: slice, next_cursor: start + limit < items.length ? String(start + limit) : null };
}

// 会话内可变状态：已读
const readAt = new Map<string, string>();
const notifications = (): Notification[] => NOTIFICATIONS.map((n) => ({ ...n, read_at: n.read_at ?? readAt.get(n.id) ?? null }));
export function resetMockState() {
  readAt.clear();
}

/** 浏览器里加一点延迟让加载态可见；测试（node）里不延迟 */
const lag = () => (typeof window !== 'undefined' && import.meta.env.MODE !== 'test' ? delay(80) : Promise.resolve());

export const handlers = [
  http.get(`${API}/meta/registration`, () => HttpResponse.json({ mode: 'invite' })),
  http.get(`${API}/health/ready`, () => HttpResponse.json(HEALTH_READY)),
  http.get(`${API}/me`, () => HttpResponse.json(ME)),

  http.get(`${API}/terminal`, async ({ request }) => {
    await lag();
    const scope = (new URL(request.url).searchParams.get('scope') ?? 'all') as TerminalScope;
    if (!['all', 'watchlist', 'holdings'].includes(scope)) return validation('scope', 'scope 取值为 all|watchlist|holdings');
    const rows = TERMINAL_ROWS.filter((r) => (scope === 'all' ? true : scope === 'holdings' ? r.holding !== null : r.in_watchlist));
    return HttpResponse.json({
      server_time: NOW, session: 'morning', account: TERMINAL_ACCOUNT, rows: rows.slice(0, 300), truncated: rows.length > 300,
      unread_notifications: notifications().filter((n) => n.read_at === null).length,
    });
  }),
  http.get(`${API}/watchlist`, () => HttpResponse.json(WATCHLIST)),
  http.get(`${API}/horizon-assessments`, async ({ request }) => {
    await lag();
    const code = new URL(request.url).searchParams.get('security_code');
    if (!code) return validation('security_code', 'security_code 必填');
    const a = HORIZON_ASSESSMENTS[code];
    return a ? HttpResponse.json(a) : notFound('周期分类结果');
  }),
  http.get(`${API}/portfolio`, () => HttpResponse.json(PORTFOLIO)),
  http.get(`${API}/quotes`, ({ request }) => {
    const codes = (new URL(request.url).searchParams.get('codes') ?? '').split(',').filter(Boolean);
    if (codes.length > 50) return validation('codes', 'codes 最多 50 个');
    return HttpResponse.json({ items: codes.length ? QUOTES.filter((q) => codes.includes(q.security_code)) : QUOTES });
  }),
  http.get(`${API}/securities/:code/bars`, async ({ params, request }) => {
    await lag();
    const url = new URL(request.url);
    const freq = url.searchParams.get('freq') ?? 'd';
    const adjust = url.searchParams.get('adjust') ?? (freq === '1m' ? 'none' : 'qfq');
    if (!['1m', 'd', 'w'].includes(freq)) return validation('freq', 'freq 取值为 1m|d|w');
    if (freq === '1m' && adjust !== 'none') return validation('adjust', '1m 只支持 adjust=none');
    if (freq === 'w') return HttpResponse.json(errorBody('NOT_IMPLEMENTED', '示例数据未提供周线'), { status: 501 });
    const res = freq === '1m' ? intradayBars(String(params.code)) : dailyBars(String(params.code));
    if (!res) return notFound('证券');
    const limit = Number(url.searchParams.get('limit') ?? 0);
    return HttpResponse.json(limit > 0 ? { ...res, items: res.items.slice(-limit) } : res);
  }),

  http.get(`${API}/suggestions`, ({ request }) => {
    const url = new URL(request.url);
    const code = url.searchParams.get('security_code');
    const status = url.searchParams.get('status') ?? 'active';
    return HttpResponse.json(page(SUGGESTION_LIST.filter((s) => (!code || s.security_code === code) && s.status === status), url));
  }),
  http.get(`${API}/suggestions/:id`, async ({ params }) => {
    await lag();
    const sg = SUGGESTIONS.find((s) => s.id === params.id);
    return sg ? HttpResponse.json(sg) : notFound('建议');
  }),
  http.get(`${API}/candidate-signals`, ({ request }) => {
    const url = new URL(request.url);
    const code = url.searchParams.get('security_code');
    const state = url.searchParams.get('state');
    const items = CANDIDATE_SIGNALS.filter((c) => (!code || c.security_code === code) && (!state || c.state === state))
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
    return HttpResponse.json(page(items, url));
  }),
  http.get(`${API}/candidate-signals/:id`, ({ params }) => {
    const cs = CANDIDATE_SIGNALS.find((c) => c.id === params.id);
    return cs ? HttpResponse.json(cs) : notFound('候选信号');
  }),
  http.get(`${API}/non-executable-reasons`, ({ request }) => {
    const url = new URL(request.url);
    const status = url.searchParams.get('status');
    const signalId = url.searchParams.get('signal_id');
    return HttpResponse.json(page(REASONS.filter((r) => (!status || r.status === status) && (!signalId || r.signal_id === signalId)), url));
  }),
  http.get(`${API}/non-executable-reasons/:id`, ({ params }) => {
    const r = REASONS.find((x) => x.id === params.id);
    return r ? HttpResponse.json(r) : notFound('不可执行原因');
  }),
  http.get(`${API}/signals`, ({ request }) => {
    const url = new URL(request.url);
    const code = url.searchParams.get('security_code');
    const items = SIGNAL_EVENTS.filter((e) => !code || e.security_code === code).sort((a, b) => b.at.localeCompare(a.at));
    return HttpResponse.json(page(items, url));
  }),

  http.get(`${API}/notifications/unread-count`, () => HttpResponse.json({ count: notifications().filter((n) => n.read_at === null).length })),
  http.get(`${API}/notifications`, ({ request }) => {
    const url = new URL(request.url);
    const unread = url.searchParams.get('unread') === 'true';
    return HttpResponse.json(page(notifications().filter((n) => !unread || n.read_at === null), url));
  }),
  http.post(`${API}/notifications/read-all`, () => {
    NOTIFICATIONS.forEach((n) => readAt.set(n.id, NOW));
    return new HttpResponse(null, { status: 204 });
  }),
  http.post(`${API}/notifications/:id/read`, ({ params }) => {
    const n = NOTIFICATIONS.find((x) => x.id === params.id);
    if (!n) return notFound('通知');
    readAt.set(n.id, NOW);
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(`${API}/daily-reports`, ({ request }) => HttpResponse.json(page(DAILY_REPORT_LIST, new URL(request.url)))),
  http.get(`${API}/daily-reports/:date`, ({ params }) => {
    const d = DAILY_REPORTS.find((x) => x.date === params.date);
    return d ? HttpResponse.json(d) : notFound('日报');
  }),

  // 兜底：其余 /api/v1/* 一律 404 信封（示例数据未覆盖）
  http.all(`${API}/*`, ({ request }) => HttpResponse.json(errorBody('NOT_FOUND', `示例数据未覆盖该端点：${new URL(request.url).pathname}`), { status: 404 })),
];
