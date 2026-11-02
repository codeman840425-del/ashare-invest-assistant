/**
 * MSW 处理器：按契约 v0.2.8 §7 的路径与响应结构返回示例数据。只拦截同源 `/api/v1/*`。
 * 未实现的端点统一返回 404 + 契约错误信封（code=NOT_FOUND），便于发现漏接。
 */
import { http, HttpResponse, delay, matchRequestUrl } from 'msw';
import type { TerminalScope, TodayResponse } from '../api/types';
import type { SectorKind } from '../api/marketTypes';
import { accountHandlers } from './accountHandlers';
import { resetStrategies, strategyHandlers } from './strategyHandlers';
import { reasonsNow, resetSignals, signalHandlers, signalsNow } from './signalHandlers';
import { draftsNow, planHandlers, resetPlanDrafts } from './planHandlers';
import { candidateHandlers, resetCandidates } from './candidateHandlers';
import { errorBody, jsonWithEtag, notFound, page, validation } from './handlerUtils';
import { allNotifications, findNotification, markAllNotificationsRead, markNotificationRead, resetNotificationStore } from './notificationStore';
import { resetStreamMock, streamHandlers } from './streamHandlers';
import { currentUser, resetSession } from './session';
import { licenceState } from './licenceStore';
import { LICENCE_UNAVAILABLE } from '../i18n/licenceLabels';
import type { DataStatus } from '../api/enums';
import type { Gap } from '../api/types';
import {
  ACCOUNT_ID, DAILY_REPORTS, HORIZON_ASSESSMENTS, noviceAssessment, DAILY_REPORT_LIST, HEALTH_READY, NOW, PORTFOLIO, QUOTES,
  SIGNAL_EVENTS, SUGGESTIONS, SUGGESTION_LIST, TERMINAL_ACCOUNT, TERMINAL_ROWS, TRADE_DATE, WATCHLIST, dailyBars, intradayBars,
} from './fixtures';
import {
  ETF_QUOTES, INDEX_SPECS, MARKET_OVERVIEW, announcements, announcementsMeta, factors, financials, fundFlows, indexBars, searchSecurities, sectorFlows,
  etfNotApplicable, isEtf, securityProfile, toWeekly,
} from './marketFixtures';
import { ENUMS } from '../api/enums';
import { TODAY_EVIDENCE, riskEvents, todayAlerts, todayDataGaps, todayPlanTriggers, todaySamples } from './todayFixtures';

export { errorBody };

const API = '/api/v1';

// 会话内可变状态：通知已读 / SSE 推送新增（notificationStore，T-F14）
const notifications = allNotifications;
export function resetMockState() {
  resetNotificationStore();
  resetStreamMock();
  resetSession();
  resetStrategies();
  resetSignals();
  resetPlanDrafts();
  resetCandidates();
}

/** 浏览器里加一点延迟让加载态可见；测试（node）里不延迟 */
const lag = () => (typeof window !== 'undefined' && import.meta.env.MODE !== 'test' ? delay(80) : Promise.resolve());

const isIndex = (code: string) => INDEX_SPECS.some((x) => x.code === code);
/** 指数没有财务、资金流：200 + 空列表 + unavailable + no_source（§7.3 v0.2.7） */
const indexEmpty = (code: string, key: string) => ({
  security_code: code, name: INDEX_SPECS.find((x) => x.code === code)!.name, items: [], sources: [],
  data_status: 'unavailable' as DataStatus, data_as_of: NOW, gaps: [{ key, reason: 'no_source', message: '指数没有该项数据（示例）' }] as Gap[],
});

const LEVEL: Record<string, number> = { info: 1, warning: 2, critical: 3 };

/**
 * 契约 v0.2.6：用户数据证书不可用时，行情读取接口仍返回缓存，但 data_status 为 stale / unavailable，
 * gaps 带 reason=data_licence_unavailable（评审 T-F22a M2）。用 setMockLicence(uid, {status:'expired'}) 等切换。
 */
function licenceOut(): boolean {
  const u = currentUser();
  return !!u && LICENCE_UNAVAILABLE.includes(licenceState(u.id));
}
const licenceGap = (key: string): Gap => ({ key, reason: 'data_licence_unavailable', message: '你的数据证书不可用，展示的是缓存数据（示例）' });
type Block = { data_status: DataStatus; gaps: Gap[] };
/** stale：保留缓存内容；unavailable：清空列表（没有可用缓存） */
function degrade<T extends Block>(body: T, key: string, mode: 'stale' | 'unavailable' = 'stale'): T {
  if (!licenceOut()) return body;
  const out = { ...body, data_status: mode, gaps: [...body.gaps, licenceGap(key)] };
  return mode === 'unavailable' && 'items' in out ? { ...out, items: [] } : out;
}

/** v0.2.3 #12：/today 首页聚合 mock（契约 §7.3；每个列表 ≤ 50，more 表示是否截断） */
function todayBody(): TodayResponse {
  const more = <T,>(items: T[]) => ({ items: items.slice(0, 50), more: items.length > 50 });
  const report = DAILY_REPORTS[0];
  const samples = todaySamples();
  const events = riskEvents().filter((e) => e.status === 'active');
  const u = currentUser();
  const licOut = !!u && (licenceOut() || licenceState(u.id) === 'not_set');
  const alerts = todayAlerts();
  const triggers = todayPlanTriggers();
  // 只带被引用到的 evidence（契约：alerts、plan_triggers 的 evidence_ids 都能在 evidence[] 找到）
  const used = new Set([...alerts, ...triggers].flatMap((x) => x.evidence_ids));
  return {
    server_time: NOW, trade_date: TRADE_DATE, session: 'morning',
    market: { regime: TERMINAL_ACCOUNT.regime, regime_position_range: TERMINAL_ACCOUNT.regime_position_range, data_status: 'fresh' },
    focus: more(TERMINAL_ROWS.filter((r) => r.focus)),
    // T-F18：取自计划草案 mock 的当前状态（待确认 + 条件已变）
    pending_plan_drafts: more(draftsNow().filter((d) => d.status === 'pending' || d.status === 'stale').map((d) => ({
      id: d.id, security_code: d.security_code, name: d.name, action: d.action, valid_until: d.valid_until, status: d.status,
    }))),
    released_reasons: more([...reasonsNow().filter((r) => r.status === 'released' && r.released_at).map((r) => {
      const cs = signalsNow().find((c) => c.id === r.signal_id);
      return { reason_id: r.id, signal_id: r.signal_id, code: r.code, security_code: cs?.security_code ?? '', name: cs?.name ?? '', released_at: r.released_at! };
    }), ...samples.released]),
    // v0.2.7：risk_event_id 指向 /risk-controls/events 中 status=active 的事件
    risk_flags: more(events.map(({ control, level, message, gated_actions, quantity_cap, evidence_ids, security_code, name, id }) => ({
      control, level, message, gated_actions, quantity_cap, evidence_ids, security_code, name, risk_event_id: id,
    })).sort((a, b) => LEVEL[b.level] - LEVEL[a.level])),
    invalidations_today: more(samples.invalidations),
    daily_report: { date: TRADE_DATE, status: 'not_yet' },
    reconciliation: report.reconciliation,
    unread_notifications: notifications().filter((n) => n.read_at === null).length,
    alerts: more(alerts),
    plan_triggers: more(triggers),
    data_gaps: { items: todayDataGaps(licOut).slice(0, 50), more: false },
    evidence: TODAY_EVIDENCE.filter((e) => used.has(e.id)),
  };
}

const routeHandlers = [
  // SSE /stream（契约 §8，T-F14，见 streamHandlers.ts；全部在本地生成，不发外网请求）
  ...streamHandlers,
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
  // v0.2.7 §7.5 风控事件：?status=active|cleared&control=&security_code=，triggered_at desc, id desc
  http.get(`${API}/risk-controls/events`, ({ request }) => {
    const url = new URL(request.url);
    const st = url.searchParams.get('status');
    if (st && !['active', 'cleared'].includes(st)) return validation('status', 'status 取值为 active|cleared');
    const control = url.searchParams.get('control');
    const code = url.searchParams.get('security_code');
    return HttpResponse.json(page(riskEvents().filter((e) => (!st || e.status === st) && (!control || e.control === control) && (!code || e.security_code === code)), url));
  }),
  http.get(`${API}/market/overview`, () => HttpResponse.json(degrade(MARKET_OVERVIEW, 'market.overview'))),
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
    // T-B46 R6 ③：示例的其他账户没有现金记录 → cash="0.00"，gaps 列 cash / user_input_missing；没有估算行，不为 partial
    return HttpResponse.json({
      ...PORTFOLIO, total_assets: '0.00', cash: '0.00', positions: [], exposure: { sector: [] }, data_status: 'fresh',
      gaps: [{ key: 'cash', reason: 'user_input_missing', message: '该账户还没有现金记录（示例）' }],
    });
  }),
  http.get(`${API}/quotes`, ({ request }) => {
    const codes = (new URL(request.url).searchParams.get('codes') ?? '').split(',').filter(Boolean);
    if (codes.length > 200) return validation('codes', 'codes 最多 200 个');
    // ETF 只在明确请求时返回（示例自选里没有 ETF）
    const items = codes.length ? [...QUOTES, ...ETF_QUOTES].filter((q) => codes.includes(q.security_code)) : QUOTES;
    return HttpResponse.json({ items: items.map((q) => degrade(q, `quote.${q.security_code}`)) });
  }),
  http.get(`${API}/securities/:code/bars`, async ({ params, request }) => {
    await lag();
    const url = new URL(request.url);
    // 评审 T-F22a m16：契约规定 freq 必填
    const freq = url.searchParams.get('freq');
    if (!freq) return validation('freq', 'freq 必填');
    const adjust = url.searchParams.get('adjust') ?? (freq === '1m' ? 'none' : 'qfq');
    if (!['1m', 'd', 'w'].includes(freq)) return validation('freq', 'freq 取值为 1m|d|w');
    if (freq === '1m' && adjust !== 'none') return validation('adjust', '1m 只支持 adjust=none');
    const code = String(params.code);
    // 个股用 fixtures 规格，指数用 marketFixtures；周线由日线聚合（T-F03）
    const day = dailyBars(code) ?? indexBars(code, 'd');
    const res = freq === '1m' ? intradayBars(code) ?? indexBars(code, '1m') : freq === 'w' ? day && toWeekly(day) : day;
    if (!res) return notFound('证券');
    // 契约：before + limit 向前翻页，limit 默认 500、最大 2000；截取后 next_before 指向更早一页
    const limit = Number(url.searchParams.get('limit') ?? 500);
    if (!Number.isInteger(limit) || limit < 1 || limit > 2000) return validation('limit', 'limit 取值 1–2000');
    const before = url.searchParams.get('before');
    const pool = before ? res.items.filter((b) => b.t < before) : res.items;
    const items = pool.slice(-limit);
    const body = { ...res, items, next_before: pool.length > items.length ? items[0].t : null };
    // 证书不可用：分时没有可用缓存 → unavailable；日/周保留缓存 → stale
    return HttpResponse.json(degrade(body, `bars.${code}.${freq}`, freq === '1m' ? 'unavailable' : 'stale'));
  }),

  // ---- T-F03 个股档案 / 市场概览 ----
  // 契约 §7.3（v0.2.7）：证券搜索（不分页）；/securities?q= 为别名，结构保持 [{security_code, name}]
  http.get(`${API}/securities/search`, async ({ request }) => {
    await lag();
    const url = new URL(request.url);
    const q = (url.searchParams.get('q') ?? '').normalize('NFKC').replace(/\s+/g, '');
    if (q.length < 1 || q.length > 20) return validation('q', 'q 归一化后长度 1–20');
    const limit = Number(url.searchParams.get('limit') ?? 20);
    if (!Number.isInteger(limit) || limit < 1 || limit > 50) return validation('limit', 'limit 取值 1–50');
    const types = (url.searchParams.get('types') ?? '').split(',').filter(Boolean);
    if (types.some((t) => !['stock', 'cdr', 'etf', 'index'].includes(t))) return validation('types', 'types 取值 stock|cdr|etf|index');
    return HttpResponse.json(searchSecurities(q, { types, limit }));
  }),
  http.get(`${API}/securities`, async ({ request }) => {
    await lag();
    const q = new URL(request.url).searchParams.get('q') ?? '';
    if (!q.trim()) return validation('q', 'q 必填');
    return HttpResponse.json(searchSecurities(q).items.map(({ security_code, name }) => ({ security_code, name })));
  }),
  http.get(`${API}/securities/:code`, async ({ params }) => {
    await lag();
    const p = securityProfile(String(params.code));
    return p ? HttpResponse.json(degrade(p, `profile.${p.security_code}`)) : notFound('证券');
  }),
  // 指数：财务、资金流返回 200 空列表 + unavailable + no_source（§7.3 v0.2.7）
  http.get(`${API}/securities/:code/financials`, async ({ params, request }) => {
    await lag();
    const code = String(params.code);
    const limit = Number(new URL(request.url).searchParams.get('limit') ?? 8);
    if (!Number.isInteger(limit) || limit < 1 || limit > 40) return validation('limit', 'limit 取值 1–40');
    if (isIndex(code)) return HttpResponse.json(indexEmpty(code, 'financials'));
    if (isEtf(code)) return HttpResponse.json(etfNotApplicable(code, 'financials'));
    const f = financials(code, limit);
    return f ? HttpResponse.json(degrade(f, 'financials')) : notFound('证券');
  }),
  http.get(`${API}/securities/:code/fund-flows`, async ({ params, request }) => {
    await lag();
    const code = String(params.code);
    const days = Number(new URL(request.url).searchParams.get('days') ?? 60);
    if (!Number.isInteger(days) || days < 1 || days > 250) return validation('days', 'days 取值 1–250');
    if (isIndex(code)) return HttpResponse.json(indexEmpty(code, 'fund_flows'));
    if (isEtf(code)) return HttpResponse.json(etfNotApplicable(code, 'fund_flows'));
    const f = fundFlows(code, days);
    return f ? HttpResponse.json(degrade(f, 'fund_flows')) : notFound('证券');
  }),
  http.get(`${API}/securities/:code/factors`, async ({ params }) => {
    await lag();
    if (isEtf(String(params.code))) {
      return HttpResponse.json({
        ...etfNotApplicable(String(params.code), 'factors'), trade_date: '2026-10-30', factor_set_version: 'mr-factors-85（示例）', counts: { total: 0, by_category: {} },
      });
    }
    const f = factors(String(params.code));
    return f ? HttpResponse.json(f.items.length ? degrade(f, 'factors') : f) : notFound('证券');
  }),
  http.get(`${API}/securities/:code/announcements`, async ({ params, request }) => {
    await lag();
    if (isEtf(String(params.code))) {
      return HttpResponse.json({ ...page([], new URL(request.url)), ...announcementsMeta(), ...etfNotApplicable(String(params.code), 'announcements') });
    }
    const list = announcements(String(params.code));
    if (!list) return notFound('证券');
    return HttpResponse.json(degrade({ ...page(list, new URL(request.url)), ...announcementsMeta() }, 'announcements'));
  }),
  http.get(`${API}/market/sector-flows`, async ({ request }) => {
    await lag();
    const url = new URL(request.url);
    const kind = url.searchParams.get('kind') as SectorKind | null;
    if (!kind || !['industry', 'concept'].includes(kind)) return validation('kind', 'kind 必填，取值为 industry|concept');
    const sort = url.searchParams.get('sort') ?? 'main_net_desc';
    if (!(ENUMS.sector_sort as readonly string[]).includes(sort)) return validation('sort', 'sort 取值见 sector_sort');
    const limit = Number(url.searchParams.get('limit') ?? 20);
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) return validation('limit', 'limit 取值 1–100');
    return jsonWithEtag(request, degrade(sectorFlows(kind, limit, sort), `sector_flows.${kind}`, 'unavailable'));
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
  // 候选信号与不可执行原因（T-F17，见 signalHandlers.ts）
  ...signalHandlers,
  // 计划草案（T-F18，见 planHandlers.ts）
  ...planHandlers,
  // 研究候选（T-F23，见 candidateHandlers.ts）
  ...candidateHandlers,
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
    const unreadRaw = url.searchParams.get('unread');
    if (unreadRaw !== null && unreadRaw !== 'true' && unreadRaw !== 'false') return validation('unread', 'unread 取值为 true|false');
    const kind = url.searchParams.get('kind');
    if (kind !== null && !(ENUMS.notification_kind as readonly string[]).includes(kind)) return validation('kind', 'kind 不是有效的通知类型');
    const unread = unreadRaw === 'true';
    return HttpResponse.json(page(notifications().filter((n) => (!unread || n.read_at === null) && (!kind || n.kind === kind)), url));
  }),
  // §7.8：已读 / 全部已读幂等，204；重复调用不改已读时间
  http.post(`${API}/notifications/read-all`, () => {
    markAllNotificationsRead();
    return new HttpResponse(null, { status: 204 });
  }),
  http.post(`${API}/notifications/:id/read`, ({ params }) => {
    if (!findNotification(String(params.id))) return notFound('通知');
    markNotificationRead(String(params.id));
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
