/**
 * MSW 处理器：按契约 v0.2.6 §7 的路径与响应结构返回示例数据。只拦截同源 `/api/v1/*`。
 * 未实现的端点统一返回 404 + 契约错误信封（code=NOT_FOUND），便于发现漏接。
 */
import { http, HttpResponse, delay, matchRequestUrl } from 'msw';
import type { Notification, TerminalScope, TodayResponse } from '../api/types';
import type { SectorKind } from '../api/marketTypes';
import { accountHandlers } from './accountHandlers';
import { resetStrategies, strategyHandlers } from './strategyHandlers';
import { errorBody, jsonWithEtag, notFound, page, validation } from './handlerUtils';
import { currentUser, resetSession } from './session';
import {
  ACCOUNT_ID, CANDIDATE_SIGNALS, DAILY_REPORTS, HORIZON_ASSESSMENTS, noviceAssessment, DAILY_REPORT_LIST, HEALTH_READY, NOTIFICATIONS, NOW, PORTFOLIO, QUOTES, REASONS,
  SIGNAL_EVENTS, SUGGESTIONS, SUGGESTION_LIST, TERMINAL_ACCOUNT, TERMINAL_ROWS, TRADE_DATE, WATCHLIST, dailyBars, intradayBars,
} from './fixtures';
import {
  MARKET_OVERVIEW, announcements, factors, financials, fundFlows, indexBars, searchSecurities, sectorFlows, securityProfile, toWeekly,
} from './marketFixtures';

export { errorBody };

const API = '/api/v1';

// 会话内可变状态：已读
const readAt = new Map<string, string>();
const notifications = (): Notification[] => NOTIFICATIONS.map((n) => ({ ...n, read_at: n.read_at ?? readAt.get(n.id) ?? null }));
export function resetMockState() {
  readAt.clear();
  resetSession();
  resetStrategies();
}

/** 浏览器里加一点延迟让加载态可见；测试（node）里不延迟 */
const lag = () => (typeof window !== 'undefined' && import.meta.env.MODE !== 'test' ? delay(80) : Promise.resolve());

const LEVEL: Record<string, number> = { info: 1, warning: 2, critical: 3 };

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
  // 策略库最小模拟（T-F22，见 strategyHandlers.ts）
  ...strategyHandlers,
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
    if (codes.length > 200) return validation('codes', 'codes 最多 200 个');
    return HttpResponse.json({ items: codes.length ? QUOTES.filter((q) => codes.includes(q.security_code)) : QUOTES });
  }),
  http.get(`${API}/securities/:code/bars`, async ({ params, request }) => {
    await lag();
    const url = new URL(request.url);
    const freq = url.searchParams.get('freq') ?? 'd';
    const adjust = url.searchParams.get('adjust') ?? (freq === '1m' ? 'none' : 'qfq');
    if (!['1m', 'd', 'w'].includes(freq)) return validation('freq', 'freq 取值为 1m|d|w');
    if (freq === '1m' && adjust !== 'none') return validation('adjust', '1m 只支持 adjust=none');
    const code = String(params.code);
    // 个股用 fixtures 规格，指数用 marketFixtures；周线由日线聚合（T-F03）
    const day = dailyBars(code) ?? indexBars(code, 'd');
    const res = freq === '1m' ? intradayBars(code) ?? indexBars(code, '1m') : freq === 'w' ? day && toWeekly(day) : day;
    if (!res) return notFound('证券');
    const limit = Number(url.searchParams.get('limit') ?? 0);
    return HttpResponse.json(limit > 0 ? { ...res, items: res.items.slice(-limit) } : res);
  }),

  // ---- T-F03 个股档案 / 市场概览 ----
  // 契约 §7.3：证券搜索（不分页，最多 20 条）
  http.get(`${API}/securities`, async ({ request }) => {
    await lag();
    const q = new URL(request.url).searchParams.get('q') ?? '';
    if (!q.trim()) return validation('q', 'q 必填');
    return HttpResponse.json(searchSecurities(q));
  }),
  // [待契约确认] 以下端点契约 v0.2.6 仍未定义，结构见 api/marketTypes.ts
  http.get(`${API}/securities/:code`, async ({ params }) => {
    await lag();
    const p = securityProfile(String(params.code));
    return p ? HttpResponse.json(p) : notFound('证券');
  }),
  http.get(`${API}/securities/:code/financials`, async ({ params }) => {
    await lag();
    const f = financials(String(params.code));
    return f ? HttpResponse.json(f) : notFound('证券');
  }),
  http.get(`${API}/securities/:code/fund-flows`, async ({ params, request }) => {
    await lag();
    const days = Number(new URL(request.url).searchParams.get('days') ?? 60) || 60;
    const f = fundFlows(String(params.code), days);
    return f ? HttpResponse.json(f) : notFound('证券');
  }),
  http.get(`${API}/securities/:code/factors`, async ({ params }) => {
    await lag();
    const f = factors(String(params.code));
    return f ? HttpResponse.json(f) : notFound('证券');
  }),
  http.get(`${API}/securities/:code/announcements`, async ({ params, request }) => {
    await lag();
    const list = announcements(String(params.code));
    if (!list) return notFound('证券');
    return HttpResponse.json({ ...page(list, new URL(request.url)), data_status: 'fresh', data_as_of: '2026-11-01T21:00:00+08:00', gaps: [] });
  }),
  http.get(`${API}/market/sector-flows`, async ({ request }) => {
    await lag();
    const url = new URL(request.url);
    const kind = (url.searchParams.get('kind') ?? 'industry') as SectorKind;
    if (!['industry', 'concept'].includes(kind)) return validation('kind', 'kind 取值为 industry|concept');
    return HttpResponse.json(sectorFlows(kind, Number(url.searchParams.get('limit') ?? 20) || 20));
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
