/**
 * T-F03 个股档案 / 市场概览示例数据。
 * 契约已定义：/securities?q=、/market/overview、/securities/{code}/bars（这里补指数与周线）。
 * 其余端点契约 v0.2.6 仍未定义，结构见 api/marketTypes.ts，全部 // [待契约确认]。
 * 公告 url 一律用保留域名 example.com 占位，前端只当外链，不取内容。
 */
import type { DataStatus } from '../api/enums';
import type { Bar, BarsResponse, Gap, MarketOverview } from '../api/types';
import type {
  Announcement, Board, FactorGroup, FactorValue, FactorsResponse, FinancialPeriod, FinancialsResponse, FundFlowDay, FundFlowsResponse,
  SecurityHit, SecurityProfile, SectorFlow, SectorFlowsResponse, SectorKind,
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

// ---------------- 指数 ----------------
interface IndexSpec { code: string; name: string; prev_close: number; price: number; amount: number; seed: number }
export const INDEX_SPECS: IndexSpec[] = [
  { code: '000001.SH', name: '上证指数（示例）', prev_close: 3254.45, price: 3268.12, amount: 412_300_000_000, seed: 101 },
  { code: '399001.SZ', name: '深证成指（示例）', prev_close: 10451.36, price: 10432.55, amount: 538_100_000_000, seed: 103 },
  { code: '000300.SH', name: '沪深300（示例）', prev_close: 3921.7, price: 3934.25, amount: 268_400_000_000, seed: 107 },
  { code: '399006.SZ', name: '创业板指（示例）', prev_close: 2142.8, price: 2131.66, amount: 201_900_000_000, seed: 109 },
  { code: '000688.SH', name: '科创50（示例）', prev_close: 1012.34, price: 1018.92, amount: 61_200_000_000, seed: 113 },
  { code: '899050.BJ', name: '北证50（示例）', prev_close: 1105.2, price: 1098.47, amount: 15_300_000_000, seed: 127 },
];
const indexOf = (code: string) => INDEX_SPECS.find((s) => s.code === code);

/** v0.2.3 #9 §7.3 最小结构（示例数据） */
export const MARKET_OVERVIEW: MarketOverview = {
  trade_date: TRADE_DATE, session: 'morning',
  indices: INDEX_SPECS.map((s) => ({
    security_code: s.code, name: s.name, price: f2(s.price), change_pct: f2(((s.price - s.prev_close) / s.prev_close) * 100), amount: f2(s.amount), t: NOW,
  })),
  breadth: { up: 2861, down: 2104, flat: 213, limit_up: 47, limit_down: 9 },
  regime: TERMINAL_ACCOUNT.regime, regime_position_range: TERMINAL_ACCOUNT.regime_position_range, turnover_total: '950400000000',
  data_status: 'fresh', data_as_of: NOW, gaps: [],
};

function indexDaily(s: IndexSpec): BarsResponse {
  const r = rng(s.seed * 31);
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
      pre_close: i === 0 ? null : f2(closes[i - 1]), volume: String(Math.round(amount / close / 100) * 100), amount: f2(amount), avg_price: null,
    };
  });
  return { security_code: s.code, name: s.name, freq: 'd', adjust: 'none', pre_close: null, items, next_before: null, data_status: 'fresh', data_as_of: NOW, gaps: [] };
}
function indexIntraday(s: IndexSpec): BarsResponse {
  const r = rng(s.seed * 17);
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
      pre_close: null, volume: String(Math.round(amount / p / 100) * 100), amount: f2(amount), avg_price: null,
    });
    prev = p;
  }
  return { security_code: s.code, name: s.name, freq: '1m', adjust: 'none', pre_close: f2(s.prev_close), items, next_before: null, data_status: 'fresh', data_as_of: NOW, gaps: [] };
}
export const indexBars = (code: string, freq: '1m' | 'd') => {
  const s = indexOf(code);
  return s ? (freq === '1m' ? indexIntraday(s) : indexDaily(s)) : null;
};

/**
 * 周线：由日线按自然周聚合，t 取该周最后一个交易日 // [待契约确认] 周线 t 的取值口径（周末日期 / 周五 / 最后交易日）
 */
export function toWeekly(daily: BarsResponse): BarsResponse {
  const groups = new Map<string, Bar[]>();
  for (const b of daily.items) {
    const d = new Date(`${b.t.slice(0, 10)}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
    const k = d.toISOString().slice(0, 10);
    groups.set(k, [...(groups.get(k) ?? []), b]);
  }
  let prevClose: string | null = null;
  const items: Bar[] = [...groups.values()].map((g) => {
    const bar: Bar = {
      t: g[g.length - 1].t, open: g[0].open, close: g[g.length - 1].close,
      high: f2(Math.max(...g.map((x) => Number(x.high)))), low: f2(Math.min(...g.map((x) => Number(x.low)))),
      pre_close: prevClose, volume: String(g.reduce((a, x) => a + Number(x.volume), 0)), amount: f2(g.reduce((a, x) => a + Number(x.amount), 0)), avg_price: null,
    };
    prevClose = bar.close;
    return bar;
  });
  return { ...daily, freq: 'w', items };
}

// ---------------- 搜索 / 主数据 ----------------
/** 契约 §7.3 /securities?q=：代码前缀或名称包含；最多 20 条 */
export function searchSecurities(q: string): SecurityHit[] {
  const k = q.trim().toUpperCase();
  if (!k) return [];
  // [待契约确认] 搜索结果是否包含指数：契约只给 {security_code, name}，无类型字段；mock 只返回个股，指数从 /market 进入
  const all: SecurityHit[] = SECURITY_CODES.map((c) => ({ security_code: c, name: specBrief(c)!.name }));
  return all.filter((h) => h.security_code.startsWith(k) || h.name.includes(q.trim())).slice(0, 20);
}

const boardOf = (code: string): Board => (code.endsWith('.BJ') ? 'bse' : code.startsWith('688') ? 'star' : code.startsWith('300') ? 'chinext' : 'main');
const CONCEPTS = ['高股息（示例）', '人工智能（示例）', '半导体（示例）', '储能（示例）', '创新药（示例）', '数据要素（示例）', '机器人（示例）'];

/** [待契约确认] GET /securities/{code} */
export function securityProfile(code: string): SecurityProfile | null {
  const s = specBrief(code);
  if (!s) return null;
  const r = rng(s.seed * 7);
  const total = Math.round((5 + r() * 120) * 1e8);
  const listYear = 1999 + Math.floor(r() * 24);
  return {
    security_code: s.code, name: s.name, exchange: s.code.slice(-2) as SecurityProfile['exchange'], board: boardOf(s.code),
    industry: `${s.sector}（示例）`, concepts: [CONCEPTS[s.seed % CONCEPTS.length], CONCEPTS[(s.seed + 3) % CONCEPTS.length]],
    list_date: `${listYear}-${String(1 + Math.floor(r() * 12)).padStart(2, '0')}-${String(1 + Math.floor(r() * 27)).padStart(2, '0')}`,
    status: SUSPENDED.has(s.code) ? 'suspended' : 'listed', risk_warning: false,
    total_shares: String(total), float_shares: String(Math.round(total * (0.55 + r() * 0.45))),
    data_status: 'fresh', data_as_of: '2026-11-02T08:30:00+08:00', gaps: [],
  };
}

// ---------------- 财务 ----------------
const PERIODS = ['2026-09-30', '2026-06-30', '2026-03-31', '2025-12-31', '2025-09-30', '2025-06-30', '2025-03-31', '2024-12-31'];
const announceOf = (p: string) => {
  const y = Number(p.slice(0, 4));
  return p.endsWith('03-31') ? `${y}-04-28` : p.endsWith('06-30') ? `${y}-08-28` : p.endsWith('09-30') ? `${y}-10-29` : `${y + 1}-04-25`;
};
/** [待契约确认] GET /securities/{code}/financials（累计口径，金额单位元） */
export function financials(code: string): FinancialsResponse | null {
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
      period_end: p, announce_date: announceOf(p), revenue: f2(rev), revenue_yoy_pct: f2((grow - 1) * 100 + 4), net_profit: f2(np),
      net_profit_yoy_pct: f2((r() - 0.4) * 60), eps: (np / (8 + s.seed) / 1e8).toFixed(3), roe_pct: f2(margin * 60 * q(p) * (0.8 + r() * 0.4)),
      gross_margin_pct: partial && i === 0 ? null : f2(margin * 100 + 12 + r() * 10), debt_ratio_pct: f2(30 + r() * 45),
      operating_cash_flow: f2(np * (0.4 + r() * 1.2) * (r() < 0.15 ? -1 : 1)),
    };
  });
  const gaps: Gap[] = partial ? [{ key: 'financials.gross_margin', reason: 'not_yet_published', message: '最新报告期毛利率未更新（示例）' }] : [];
  return { security_code: s.code, name: s.name, items, data_status: partial ? 'partial' : 'fresh', data_as_of: '2026-11-01T20:00:00+08:00', gaps };
}

// ---------------- 资金流 ----------------
/** [待契约确认] GET /securities/{code}/fund-flows?days= */
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
      trade_date: d, main_net: f2(main), super_large_net: f2(sl), large_net: f2(lg), medium_net: f2(md), small_net: f2(-main - md),
      main_net_pct: f2((main / scale) * 100),
    };
  });
  const gaps: Gap[] = suspended
    ? [{ key: 'capital', reason: 'upstream_error', message: '停牌，当日无资金流（示例）' }]
    : s.data_status === 'partial' ? [{ key: 'capital', reason: 'not_yet_published', message: '当日资金流尚未更新（约 30 分钟一次，示例）' }] : [];
  const status: DataStatus = gaps.length ? 'partial' : s.data_status === 'stale' ? 'stale' : 'fresh';
  return { security_code: s.code, name: s.name, items, data_status: status, data_as_of: s.data_as_of, gaps };
}

// ---------------- 因子 ----------------
const FACTOR_DEFS: { id: string; name: string; group: FactorGroup; unit: string | null; base: number; spread: number }[] = [
  { id: 'f.pe_ttm', name: '市盈率 PE(TTM)', group: 'value', unit: '倍', base: 8, spread: 60 },
  { id: 'f.pb', name: '市净率 PB', group: 'value', unit: '倍', base: 0.6, spread: 8 },
  { id: 'f.dividend_yield', name: '股息率(TTM)', group: 'value', unit: '%', base: 0, spread: 6 },
  { id: 'f.roe_ttm', name: 'ROE(TTM)', group: 'quality', unit: '%', base: 2, spread: 22 },
  { id: 'f.gross_margin', name: '毛利率', group: 'quality', unit: '%', base: 10, spread: 50 },
  { id: 'f.revenue_yoy', name: '营收同比', group: 'growth', unit: '%', base: -15, spread: 50 },
  { id: 'f.np_yoy', name: '归母净利同比', group: 'growth', unit: '%', base: -30, spread: 90 },
  { id: 'f.mom_20d', name: '20 日涨跌幅', group: 'momentum', unit: '%', base: -12, spread: 26 },
  { id: 'f.mom_60d', name: '60 日涨跌幅', group: 'momentum', unit: '%', base: -20, spread: 45 },
  { id: 'f.vol_60d', name: '60 日年化波动率', group: 'volatility', unit: '%', base: 15, spread: 45 },
  { id: 'f.turnover_20d', name: '20 日平均换手率', group: 'liquidity', unit: '%', base: 0.3, spread: 6 },
  { id: 'f.amount_20d', name: '20 日日均成交额', group: 'liquidity', unit: '亿元', base: 0.5, spread: 40 },
];
/** [待契约确认] GET /securities/{code}/factors：分位为 0–100（全市场 / 申万一级行业内） */
export function factors(code: string): FactorsResponse | null {
  const s = specBrief(code);
  if (!s) return null;
  const r = rng(s.seed * 23);
  const bj = code.endsWith('.BJ');
  const items: FactorValue[] = FACTOR_DEFS.map((d) => {
    const x = r();
    const missing = bj && d.group === 'value' && d.id === 'f.dividend_yield';
    return {
      factor_id: d.id, name: d.name, group: d.group, unit: d.unit, value: missing ? null : f2(d.base + x * d.spread),
      pct_rank_market: missing ? null : f2(Math.min(99.9, x * 100)), pct_rank_industry: missing ? null : f2(Math.min(99.9, Math.max(0.1, x * 100 + (r() - 0.5) * 30))),
    };
  });
  const gaps: Gap[] = bj ? [{ key: 'f.dividend_yield', reason: 'no_source', message: '北交所股息率暂无数据源（示例）' }] : [];
  return {
    security_code: s.code, name: s.name, trade_date: '2026-10-30', calc_version: 'factors-0.1（示例）', items,
    data_status: gaps.length ? 'partial' : 'fresh', data_as_of: '2026-10-30T18:30:00+08:00', gaps,
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
/** [待契约确认] GET /securities/{code}/announcements（按发布时间倒序；url 为保留域名占位） */
export function announcements(code: string): Announcement[] | null {
  const s = specBrief(code);
  if (!s) return null;
  return ANN_TITLES.map(([title, category], i) => {
    const id = `ann_${s.code.slice(0, 6)}_${String(i + 1).padStart(3, '0')}`;
    return {
      id, published_at: `${ANN_DATES[i]}T${i % 2 ? '17:30' : '20:05'}:00+08:00`, title, category,
      // 第 7 条故意不给链接，演示“无原文链接”
      url: i === 6 ? null : `https://example.com/disclosure/${s.code}/${id}.pdf`,
    };
  });
}

// ---------------- 板块资金 ----------------
const INDUSTRIES = ['银行', '电子', '计算机', '医药生物', '食品饮料', '煤炭', '基础化工', '机械设备', '有色金属', '电力设备', '汽车', '非银金融', '通信', '传媒'];
const CONCEPT_NAMES = ['人工智能', '半导体', '储能', '机器人', '低空经济', '创新药', '高股息', '数据要素', '固态电池', '消费电子', '算力', '卫星互联网'];
/** [待契约确认] GET /market/sector-flows?kind= */
export function sectorFlows(kind: SectorKind, limit: number): SectorFlowsResponse {
  const names = kind === 'industry' ? INDUSTRIES : CONCEPT_NAMES;
  const r = rng(kind === 'industry' ? 501 : 503);
  const items: SectorFlow[] = names.map((n, i) => {
    const chg = (r() - 0.45) * 5;
    const leaderCode = SECURITY_CODES.find((c) => specBrief(c)!.sector === n) ?? SECURITY_CODES[i % 7];
    const ls = specBrief(leaderCode)!;
    return {
      sector_id: `${kind}_${String(i + 1).padStart(3, '0')}`, name: `${n}（示例）`, change_pct: f2(chg), main_net: f2((chg + (r() - 0.5) * 2) * 6e8),
      up_count: Math.round(10 + r() * 80), down_count: Math.round(5 + r() * 60),
      leader: { security_code: ls.code, name: ls.name, change_pct: f2(((ls.price - ls.prev_close) / ls.prev_close) * 100) },
    };
  });
  items.sort((a, b) => Number(b.main_net) - Number(a.main_net));
  return {
    kind, trade_date: TRADE_DATE, items: items.slice(0, Math.min(Math.max(limit, 1), 50)), data_status: 'fresh', data_as_of: '2026-11-02T10:30:00+08:00', gaps: [],
  };
}
