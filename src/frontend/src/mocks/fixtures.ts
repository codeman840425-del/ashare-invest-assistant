import { projectNotification, type NotificationInput } from '../lib/notifications';
import { withDailyDimensions } from './phase2Fixtures';
/**
 * 示例数据（全部虚构）—— 按契约 v0.2.2 结构生成，仅供开发与测试（MSW）使用。
 * 证券代码/简称、价格、持仓、金额、策略名都只是演示，不对应任何真实账户、行情或策略；
 * 不联网，不调用后端或麦蕊接口。生成过程是确定性的（固定种子），便于截图与测试复现。
 */
import type {
  Action, ConfidenceLevel, DataStatus, Dimension, DimensionView, Horizon, Lifecycle, ReasonCode, StrategyEvalState, TLeg,
  CandidateSignalState, RiskLevel,
} from '../api/enums';
import { ENUMS } from '../api/enums';
import { minuteEnds } from '../lib/market';
import type {
  Bar, BarsResponse, CandidateSignal, DailyReport, DailyReportListItem, DimensionCell, DimensionMatrixRow, DimensionViewEntry,
  Evidence, Gap, HealthReady, Me, NonExecutableReason, Notification, Portfolio, PortfolioPosition, QuoteItem, ReleaseCondition, RiskFlag, RuleRef,
  SignalEvent, StrategyConclusion, Suggestion, SuggestionListItem, SuggestionSummary, TerminalAccount, TerminalRow,
  TextWithEvidence, WatchlistItem, WatchlistResponse, Divergence, HorizonAssessment, HorizonCap, HorizonReason,
} from '../api/types';

export const SAMPLE_LABEL = '示例数据';
export const NOW = '2026-11-02T10:31:00+08:00';
export const TRADE_DATE = '2026-11-02';
export const REPORT_DATE = '2026-10-30';
const DIMENSIONS = ENUMS.dimension;

/** 契约约定的虚构 ID 格式 00000000-0000-4000-8000-0000000000xx */
export const uid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
export const ACCOUNT_ID = uid(1);
const f2 = (n: number) => n.toFixed(2);

// ---------------- 策略（L2 模板，名称为示例） ----------------
/** v0.2.2 DimensionCell.rules_passed/rules_total/key_evidence_ids 只统计的规则角色 */
export const COUNTED_ROLES: ReadonlySet<string> = new Set(['entry', 'filter', 'hold']);
/** v0.2.3：exit_hits/exit_total 统计 role ∈ {weakening, exit} 且已求值的规则 */
export const EXIT_ROLES: ReadonlySet<string> = new Set(['weakening', 'exit']);

interface StrategyMeta { key: string; name: string; horizon: Horizon; version_no: number; lifecycle: Lifecycle; priority_weight: string; version_id: string; instance_id: string }
const STRATEGY_LIST: Omit<StrategyMeta, 'version_id' | 'instance_id'>[] = [
  { key: 'demo_trend', name: '趋势跟随（示例）', horizon: 'swing', version_no: 2, lifecycle: 'published', priority_weight: '1.00' },
  { key: 'demo_reversal', name: '超跌修复（示例）', horizon: 'short', version_no: 1, lifecycle: 'observing', priority_weight: '0.55' },
  { key: 'demo_value', name: '价值质量（示例）', horizon: 'long', version_no: 3, lifecycle: 'published', priority_weight: '1.00' },
  { key: 'demo_t', name: '日内做T（示例）', horizon: 'intraday_t', version_no: 1, lifecycle: 'published', priority_weight: '0.90' },
];
export const STRATEGIES: Record<string, StrategyMeta> = Object.fromEntries(
  STRATEGY_LIST.map((s, i) => [s.key, { ...s, version_id: uid(300 + i), instance_id: uid(200 + i) }]),
);

// ---------------- 证券规格 ----------------
/** released：已由系统解除的原因（T-F17 示例“自动重评状态”；不计入 executability） */
interface StratSpec { key: string; action: Action; score: number; conf: number; state?: CandidateSignalState; reasons?: ReasonCode[]; released?: ReasonCode[]; t_leg?: TLeg }
interface SecSpec {
  code: string; name: string; sector: string; prev_close: number; price: number; volume_lots: number;
  holding?: { qty: number; sellable: number; cost: number }; in_watchlist: boolean; focus: boolean;
  data_status: DataStatus; data_as_of: string; strategies: StratSpec[]; seed: number;
}

const SPECS: SecSpec[] = [
  {
    code: '600000.SH', name: '示例银行', sector: '银行', prev_close: 10.02, price: 10.24, volume_lots: 412300, in_watchlist: true, focus: true,
    holding: { qty: 10000, sellable: 10000, cost: 9.46 }, data_status: 'fresh', data_as_of: NOW, seed: 11,
    strategies: [
      { key: 'demo_trend', action: 'buy', score: 78, conf: 0.62, state: 'blocked', reasons: ['POSITION_CAP_REACHED', 'STRATEGY_CONFLICT'] },
      { key: 'demo_reversal', action: 'wait', score: 41, conf: 0.48 },
      { key: 'demo_value', action: 'reduce', score: 66, conf: 0.57, state: 'blocked', reasons: ['STRATEGY_CONFLICT'] },
    ],
  },
  {
    code: '000001.SZ', name: '演示科技', sector: '计算机', prev_close: 23.6, price: 23.18, volume_lots: 268100, in_watchlist: true, focus: true,
    holding: { qty: 3000, sellable: 3000, cost: 21.05 }, data_status: 'fresh', data_as_of: NOW, seed: 23,
    strategies: [
      { key: 'demo_trend', action: 'hold', score: 64, conf: 0.71 },
      { key: 'demo_value', action: 'hold', score: 59, conf: 0.66 },
    ],
  },
  {
    code: '300001.SZ', name: '演示电子', sector: '电子', prev_close: 41.3, price: 43.02, volume_lots: 156400, in_watchlist: true, focus: false,
    data_status: 'fresh', data_as_of: NOW, seed: 37,
    strategies: [{ key: 'demo_trend', action: 'buy', score: 82, conf: 0.74, state: 'drafted' }],
  },
  {
    code: '600002.SH', name: '演示医药', sector: '医药生物', prev_close: 18.4, price: 17.71, volume_lots: 98200, in_watchlist: false, focus: false,
    holding: { qty: 2000, sellable: 0, cost: 18.9 }, data_status: 'partial', data_as_of: NOW, seed: 41,
    strategies: [
      { key: 'demo_trend', action: 'sell', score: 71, conf: 0.52, state: 'blocked', reasons: ['T1_NOT_SELLABLE'] },
      { key: 'demo_value', action: 'hold', score: 55, conf: 0.39 },
    ],
  },
  {
    code: '002001.SZ', name: '演示材料', sector: '基础化工', prev_close: 12.85, price: 13.04, volume_lots: 187500, in_watchlist: true, focus: true,
    holding: { qty: 5000, sellable: 5000, cost: 12.2 }, data_status: 'fresh', data_as_of: NOW, seed: 53,
    strategies: [
      { key: 'demo_t', action: 'reduce', t_leg: 'sell_first', score: 69, conf: 0.58, state: 'drafted', released: ['NON_TRADING_TIME'] },
      { key: 'demo_trend', action: 'hold', score: 61, conf: 0.63 },
    ],
  },
  {
    code: '000002.SZ', name: '演示消费', sector: '食品饮料', prev_close: 56.2, price: 56.95, volume_lots: 64300, in_watchlist: true, focus: false,
    data_status: 'fresh', data_as_of: NOW, seed: 67,
    strategies: [
      { key: 'demo_value', action: 'buy', score: 73, conf: 0.6, state: 'blocked', reasons: ['COOLING_OFF', 'STRATEGY_CONFLICT'] },
      { key: 'demo_reversal', action: 'wait', score: 38, conf: 0.44 },
    ],
  },
  {
    code: '688001.SH', name: '演示芯片', sector: '电子', prev_close: 88.5, price: 86.9, volume_lots: 45200, in_watchlist: true, focus: false,
    data_status: 'stale', data_as_of: '2026-11-02T10:18:00+08:00', seed: 79,
    strategies: [
      { key: 'demo_trend', action: 'wait', score: 35, conf: 0.33 },
      { key: 'demo_reversal', action: 'wait', score: 47, conf: 0.36 },
    ],
  },
  {
    code: '601001.SH', name: '演示能源', sector: '煤炭', prev_close: 15.12, price: 15.12, volume_lots: 0, in_watchlist: true, focus: false,
    data_status: 'stale', data_as_of: '2026-10-30T15:00:00+08:00', seed: 83, strategies: [],
  },
  {
    code: '830001.BJ', name: '演示精工', sector: '机械设备', prev_close: 9.66, price: 9.66, volume_lots: 0, in_watchlist: true, focus: false,
    data_status: 'unavailable', data_as_of: '2026-10-30T15:00:00+08:00', seed: 97,
    strategies: [{ key: 'demo_trend', action: 'buy', score: 57, conf: 0.41, state: 'blocked', reasons: ['SUSPENDED'] }],
  },
];

// ---------------- 工具 ----------------
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}
const confLevel = (v: number): ConfidenceLevel => (v >= 0.7 ? 'high' : v >= 0.4 ? 'medium' : 'low');
const isBullish = (a: Action) => a === 'buy' || a === 'add';
const isBearish = (a: Action) => a === 'reduce' || a === 'sell';
const isDirectional = (a: Action) => a !== 'hold' && a !== 'wait';
const EVAL_STATE: Record<Action, StrategyEvalState> = {
  buy: 'entry_ok', add: 'entry_ok', hold: 'hold_ok', wait: 'not_triggered', reduce: 'weakening', sell: 'exit_signal',
};
const LEVEL_RANK: Record<RiskLevel, number> = { info: 1, warning: 2, critical: 3 };

export const SECURITY_CODES = SPECS.map((s) => s.code);
const specOf = (code: string) => SPECS.find((s) => s.code === code);
export const nameOf = (code: string) => specOf(code)?.name ?? code;
/** T-F03：个股档案 mock 复用的证券规格摘要（只读） */
export const specBrief = (code: string) => {
  const s = specOf(code);
  return s
    ? { code: s.code, name: s.name, sector: s.sector, prev_close: s.prev_close, price: s.price, volume_lots: s.volume_lots, data_status: s.data_status, data_as_of: s.data_as_of, seed: s.seed }
    : null;
};

function quoteGaps(s: SecSpec): Gap[] {
  if (s.data_status === 'stale') return [{ key: 'quote', reason: 'quota_deferred', message: '超过刷新间隔 ×2 未更新（示例）' }];
  if (s.data_status === 'unavailable') return [{ key: 'quote', reason: 'upstream_error', message: '停牌，无实时成交（示例）' }];
  if (s.data_status === 'partial') return [{ key: 'capital', reason: 'not_yet_published', message: '当日资金流尚未更新（约 30 分钟一次，示例）' }];
  return [];
}

// ---------------- 行情 / 自选 / 持仓 ----------------
export const QUOTES: QuoteItem[] = SPECS.map((s) => ({
  security_code: s.code, name: s.name, price: f2(s.price), change_pct: f2(((s.price - s.prev_close) / s.prev_close) * 100),
  volume: String(s.volume_lots * 100), amount: f2(s.volume_lots * 100 * s.price), t: s.data_as_of,
  data_status: s.data_status, data_as_of: s.data_as_of, gaps: quoteGaps(s),
}));

export const WATCHLIST: WatchlistResponse = {
  items: SPECS.filter((s) => s.in_watchlist).map((s, i): WatchlistItem => ({
    security_code: s.code, name: s.name, focus: s.focus, group: s.holding ? '持仓相关' : null, note: null,
    added_at: `2026-10-${String(10 + i).padStart(2, '0')}T20:00:00+08:00`, refresh_tier: s.focus ? 'tier1' : 'tier2',
  })),
  caps: { watchlist: 100, focus: 20 },
};

const CASH = 190000;
const positionsRaw = SPECS.filter((s) => s.holding).map((s) => {
  const h = s.holding!;
  const mv = h.qty * s.price;
  return { s, h, mv, pnl: (s.price - h.cost) * h.qty };
});
const MV = positionsRaw.reduce((a, p) => a + p.mv, 0);
/**
 * 示例可转债持仓（契约 v0.2.9 #1/#2，U3 已定）：不在证券主数据中（security_type=null）、无行情（estimated=true），
 * market_value / pnl / pnl_pct 为 null，weight_pct 与 total_assets 按成本估算，顶层 data_status=partial。
 * 不放进 SPECS（没有行情、自选与个股页数据）。前端只按 security_type / estimated 显示（T-B46 R6），不看代码前缀。
 */
const CB = { code: '113050.SH', name: '示例转债', qty: 100, sellable: 100, cost: 118.5 };
const CB_MV = CB.qty * CB.cost;
const TOTAL = CASH + MV + CB_MV;

/** 证券所属行业（示例；T-F18 计划草案的 sector_pct 用） */
export const sectorOf = (code: string): string | null => SPECS.find((x) => x.code === code)?.sector ?? null;

export const PORTFOLIO: Portfolio = {
  cash: f2(CASH),
  total_assets: f2(TOTAL),
  positions: positionsRaw
    .map(({ s, h, mv, pnl }): PortfolioPosition => ({
      security_code: s.code, name: s.name, security_type: 'stock', qty: String(h.qty), sellable_qty: String(h.sellable), cost_price: f2(h.cost),
      market_value: f2(mv), pnl: f2(pnl), pnl_pct: f2(((s.price - h.cost) / h.cost) * 100),
      weight_pct: f2((mv / TOTAL) * 100), estimated: false,
    }))
    .concat([{
      security_code: CB.code, name: CB.name, security_type: null, qty: String(CB.qty), sellable_qty: String(CB.sellable), cost_price: CB.cost.toFixed(3),
      market_value: null, pnl: null, pnl_pct: null, weight_pct: f2((CB_MV / TOTAL) * 100), estimated: true,
    }])
    .sort((a, b) => Number(b.weight_pct) - Number(a.weight_pct)),
  exposure: {
    sector: Object.entries(
      positionsRaw.reduce<Record<string, number>>((acc, { s, mv }) => ({ ...acc, [s.sector]: (acc[s.sector] ?? 0) + mv }), {}),
    )
      .sort((a, b) => b[1] - a[1])
      .map(([name, v]) => ({ name, pct: f2((v / TOTAL) * 100) }))
      // v0.2.9 #30 ③：没有行业归属的持仓（示例可转债，按成本估算）合并为“未分类”，不参与 RC4
      .concat([{ name: '未分类', pct: f2((CB_MV / TOTAL) * 100) }]),
  },
  // v0.2.9 #1：含无行情的估算行时顶层为 partial
  data_status: 'partial', data_as_of: NOW, gaps: [],
};

// ---------------- 证据 ----------------
function buildEvidence(s: SecSpec): Evidence[] {
  const r = rng(s.seed);
  const asOfDay = `${REPORT_DATE}T15:00:00+08:00`;
  const fetchedDay = `${REPORT_DATE}T16:40:00+08:00`;
  const ma20 = s.price * (0.95 + r() * 0.06);
  const ma60 = s.price * (0.92 + r() * 0.1);
  const mk = (id: string, key: string, value: Evidence['value'], unit: string | null, endpoint: string | null, intraday = false,
    provider: Evidence['provider'] = 'mairui', ep: Evidence['epistemic_type'] = 'fact'): Evidence => ({
    id, key, value, unit, provider, endpoint,
    data_as_of: intraday ? s.data_as_of : asOfDay,
    fetched_at: intraday ? s.data_as_of.replace(/:00\+/, ':05+') : fetchedDay,
    epistemic_type: ep,
  });
  return [
    mk('E1', 'price', f2(s.price), 'CNY', '/hsrl/ssjy_more', true),
    mk('E2', 'ma20', f2(ma20), 'CNY', null, false, 'system'),
    mk('E3', 'factor.ma_trend', s.price > ma20 ? 'up' : 'down', null, '/factor/momentum/{code}'),
    mk('E4', 'ma60', f2(ma60), 'CNY', null, false, 'system'),
    mk('E5', 'factor.volume_ratio', (0.5 + r() * 1.4).toFixed(2), null, '/factor/momentum/{code}'),
    mk('E6', 'factor.main_5d_net', String(Math.round((r() - 0.5) * 9000)), '万元', '/factor/capital/{code}'),
    mk('E7', 'factor.pe_ttm_rank', (r() * 100).toFixed(1), '%', '/factor/valuation/{code}'),
    mk('E8', 'factor.roe_ttm', (4 + r() * 14).toFixed(2), '%', '/factor/quality/{code}'),
    mk('E9', 'factor.limit_up_count_20d', String(Math.floor(r() * 3)), '次', '/factor/sentiment/{code}'),
    mk('E10', 'sector.rs_20d', ((r() - 0.5) * 12).toFixed(2), '%', null, false, 'system', 'estimate'),
    mk('E11', 'factor.recent_event', r() > 0.5 ? '回购进展公告' : '无', null, '/factor/event/{code}'),
    mk('E12', 'atr14', f2(s.price * (0.018 + r() * 0.02)), 'CNY', null, false, 'system'),
  ];
}

const DIM_EVIDENCE: Record<Dimension, string> = {
  technical: 'E3', capital: 'E6', fundamental: 'E8', sentiment: 'E9', sector_market: 'E10', news: 'E11',
};
const DIM_RULE: Record<Dimension, { prefix: string; text: [string, string]; threshold: string | null }> = {
  technical: { prefix: 'T', text: ['收盘价站上 MA20 且 MA20 上行', '收盘价跌破 MA20'], threshold: 'up' },
  capital: { prefix: 'C', text: ['近 5 日主力资金净流入', '近 5 日主力资金净流出'], threshold: '0' },
  fundamental: { prefix: 'F', text: ['ROE(TTM) ≥ 8% 且估值分位 < 70%', '估值分位偏高（≥ 80%）'], threshold: '8' },
  sentiment: { prefix: 'S', text: ['近 20 日无连续炸板，情绪平稳', '近 20 日涨停后回落'], threshold: '2' },
  sector_market: { prefix: 'M', text: ['所属行业 20 日相对强弱为正', '所属行业 20 日相对强弱为负'], threshold: '0' },
  news: { prefix: 'N', text: ['近期公告类型偏正面（回购/增持）', '近期公告类型偏负面（减持/问询）'], threshold: null },
};

function viewsFor(s: SecSpec, st: StratSpec, ev: Evidence[]): Record<Dimension, DimensionView> {
  const r = rng(s.seed * 7 + st.key.length * 13);
  const out = {} as Record<Dimension, DimensionView>;
  DIMENSIONS.forEach((d) => {
    const x = r();
    let v: DimensionView;
    if (d === 'news') v = ev[10].value === '无' ? 'unknown' : 'neutral';
    else if (isBullish(st.action)) v = x < 0.6 ? 'bullish' : x < 0.85 ? 'neutral' : 'bearish';
    else if (isBearish(st.action)) v = x < 0.55 ? 'bearish' : x < 0.85 ? 'neutral' : 'bullish';
    else v = x < 0.3 ? 'bullish' : x < 0.7 ? 'neutral' : 'bearish';
    if (s.data_status === 'partial' && d === 'capital') v = 'unknown';
    if (st.key === 'demo_t' && d === 'fundamental') v = 'unknown';
    out[d] = v;
  });
  // 主样例：刻意制造“基本面 vs 技术”的分歧
  if (s.code === '600000.SH') {
    if (st.key === 'demo_trend') Object.assign(out, { technical: 'bullish', capital: 'bullish', fundamental: 'neutral', sector_market: 'bullish' });
    if (st.key === 'demo_value') Object.assign(out, { technical: 'neutral', fundamental: 'bearish', capital: 'neutral' });
    if (st.key === 'demo_reversal') Object.assign(out, { technical: 'neutral', sentiment: 'neutral', capital: 'neutral' });
  }
  return out;
}

const REASON_DEFS: Partial<Record<ReasonCode, { desc: string; rc: ReleaseCondition }>> = {
  POSITION_CAP_REACHED: {
    desc: '该股市值已占总资产约 22%，超过单只上限 20%（RC2）',
    rc: { kind: 'expr', expr: 'position_pct < 20', at: null, event: null, action: null, check_on: ['tick', 'holding_change'], human_text: '该股仓位占比回落到 20% 以下后自动重评', machine_checkable: true },
  },
  STRATEGY_CONFLICT: {
    desc: '您启用的其他策略对同一证券给出相反方向的候选信号，按规定并列展示、不自动拟定草案',
    rc: { kind: 'user_action', expr: null, at: null, event: null, action: 'choose_strategy_side', check_on: ['user_action', 'tick'], human_text: '由您选择采用某一方，或重评后各策略方向一致时自动解除', machine_checkable: false },
  },
  T1_NOT_SELLABLE: {
    desc: '今日买入的 2,000 股按 T+1 规则当日不可卖出',
    rc: { kind: 'time', expr: null, at: '2026-11-03T09:30:00+08:00', event: null, action: null, check_on: ['schedule', 'holding_change'], human_text: '下一交易日 09:30 或可卖数量 ≥ 1 手时自动重评', machine_checkable: true },
  },
  COOLING_OFF: {
    desc: '该股 10-28 触发止损卖出，处于冷静期（默认 3 个交易日）',
    rc: { kind: 'time', expr: null, at: '2026-11-03T09:30:00+08:00', event: null, action: null, check_on: ['schedule'], human_text: '冷静期于 2026-11-03 09:30 到期后自动重评', machine_checkable: true },
  },
  NON_TRADING_TIME: {
    desc: '盘前集合竞价阶段，日内做T 策略不在可执行时段（示例）',
    rc: { kind: 'time', expr: null, at: '2026-11-02T09:30:00+08:00', event: null, action: null, check_on: ['schedule'], human_text: '到达连续竞价时段（09:30）后自动重评', machine_checkable: true },
  },
  SUSPENDED: {
    desc: '该证券停牌，无实时成交',
    rc: { kind: 'event', expr: null, at: null, event: 'security.resumed', action: null, check_on: ['tick', 'daily_close'], human_text: '复牌且行情恢复成交后自动重评', machine_checkable: true },
  },
};

export const CANDIDATE_SIGNALS: CandidateSignal[] = [];
export const REASONS: NonExecutableReason[] = [];
export const SUGGESTIONS: Suggestion[] = [];

function validUntil(h: Horizon) {
  return h === 'intraday_t' ? '2026-11-02T14:50:00+08:00' : h === 'short' ? '2026-11-03T15:00:00+08:00' : '2026-11-09T15:00:00+08:00';
}

let seq = 1000;
SPECS.forEach((s, si) => {
  const ev = buildEvidence(s);
  const atr = Number(ev[11].value);
  const gaps = quoteGaps(s);
  const strategies: StrategyConclusion[] = [];
  const csIds: string[] = [];
  const executableIds: string[] = [];
  const blockedIds: string[] = [];
  const allReasonIds: string[] = [];
  const allDraftIds: string[] = [];

  s.strategies.forEach((st) => {
    const meta = STRATEGIES[st.key];
    const views = viewsFor(s, st, ev);
    const r = rng(s.seed + st.score);
    const dimension_views: DimensionViewEntry[] = DIMENSIONS.map((d) => {
      const v = views[d];
      const rule = DIM_RULE[d];
      const passed = v === 'bullish' ? !isBearish(st.action) : v === 'bearish' ? isBearish(st.action) : r() > 0.5;
      const evId = DIM_EVIDENCE[d];
      // 示例：部分中性维度模拟“输入缺失、无法求值”（v0.2.2 passed = null）
      const missing = v === 'neutral' && r() < 0.35;
      const val = missing ? null : ev.find((e) => e.id === evId)!.value;
      const rules: RuleRef[] = v === 'unknown' ? [] : [{
        rule_id: `${rule.prefix}1`, snippet_id: null, snippet_version: null,
        // v0.2.2：数据缺失无法求值 → passed = null
        role: isBearish(st.action) ? 'exit' : st.action === 'hold' ? 'hold' : 'entry', dimension: d, passed: val == null ? null : passed,
        value: val == null ? null : String(val), threshold: rule.threshold, evidence_ids: [evId],
      }];
      return {
        dimension: d, view: v,
        score: v === 'unknown' ? null : Math.round(v === 'bullish' ? 65 + r() * 30 : v === 'bearish' ? 10 + r() * 30 : 40 + r() * 20),
        rules,
      };
    });
    const rule_refs = dimension_views.flatMap((dv) => dv.rules);
    const stops = {
      stop_loss: st.action === 'wait' ? null : f2(s.price - 2 * atr),
      take_profit: isBullish(st.action) || st.action === 'hold' ? f2(s.price + 3.5 * atr) : null,
      time_stop_days: meta.horizon === 'swing' ? 10 : meta.horizon === 'short' ? 3 : meta.horizon === 'intraday_t' ? 0 : 40,
    };
    const want: DimensionView = isBearish(st.action) ? 'bearish' : 'bullish';
    const against: DimensionView = isBearish(st.action) ? 'bullish' : 'bearish';
    const textIdx = isBearish(st.action) ? 1 : 0;
    const reasons: TextWithEvidence[] = dimension_views.filter((dv) => dv.view === want).slice(0, 3)
      .map((dv) => ({ text: DIM_RULE[dv.dimension].text[textIdx], expr: null, evidence_ids: [DIM_EVIDENCE[dv.dimension]] }));
    if (reasons.length === 0) {
      reasons.push({ text: st.action === 'wait' ? '入场条件未全部满足（3/5 条通过）' : '持有条件维持：未触发离场规则', expr: null, evidence_ids: ['E3'] });
    }
    const counter_evidence: TextWithEvidence[] = dimension_views.filter((dv) => dv.view === against).slice(0, 2)
      .map((dv) => ({ text: DIM_RULE[dv.dimension].text[1 - textIdx], expr: null, evidence_ids: [DIM_EVIDENCE[dv.dimension]] }));
    counter_evidence.push({ text: `量比 ${ev[4].value}，${Number(ev[4].value) < 0.8 ? '成交偏清淡' : '量能未明显放大'}（示例）`, expr: 'volume_ratio < 1.0', evidence_ids: ['E5'] });
    if (Number(meta.priority_weight) < 0.6) counter_evidence.push({ text: '该策略近 30 次模拟跟踪胜率 38%（n=30），已降低排序优先级', expr: null, evidence_ids: [] });
    const invalidation: TextWithEvidence[] = [
      { text: `连续 2 日收于 MA20（${ev[1].value}）下方`, expr: 'close < ma(close, 20) for 2 days', evidence_ids: ['E2'] },
      ...(stops.stop_loss ? [{ text: `盘中价格跌破 ${stops.stop_loss}（止损位）`, expr: `price < ${stops.stop_loss}`, evidence_ids: ['E1', 'E12'] }] : []),
      ...(st.key === 'demo_value' ? [{ text: '下一期季报 ROE(TTM) < 8%', expr: 'roe_ttm < 8 at next report', evidence_ids: ['E8'] }] : []),
    ];
    const confidence = { level: confLevel(Number((0.5 * st.conf).toFixed(2))), value: Number((0.5 * st.conf).toFixed(2)), components: { data_completeness: st.conf, dimension_agreement: null, condition_margin: null, margin_rules: [] } };

    let csId: string | null = null;
    if (isDirectional(st.action)) {
      csId = uid(seq++);
      csIds.push(csId);
      const reason_ids: string[] = [];
      (st.reasons ?? []).forEach((code) => {
        const rid = uid(seq++);
        reason_ids.push(rid);
        const def = REASON_DEFS[code]!;
        REASONS.push({
          id: rid, signal_id: csId!, security_code: s.code, name: s.name, code, description: def.desc,
          evidence: code === 'POSITION_CAP_REACHED' || code === 'SUSPENDED' ? [ev[0]] : [],
          release_condition: def.rc, status: 'active', detected_at: s.data_as_of, released_at: null, release_evidence: null, released_by: 'system',
        });
      });
      (reason_ids.length ? blockedIds : executableIds).push(csId);
      // 已解除的原因：系统按 release_condition 自动重评后解除（独立 id 段，不影响其他示例 id）
      (st.released ?? []).forEach((code) => {
        const rid = uid(7600 + REASONS.length);
        reason_ids.push(rid);
        const def = REASON_DEFS[code]!;
        REASONS.push({
          id: rid, signal_id: csId!, security_code: s.code, name: s.name, code, description: def.desc, evidence: [], release_condition: def.rc, status: 'released',
          detected_at: `${TRADE_DATE}T09:15:00+08:00`, released_at: `${TRADE_DATE}T09:30:00+08:00`,
          release_evidence: { session: 'morning', checked_at: `${TRADE_DATE}T09:30:00+08:00` }, released_by: 'system',
        });
      });
      allReasonIds.push(...reason_ids);
      const plan_draft_ids = st.state === 'drafted' ? [uid(seq++)] : [];
      allDraftIds.push(...plan_draft_ids);
      const risk_flags: RiskFlag[] = s.code === '600000.SH' && st.action === 'buy'
        ? [{ control: 'position_cap', level: 'warning', message: '该股已占总资产约 22%（上限 20%）', gated_actions: ['buy', 'add'], quantity_cap: '0', evidence_ids: ['E1'] }]
        : [];
      const base: CandidateSignal = {
        id: csId, instance_id: meta.instance_id, strategy_version_id: meta.version_id, strategy_key: st.key, strategy_name: meta.name,
        lifecycle: meta.lifecycle, security_code: s.code, name: s.name, horizon: meta.horizon, state: st.state ?? 'open',
        proposed_action: st.action, t_leg: st.t_leg ?? null, score: st.score, confidence: { level: confLevel(st.conf), value: st.conf }, stops, rule_refs, evidence: ev,
        counter_evidence, invalidation, model_refs: [], risk_flags,
        gate_results: [{ gate: 'gate_tradability', passed: !(st.reasons ?? []).includes('SUSPENDED') }, { gate: 'gate_data_fresh', passed: s.data_status === 'fresh' }],
        reason_ids, plan_draft_ids, valid_until: validUntil(meta.horizon), snapshot_id: uid(500 + si), feature_set_version: 'fs_3',
        created_at: s.data_as_of, data_status: s.data_status, data_as_of: s.data_as_of, gaps,
      };
      CANDIDATE_SIGNALS.push(base);
    }
    strategies.push({
      strategy_version_id: meta.version_id, strategy_key: st.key, strategy_name: meta.name, version_no: meta.version_no,
      instance_id: meta.instance_id, horizon: meta.horizon, lifecycle: meta.lifecycle, state: EVAL_STATE[st.action],
      action: st.action, t_leg: st.t_leg ?? null, candidate_signal_id: csId, score: st.score, confidence, rule_refs, model_refs: [],
      priority_weight: meta.priority_weight, priority_downweighted: Number(meta.priority_weight) < 1, dimension_views, stops,
      reasons, counter_evidence, invalidation, valid_until: isDirectional(st.action) ? validUntil(meta.horizon) : null,
    });
  });

  // 历史候选信号（已过期/已被取代），用于 K 线上的历史标记
  if (strategies.length) {
    const days = tradingDays(TRADE_DATE, 120);
    const r = rng(s.seed * 5);
    (['buy', 'reduce', 'buy'] as Action[]).forEach((a, i) => {
      const st = strategies[i % strategies.length];
      const meta = STRATEGIES[st.strategy_key];
      const day = days[24 + i * 28 + Math.floor(r() * 8)];
      CANDIDATE_SIGNALS.push({
        id: uid(seq++), instance_id: meta.instance_id, strategy_version_id: meta.version_id, strategy_key: meta.key, strategy_name: meta.name,
        lifecycle: meta.lifecycle, security_code: s.code, name: s.name, horizon: meta.horizon, state: i === 2 ? 'superseded' : 'expired',
        proposed_action: a, t_leg: null, score: 60 + i * 5, confidence: { level: 'medium', value: 0.5 }, stops: { stop_loss: null, take_profit: null, time_stop_days: 10 },
        rule_refs: st.rule_refs.length ? st.rule_refs : [{ rule_id: 'T1', snippet_id: null, snippet_version: null, role: 'entry', dimension: 'technical', passed: true, value: 'up', threshold: 'up', evidence_ids: ['E3'] }],
        evidence: ev, counter_evidence: st.counter_evidence, invalidation: st.invalidation, model_refs: [], risk_flags: [],
        gate_results: [{ gate: 'gate_tradability', passed: true }], reason_ids: [], plan_draft_ids: [],
        valid_until: `${day}T15:00:00+08:00`, snapshot_id: uid(600 + si * 3 + i), feature_set_version: 'fs_3',
        created_at: `${day}T16:45:00+08:00`, data_status: 'fresh', data_as_of: `${day}T15:00:00+08:00`, gaps: [],
      });
    });
  }

  const actions: Partial<Record<Action, number>> = {};
  strategies.forEach((x) => (actions[x.action] = (actions[x.action] ?? 0) + 1));
  // v0.2.3：≥ 2 个策略且 (action, t_leg) 全部相同 → unanimous
  const distinct = new Set(strategies.map((x) => `${x.action}|${x.t_leg ?? ''}`)).size;
  const consensusStatus = strategies.length === 0 ? 'none' : strategies.length === 1 ? 'single' : distinct === 1 ? 'unanimous' : 'divergent';

  const dimension_matrix: DimensionMatrixRow[] = DIMENSIONS.map((d) => {
    const cells: DimensionCell[] = strategies.map((x) => {
      const dv = x.dimension_views.find((v) => v.dimension === d)!;
      return {
        strategy_key: x.strategy_key, strategy_version_id: x.strategy_version_id, view: dv.view, score: dv.score,
        // v0.2.2：只统计 role ∈ {entry, filter, hold}；key_evidence_ids 取其中 passed = true 的前 3 个证据
        key_evidence_ids: dv.rules.filter((ru) => COUNTED_ROLES.has(ru.role) && ru.passed === true).flatMap((ru) => ru.evidence_ids).slice(0, 3),
        rules_passed: dv.rules.filter((ru) => COUNTED_ROLES.has(ru.role) && ru.passed === true).length,
        rules_total: dv.rules.filter((ru) => COUNTED_ROLES.has(ru.role)).length,
        exit_hits: dv.rules.filter((ru) => EXIT_ROLES.has(ru.role) && ru.passed === true).length,
        exit_total: dv.rules.filter((ru) => EXIT_ROLES.has(ru.role) && ru.passed !== null).length,
      };
    });
    return { dimension: d, divergent: isDivergent(cells.map((c) => c.view)), cells };
  });

  const risk_flags: RiskFlag[] = [];
  if (s.code === '600000.SH') risk_flags.push({ control: 'position_cap', level: 'warning', message: '该股已占总资产约 22%（上限 20%）', gated_actions: ['buy', 'add'], quantity_cap: '0', evidence_ids: ['E1'] });
  if (s.code === '600002.SH') risk_flags.push({ control: 'stop_take', level: 'critical', message: '现价 17.71 已接近策略止损位，请核对失效条件', gated_actions: [], quantity_cap: null, evidence_ids: ['E1', 'E12'] });
  if (s.sector === '电子') risk_flags.push({ control: 'sector_concentration', level: 'info', message: '电子行业自选 2 只；若均建仓，行业占比将约 38%（上限 40%）', gated_actions: [], quantity_cap: null, evidence_ids: [] });

  const divergence: Divergence[] = consensusStatus !== 'divergent' ? [] : s.code === '600000.SH'
    ? [
        { dimensions: ['fundamental', 'technical'], summary: '估值分位偏高（价值质量策略偏空） vs 趋势向上（趋势跟随策略偏多）', resolving_info: [{ description: '下一期季报 profit_yoy 是否转正', subscribable: true }, { description: '估值分位是否回落到 70% 以下', subscribable: true }] },
        { dimensions: ['capital'], summary: '近 5 日主力净流入，但所属行业 20 日资金净流出', resolving_info: [{ description: '行业资金流连续 3 日转正', subscribable: true }] },
      ]
    : [{ dimensions: dimension_matrix.filter((m) => m.divergent).map((m) => m.dimension), summary: '各策略周期不同、关注维度不同，结论不一致', resolving_info: [{ description: '等待下一交易日收盘后重评', subscribable: false }] }];

  const ACTION_CN: Record<Action, string> = { buy: '买入条件满足', add: '加仓条件满足', hold: '持有条件维持', reduce: '减仓条件满足', sell: '卖出条件满足', wait: '条件未满足，等待' };
  SUGGESTIONS.push({
    id: uid(100 + si), security_code: s.code, name: s.name, created_at: s.data_as_of, status: 'active',
    engine_policy: null, origin: s.code === '600000.SH' ? 'intraday_event' : 'daily_batch', snapshot_id: uid(500 + si), feature_set_version: 'fs_3',
    candidate_signal_ids: csIds,
    executability: {
      status: csIds.length === 0 ? 'not_applicable' : executableIds.length ? 'executable' : 'blocked',
      reason_ids: allReasonIds, executable_signal_ids: executableIds, blocked_signal_ids: blockedIds,
    },
    plan_draft_ids: allDraftIds,
    horizon_assessment: { suitable: s.strategies.length ? Array.from(new Set(s.strategies.map((x) => STRATEGIES[x.key].horizon))) : ['long'], user_overridden: false },
    consensus: { status: consensusStatus, actions },
    strategies, dimension_matrix, divergence, risk_flags, evidence: ev,
    explanation: {
      source: 'template',
      text: strategies.length
        ? `${s.name}：${strategies.map((x) => `${x.strategy_name}的规则信号为“${ACTION_CN[x.action]}”，规则满足度 ${x.score}`).join('；')}。各策略结论并列展示，系统不合成单一结论。（示例数据）`
        : `${s.name}：暂无启用的策略实例，仅展示行情。（示例数据）`,
      llm_call_id: null,
    },
    supersedes_id: s.code === '600000.SH' ? uid(99) : null,
    superseded_by_id: null,
    data_status: s.data_status, data_as_of: s.data_as_of,
    gaps: [...gaps, { key: 'news', reason: 'no_source', message: '本产品不提供新闻资讯，消息维度仅基于公告类型与标题' }],
  });
});

/**
 * 契约 v0.2.9 #30 ③：STRATEGY_CONFLICT 的 evidence 每个对方信号一条，key 为保留键 `signal.conflict_signal_id`，
 * value 为对方信号 id（provider=system、epistemic_type=fact）。示例按同证券、方向相反、未结束的信号写入。
 */
const DIR = (a: string) => (a === 'buy' || a === 'add' ? 'buy' : a === 'sell' || a === 'reduce' ? 'sell' : null);
for (const r of REASONS) {
  if (r.code !== 'STRATEGY_CONFLICT') continue;
  const me = CANDIDATE_SIGNALS.find((c) => c.id === r.signal_id);
  if (!me) continue;
  const others = CANDIDATE_SIGNALS.filter((o) => o.id !== me.id && o.security_code === me.security_code && DIR(o.proposed_action) && DIR(me.proposed_action) && DIR(o.proposed_action) !== DIR(me.proposed_action));
  r.evidence = others.map((o, i) => ({
    id: `EC${i + 1}`, key: 'signal.conflict_signal_id', value: o.id, unit: null, provider: 'system', endpoint: null,
    data_as_of: r.detected_at, fetched_at: r.detected_at, epistemic_type: 'fact',
  }));
}

/** 维度分歧（v0.2.3）：同时存在 bullish 与 bearish；neutral、unknown 不参与 */
export function isDivergent(views: DimensionView[]): boolean {
  return views.includes('bullish') && views.includes('bearish');
}

export function summarize(sg: Suggestion): SuggestionSummary {
  const scores = sg.strategies.map((x) => x.score).filter((x): x is number => x !== null);
  return {
    id: sg.id, created_at: sg.created_at, status: sg.status, consensus: sg.consensus.status,
    actions: sg.strategies.map((x) => ({ strategy_key: x.strategy_key, strategy_name: x.strategy_name, action: x.action, t_leg: x.t_leg, lifecycle: x.lifecycle })),
    executability_status: sg.executability.status,
    divergent_dimensions: sg.dimension_matrix.filter((m) => m.divergent).map((m) => m.dimension),
    top_score: scores.length ? Math.max(...scores) : null,
  };
}

export const SUGGESTION_LIST: SuggestionListItem[] = SUGGESTIONS.map((sg) => ({ ...summarize(sg), security_code: sg.security_code, name: sg.name }));
export const suggestionOf = (code: string) => SUGGESTIONS.find((x) => x.security_code === code);

// ---------------- 终端聚合 ----------------
export const TERMINAL_ACCOUNT: TerminalAccount = {
  account_id: ACCOUNT_ID, total_assets: f2(TOTAL), cash_available: f2(CASH), position_pct: f2((MV / TOTAL) * 100),
  pnl_day: '1864.00', regime: 'range', regime_position_range: { min_pct: '40.00', max_pct: '60.00' }, data_status: 'fresh',
};

export const TERMINAL_ROWS: TerminalRow[] = (() => {
  const rows = SPECS.map((s): TerminalRow & { _w: number; _added: number } => {
    const sg = suggestionOf(s.code)!;
    const q = QUOTES.find((x) => x.security_code === s.code)!;
    const pos = PORTFOLIO.positions.find((p) => p.security_code === s.code);
    const maxLevel = sg.risk_flags.reduce<RiskLevel | null>((m, f) => (m === null || LEVEL_RANK[f.level] > LEVEL_RANK[m] ? f.level : m), null);
    return {
      security_code: s.code, name: s.name, in_watchlist: s.in_watchlist, focus: s.focus,
      quote: s.data_status === 'unavailable' ? null : { price: q.price, change_pct: q.change_pct, amount: q.amount, t: q.t },
      holding: pos ? { qty: pos.qty, sellable_qty: pos.sellable_qty, cost_price: pos.cost_price, weight_pct: pos.weight_pct, pnl: pos.pnl, pnl_pct: pos.pnl_pct, security_type: pos.security_type, estimated: pos.estimated } : null,
      suggestion: summarize(sg),
      active_reason_count: REASONS.filter((r) => r.status === 'active' && sg.candidate_signal_ids.includes(r.signal_id)).length,
      max_risk_level: maxLevel, data_status: s.data_status, data_as_of: s.data_status === 'unavailable' ? null : s.data_as_of,
      _w: pos ? Number(pos.weight_pct) : -1, _added: SPECS.indexOf(s),
    };
  });
  // 契约排序：持仓按 weight_pct 降序 → 重点关注 → 其余自选按加入时间
  rows.sort((a, b) => {
    const ga = a.holding ? 0 : a.focus ? 1 : 2;
    const gb = b.holding ? 0 : b.focus ? 1 : 2;
    if (ga !== gb) return ga - gb;
    if (ga === 0) return b._w - a._w;
    return a._added - b._added;
  });
  return rows.map(({ _w, _added, ...row }) => { void _w; void _added; return row; });
})();

// ---------------- K 线 / 分时 ----------------
export function tradingDays(end: string, n: number): string[] {
  const out: string[] = [];
  const d = new Date(`${end}T00:00:00Z`);
  while (out.length < n) {
    const wd = d.getUTCDay();
    if (wd !== 0 && wd !== 6) out.unshift(d.toISOString().slice(0, 10));
    d.setUTCDate(d.getUTCDate() - 1);
  }
  return out;
}

/** 示例：前复权基准日（§5.1 v0.2.7 adjust_as_of） */
export const ADJUST_AS_OF = '2026-10-30';

/** 示例：最近 120 根之前的历史日 K 根数（窗口加载演示用，共约 2.4 年） */
export const HISTORY_DAYS = 480;

function historyBars(firstDay: string, firstClose: number, seed: number, lots: number): Bar[] {
  const days = tradingDays(firstDay, HISTORY_DAYS + 1).slice(0, -1);
  const r = rng(seed * 97 + 13);
  const closes: number[] = new Array(days.length);
  let next = firstClose;
  for (let i = days.length - 1; i >= 0; i--) {
    closes[i] = next / (1 + Math.sin(i / 17 + seed) * 0.005 + (r() - 0.5) * 0.03);
    next = closes[i];
  }
  return days.map((t, i) => {
    const close = closes[i];
    const prev = i === 0 ? null : closes[i - 1];
    const open = (prev ?? close) * (1 + (r() - 0.5) * 0.012);
    const high = Math.max(open, close) * (1 + r() * 0.015);
    const low = Math.min(open, close) * (1 - r() * 0.015);
    const volume = Math.round((0.6 + r()) * lots) * 100;
    return {
      t, open: f2(open), high: f2(high), low: f2(low), close: f2(close), pre_close: prev === null ? null : f2(prev),
      volume: String(volume), amount: f2(volume * close), avg_price: null, is_final: true,
    };
  });
}

export function dailyBars(code: string): BarsResponse | null {
  const s = specOf(code);
  if (!s) return null;
  const r = rng(s.seed * 31);
  const days = tradingDays(TRADE_DATE, 120);
  const closes: number[] = new Array(days.length);
  closes[days.length - 1] = s.price;
  closes[days.length - 2] = s.prev_close;
  for (let i = days.length - 3; i >= 0; i--) {
    const drift = Math.sin(i / 14 + s.seed) * 0.006;
    closes[i] = closes[i + 1] / (1 + drift + (r() - 0.5) * 0.035);
  }
  const items: Bar[] = days.map((t, i) => {
    const close = closes[i];
    const open = i === 0 ? close * (1 + (r() - 0.5) * 0.02) : closes[i - 1] * (1 + (r() - 0.5) * 0.012);
    const high = Math.max(open, close) * (1 + r() * 0.015);
    const low = Math.min(open, close) * (1 - r() * 0.015);
    const volume = Math.round((0.6 + r()) * (s.volume_lots || 120000)) * 100;
    return {
      t, open: f2(open), high: f2(high), low: f2(low), close: f2(close), pre_close: i === 0 ? null : f2(closes[i - 1]),
      volume: String(volume), amount: f2(volume * close), avg_price: null, is_final: t !== TRADE_DATE,
    };
  });
  // T-F21 窗口加载：在最近 120 根之前补 HISTORY_DAYS 根更早的示例日 K（独立随机序列，最近 120 根的数值不变）
  const hist = historyBars(days[0], closes[0], s.seed, s.volume_lots || 120000);
  if (hist.length) items[0] = { ...items[0], pre_close: hist[hist.length - 1].close };
  items.unshift(...hist);
  // 停牌：最后一个交易日无成交
  const last = s.data_status === 'unavailable' || s.code === '601001.SH' ? items.slice(0, -1) : items;
  return {
    security_code: s.code, name: s.name, freq: 'd', adjust: 'qfq', pre_close: null, items: last, next_before: null, adjust_as_of: ADJUST_AS_OF,
    data_status: s.data_status === 'fresh' || s.data_status === 'partial' ? 'fresh' : s.data_status,
    data_as_of: s.data_as_of, gaps: quoteGaps(s).filter((g) => g.key === 'quote'),
  };
}

export function intradayBars(code: string): BarsResponse | null {
  const s = specOf(code);
  if (!s) return null;
  const r = rng(s.seed * 17);
  const mins = minuteEnds();
  const n = s.data_status === 'unavailable' || s.code === '601001.SH' ? 0 : s.data_status === 'stale' ? mins.indexOf('10:18') + 1 : mins.indexOf('10:31') + 1;
  const path: number[] = [];
  let p = s.prev_close;
  for (let i = 0; i < n; i++) {
    const target = s.prev_close + ((s.price - s.prev_close) * i) / Math.max(1, n - 1);
    p = p + (target - p) * 0.25 + (r() - 0.5) * s.price * 0.003;
    path.push(i === n - 1 ? s.price : p);
  }
  let cumAmt = 0;
  let cumVol = 0;
  let prev = s.prev_close;
  const items: Bar[] = path.map((close, i) => {
    const vol = Math.round((0.3 + r() * (i < 15 ? 2.5 : 1)) * (s.volume_lots / 60)) * 100;
    const open = prev;
    const high = Math.max(open, close) * (1 + r() * 0.0015);
    const low = Math.min(open, close) * (1 - r() * 0.0015);
    cumAmt += close * vol;
    cumVol += vol;
    prev = close;
    return {
      t: `${TRADE_DATE}T${mins[i]}:00+08:00`, open: f2(open), high: f2(high), low: f2(low), close: f2(close), pre_close: null,
      volume: String(vol), amount: f2(close * vol), avg_price: (cumAmt / cumVol).toFixed(3), is_final: i < path.length - 1,
    };
  });
  return {
    security_code: s.code, name: s.name, freq: '1m', adjust: 'none', pre_close: f2(s.prev_close), items, next_before: null, adjust_as_of: null,
    data_status: n === 0 ? 'unavailable' : s.data_status === 'partial' ? 'fresh' : s.data_status,
    data_as_of: s.data_as_of, gaps: n === 0 ? [{ key: 'quote', reason: 'upstream_error', message: '停牌或无当日成交，无分时数据（示例）' }] : quoteGaps(s).filter((g) => g.key === 'quote'),
  };
}

// ---------------- 盘中规则事件（不含动作建议） ----------------
const csOf = (code: string, key: string) => CANDIDATE_SIGNALS.find((c) => c.security_code === code && c.strategy_key === key && c.created_at.startsWith(TRADE_DATE));
export const SIGNAL_EVENTS: SignalEvent[] = [
  { signal_event_id: 'se_7', security_code: '600000.SH', kind: 'rule_flip', at: '2026-11-02T10:31:00+08:00', message: '价格站上 MA20，规则 T1 由不满足变为满足', strategy_key: 'demo_trend', rule_id: 'T1', price: '10.24' },
  { signal_event_id: 'se_6', security_code: '300001.SZ', kind: 'breakout', at: '2026-11-02T10:12:00+08:00', message: '价格突破 20 日区间上沿', strategy_key: 'demo_trend', rule_id: 'T1', price: '42.80' },
  { signal_event_id: 'se_5', security_code: '600002.SH', kind: 'invalidation_near', at: '2026-11-02T10:05:00+08:00', message: '距止损位不足 1 个 ATR，请核对失效条件', strategy_key: 'demo_trend', rule_id: null, price: '17.71' },
  { signal_event_id: 'se_4', security_code: '688001.SH', kind: 'data_stale', at: '2026-11-02T10:22:00+08:00', message: '行情超过刷新间隔 ×2 未更新，相关行已灰显', strategy_key: null, rule_id: null, price: null },
  { signal_event_id: 'se_3', security_code: '002001.SZ', kind: 'vwap_deviation', at: '2026-11-02T09:48:00+08:00', message: '价格偏离分时均价 +1.6%', strategy_key: 'demo_t', rule_id: 'V1', price: '13.15' },
  { signal_event_id: 'se_2', security_code: '000002.SZ', kind: 'volume_spike', at: '2026-11-02T09:41:00+08:00', message: '5 分钟成交量达到前 20 日同时段均值 2.3 倍', strategy_key: null, rule_id: null, price: '56.70' },
  { signal_event_id: 'se_1', security_code: '830001.BJ', kind: 'suspended', at: '2026-11-02T09:25:00+08:00', message: '停牌，相关候选信号暂不可执行（复牌后自动重评）', strategy_key: null, rule_id: null, price: null },
].map((e) => {
  const cs = e.strategy_key ? csOf(e.security_code, e.strategy_key) : undefined;
  const primary = e.strategy_key ? STRATEGIES[e.strategy_key].instance_id : null;
  // T-A34示例数据：首事件冻结为三个虚构匹配实例，仍只是一条事件，不按实例重复通知。
  return {
    ...e, kind: e.kind as SignalEvent['kind'], name: nameOf(e.security_code),
    message: e.signal_event_id === 'se_7' ? `${e.message}（示例数据 · 多实例）` : e.message,
    instance_id: primary, instance_ids: primary ? (e.signal_event_id === 'se_7' ? [primary, uid(280), uid(281)] : [primary]) : [], candidate_signal_id: cs?.id ?? null,
  };
});

// ---------------- 通知 ----------------
const sgId = (code: string) => suggestionOf(code)!.id;
export const NOTIFICATIONS: Notification[] = ([
  { id: uid(901), kind: 'suggestion_change', severity: 'important', title: '示例银行：各策略结论出现分歧（买入 / 等待 / 减仓）', body: '各策略并列展示，系统不合并为单一结论。', created_at: '2026-11-02T10:31:00+08:00', read_at: null, security_code: '600000.SH', name: '示例银行', target: { type: 'suggestion', id: sgId('600000.SH'), route: `/suggestions/${sgId('600000.SH')}` } },
  { id: uid(902), kind: 'plan_draft_ready', severity: 'attention', title: '演示电子：按您的持仓和资金拟定的计划草案待确认', body: null, created_at: '2026-11-02T10:12:30+08:00', read_at: null, security_code: '300001.SZ', name: '演示电子', target: { type: 'plan_draft', id: suggestionOf('300001.SZ')!.plan_draft_ids[0], route: `/plan-drafts/${suggestionOf('300001.SZ')!.plan_draft_ids[0]}` } },
  { id: uid(903), kind: 'invalidation', severity: 'important', title: '演示医药：接近失效条件（止损位）', body: '请核对候选信号卡中的失效条件。', created_at: '2026-11-02T10:05:00+08:00', read_at: null, security_code: '600002.SH', name: '演示医药', target: { type: 'suggestion', id: sgId('600002.SH'), route: `/suggestions/${sgId('600002.SH')}` } },
  { id: uid(904), kind: 'reason_released', severity: 'info', title: '演示材料：“非交易时段”原因已解除，已重新检查', body: null, created_at: '2026-11-02T09:30:02+08:00', read_at: null, security_code: '002001.SZ', name: '演示材料', target: { type: 'suggestion', id: sgId('002001.SZ'), route: `/suggestions/${sgId('002001.SZ')}` } },
  { id: uid(905), kind: 'strategy_health', severity: 'attention', title: '超跌修复（示例）进入观察期，优先级权重 0.55', body: null, created_at: '2026-11-02T08:30:00+08:00', read_at: null, security_code: null, name: null, target: { type: 'strategy_version', id: STRATEGIES.demo_reversal.version_id, route: `/strategies/${uid(501)}?version=${STRATEGIES.demo_reversal.version_id}` } },
  // ↑ strategy_version 按 §5.1 为 /strategies/{strategy_id}?version={id}（uid(501) 即 strategyHandlers 中 demo_reversal 的 strategy_id，T-F14）
  // 契约 §5.1 Notification.target.route 的两种带查询参数的深链（评审 P2）
  { id: uid(908), kind: 'import', severity: 'info', title: '交割单导入已完成：主账户（示例）', body: '可在导入向导中查看本批次的写入结果。', created_at: '2026-11-01T20:32:00+08:00', read_at: null, security_code: null, name: null, target: { type: 'import_batch', id: uid(820), route: `/portfolio/import?batch=${uid(820)}` } },
  { id: uid(909), kind: 'import', severity: 'attention', title: '对账发现 2 处重要差异：主账户（示例）', body: null, created_at: '2026-11-01T20:33:00+08:00', read_at: null, security_code: null, name: null, target: { type: 'reconciliation', id: ACCOUNT_ID, route: `/portfolio?tab=reconciliation&account_id=${ACCOUNT_ID}` } },
  { id: uid(906), kind: 'daily_report', severity: 'info', title: `${REPORT_DATE} 盘后日报已生成`, body: null, created_at: '2026-10-30T17:42:00+08:00', read_at: '2026-10-30T18:02:00+08:00', security_code: null, name: null, target: { type: 'daily_report', id: REPORT_DATE, route: `/daily-reports/${REPORT_DATE}` } },
  { id: uid(907), kind: 'system', severity: 'info', title: '系统维护提示：周六 22:00 起暂停采集 30 分钟（示例）', body: null, created_at: '2026-10-29T09:00:00+08:00', read_at: '2026-10-29T09:10:00+08:00', security_code: null, name: null, target: { type: 'none', id: null, route: null } },
] satisfies NotificationInput[]).map(projectNotification);

// ---------------- 盘后日报 ----------------
export const DAILY_REPORTS: DailyReport[] = [(() => {
  const evidence: Evidence[] = [
    { id: 'M1', key: 'market.breadth', value: '上涨 2,861 / 下跌 2,104', unit: null, provider: 'mairui', endpoint: '/hsrl/zdtj', data_as_of: `${REPORT_DATE}T15:00:00+08:00`, fetched_at: `${REPORT_DATE}T16:40:00+08:00`, epistemic_type: 'fact' },
    { id: 'M2', key: 'market.regime_score', value: 52, unit: null, provider: 'system', endpoint: null, data_as_of: `${REPORT_DATE}T15:00:00+08:00`, fetched_at: `${REPORT_DATE}T16:45:00+08:00`, epistemic_type: 'estimate' },
  ];
  let n = 0;
  const stocks = SPECS.map((s) => {
    const sg = suggestionOf(s.code)!;
    const ev = sg.evidence;
    const e1 = `S${++n}`;
    const e2 = `S${++n}`;
    evidence.push(
      { ...ev[0], id: e1, key: 'close', value: f2(s.prev_close), data_as_of: `${REPORT_DATE}T15:00:00+08:00`, fetched_at: `${REPORT_DATE}T16:40:00+08:00`, endpoint: '/hsstock/history' },
      { ...ev[4], id: e2 },
    );
    const first = sg.strategies[0];
    return {
      security_code: s.code, name: s.name, analysis_snapshot_id: null, dimensions: null,
      // v0.2.3：日报所属交易日收盘价/涨跌幅；无数据为 null
      close: s.data_status === 'unavailable' ? null : f2(s.prev_close),
      change_pct: s.data_status === 'unavailable' ? null : f2(((s.seed % 9) - 4) * 0.61),
      data_status: (s.data_status === 'unavailable' ? 'unavailable' : 'fresh') as DataStatus,
      max_risk_level: sg.risk_flags.reduce<RiskLevel | null>((m, f) => (m === null || LEVEL_RANK[f.level] > LEVEL_RANK[m] ? f.level : m), null),
      suggestion_id: sg.id, suggestion: summarize(sg),
      change_fields: [],
      change_from_previous: (s.code === '600000.SH' ? 'changed' : s.code === '300001.SZ' ? 'new' : 'unchanged') as 'changed' | 'new' | 'unchanged',
      highlights: [
        { text: `收盘 ${f2(s.prev_close)}，量比 ${ev[4].value}`, expr: null, evidence_ids: [e1, e2] },
        ...(sg.consensus.status === 'divergent' ? [{ text: '各策略结论存在分歧，已并列展示', expr: null, evidence_ids: [e1] }] : []),
      ],
      invalidation: first ? first.invalidation.slice(0, 1).map((t) => ({ ...t, evidence_ids: [e1] })) : [],
      next_watch: first ? [{ text: `关注 MA20（${ev[1].value}）附近的收盘表现`, expr: null, evidence_ids: [e1] }] : [{ text: '暂无启用的策略实例', expr: null, evidence_ids: [] }],
    };
  });
  return {
    date: REPORT_DATE, generated_at: `${REPORT_DATE}T17:42:00+08:00`, account_id: ACCOUNT_ID,
    market: {
      regime: 'range', regime_position_range: { min_pct: '40.00', max_pct: '60.00' },
      breadth: { up: 2861, down: 2104, limit_up: 47, limit_down: 9 },
      summary: [
        { text: '全市场上涨家数多于下跌家数，涨停 47 家、跌停 9 家', expr: null, evidence_ids: ['M1'] },
        { text: '大盘环境判定为“震荡”，参考仓位区间 40%–60%（模板参数，不是指令）', expr: 'regime_score in [40, 60)', evidence_ids: ['M2'] },
      ],
    },
    account: { total_assets: f2(TOTAL), cash: f2(CASH), position_pct: f2((MV / TOTAL) * 100), pnl_day: '1864.00', position_vs_regime: (MV / TOTAL) * 100 > 60 ? 'above' : (MV / TOTAL) * 100 < 40 ? 'below' : 'within' },
    reconciliation: { status: 'diff', as_of: `${REPORT_DATE}T17:30:00+08:00`, diff_count: 2, important_count: 1 },
    stocks,
    pending: { plan_drafts: SUGGESTIONS.reduce((a, x) => a + x.plan_draft_ids.length, 0), active_reasons: REASONS.filter((r) => r.status === 'active').length },
    explanation: {
      source: 'template',
      text: '账户总仓位处于当前震荡环境的参考区间附近；示例银行单只仓位超上限，买入方向的候选信号暂不可执行。9 只持仓/自选中 3 只各策略结论存在分歧（并列展示，未合并）；2 只数据不完整，见“数据缺口”。（示例数据）',
      llm_call_id: null,
    },
    evidence,
    data_status: 'partial', data_as_of: `${REPORT_DATE}T15:00:00+08:00`,
    gaps: [
      { key: 'news', reason: 'no_source', message: '本产品不提供新闻资讯；消息维度仅基于公告类型与标题' },
      { key: 'capital.600002.SH', reason: 'not_yet_published', message: '演示医药当日资金流在 17:30 前未发布，资金维度标为“未知”' },
      { key: 'quote.601001.SH', reason: 'quota_deferred', message: '演示能源日 K 补数排队中（配额顺延），次日 08:30 前补齐' },
      { key: 'trades', reason: 'user_input_missing', message: '10-29 至 10-30 的交割单尚未导入，持仓按上次导入快照估算' },
    ],
  };
})()];

/**
 * T-F13：上一期日报（示例）——当期无账户/持仓/现金记录（account=null、reconciliation not_imported）、市场宽度缺失、
 * 一只已移出自选的证券（suggestion=null），用于覆盖日报页的空值分支与日期切换。
 */
export const PREV_REPORT_DATE = '2026-10-29';
DAILY_REPORTS.push((() => {
  const cur = DAILY_REPORTS[0]!;
  // 上一期的证据时点不能晚于报告日：这里不复用本期证据 ID（只保留文字，示例）
  const noEv = (xs: TextWithEvidence[]) => xs.map((x) => ({ ...x, evidence_ids: [] }));
  const keep = cur.stocks.slice(0, 3).map((s) => ({
    ...s, change_from_previous: 'unchanged' as const,
    highlights: noEv(s.highlights), invalidation: noEv(s.invalidation), next_watch: noEv(s.next_watch),
  }));
  const removed = {
    analysis_snapshot_id: null, dimensions: null, security_code: '000003.SZ', name: '示例已移出', close: null, change_pct: null, data_status: 'unavailable' as DataStatus,
    max_risk_level: null, suggestion_id: null, suggestion: null, change_from_previous: 'removed' as const, change_fields: [],
    highlights: [], invalidation: [], next_watch: [],
  };
  return {
    ...cur,
    date: PREV_REPORT_DATE, generated_at: `${PREV_REPORT_DATE}T17:40:00+08:00`, account_id: null,
    market: { regime: 'range', regime_position_range: null, breadth: null, summary: [{ text: '市场宽度数据缺失，大盘环境沿用上一交易日判定（示例）', expr: null, evidence_ids: [] }] },
    evidence: [],
    account: null,
    reconciliation: { status: 'not_imported', as_of: null, diff_count: 0, important_count: 0 },
    stocks: [...keep, removed],
    pending: { plan_drafts: 0, active_reasons: 0 },
    explanation: { source: 'template', text: '当期尚无账户、持仓或现金记录，账户概览为空；逐股卡片按自选生成。（示例数据）', llm_call_id: null },
    // 示例旧记录缺顶层来源时点，读取投影为null，不借生成时间或按收盘时刻猜填。
    data_status: 'partial', data_as_of: null,
    gaps: [{ key: 'market.breadth', reason: 'not_yet_published', message: '市场宽度在生成时尚未发布（示例）' }],
  } satisfies DailyReport;
})());

DAILY_REPORTS[0] = withDailyDimensions(DAILY_REPORTS[0]);

export const DAILY_REPORT_LIST: DailyReportListItem[] = DAILY_REPORTS.map((d) => ({
  date: d.date, generated_at: d.generated_at, regime: d.market.regime, reconciliation_status: d.reconciliation.status, stock_count: d.stocks.length,
}));

// ---------------- 账号 / 健康 ----------------
export const ME: Me = {
  id: uid(2), username: 'demo_user', display_name: '示例用户', role: 'user', status: 'approved',
  entitlements: { 'watchlist.per_user_cap': 100 }, data_licence_status: 'active',
};
export const HEALTH_READY: HealthReady = { status: 'ok', db: 'ok', redis: 'ok', ingest: 'ok', checked_at: NOW, version: 'mock-0.2' };

// ---------------- 周期分类（v0.2.2 /horizon-assessments，示例数据） ----------------
const HZ_TEXT: Record<Horizon, { for: [string, string]; against: [string, string]; key: string }> = {
  intraday_t: { for: ['日内振幅足以覆盖往返费用（示例）', 'E12'], against: ['需持有底仓才能做 T（示例）', 'E1'], key: 'f.atr_pct' },
  short: { for: ['近 20 日量比活跃（示例）', 'E5'], against: ['短线换手要求高，需盯盘（示例）', 'E9'], key: 'f.turnover_20d' },
  swing: { for: ['均线趋势结构清晰（示例）', 'E3'], against: ['板块相对强弱一般（示例）', 'E10'], key: 'f.ma_trend' },
  long: { for: ['ROE(TTM) 处于中上水平（示例）', 'E8'], against: ['估值分位偏高（示例）', 'E7'], key: 'f.roe_ttm' },
};
/** 按证券代码索引；inputs_missing 非空的周期分数按封顶 59 处理 */
export const HORIZON_ASSESSMENTS: Record<string, HorizonAssessment> = {};
SUGGESTIONS.forEach((sg, i) => {
  const r = rng(9000 + i);
  const missing: string[] = i % 3 === 2 ? [HZ_TEXT.long.key] : [];
  // v0.2.6（T006e）：LG0 的 else_cap 记为 data_missing、rule_id = LG0（只给第 2 只示例股）
  const lg0 = i === 1;
  const scores = {} as Record<Horizon, number>;
  const reasons: HorizonReason[] = [];
  for (const h of ENUMS.horizon) {
    const suitable = sg.horizon_assessment.suitable.includes(h);
    let sc = Math.round(suitable ? 60 + r() * 35 : 15 + r() * 40);
    if (missing.includes(HZ_TEXT[h].key) || (lg0 && h === 'long')) sc = Math.min(sc, 59);
    scores[h] = sc;
    reasons.push({ horizon: h, polarity: 'for', text: HZ_TEXT[h].for[0], expr: null, evidence_ids: [HZ_TEXT[h].for[1]] });
    reasons.push({ horizon: h, polarity: 'against', text: HZ_TEXT[h].against[0], expr: null, evidence_ids: [HZ_TEXT[h].against[1]] });
  }
  // v0.2.3：证据只在本响应内解析；封顶原因写入 caps[]
  const used = new Set(reasons.flatMap((x) => x.evidence_ids));
  const caps: HorizonCap[] = missing.length ? [{ horizon: 'long', cap: 59, kind: 'data_missing', rule_id: null, inputs_missing: [...missing] }] : [];
  if (lg0) caps.push({ horizon: 'long', cap: 59, kind: 'data_missing', rule_id: 'LG0', inputs_missing: [] });
  HORIZON_ASSESSMENTS[sg.security_code] = {
    suitable: sg.horizon_assessment.suitable, scores, reasons, inputs_missing: [...new Set(missing)].sort(), caps, hints: [], classifier_version: '1.2.0',
    snapshot_id: sg.snapshot_id, evidence: sg.evidence.filter((e) => used.has(e.id)),
  };
});

/**
 * 自报经验为新手的用户看到的周期分类（契约 v0.2.5 #2，classifier 1.2.0）：SH0C / IT0C 为 mode: hint，
 * 只写入 hints[]，不改分数、不进 caps[]、不影响 suitable。画像未填写时不提示（见 handlers：只对 novice_user 生效）。
 */
export function noviceAssessment(a: HorizonAssessment): HorizonAssessment {
  return {
    ...a,
    hints: [
      ...a.hints,
      { horizon: 'short', rule_id: 'SH0C', text: '短线需要盯盘与止损纪律，您自报的经验为新手' },
      { horizon: 'intraday_t', rule_id: 'IT0C', text: '做T 需要盘中决断与纪律，您自报的经验为新手' },
    ],
  };
}

/**
 * 示例：分类器数据层（T-B48/T-B30a）接上之前的周期分类（T-B46/T-B47 裁定 R8/R9）：四个周期都因必需特征缺失按 data_missing 封顶，
 * suitable 为空。默认 mock 不用它（保留各周期的示例分布），测试与截图通过 server.use 覆盖。
 */
export function allDataMissingAssessment(a: HorizonAssessment): HorizonAssessment {
  const keys: Record<Horizon, string> = { intraday_t: 'f.intraday_amplitude_20d', short: 'f.turnover_20d_avg', swing: 'f.ma_trend', long: 'f.roe_ttm' };
  const caps: HorizonCap[] = ENUMS.horizon.map((h) => ({ horizon: h, cap: 59, kind: 'data_missing', rule_id: null, inputs_missing: [keys[h]] }));
  const scores = Object.fromEntries(ENUMS.horizon.map((h) => [h, Math.min(a.scores[h], 59)])) as Record<Horizon, number>;
  return { ...a, suitable: [], scores, caps, inputs_missing: [...new Set(Object.values(keys))].sort() };
}
