/**
 * MSW 处理器：按契约 v0.2.5 §7 的路径与响应结构返回示例数据。只拦截同源 `/api/v1/*`。
 * 未实现的端点统一返回 404 + 契约错误信封（code=NOT_FOUND），便于发现漏接。
 */
import { http, HttpResponse, delay, matchRequestUrl } from 'msw';
import type { MarketOverview, Notification, TerminalScope, TodayResponse } from '../api/types';
import { accountHandlers } from './accountHandlers';
import { errorBody, jsonWithEtag, notFound, page, validation } from './handlerUtils';
import { currentUser, resetSession } from './session';
import {
  ACCOUNT_ID, CANDIDATE_SIGNALS, DAILY_REPORTS, HORIZON_ASSESSMENTS, noviceAssessment, DAILY_REPORT_LIST, HEALTH_READY, NOTIFICATIONS, NOW, PORTFOLIO, QUOTES, REASONS,
  SIGNAL_EVENTS, SUGGESTIONS, SUGGESTION_LIST, TERMINAL_ACCOUNT, TERMINAL_ROWS, TRADE_DATE, WATCHLIST, dailyBars, intradayBars,
} from './fixtures';

export { errorBody };

const API = '/api/v1';

// 会话内可变状态：已读
const readAt = new Map<string, string>();
const notifications = (): Notification[] => NOTIFICATIONS.map((n) => ({ ...n, read_at: n.read_at ?? readAt.get(n.id) ?? null }));
export function resetMockState() {
  readAt.clear();
  resetSession();
}

/** 浏览器里加一点延迟让加载态可见；测试（node）里不延迟 */
const lag = () => (typeof window !== 'undefined' && import.meta.env.MODE !== 'test' ? delay(80) : Promise.resolve());

const LEVEL: Record<string, number> = { info: 1, warning: 2, critical: 3 };

/** v0.2.3 #9 §7.3 最小结构（示例数据） */
const MARKET_OVERVIEW: MarketOverview = {
  trade_date: TRADE_DATE, session: 'morning',
  indices: [
    { security_code: '000001.SH', name: '上证指数（示例）', price: '3268.12', change_pct: '0.42', amount: '412300000000', t: NOW },
    { security_code: '399001.SZ', name: '深证成指（示例）', price: '10432.55', change_pct: '-0.18', amount: '538100000000', t: NOW },
  ],
  breadth: { up: 2861, down: 2104, flat: 213, limit_up: 47, limit_down: 9 },
  regime: TERMINAL_ACCOUNT.regime, regime_position_range: TERMINAL_ACCOUNT.regime_position_range, turnover_total: '950400000000',
  data_status: 'fresh', data_as_of: NOW, gaps: [],
};

/** v0.2.3 #12：/today 首页聚合 mock（契约 §7.3；每个列表 ≤ 50，more 表示是否截断） */
function todayBody(): TodayResponse {
  const more = <T,>(items: T[]) => ({ items: items.slice(0, 50), more: items.length > 50 });
  const nameOf = (code: string) => TERMINAL_ROWS.find((r) => r.security_code === code)?.name ?? code;
  const report = DAILY_REPORTS[0];
  return {
    server_time: NOW, trade_date: TRADE_DATE, session: 'morning',
    market: { regime: TERMINAL_ACCOUNT.regime, regime_position_range: TERMINAL_ACCOUNT.regime_position_range, data_status: 'fresh' },
    focus: more(TERMINAL_ROWS.filter((r) => r.focus)),
    pending_plan_drafts: more(SUGGESTIONS.flatMap((sg) => sg.plan_draft_ids.map((id) => ({
      id, security_code: sg.security_code, name: nameOf(sg.security_code), action: sg.strategies[0]?.action ?? 'wait', valid_until: null, status: 'pending' as const,
    })))),
    released_reasons: more(REASONS.filter((r) => r.status === 'released' && r.released_at).map((r) => {
      const cs = CANDIDATE_SIGNALS.find((c) => c.id === r.signal_id);
      return { reason_id: r.id, signal_id: r.signal_id, code: r.code, security_code: cs?.security_code ?? '', name: cs?.name ?? '', released_at: r.released_at! };
    })),
    risk_flags: more(SUGGESTIONS.flatMap((sg) => sg.risk_flags.map((f) => ({ ...f, security_code: sg.security_code, name: nameOf(sg.security_code) })))
      .sort((a, b) => LEVEL[b.level] - LEVEL[a.level])),
    invalidations_today: more([]),
    daily_report: { date: TRADE_DATE, status: 'not_yet' },
    reconciliation: report.reconciliation,
    unread_notifications: notifications().filter((n) => n.read_at === null).length,
  };
}

const routeHandlers = [
  // 鉴权、账号、券商账户、成交、导入、对账（T-F02/T-F02a/T-F04，见 accountHandlers.ts）
  ...accountHandlers,
  http.get(`${API}/health/ready`, () => HttpResponse.json(HEALTH_READY)),

  http.get(`${API}/terminal`, async ({ request }) => {
    await lag();
    const scope = (new URL(request.url).searchParams.get('scope') ?? 'all') as TerminalScope;
    if (!['all', 'watchlist', 'holdings'].includes(scope)) return validation('scope', 'scope 取值为 all|watchlist|holdings');
    const rows = TERMINAL_ROWS.filter((r) => (scope === 'all' ? true : scope === 'holdings' ? r.holding !== null : r.in_watchlist));
    // v0.2.3 #16：trade_date 由服务端给出；弱 ETag，If-None-Match 未变时 304
    return jsonWithEtag(request, {
      server_time: NOW, trade_date: TRADE_DATE, session: 'morning', account: TERMINAL_ACCOUNT, rows: rows.slice(0, 300), truncated: rows.length > 300,
      unread_notifications: notifications().filter((n) => n.read_at === null).length,
    });
  }),
  http.get(`${API}/today`, async ({ request }) => {
    await lag();
    return jsonWithEtag(request, todayBody());
  }),
  http.get(`${API}/market/overview`, () => HttpResponse.json(MARKET_OVERVIEW)),
  http.get(`${API}/watchlist`, () => HttpResponse.json(WATCHLIST)),
  http.get(`${API}/horizon-assessments`, async ({ request }) => {
    await lag();
    const code = new URL(request.url).searchParams.get('security_code');
    if (!code) return validation('security_code', 'security_code 必填');
    const a = HORIZON_ASSESSMENTS[code];
    if (!a) return notFound('周期分类结果');
    return HttpResponse.json(currentUser()?.username === 'novice_user' ? noviceAssessment(a) : a);
  }),
  // v0.2.4 #14：account_id 可选；示例数据的持仓都在主账户，其他账户为空
  http.get(`${API}/portfolio`, ({ request }) => {
    const id = new URL(request.url).searchParams.get('account_id');
    if (!id || id === ACCOUNT_ID) return HttpResponse.json(PORTFOLIO);
    return HttpResponse.json({ ...PORTFOLIO, total_assets: '0.00', cash: '0.00', positions: [], exposure: { sector: [] } });
  }),
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
    if (freq === 'w') return notFound('周线（示例数据未提供）');
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
    const code = url.searchParams.get('code');
    const base = REASONS.filter((r) => (!status || r.status === status) && (!signalId || r.signal_id === signalId) && (!code || r.code === code));
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
    const r = REASONS.find((x) => x.id === params.id);
    return r ? HttpResponse.json(r) : notFound('不可执行原因');
  }),
  http.get(`${API}/signals`, ({ request }) => {
    const url = new URL(request.url);
    const code = url.searchParams.get('security_code');
    const since = url.searchParams.get('since');
    const sinceMs = since ? Date.parse(since) : NaN;
    if (since && Number.isNaN(sinceMs)) return validation('since', 'since 须为 ISO 8601 时间');
    const items = SIGNAL_EVENTS.filter((e) => (!code || e.security_code === code) && (!since || Date.parse(e.at) >= sinceMs)).sort((a, b) => b.at.localeCompare(a.at));
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

];

/** 路径存在但方法不对时的允许方法（评审 m2）；/admin/* 例外，按契约 §1.3 对外一律 404 */
function allowedMethods(url: URL): string[] {
  const out = new Set<string>();
  for (const h of routeHandlers) {
    const { method, path } = h.info;
    if (typeof method !== 'string' || typeof path !== 'string') continue;
    if (matchRequestUrl(url, path, url.origin).matches) out.add(method.toUpperCase());
  }
  return [...out];
}

export const handlers = [
  ...routeHandlers,
  // 兜底：方法不对 → 405 + Allow；其余 /api/v1/* → 404 信封（示例数据未覆盖）
  http.all(`${API}/*`, ({ request }) => {
    const url = new URL(request.url);
    const allow = url.pathname.startsWith(`${API}/admin/`) ? [] : allowedMethods(url);
    if (allow.length) {
      return HttpResponse.json(errorBody('METHOD_NOT_ALLOWED', `该端点不支持 ${request.method}`, { allowed: allow }), { status: 405, headers: { Allow: allow.join(', ') } });
    }
    return HttpResponse.json(errorBody('NOT_FOUND', `示例数据未覆盖该端点：${url.pathname}`), { status: 404 });
  }),
];
