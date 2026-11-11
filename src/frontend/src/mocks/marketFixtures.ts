/**
 * T-F03 个股档案 / 市场概览示例数据。
 * 结构按契约 v0.2.7 §5.1 / §7.3（T-A08）：/securities/search、/securities/{code}、financials、fund-flows、factors、
 * announcements、/market/sector-flows，以及指数日线与周线（§6.2）。
 * 公告 url 一律用保留域名 example.com 占位，前端只当外链，不取内容。
 */
import type { Board, DataStatus, SecurityRiskFlag } from '../api/enums';
import type { Bar, BarsResponse, Gap, MarketOverview } from '../api/types';
import type {
  Announcement, AnnouncementsResponse, FactorValue, FactorsResponse, FinancialPeriod, FinancialsResponse, FundFlowDay, FundFlowsResponse,
  ProviderRef, SecurityHit, SecurityProfile, SecuritySearchResponse, SectorFlow, SectorFlowsResponse, SectorKind,
} from '../api/marketTypes';
import { minuteEnds } from '../lib/market';
import { NOW, SECURITY_CODES, TERMINAL_ACCOUNT, TRADE_DATE, specBrief, tradingDays } from './fixtures';

const f2 = (n: number) => n.toFixed(2);
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}
const SUSPENDED = new Set(['601001.SH', '830001.BJ']);
const MAIRUI = (endpoint: string | null, fetched_at: string | null): ProviderRef => ({ provider: 'mairui', endpoint, fetched_at });
const MASTER_AS_OF = '2026-11-02';
const ATTRIBUTION = '证券列表来自上交所、深交所、北交所公开信息（示例）';

// ---------------- 指数 ----------------
interface IndexSpec { code: string; name: string; prev_close: number; price: number; amount: number; seed: number; dp?: number }
export const INDEX_SPECS: IndexSpec[] = [
  { code: '000001.SH', name: '上证指数（示例）', prev_close: 3254.45, price: 3268.12, amount: 412_300_000_000, seed: 101 },
  { code: '399001.SZ', name: '深证成指（示例）', prev_close: 10451.36, price: 10432.55, amount: 538_100_000_000, seed: 103 },
  { code: '000300.SH', name: '沪深300（示例）', prev_close: 3921.7, price: 3934.25, amount: 268_400_000_000, seed: 107 },
  { code: '399006.SZ', name: '创业板指（示例）', prev_close: 2142.8, price: 2131.66, amount: 201_900_000_000, seed: 109 },
  { code: '000688.SH', name: '科创50（示例）', prev_close: 1012.34, price: 1018.92, amount: 61_200_000_000, seed: 113 },
  { code: '899050.BJ', name: '北证50（示例）', prev_close: 1105.2, price: 1098.47, amount: 15_300_000_000, seed: 127 },
];
/** v0.2.8：ETF 示例（价格 3 位小数，每手 100 份）；行情走指数同款生成器，财务/资金流/因子/公告为 not_applicable */
export const ETF_SPECS: IndexSpec[] = [
  { code: '510300.SH', name: '示例沪深300ETF', prev_close: 3.912, price: 3.948, amount: 2_130_000_000, seed: 131, dp: 3 },
];
export const isEtf = (code: string) => ETF_SPECS.some((s) => s.code === code);
/** v0.2.8 #8：ETF 行情与股票同口径，价格 3 位小数（示例） */
export const ETF_QUOTES = ETF_SPECS.map((s) => ({
  security_code: s.code, name: s.name, price: s.price.toFixed(3), change_pct: f2(((s.price - s.prev_close) / s.prev_close) * 100),
  volume: String(Math.round(s.amount / s.price / 100) * 100), amount: f2(s.amount * 0.45), t: NOW,
  data_status: 'fresh' as DataStatus, data_as_of: NOW, gaps: [] as Gap[],
}));
/** v0.2.8 #6：ETF 的财务、资金流、因子、公告 → 200 + 空 items + unavailable + not_applicable */
export const etfNotApplicable = (code: string, key: string) => ({
  security_code: code, name: ETF_SPECS.find((x) => x.code === code)!.name, items: [] as never[], sources: [] as ProviderRef[],
  data_status: 'unavailable' as DataStatus, data_as_of: NOW, gaps: [{ key, reason: 'not_applicable', message: 'ETF 没有该项数据（示例）' }] as Gap[],
});
const indexOf = (code: string) => INDEX_SPECS.find((s) => s.code === code) ?? ETF_SPECS.find((s) => s.code === code);

/** v0.2.3 #9 §7.3 最小结构（示例数据） */
export const MARKET_OVERVIEW: MarketOverview = {
  trade_date: TRADE_DATE, session: 'morning',
  indices: INDEX_SPECS.map((s) => ({
    security_code: s.code, name: s.name, price: f2(s.price), change_pct: f2(((s.price - s.prev_close) / s.prev_close) * 100), amount: f2(s.amount), t: NOW,
  })),
  breadth: { up: 2861, down: 2104, flat: 213, limit_up: 47, limit_down: 9 },
  regime: TERMINAL_ACCOUNT.regime, regime_position_range: TERMINAL_ACCOUNT.regime_position_range, turnover_total: '950400000000.50',
  data_status: 'fresh', data_as_of: NOW, gaps: [],
};

function indexDaily(s: IndexSpec): BarsResponse {
  const r = rng(s.seed * 31);
  const f2 = (n: number) => n.toFixed(s.dp ?? 2);
  const days = tradingDays(TRADE_DATE, 120);
  const closes: number[] = new Array(days.length);
  closes[days.length - 1] = s.price;
  closes[days.length - 2] = s.prev_close;
  for (let i = days.length - 3; i >= 0; i--) closes[i] = closes[i + 1] / (1 + Math.sin(i / 17 + s.seed) * 0.003 + (r() - 0.5) * 0.016);
  const items: Bar[] = days.map((t, i) => {
    const close = closes[i];
    const open = i === 0 ? close : closes[i - 1] * (1 + (r() - 0.5) * 0.006);
    const amount = s.amount * (0.7 + r() * 0.6) * (i === days.length - 1 ? 0.45 : 1);
    return {
      t, open: f2(open), high: f2(Math.max(open, close) * (1 + r() * 0.007)), low: f2(Math.min(open, close) * (1 - r() * 0.007)), close: f2(close),
      pre_close: i === 0 ? null : f2(closes[i - 1]), volume: String(Math.round(amount / close / 100) * 100), amount: amount.toFixed(2), avg_price: null,
      // 盘中：当日 K 线尚未收盘
      is_final: t !== TRADE_DATE,
    };
  });
  return { security_code: s.code, name: s.name, freq: 'd', adjust: 'none', pre_close: null, items, next_before: null, adjust_as_of: null, data_status: 'fresh', data_as_of: NOW, gaps: [] };
}
function indexIntraday(s: IndexSpec): BarsResponse {
  const r = rng(s.seed * 17);
  const f2 = (n: number) => n.toFixed(s.dp ?? 2);
  const mins = minuteEnds();
  const n = mins.indexOf('10:31') + 1;
  let p = s.prev_close;
  let prev = s.prev_close;
  const items: Bar[] = [];
  for (let i = 0; i < n; i++) {
    const target = s.prev_close + ((s.price - s.prev_close) * i) / (n - 1);
    p = i === n - 1 ? s.price : p + (target - p) * 0.2 + (r() - 0.5) * s.price * 0.0012;
    const amount = (s.amount / 240) * (0.5 + r() * (i < 15 ? 2.2 : 0.9));
    items.push({
      t: `${TRADE_DATE}T${mins[i]}:00+08:00`, open: f2(prev), high: f2(Math.max(prev, p) * 1.0003), low: f2(Math.min(prev, p) * 0.9997), close: f2(p),
      pre_close: null, volume: String(Math.round(amount / p / 100) * 100), amount: amount.toFixed(2), avg_price: null, is_final: i < n - 1,
    });
    prev = p;
  }
  return { security_code: s.code, name: s.name, freq: '1m', adjust: 'none', pre_close: f2(s.prev_close), items, next_before: null, adjust_as_of: null, data_status: 'fresh', data_as_of: NOW, gaps: [] };
}
export const indexBars = (code: string, freq: '1m' | 'd') => {
  const s = indexOf(code);
  return s ? (freq === '1m' ? indexIntraday(s) : indexDaily(s)) : null;
};

/**
 * 周线（§6.2 v0.2.7）：由日线按自然周（周一至周日）聚合；t = 该周最后一个交易日；
 * 第一根的 pre_close 取该周第一根日 K 的 pre_close，之后为上一根周 K 的 close；整周无交易（全周停牌）不出 K 线；
 * is_final 只在该周最后一个交易日已收盘时为 true（这里以“该周所有日 K 都 is_final 且已不是本周”为准）。
 */
const dpOf = (v: string) => (v.split('.')[1] ?? '').length || 2;
export function toWeekly(daily: BarsResponse): BarsResponse {
  const groups = new Map<string, Bar[]>();
  for (const b of daily.items) {
    const d = new Date(`${b.t.slice(0, 10)}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
    const k = d.toISOString().slice(0, 10);
    groups.set(k, [...(groups.get(k) ?? []), b]);
  }
  const weekOf = (t: string) => {
    const d = new Date(`${t.slice(0, 10)}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
    return d.toISOString().slice(0, 10);
  };
  const currentWeek = weekOf(TRADE_DATE);
  let prevClose: string | null = null;
  const items: Bar[] = [];
  for (const [wk, all] of groups) {
    // 停牌日在日线中不出现（成交量为 0 的占位也剔除）；整周无交易则不出 K 线
    const g = all.filter((x) => Number(x.volume) > 0);
    if (!g.length) continue;
    const bar: Bar = {
      t: g[g.length - 1].t, open: g[0].open, close: g[g.length - 1].close,
      // 小数位跟随日线（ETF 为 3 位）
      high: Math.max(...g.map((x) => Number(x.high))).toFixed(dpOf(g[0].open)), low: Math.min(...g.map((x) => Number(x.low))).toFixed(dpOf(g[0].open)),
      pre_close: items.length === 0 ? g[0].pre_close : prevClose,
      volume: String(g.reduce((a, x) => a + Number(x.volume), 0)), amount: f2(g.reduce((a, x) => a + Number(x.amount), 0)), avg_price: null,
      is_final: wk !== currentWeek && g.every((x) => x.is_final),
    };
    prevClose = bar.close;
    items.push(bar);
  }
  return { ...daily, freq: 'w', items };
}

// ---------------- 搜索 / 主数据 ----------------
const boardOf = (code: string): Board => (code.endsWith('.BJ') ? 'bse' : code.startsWith('688') ? 'star' : code.startsWith('300') ? 'chinext' : 'main');
const exchangeOf = (code: string) => code.slice(-2) as SecurityHit['exchange'];
const CONCEPTS = ['高股息（示例）', '人工智能（示例）', '半导体（示例）', '储能（示例）', '创新药（示例）', '数据要素（示例）', '机器人（示例）'];
const TYPE_ORDER: SecurityHit['type'][] = ['stock', 'cdr', 'etf', 'index'];
const MATCH_ORDER: SecurityHit['match_kind'][] = ['code_exact', 'name_exact', 'initials_exact', 'code_prefix', 'name_prefix', 'initials_prefix', 'name_contains', 'former_name', 'former_code', 'fuzzy'];

/**
 * 契约 §7.3 GET /securities/search?q&types&include_delisted&limit（v0.2.7）：按 security_match_kind 层级排序。
 * 示例数据没有当前简称的拼音，只演示代码/名称的精确、前缀、包含三类命中，以及曾用名（T-F26）。
 */
/**
 * T-F26（契约 v0.2.9 内 #33 ②，§9 v0.2.9 验收 3）：曾用名示例。虚构夹具“示例银行”的曾用名“示例发展”，首字母 SLFZ。
 * 曾用名原文或其首字母完全相同 → match_kind=former_name，matched_text=曾用名原文。
 */
export const FORMER_NAMES: Record<string, { name: string; initials: string; until: string }[]> = {
  '600000.SH': [{ name: '示例发展', initials: 'SLFZ', until: '2019-06-30' }],
};
/** quote_missing 的取值由调用方按本人证书给（ETF、指数恒为 null，在这里统一处理） */
export type QuoteMissingOf = (code: string) => boolean | null;
/** 风险标记示例（契约 #29）：演示材料带 *ST（退市风险警示），仅为示例数据 */
export const DEMO_RISK_FLAG: Record<string, SecurityRiskFlag> = { '002001.SZ': 'star_st' };

export function searchSecurities(q: string, opts: { types?: string[]; limit?: number; quoteMissing?: QuoteMissingOf } = {}): SecuritySearchResponse {
  // 归一化：NFKC、去空白、转大写；600000.SH / SH600000 / 600000 都按代码处理
  const raw = q.normalize('NFKC').replace(/\s+/g, '');
  const up = raw.toUpperCase();
  const m = /^(?:SH|SZ|BJ)?(\d{1,6})(?:\.(?:SH|SZ|BJ))?$/.exec(up);
  const k = m ? m[1] : up;
  // v0.2.8 #4：默认 stock,cdr,etf；仍不含指数
  const types = opts.types?.length ? opts.types : ['stock', 'cdr', 'etf'];
  const pool: SecurityHit[] = [
    ...SECURITY_CODES.map((c): SecurityHit => ({
      security_code: c, name: specBrief(c)!.name, type: 'stock', exchange: exchangeOf(c), board: boardOf(c), listing_status: 'listed',
      risk_flag: DEMO_RISK_FLAG[c] ?? null, match_kind: 'fuzzy', matched_text: null, quote_missing: opts.quoteMissing ? opts.quoteMissing(c) : null,
    })),
    ...ETF_SPECS.map((s): SecurityHit => ({
      security_code: s.code, name: s.name, type: 'etf', exchange: exchangeOf(s.code), board: null, listing_status: 'listed',
      risk_flag: null, match_kind: 'fuzzy', matched_text: null, quote_missing: null,
    })),
    ...INDEX_SPECS.map((s): SecurityHit => ({
      security_code: s.code, name: s.name, type: 'index', exchange: exchangeOf(s.code), board: null, listing_status: null,
      risk_flag: null, match_kind: 'fuzzy', matched_text: null, quote_missing: null,
    })),
  ].filter((h) => types.includes(h.type));
  const kindOf = (h: SecurityHit): { match_kind: SecurityHit['match_kind']; matched_text: string | null } | null => {
    const hit = (match_kind: SecurityHit['match_kind'], matched_text: string | null = null) => ({ match_kind, matched_text });
    if (h.security_code.slice(0, 6) === k) return hit('code_exact');
    if (h.name === raw) return hit('name_exact');
    if (h.security_code.startsWith(k)) return hit('code_prefix');
    if (h.name.startsWith(raw)) return hit('name_prefix');
    if (h.name.includes(raw)) return hit('name_contains');
    const former = (FORMER_NAMES[h.security_code] ?? []).find((f) => f.name === raw || f.initials === up);
    if (former) return hit('former_name', former.name);
    return null;
  };
  const items = pool
    .map((h) => { const m = kindOf(h); return m ? { ...h, ...m } : { ...h, match_kind: null }; })
    .filter((h): h is SecurityHit => h.match_kind !== null)
    .sort((a, b) => MATCH_ORDER.indexOf(a.match_kind) - MATCH_ORDER.indexOf(b.match_kind) || TYPE_ORDER.indexOf(a.type) - TYPE_ORDER.indexOf(b.type) || a.security_code.localeCompare(b.security_code))
    .slice(0, Math.min(Math.max(opts.limit ?? 20, 1), 50));
  return { items, master_as_of: MASTER_AS_OF };
}

/** 契约 §7.3 GET /securities/{code}（v0.2.7 SecurityProfile；指数的板块、股本、行业为 null，概念为 []） */
export function securityProfile(code: string): SecurityProfile | null {
  const idx = INDEX_SPECS.find((x) => x.code === code);
  if (idx) {
    return {
      security_code: idx.code, name: idx.name, type: 'index', exchange: exchangeOf(idx.code), board: null, list_date: null, list_date_basis: null,
      delist_date: null, listing_status: 'listed', risk_flag: null, former_names: [], code_history: [], master_as_of: MASTER_AS_OF, attribution: ATTRIBUTION,
      industry: null, concepts: [], total_shares: null, float_shares: null, suspended: null,
      sources: [{ provider: 'exchange', endpoint: null, fetched_at: '2026-11-02T08:00:00+08:00' }],
      data_status: 'fresh', data_as_of: '2026-11-02T08:30:00+08:00', gaps: [],
    };
  }
  const etf = ETF_SPECS.find((x) => x.code === code);
  if (etf) {
    // v0.2.8 #5：ETF 的板块、上市依据、风险标记、股本、行业为 null，概念为 []，不计入缺失、不出 gap
    return {
      security_code: etf.code, name: etf.name, type: 'etf', exchange: exchangeOf(etf.code), board: null, list_date: '2012-05-28', list_date_basis: null,
      delist_date: null, listing_status: 'listed', risk_flag: null, former_names: [], code_history: [], master_as_of: MASTER_AS_OF, attribution: ATTRIBUTION,
      industry: null, concepts: [], total_shares: null, float_shares: null, suspended: false,
      sources: [{ provider: 'exchange', endpoint: null, fetched_at: '2026-11-02T08:00:00+08:00' }],
      data_status: 'fresh', data_as_of: '2026-11-02T08:30:00+08:00', gaps: [],
    };
  }
  const s = specBrief(code);
  if (!s) return null;
  const r = rng(s.seed * 7);
  const total = Math.round((5 + r() * 120) * 1e8);
  const listYear = 1999 + Math.floor(r() * 24);
  const bj = s.code.endsWith('.BJ');
  return {
    security_code: s.code, name: s.name, type: 'stock', exchange: exchangeOf(s.code), board: boardOf(s.code),
    list_date: `${listYear}-${String(1 + Math.floor(r() * 12)).padStart(2, '0')}-${String(1 + Math.floor(r() * 27)).padStart(2, '0')}`,
    list_date_basis: bj ? 'neeq_select' : 'listing', delist_date: null, listing_status: 'listed', risk_flag: DEMO_RISK_FLAG[s.code] ?? null,
    // 北交所示例演示代码切换历史（示例）
    former_names: (FORMER_NAMES[s.code] ?? []).map(({ name, until }) => ({ name, until })),
    code_history: bj ? [{ security_code: `43${s.code.slice(2, 6)}.BJ`, until: '2024-10-08' }] : [],
    master_as_of: MASTER_AS_OF, attribution: ATTRIBUTION,
    industry: { taxonomy: 'sw_l1', code: `SW${String(s.seed).padStart(4, '0')}`, name: `${s.sector}（示例）` },
    concepts: [CONCEPTS[s.seed % CONCEPTS.length], CONCEPTS[(s.seed + 3) % CONCEPTS.length]].map((name, i) => ({ code: `GN${s.seed}${i}`, name })),
    total_shares: String(total), float_shares: String(Math.round(total * (0.55 + r() * 0.45))),
    suspended: SUSPENDED.has(s.code),
    sources: [
      { provider: 'exchange', endpoint: null, fetched_at: '2026-11-02T08:00:00+08:00' },
      MAIRUI(null, '2026-11-02T08:30:00+08:00'),
    ],
    data_status: 'fresh', data_as_of: '2026-11-02T08:30:00+08:00', gaps: [],
  };
}

// ---------------- 财务 ----------------
const PERIODS = ['2026-09-30', '2026-06-30', '2026-03-31', '2025-12-31', '2025-09-30', '2025-06-30', '2025-03-31', '2024-12-31'];
const reportPeriodOf = (p: string): FinancialPeriod['report_period'] => (p.endsWith('03-31') ? 'q1' : p.endsWith('06-30') ? 'h1' : p.endsWith('09-30') ? 'q3' : 'fy');
const nextDay = (d: string) => {
  const x = new Date(`${d}T00:00:00Z`);
  x.setUTCDate(x.getUTCDate() + 1);
  return x.toISOString().slice(0, 10);
};
const announceOf = (p: string) => {
  const y = Number(p.slice(0, 4));
  return p.endsWith('03-31') ? `${y}-04-28` : p.endsWith('06-30') ? `${y}-08-28` : p.endsWith('09-30') ? `${y}-10-29` : `${y + 1}-04-25`;
};
/** §7.3 GET /securities/{code}/financials（累计口径，金额单位元；默认 8 期，最多 40） */
export function financials(code: string, limit = 8): FinancialsResponse | null {
  const s = specBrief(code);
  if (!s) return null;
  const r = rng(s.seed * 13);
  const annualRev = (20 + r() * 400) * 1e8;
  const margin = 0.05 + r() * 0.25;
  const q = (p: string) => (p.endsWith('03-31') ? 0.24 : p.endsWith('06-30') ? 0.49 : p.endsWith('09-30') ? 0.74 : 1);
  const partial = s.data_status === 'partial' || s.code === '688001.SH';
  const items: FinancialPeriod[] = PERIODS.map((p, i) => {
    const grow = 1 + (r() - 0.35) * 0.3;
    const rev = annualRev * q(p) * (i < 4 ? 1 : 0.92) * grow;
    const np = rev * margin * (0.8 + r() * 0.4);
    return {
      period_end: p, report_period: reportPeriodOf(p), announce_date: announceOf(p), available_from: nextDay(announceOf(p)), is_restated: false,
      revenue: f2(rev), revenue_yoy_pct: f2((grow - 1) * 100 + 4), net_profit: f2(np),
      net_profit_yoy_pct: f2((r() - 0.4) * 60), deducted_net_profit: f2(np * (0.88 + r() * 0.1)),
      eps: (np / (8 + s.seed) / 1e8).toFixed(3), bvps: (2 + r() * 12).toFixed(3), roe_pct: f2(margin * 60 * q(p) * (0.8 + r() * 0.4)),
      gross_margin_pct: partial && i === 0 ? null : f2(margin * 100 + 12 + r() * 10), debt_ratio_pct: f2(30 + r() * 45),
      operating_cash_flow: f2(np * (0.4 + r() * 1.2) * (r() < 0.15 ? -1 : 1)),
    };
  });
  const gaps: Gap[] = partial ? [{ key: 'financials.gross_margin', reason: 'not_yet_published', message: '最新报告期毛利率未更新（示例）' }] : [];
  return {
    security_code: s.code, name: s.name, items: items.slice(0, Math.min(Math.max(limit, 1), 40)), sources: [MAIRUI(null, '2026-11-01T20:00:00+08:00')],
    data_status: partial ? 'partial' : 'fresh', data_as_of: '2026-11-01T20:00:00+08:00', gaps,
  };
}

// ---------------- 资金流 ----------------
/** §7.3 GET /securities/{code}/fund-flows?days=（默认 60，最多 250） */
export function fundFlows(code: string, days: number): FundFlowsResponse | null {
  const s = specBrief(code);
  if (!s) return null;
  const r = rng(s.seed * 19);
  const suspended = SUSPENDED.has(code);
  const noToday = suspended || s.data_status === 'partial';
  const dates = tradingDays(TRADE_DATE, Math.min(Math.max(days, 1), 250)).filter((d) => !(noToday && d === TRADE_DATE));
  const scale = (s.volume_lots || 120000) * 100 * s.price;
  const items: FundFlowDay[] = dates.map((d, i) => {
    const sl = (r() - 0.5 + Math.sin(i / 6 + s.seed) * 0.25) * scale * 0.06;
    const lg = (r() - 0.5) * scale * 0.05;
    const md = (r() - 0.5) * scale * 0.04;
    const main = sl + lg;
    return {
      trade_date: d, amount: f2(scale * (0.7 + r() * 0.6)), main_net: f2(main), super_large_net: f2(sl), large_net: f2(lg), medium_net: f2(md),
      // 示例：最早一天的小单分档缺失，演示分档可为 null
      small_net: i === 0 ? null : f2(-main - md),
      main_net_pct: f2((main / scale) * 100),
      // 盘中：当日数据尚未收盘
      is_final: d !== TRADE_DATE,
    };
  });
  const gaps: Gap[] = suspended
    ? [{ key: 'capital', reason: 'upstream_error', message: '停牌，当日无资金流（示例）' }]
    : s.data_status === 'partial' ? [{ key: 'capital', reason: 'not_yet_published', message: '当日资金流尚未更新（约 30 分钟一次，示例）' }] : [];
  const status: DataStatus = gaps.length ? 'partial' : s.data_status === 'stale' ? 'stale' : 'fresh';
  return { security_code: s.code, name: s.name, items, sources: [MAIRUI(null, s.data_as_of)], data_status: status, data_as_of: s.data_as_of, gaps };
}

// ---------------- 因子 ----------------
/**
 * factor_category 键名契约【待 T003 补测】，示例数据暂用以下占位键（前端按原样分组，标签见 FACTOR_CATEGORY_LABEL）
 */
const FACTOR_DEFS: { id: string; feature_key: string | null; name: string; category: string; unit: string | null; base: number; spread: number }[] = [
  { id: 'f.pe_ttm', feature_key: 'pe_ttm', name: '市盈率 PE(TTM)', category: 'valuation', unit: '倍', base: 8, spread: 60 },
  { id: 'f.pb', feature_key: 'pb', name: '市净率 PB', category: 'valuation', unit: '倍', base: 0.6, spread: 8 },
  { id: 'f.dividend_yield', feature_key: null, name: '股息率(TTM)', category: 'valuation', unit: '%', base: 0, spread: 6 },
  { id: 'f.roe_ttm', feature_key: 'roe_ttm', name: 'ROE(TTM)', category: 'quality', unit: '%', base: 2, spread: 22 },
  { id: 'f.gross_margin', feature_key: null, name: '毛利率', category: 'quality', unit: '%', base: 10, spread: 50 },
  { id: 'f.revenue_yoy', feature_key: null, name: '营收同比', category: 'growth', unit: '%', base: -15, spread: 50 },
  { id: 'f.np_yoy', feature_key: null, name: '归母净利同比', category: 'growth', unit: '%', base: -30, spread: 90 },
  { id: 'f.mom_20d', feature_key: 'ret_20d', name: '20 日涨跌幅', category: 'momentum', unit: '%', base: -12, spread: 26 },
  { id: 'f.mom_60d', feature_key: null, name: '60 日涨跌幅', category: 'momentum', unit: '%', base: -20, spread: 45 },
  { id: 'f.vol_60d', feature_key: null, name: '60 日年化波动率', category: 'volatility', unit: '%', base: 15, spread: 45 },
  { id: 'f.turnover_20d', feature_key: null, name: '20 日平均换手率', category: 'liquidity', unit: '%', base: 0.3, spread: 6 },
  { id: 'f.amount_20d', feature_key: null, name: '20 日日均成交额', category: 'liquidity', unit: '亿元', base: 0.5, spread: 40 },
];
const FACTOR_UNIVERSE = 5300;
/** §7.3 GET /securities/{code}/factors：只给全市场排名（没有行业内分位）；指数返回空列表 + no_source */
export function factors(code: string): FactorsResponse | null {
  const idx = INDEX_SPECS.find((x) => x.code === code);
  if (idx) {
    // F-10 / T-A158：无因子批次 → trade_date、factor_set_version 均为 null，且**不**下发合成版本名
    return {
      security_code: idx.code, name: idx.name, trade_date: null, factor_set_version: null, counts: { total: 0, by_category: {} },
      items: [], sources: [], data_status: 'unavailable', data_as_of: '2026-10-30T18:30:00+08:00', gaps: [{ key: 'factors', reason: 'no_source', message: '指数没有因子数据（示例）' }],
    };
  }
  const s = specBrief(code);
  if (!s) return null;
  const r = rng(s.seed * 23);
  const bj = code.endsWith('.BJ');
  const items: FactorValue[] = FACTOR_DEFS.map((d) => {
    const x = r();
    const missing = bj && d.id === 'f.dividend_yield';
    const rank = Math.max(1, Math.round((1 - x) * FACTOR_UNIVERSE));
    return {
      factor_id: d.id, feature_key: d.feature_key, name: d.name, category: d.category, unit: d.unit, value: missing ? null : f2(d.base + x * d.spread),
      market_rank: missing ? null : rank, market_rank_pct: missing ? null : f2((1 - rank / FACTOR_UNIVERSE) * 100),
    };
  });
  const by_category: Record<string, number> = {};
  for (const it of items) by_category[it.category] = (by_category[it.category] ?? 0) + 1;
  const gaps: Gap[] = bj ? [{ key: 'factor.f.dividend_yield', reason: 'no_source', message: '北交所股息率暂无数据源（示例）' }] : [];
  return {
    security_code: s.code, name: s.name, trade_date: '2026-10-30', factor_set_version: 'mr-factors-85（示例）', counts: { total: items.length, by_category }, items,
    sources: [MAIRUI(null, '2026-10-30T18:30:00+08:00')], data_status: gaps.length ? 'partial' : 'fresh', data_as_of: '2026-10-30T18:30:00+08:00', gaps,
  };
}

// ---------------- 公告（只给外链） ----------------
const ANN_TITLES: [string, string][] = [
  ['2026 年第三季度报告（示例）', '定期报告'], ['关于股东减持计划实施进展的公告（示例）', '股东变动'], ['董事会决议公告（示例）', '公司治理'],
  ['关于召开临时股东大会的通知（示例）', '公司治理'], ['2026 年半年度报告（示例）', '定期报告'], ['关于回购股份进展的公告（示例）', '回购'],
  ['关于获得政府补助的公告（示例）', '其他'], ['2026 年半年度业绩预告（示例）', '业绩预告'], ['关于对外投资的公告（示例）', '重大事项'],
  ['2026 年第一季度报告（示例）', '定期报告'], ['2025 年年度报告（示例）', '定期报告'], ['2025 年度利润分配方案公告（示例）', '分红'],
  ['关于诉讼事项的公告（示例）', '重大事项'], ['关于股票交易异常波动的公告（示例）', '交易提示'],
];
const ANN_DATES = ['2026-10-29', '2026-10-21', '2026-10-15', '2026-09-26', '2026-08-28', '2026-08-12', '2026-07-30', '2026-07-12', '2026-06-18', '2026-04-28', '2026-04-25', '2026-04-25', '2026-03-11', '2026-02-06'];
/** §7.3 公告免责声明（契约原文） */
export const ANNOUNCEMENT_DISCLAIMER = '公告内容以交易所及上市公司披露原文为准，本系统仅提供标题与原文链接。';
/** §7.3 GET /securities/{code}/announcements（按发布时间倒序；url 为保留域名占位） */
export function announcements(code: string): Announcement[] | null {
  const s = specBrief(code);
  if (!s) return null;
  return ANN_TITLES.map(([title, raw], i) => {
    const id = `ann_${s.code.slice(0, 6)}_${String(i + 1).padStart(3, '0')}`;
    const published_at = `${ANN_DATES[i]}T${i % 2 ? '17:30' : '20:05'}:00+08:00`;
    return {
      id, published_at, title, category: raw === '定期报告' ? 'periodic_report' : 'other', category_raw: raw, level_raw: null,
      // 第 7 条演示“原始链接不在白名单”：url 为 null，url_host 仍是原始主机名（契约 v0.2.7：无链接时 url_host 才为 null）
      url: i === 6 ? null : `https://example.com/disclosure/${s.code}/${id}.pdf`, url_host: 'example.com',
      file_format: 'pdf', first_seen_at: published_at,
    };
  });
}
export const announcementsMeta = (): Pick<AnnouncementsResponse, 'disclaimer' | 'sources' | 'data_status' | 'data_as_of' | 'gaps'> => ({
  disclaimer: ANNOUNCEMENT_DISCLAIMER, sources: [MAIRUI(null, '2026-11-01T21:00:00+08:00')], data_status: 'fresh', data_as_of: '2026-11-01T21:00:00+08:00', gaps: [],
});

// ---------------- 板块资金 ----------------
const INDUSTRIES = ['银行', '电子', '计算机', '医药生物', '食品饮料', '煤炭', '基础化工', '机械设备', '有色金属', '电力设备', '汽车', '非银金融', '通信', '传媒'];
const CONCEPT_NAMES = ['人工智能', '半导体', '储能', '机器人', '低空经济', '创新药', '高股息', '数据要素', '固态电池', '消费电子', '算力', '卫星互联网'];
/** §7.3 GET /market/sector-flows?kind=&sort=&limit=（盘后数据，上一交易日） */
export function sectorFlows(kind: SectorKind, limit: number, sort = 'main_net_desc'): SectorFlowsResponse {
  const names = kind === 'industry' ? INDUSTRIES : CONCEPT_NAMES;
  const r = rng(kind === 'industry' ? 501 : 503);
  const items: SectorFlow[] = names.map((n, i) => {
    const chg = (r() - 0.45) * 5;
    const leaderCode = SECURITY_CODES.find((c) => specBrief(c)!.sector === n) ?? SECURITY_CODES[i % 7];
    const ls = specBrief(leaderCode)!;
    return {
      sector_code: `${kind === 'industry' ? 'SW' : 'GN'}${String(i + 1).padStart(4, '0')}`, name: `${n}（示例）`, change_pct: f2(chg),
      main_net: f2((chg + (r() - 0.5) * 2) * 6e8), amount: f2((40 + r() * 400) * 1e8),
      up_count: Math.round(10 + r() * 80), down_count: Math.round(5 + r() * 60),
      leader: { security_code: ls.code, name: ls.name, change_pct: f2(((ls.price - ls.prev_close) / ls.prev_close) * 100) },
    };
  });
  const [field, dir] = sort.startsWith('change_pct') ? (['change_pct', sort.endsWith('asc') ? 1 : -1] as const) : (['main_net', sort.endsWith('asc') ? 1 : -1] as const);
  items.sort((a, b) => dir * (Number(a[field]) - Number(b[field])));
  return {
    kind, taxonomy: kind === 'industry' ? 'sw_l1' : null, trade_date: '2026-10-30', items: items.slice(0, Math.min(Math.max(limit, 1), 100)),
    sources: [MAIRUI(null, '2026-10-30T18:00:00+08:00')], data_status: 'fresh', data_as_of: '2026-10-30T18:00:00+08:00', gaps: [],
  };
}
