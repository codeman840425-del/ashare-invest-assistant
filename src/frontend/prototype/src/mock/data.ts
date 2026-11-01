/**
 * 示例数据（全部虚构）：证券代码/简称、价格、持仓、金额、策略名均为演示用途，
 * 不对应任何真实账户、真实行情或真实策略。不联网、不调用后端或麦蕊接口。
 */
import type {
  Action, CandidateSignal, CandidateSignalState, DailyReport, DataStatus, Dimension, DimensionView,
  Evidence, Gap, Horizon, Lifecycle, NonExecutableReason, NotificationItem, Portfolio, QuoteItem,
  ReasonCode, RiskFlag, SignalEvent, Suggestion, SuggestionStrategy, TextWithEvidence, WatchlistItem, ConfidenceLevel,
} from '../types/contract';
import { DIMENSIONS } from '../labels';

export const NOW = '2026-11-02T10:31:00+08:00';
export const TRADE_DATE = '2026-11-02';
export const REPORT_DATE = '2026-10-30';

const uid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

// ---------------- 策略（L2 模板，名称为示例） ----------------
export interface StrategyMeta {
  strategy_key: string;
  name: string; // 契约 Suggestion.strategies[] 无显示名，需从 /strategies 反查（遗留问题）
  horizon: Horizon;
  version_no: number;
  lifecycle: Lifecycle;
  priority_weight: number;
}
export const STRATEGIES: Record<string, StrategyMeta> = {
  demo_trend: { strategy_key: 'demo_trend', name: '趋势跟随（示例）', horizon: 'swing', version_no: 2, lifecycle: 'published', priority_weight: 1 },
  demo_reversal: { strategy_key: 'demo_reversal', name: '超跌修复（示例）', horizon: 'short', version_no: 1, lifecycle: 'observing', priority_weight: 0.55 },
  demo_value: { strategy_key: 'demo_value', name: '价值质量（示例）', horizon: 'long', version_no: 3, lifecycle: 'published', priority_weight: 1 },
  demo_t: { strategy_key: 'demo_t', name: '日内做T（示例）', horizon: 'intraday_t', version_no: 1, lifecycle: 'published', priority_weight: 0.9 },
};

// ---------------- 证券规格 ----------------
interface StratSpec {
  key: keyof typeof STRATEGIES;
  action: Action;
  score: number;
  conf: number;
  state?: CandidateSignalState;
  reasons?: ReasonCode[];
  t_leg?: 'sell_first' | 'buy_first';
}
interface SecSpec {
  code: string;
  name: string;
  sector: string;
  prev_close: number;
  price: number;
  volume: number; // 手
  holding?: { qty: number; sellable: number; cost: number };
  focus: boolean;
  data_status: DataStatus;
  data_as_of: string;
  strategies: StratSpec[];
  seed: number;
}

const SPECS: SecSpec[] = [
  {
    code: '600000.SH', name: '演示银行', sector: '银行', prev_close: 10.02, price: 10.24, volume: 412300, focus: true,
    holding: { qty: 10000, sellable: 10000, cost: 9.46 }, data_status: 'fresh', data_as_of: NOW, seed: 11,
    strategies: [
      { key: 'demo_trend', action: 'buy', score: 78, conf: 0.62, state: 'blocked', reasons: ['POSITION_CAP_REACHED', 'STRATEGY_CONFLICT'] },
      { key: 'demo_reversal', action: 'wait', score: 41, conf: 0.48 },
      { key: 'demo_value', action: 'reduce', score: 66, conf: 0.57, state: 'blocked', reasons: ['STRATEGY_CONFLICT'] },
    ],
  },
  {
    code: '000001.SZ', name: '演示科技', sector: '计算机', prev_close: 23.6, price: 23.18, volume: 268100, focus: true,
    holding: { qty: 3000, sellable: 3000, cost: 21.05 }, data_status: 'fresh', data_as_of: NOW, seed: 23,
    strategies: [
      { key: 'demo_trend', action: 'hold', score: 64, conf: 0.71 },
      { key: 'demo_value', action: 'hold', score: 59, conf: 0.66 },
    ],
  },
  {
    code: '300001.SZ', name: '演示电子', sector: '电子', prev_close: 41.3, price: 43.02, volume: 156400, focus: false,
    data_status: 'fresh', data_as_of: NOW, seed: 37,
    strategies: [{ key: 'demo_trend', action: 'buy', score: 82, conf: 0.74, state: 'drafted' }],
  },
  {
    code: '600002.SH', name: '演示医药', sector: '医药生物', prev_close: 18.4, price: 17.71, volume: 98200, focus: false,
    holding: { qty: 2000, sellable: 0, cost: 18.9 }, data_status: 'partial', data_as_of: NOW, seed: 41,
    strategies: [
      { key: 'demo_trend', action: 'sell', score: 71, conf: 0.52, state: 'blocked', reasons: ['T1_NOT_SELLABLE'] },
      { key: 'demo_value', action: 'hold', score: 55, conf: 0.39 },
    ],
  },
  {
    code: '002001.SZ', name: '演示材料', sector: '基础化工', prev_close: 12.85, price: 13.04, volume: 187500, focus: true,
    holding: { qty: 5000, sellable: 5000, cost: 12.2 }, data_status: 'fresh', data_as_of: NOW, seed: 53,
    strategies: [
      { key: 'demo_t', action: 'reduce', t_leg: 'sell_first', score: 69, conf: 0.58, state: 'drafted' },
      { key: 'demo_trend', action: 'hold', score: 61, conf: 0.63 },
    ],
  },
  {
    code: '000002.SZ', name: '演示消费', sector: '食品饮料', prev_close: 56.2, price: 56.95, volume: 64300, focus: false,
    data_status: 'fresh', data_as_of: NOW, seed: 67,
    strategies: [
      { key: 'demo_value', action: 'buy', score: 73, conf: 0.6, state: 'blocked', reasons: ['COOLING_OFF', 'STRATEGY_CONFLICT'] },
      { key: 'demo_reversal', action: 'wait', score: 38, conf: 0.44 },
    ],
  },
  {
    code: '688001.SH', name: '演示芯片', sector: '电子', prev_close: 88.5, price: 86.9, volume: 45200, focus: false,
    data_status: 'stale', data_as_of: '2026-11-02T10:18:00+08:00', seed: 79,
    strategies: [
      { key: 'demo_trend', action: 'wait', score: 35, conf: 0.33 },
      { key: 'demo_reversal', action: 'wait', score: 47, conf: 0.36 },
    ],
  },
  {
    code: '601001.SH', name: '演示能源', sector: '煤炭', prev_close: 15.12, price: 15.12, volume: 0, focus: false,
    data_status: 'stale', data_as_of: '2026-10-30T15:00:00+08:00', seed: 83,
    strategies: [],
  },
  {
    code: '830001.BJ', name: '演示精工', sector: '机械设备', prev_close: 9.66, price: 9.66, volume: 0, focus: false,
    data_status: 'unavailable', data_as_of: '2026-10-30T15:00:00+08:00', seed: 97,
    strategies: [{ key: 'demo_trend', action: 'buy', score: 57, conf: 0.41, state: 'blocked', reasons: ['SUSPENDED'] }],
  },
];

// ---------------- 工具 ----------------
const ACTION_CN: Record<Action, string> = { buy: '买入条件满足', add: '加仓条件满足', hold: '持有条件维持', reduce: '减仓条件满足', sell: '卖出条件满足', wait: '条件未满足，等待' };
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}
const f2 = (n: number) => n.toFixed(2);
const confLevel = (v: number): ConfidenceLevel => (v >= 0.7 ? 'high' : v >= 0.4 ? 'medium' : 'low');
const isBullish = (a: Action) => a === 'buy' || a === 'add';
const isBearish = (a: Action) => a === 'reduce' || a === 'sell';

// ---------------- 行情 ----------------
export const SECURITIES = SPECS.map((s) => ({ code: s.code, name: s.name, sector: s.sector }));
export const nameOf = (code: string) => SPECS.find((s) => s.code === code)?.name ?? code;
export const specOf = (code: string) => SPECS.find((s) => s.code === code)!;

export const WATCHLIST: WatchlistItem[] = SPECS.map((s) => ({
  security_code: s.code, name: s.name, focus: s.focus, in_portfolio: !!s.holding,
}));

export const QUOTES: Record<string, QuoteItem> = Object.fromEntries(
  SPECS.map((s) => {
    const gaps: Gap[] = [];
    if (s.data_status === 'stale') gaps.push({ key: 'quote', reason: 'quota_deferred', message: '超过刷新间隔 ×2 未更新（示例）' });
    if (s.data_status === 'unavailable') gaps.push({ key: 'quote', reason: 'upstream_error', message: '停牌，无实时成交（示例）' });
    if (s.data_status === 'partial') gaps.push({ key: 'capital', reason: 'not_yet_published', message: '当日资金流尚未更新（约 30 分钟一次）' });
    return [s.code, {
      security_code: s.code, price: f2(s.price), change_pct: f2(((s.price - s.prev_close) / s.prev_close) * 100),
      volume: String(s.volume * 100), amount: f2(s.volume * 100 * s.price), t: s.data_as_of,
      data_status: s.data_status, data_as_of: s.data_as_of, gaps,
    } satisfies QuoteItem];
  }),
);

// ---------------- 持仓 ----------------
const CASH = 190000;
const positionsRaw = SPECS.filter((s) => s.holding).map((s) => {
  const h = s.holding!;
  const mv = h.qty * s.price;
  return { s, h, mv, pnl: (s.price - h.cost) * h.qty };
});
const TOTAL = CASH + positionsRaw.reduce((a, p) => a + p.mv, 0);
export const PORTFOLIO: Portfolio = {
  cash: f2(CASH),
  total_assets: f2(TOTAL),
  positions: positionsRaw.map(({ s, h, mv, pnl }) => ({
    security_code: s.code, qty: String(h.qty), sellable_qty: String(h.sellable), cost: f2(h.cost),
    market_value: f2(mv), pnl: f2(pnl), weight_pct: f2((mv / TOTAL) * 100),
  })),
  exposure: { sector: [] },
  data_status: 'fresh', data_as_of: NOW, gaps: [],
};
{
  const bySector: Record<string, number> = {};
  positionsRaw.forEach(({ s, mv }) => (bySector[s.sector] = (bySector[s.sector] ?? 0) + mv));
  PORTFOLIO.exposure.sector = Object.entries(bySector)
    .sort((a, b) => b[1] - a[1])
    .map(([name, v]) => ({ name, pct: f2((v / TOTAL) * 100) }));
}
export const positionOf = (code: string) => PORTFOLIO.positions.find((p) => p.security_code === code) ?? null;

// ---------------- 证据 / 维度 / 候选信号 / 建议卡 ----------------
function buildEvidence(s: SecSpec): Evidence[] {
  const r = rng(s.seed);
  const asOfDay = `${REPORT_DATE}T15:00:00+08:00`;
  const fetchedDay = `${REPORT_DATE}T16:40:00+08:00`;
  const ma20 = s.price * (0.95 + r() * 0.06);
  const ma60 = s.price * (0.92 + r() * 0.1);
  const mk = (id: string, key: string, value: Evidence['value'], unit: string | null, endpoint: string | null, intraday = false, provider: Evidence['provider'] = 'mairui', ep: Evidence['epistemic_type'] = 'fact'): Evidence => ({
    id, key, value, unit, provider, endpoint,
    data_as_of: intraday ? s.data_as_of : asOfDay, fetched_at: intraday ? s.data_as_of.replace(/:00\+/, ':05+') : fetchedDay, epistemic_type: ep,
  });
  return [
    mk('E1', 'price', f2(s.price), 'CNY', '/hsrl/ssjy_more', true),
    mk('E2', 'ma20', f2(ma20), 'CNY', null, false, 'local'),
    mk('E3', 'factor.ma_trend', s.price > ma20 ? 'up' : 'down', null, '/factor/momentum/{code}'),
    mk('E4', 'ma60', f2(ma60), 'CNY', null, false, 'local'),
    mk('E5', 'factor.volume_ratio', (0.5 + r() * 1.4).toFixed(2), null, '/factor/momentum/{code}'),
    mk('E6', 'factor.main_5d_net', String(Math.round((r() - 0.5) * 9000)), '万元', '/factor/capital/{code}'),
    mk('E7', 'factor.pe_ttm_rank', (r() * 100).toFixed(1), '%', '/factor/valuation/{code}'),
    mk('E8', 'factor.roe_ttm', (4 + r() * 14).toFixed(2), '%', '/factor/quality/{code}'),
    mk('E9', 'factor.limit_up_count_20d', String(Math.floor(r() * 3)), '次', '/factor/sentiment/{code}'),
    mk('E10', 'sector.rs_20d', ((r() - 0.5) * 12).toFixed(2), '%', null, false, 'local', 'estimate'),
    mk('E11', 'factor.recent_event', r() > 0.5 ? '回购进展公告' : '无', null, '/factor/event/{code}'),
    mk('E12', 'atr14', f2(s.price * (0.018 + r() * 0.02)), 'CNY', null, false, 'local'),
  ];
}

const DIM_EVIDENCE: Record<Dimension, string> = {
  technical: 'E3', capital: 'E6', fundamental: 'E8', sentiment: 'E9', sector_market: 'E10', news: 'E11',
};
const DIM_RULE: Record<Dimension, { prefix: string; text: [string, string]; threshold: string }> = {
  technical: { prefix: 'T', text: ['收盘价站上 MA20 且 MA20 上行', '收盘价跌破 MA20'], threshold: 'up' },
  capital: { prefix: 'C', text: ['近 5 日主力资金净流入', '近 5 日主力资金净流出'], threshold: '0' },
  fundamental: { prefix: 'F', text: ['ROE(TTM) ≥ 8% 且估值分位 < 70%', '估值分位偏高（≥ 80%）'], threshold: '8' },
  sentiment: { prefix: 'S', text: ['近 20 日无连续炸板，情绪平稳', '近 20 日涨停后回落'], threshold: '≤2' },
  sector_market: { prefix: 'M', text: ['所属行业 20 日相对强弱为正', '所属行业 20 日相对强弱为负'], threshold: '0' },
  news: { prefix: 'N', text: ['近期公告类型偏正面（回购/增持）', '近期公告类型偏负面（减持/问询）'], threshold: '—' },
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

const REASON_TEXT: Record<string, { desc: (s: SecSpec) => string; rc: NonExecutableReason['release_condition'] }> = {
  POSITION_CAP_REACHED: {
    desc: () => '该股市值已占总资产约 22%，超过单只上限 20%（RC2）',
    rc: { kind: 'expr', expr: 'position_pct < 20', at: null, event: null, action: null, check_on: ['tick', 'holding_change'], human_text: '该股仓位占比回落到 20% 以下后自动重评', machine_checkable: true },
  },
  STRATEGY_CONFLICT: {
    desc: () => '您启用的其他策略对同一证券给出相反方向的候选信号，按规定并列展示、不自动拟定草案',
    rc: { kind: 'user_action', expr: null, at: null, event: null, action: 'choose_strategy_side', check_on: ['user_action', 'tick'], human_text: '由您选择采用某一方，或重评后各策略方向一致时自动解除', machine_checkable: false },
  },
  T1_NOT_SELLABLE: {
    desc: () => '今日买入的 2,000 股按 T+1 规则当日不可卖出',
    rc: { kind: 'time', expr: 'sellable_qty >= 100', at: '2026-11-03T09:30:00+08:00', event: null, action: null, check_on: ['schedule', 'holding_change'], human_text: '下一交易日 09:30 或可卖数量 ≥ 1 手时自动重评', machine_checkable: true },
  },
  COOLING_OFF: {
    desc: () => '该股 10-28 触发止损卖出，处于冷静期（默认 3 个交易日）',
    rc: { kind: 'time', expr: 'now >= cooling_until', at: '2026-11-03T09:30:00+08:00', event: null, action: null, check_on: ['schedule'], human_text: '冷静期于 2026-11-03 09:30 到期后自动重评', machine_checkable: true },
  },
  SUSPENDED: {
    desc: () => '该证券停牌，无实时成交',
    rc: { kind: 'event', expr: null, at: null, event: 'security.resumed', action: null, check_on: ['tick', 'daily_close'], human_text: '复牌且行情恢复成交后自动重评', machine_checkable: true },
  },
};

export const CANDIDATE_SIGNALS: CandidateSignal[] = [];
export const REASONS: NonExecutableReason[] = [];
export const SUGGESTIONS: Suggestion[] = [];

let seq = 30;
SPECS.forEach((s, si) => {
  const ev = buildEvidence(s);
  const atr = Number(ev[11].value);
  const sgId = uid(100 + si);
  const strategies: SuggestionStrategy[] = [];
  const csIds: string[] = [];
  const allReasonIds: string[] = [];
  const allDraftIds: string[] = [];
  const matrixViews: Record<string, Record<Dimension, DimensionView>> = {};

  s.strategies.forEach((st) => {
    const meta = STRATEGIES[st.key];
    const views = viewsFor(s, st, ev);
    matrixViews[st.key] = views;
    const r = rng(s.seed + st.score);
    const dimension_views = DIMENSIONS.map((d) => {
      const v = views[d];
      const rule = DIM_RULE[d];
      const passed = v === 'bullish' ? true : v === 'bearish' ? false : r() > 0.5;
      const evId = DIM_EVIDENCE[d];
      const val = ev.find((e) => e.id === evId)!.value;
      return {
        dimension: d, view: v,
        score: v === 'unknown' ? null : Math.round(v === 'bullish' ? 65 + r() * 30 : v === 'bearish' ? 10 + r() * 30 : 40 + r() * 20),
        rules: v === 'unknown' ? [] : [{ rule_id: `${rule.prefix}1`, pass: passed, value: val == null ? null : String(val), threshold: rule.threshold, evidence_id: evId }],
      };
    });
    const stop_loss = st.action === 'wait' ? null : f2(s.price - 2 * atr);
    const take_profit = isBullish(st.action) || st.action === 'hold' ? f2(s.price + 3.5 * atr) : null;
    const reasons: TextWithEvidence[] = dimension_views
      .filter((dv) => (isBearish(st.action) ? dv.view === 'bearish' : dv.view === 'bullish'))
      .slice(0, 3)
      .map((dv) => ({ text: DIM_RULE[dv.dimension].text[isBearish(st.action) ? 1 : 0], expr: null, evidence_ids: [DIM_EVIDENCE[dv.dimension]] }));
    if (reasons.length === 0) reasons.push({ text: st.action === 'wait' ? '入场条件未全部满足（3/5 条通过）' : '持有条件维持：未触发离场规则', expr: null, evidence_ids: ['E3'] });
    const counter: TextWithEvidence[] = dimension_views
      .filter((dv) => (isBearish(st.action) ? dv.view === 'bullish' : dv.view === 'bearish'))
      .slice(0, 2)
      .map((dv) => ({ text: DIM_RULE[dv.dimension].text[isBearish(st.action) ? 0 : 1], expr: null, evidence_ids: [DIM_EVIDENCE[dv.dimension]] }));
    counter.push({ text: `量比 ${ev[4].value}，${Number(ev[4].value) < 0.8 ? '成交偏清淡' : '量能未明显放大'}（示例）`, expr: 'volume_ratio < 1.0', evidence_ids: ['E5'] });
    if (STRATEGIES[st.key].priority_weight < 0.6) counter.push({ text: '该策略近 30 次模拟跟踪胜率 38%（n=30），已降低排序优先级', expr: null, evidence_ids: [] });
    const invalidation: TextWithEvidence[] = [
      { text: `连续 2 日收于 MA20（${ev[1].value}）下方`, expr: 'close < ma(close, 20) for 2 days', evidence_ids: ['E2'] },
      ...(stop_loss ? [{ text: `盘中价格跌破 ${stop_loss}（止损位）`, expr: `price_below ${stop_loss}`, evidence_ids: ['E1', 'E12'] }] : []),
      ...(st.key === 'demo_value' ? [{ text: '下一期季报 ROE(TTM) < 8%', expr: 'roe_ttm < 8 at next report', evidence_ids: ['E8'] }] : []),
    ];

    const directional = st.action !== 'hold' && st.action !== 'wait';
    let csId: string | undefined;
    if (directional) {
      csId = uid(seq++);
      csIds.push(csId);
      const reason_ids: string[] = [];
      (st.reasons ?? []).forEach((code) => {
        const rid = uid(seq++);
        reason_ids.push(rid);
        const def = REASON_TEXT[code];
        REASONS.push({
          id: rid, signal_id: csId!, code, description: def.desc(s),
          evidence: code === 'POSITION_CAP_REACHED' ? [ev[0]] : code === 'SUSPENDED' ? [ev[0]] : [],
          release_condition: def.rc, status: 'active', detected_at: s.data_as_of, released_at: null, release_evidence: null, released_by: 'system',
        });
      });
      allReasonIds.push(...reason_ids);
      const plan_draft_ids = st.state === 'drafted' ? [uid(seq++)] : [];
      allDraftIds.push(...plan_draft_ids);
      const risk_flags: RiskFlag[] = [];
      if (s.code === '600000.SH' && st.action === 'buy') risk_flags.push({ control: 'position_cap', level: 'warning', message: '该股已占总资产约 22%（上限 20%）', gated_actions: ['buy', 'add'], quantity_cap: '0', evidence_ids: ['E1'] });
      CANDIDATE_SIGNALS.push({
        id: csId, instance_id: uid(200 + si * 10 + st.key.length), strategy_version_id: uid(300 + Object.keys(STRATEGIES).indexOf(st.key)),
        strategy_key: st.key, lifecycle: meta.lifecycle, security_code: s.code, horizon: meta.horizon,
        state: st.state ?? 'open', proposed_action: st.action, t_leg: st.t_leg ?? null, score: st.score,
        confidence: { level: confLevel(st.conf), value: st.conf },
        stops: { stop_loss, take_profit, time_stop_days: meta.horizon === 'swing' ? 10 : meta.horizon === 'short' ? 3 : meta.horizon === 'intraday_t' ? 0 : 40 },
        rule_refs: dimension_views.flatMap((dv) => dv.rules.map((ru) => ({
          rule_id: ru.rule_id, snippet_id: null, snippet_version: null, role: ru.pass ? 'entry' : 'counter', dimension: dv.dimension,
          passed: ru.pass, value: ru.value, threshold: ru.threshold, evidence_ids: [ru.evidence_id],
        }))),
        evidence: ev, counter_evidence: counter, invalidation, model_refs: [], risk_flags,
        gate_results: [{ gate: 'gate_tradability', passed: !(st.reasons ?? []).includes('SUSPENDED') }],
        reason_ids, plan_draft_ids,
        valid_until: meta.horizon === 'intraday_t' ? '2026-11-02T14:50:00+08:00' : meta.horizon === 'short' ? '2026-11-03T15:00:00+08:00' : '2026-11-09T15:00:00+08:00',
        snapshot_id: uid(500 + si), feature_set_version: 'fs_3', created_at: s.data_as_of,
        data_status: s.data_status, data_as_of: s.data_as_of, gaps: QUOTES[s.code].gaps,
      });
    }
    strategies.push({
      strategy_version_id: uid(300 + Object.keys(STRATEGIES).indexOf(st.key)), strategy_key: st.key, version_no: meta.version_no,
      horizon: meta.horizon, action: st.action, t_leg: st.t_leg ?? null, score: st.score, confidence: { level: confLevel(st.conf), value: st.conf },
      lifecycle: meta.lifecycle,
      rule_refs: dimension_views.flatMap((dv) => dv.rules.map((ru) => ({ rule_id: ru.rule_id, snippet_version: 1, role: 'entry' as const, passed: ru.pass }))),
      model_refs: [], priority_weight: meta.priority_weight, priority_downweighted: meta.priority_weight < 1,
      dimension_views, stop_loss, take_profit, invalidation, reasons, counter_evidence: counter, candidate_signal_id: csId,
    });
  });

  const actions: Partial<Record<Action, number>> = {};
  strategies.forEach((x) => (actions[x.action] = (actions[x.action] ?? 0) + 1));
  const distinct = Object.keys(actions).length;
  const consensus = {
    status: strategies.length === 0 ? 'none' : strategies.length === 1 ? 'single' : distinct === 1 ? 'unanimous' : 'divergent',
    actions,
  } as Suggestion['consensus'];

  const gaps: Gap[] = [...QUOTES[s.code].gaps, { key: 'news', reason: 'no_source', message: '本产品不提供新闻资讯，消息维度仅基于公告类型与标题' }];
  const risk_flags: RiskFlag[] = [];
  const pos = positionsRaw.find((p) => p.s.code === s.code);
  if (s.code === '600000.SH') risk_flags.push({ control: 'position_cap', level: 'warning', message: '该股已占总资产约 22%（上限 20%）', gated_actions: ['buy', 'add'], quantity_cap: '0', evidence_ids: ['E1'] });
  if (pos && s.code === '600002.SH') risk_flags.push({ control: 'stop_take', level: 'critical', message: '现价 17.71 已接近策略止损位，请核对失效条件', gated_actions: [], quantity_cap: null, evidence_ids: ['E1', 'E12'] });
  if (s.sector === '电子') risk_flags.push({ control: 'sector_concentration', level: 'info', message: '电子行业自选 2 只；若均建仓，行业占比将约 38%（上限 40%）', gated_actions: [], quantity_cap: null, evidence_ids: [] });

  const divergence = consensus.status === 'divergent'
    ? s.code === '600000.SH'
      ? [
          { dimensions: ['fundamental', 'technical'] as Dimension[], summary: '估值分位偏高（价值质量策略偏空） vs 趋势向上（趋势跟随策略偏多）', resolving_info: [{ description: '下一期季报 profit_yoy 是否转正', subscribable: true }, { description: '估值分位是否回落到 70% 以下', subscribable: true }] },
          { dimensions: ['capital'] as Dimension[], summary: '近 5 日主力净流入，但所属行业 20 日资金净流出', resolving_info: [{ description: '行业资金流连续 3 日转正', subscribable: true }] },
        ]
      : [{ dimensions: ['technical', 'fundamental'] as Dimension[], summary: '各策略周期不同、关注维度不同，结论不一致', resolving_info: [{ description: '等待下一交易日收盘后重评', subscribable: false }] }]
    : [];

  SUGGESTIONS.push({
    id: sgId, security_code: s.code, created_at: s.data_as_of, origin: s.code === '600000.SH' ? 'intraday_event' : 'daily_batch', status: 'active',
    snapshot_id: uid(500 + si), feature_set_version: 'fs_3', candidate_signal_ids: csIds,
    executability: { status: csIds.length === 0 ? 'not_applicable' : allReasonIds.length ? 'blocked' : 'executable', reason_ids: allReasonIds },
    plan_draft_ids: allDraftIds,
    horizon_assessment: { suitable: s.strategies.length ? Array.from(new Set(s.strategies.map((x) => STRATEGIES[x.key].horizon))) : ['long'], user_overridden: false },
    consensus, strategies,
    dimension_matrix: DIMENSIONS.map((d) => ({
      dimension: d,
      cells: strategies.map((x) => {
        const dv = x.dimension_views.find((v) => v.dimension === d)!;
        const e = ev.find((ee) => ee.id === DIM_EVIDENCE[d])!;
        return { strategy_key: x.strategy_key, view: dv.view, score: dv.score, key_evidence: dv.view === 'unknown' ? '数据缺失' : `${e.key}=${e.value}${e.unit ?? ''}` };
      }),
    })),
    divergence, risk_flags, evidence: ev,
    explanation: {
      source: 'template',
      text: strategies.length
        ? `${s.name}：${strategies.map((x) => `${STRATEGIES[x.strategy_key].name}给出“${ACTION_CN[x.action]}”，规则满足度 ${x.score}`).join('；')}。以上为规则信号，各策略结论并列展示，系统不合成单一结论。`
        : `${s.name}：暂无启用的策略实例，仅展示行情。`,
      llm_call_id: null,
    },
    supersedes_id: s.code === '600000.SH' ? uid(99) : null,
    data_status: s.data_status, data_as_of: s.data_as_of, gaps,
  });
});

export const suggestionOf = (code: string) => SUGGESTIONS.find((x) => x.security_code === code)!;
export const suggestionById = (id: string) => SUGGESTIONS.find((x) => x.id === id);
export const signalById = (id?: string) => CANDIDATE_SIGNALS.find((c) => c.id === id);
export const reasonsOf = (signalId: string) => REASONS.filter((r) => r.signal_id === signalId);

// ---------------- K 线 / 分时（示例数据，确定性伪随机生成） ----------------
export interface ChartBar { time: string; open: number; high: number; low: number; close: number; volume: number }
export interface ChartMarker { time: string | number; action: Action; strategy_key: string; text: string }

function tradingDays(end: string, n: number): string[] {
  const out: string[] = [];
  const d = new Date(`${end}T00:00:00Z`);
  while (out.length < n) {
    const wd = d.getUTCDay();
    if (wd !== 0 && wd !== 6) out.unshift(d.toISOString().slice(0, 10));
    d.setUTCDate(d.getUTCDate() - 1);
  }
  return out;
}
export function dailyBars(code: string): ChartBar[] {
  const s = specOf(code);
  const r = rng(s.seed * 31);
  const days = tradingDays(TRADE_DATE, 120);
  const closes: number[] = new Array(days.length);
  closes[days.length - 1] = s.price;
  closes[days.length - 2] = s.prev_close;
  for (let i = days.length - 3; i >= 0; i--) {
    const drift = Math.sin(i / 14 + s.seed) * 0.006;
    closes[i] = closes[i + 1] / (1 + drift + (r() - 0.5) * 0.035);
  }
  return days.map((t, i) => {
    const close = closes[i];
    const open = i === 0 ? close * (1 + (r() - 0.5) * 0.02) : closes[i - 1] * (1 + (r() - 0.5) * 0.012);
    const high = Math.max(open, close) * (1 + r() * 0.015);
    const low = Math.min(open, close) * (1 - r() * 0.015);
    return { time: t, open: +open.toFixed(2), high: +high.toFixed(2), low: +low.toFixed(2), close: +close.toFixed(2), volume: Math.round((0.6 + r()) * (s.volume || 120000) * 100) };
  });
}
export function dailyMarkers(code: string): ChartMarker[] {
  const sg = suggestionOf(code);
  const days = tradingDays(TRADE_DATE, 120);
  const out: ChartMarker[] = [];
  const r = rng(specOf(code).seed * 5);
  // 历史候选信号（已被取代/已过期）
  ['buy', 'reduce', 'buy', 'wait'].forEach((a, i) => {
    const idx = 20 + i * 24 + Math.floor(r() * 8);
    out.push({ time: days[idx], action: a as Action, strategy_key: i % 2 ? 'demo_value' : 'demo_trend', text: `${a === 'buy' ? 'B' : a === 'reduce' ? 'R' : 'W'}` });
  });
  sg.strategies.filter((x) => x.action !== 'hold').forEach((x) => {
    out.push({ time: TRADE_DATE, action: x.action, strategy_key: x.strategy_key, text: x.action === 'buy' || x.action === 'add' ? 'B' : x.action === 'wait' ? 'W' : x.action === 'sell' ? 'S' : 'R' });
  });
  return out;
}

/** 分时：北京时间按“本地时间当作 UTC”换算为 UTCTimestamp（lightweight-charts 只认 UTC） */
export function bjTs(hhmm: string): number {
  return Date.UTC(2026, 10, 2, Number(hhmm.slice(0, 2)), Number(hhmm.slice(3, 5))) / 1000;
}
function minutesOfDay(): string[] {
  const out: string[] = [];
  const push = (h0: number, m0: number, h1: number, m1: number) => {
    for (let t = h0 * 60 + m0; t <= h1 * 60 + m1; t++) out.push(`${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`);
  };
  push(9, 30, 11, 30);
  push(13, 1, 15, 0);
  return out;
}
export interface IntradayPoint { time: number; price?: number; avg?: number; volume?: number }
export function intraday(code: string): IntradayPoint[] {
  const s = specOf(code);
  const r = rng(s.seed * 17);
  const mins = minutesOfDay();
  const nowIdx = mins.indexOf('10:31');
  const n = s.data_status === 'unavailable' ? 0 : s.data_status === 'stale' ? mins.indexOf('10:18') + 1 : nowIdx + 1;
  const path: number[] = [];
  let p = s.prev_close;
  for (let i = 0; i < n; i++) {
    const target = s.prev_close + ((s.price - s.prev_close) * i) / Math.max(1, n - 1);
    p = p + (target - p) * 0.25 + (r() - 0.5) * s.price * 0.003;
    path.push(i === n - 1 ? s.price : p);
  }
  let pv = 0, vv = 0;
  return mins.map((m, i) => {
    if (i >= n) return { time: bjTs(m) };
    const vol = Math.round((0.3 + r() * (i < 15 ? 2.5 : 1)) * (s.volume / 60) * 100);
    pv += path[i] * vol; vv += vol;
    return { time: bjTs(m), price: +path[i].toFixed(2), avg: +(pv / vv).toFixed(3), volume: vol };
  });
}
export function intradayMarkers(code: string): ChartMarker[] {
  const sg = suggestionOf(code);
  if (specOf(code).data_status === 'unavailable') return [];
  const out: ChartMarker[] = [];
  const first = sg.strategies.find((x) => x.action !== 'hold' && x.action !== 'wait');
  if (first) out.push({ time: bjTs(specOf(code).data_status === 'stale' ? '10:05' : '10:12'), action: first.action, strategy_key: first.strategy_key, text: '候选' });
  if (code === '600000.SH') out.push({ time: bjTs('10:31'), action: 'reduce', strategy_key: 'demo_value', text: '候选' });
  if (code === '002001.SZ') out.push({ time: bjTs('09:48'), action: 'reduce', strategy_key: 'demo_t', text: '先卖' });
  return out;
}

export const SIGNAL_EVENTS: (SignalEvent & { text: string })[] = [
  { signal_event_id: 'se_7', security_code: '600000.SH', kind: 'quote_flip', at: '2026-11-02T10:31:00+08:00', text: '价格站上 MA20，趋势跟随（示例）入场规则 T1 由不满足变为满足' },
  { signal_event_id: 'se_6', security_code: '300001.SZ', kind: 'breakout', at: '2026-11-02T10:12:00+08:00', text: '突破 20 日高点，候选信号已生成，计划草案待确认' },
  { signal_event_id: 'se_5', security_code: '600002.SH', kind: 'invalidation_near', at: '2026-11-02T10:05:00+08:00', text: '距止损位不足 1 个 ATR，请核对失效条件' },
  { signal_event_id: 'se_4', security_code: '002001.SZ', kind: 'vwap_deviation', at: '2026-11-02T09:48:00+08:00', text: '偏离分时均价 +1.6%，做T（先卖）条件满足（候选）' },
  { signal_event_id: 'se_3', security_code: '688001.SH', kind: 'data_stale', at: '2026-11-02T10:22:00+08:00', text: '行情超过刷新间隔 ×2 未更新，相关行已灰显' },
  { signal_event_id: 'se_2', security_code: '830001.BJ', kind: 'suspended', at: '2026-11-02T09:25:00+08:00', text: '停牌，候选信号暂不可执行（复牌后自动重评）' },
];

export const NOTIFICATIONS: NotificationItem[] = [
  { id: 'n1', kind: 'suggestion_change', severity: 'important', title: '演示银行：各策略出现分歧（买入 / 等待 / 减仓）', created_at: '2026-11-02T10:31:00+08:00', read: false, link: '#/suggestions/600000.SH' },
  { id: 'n2', kind: 'plan_draft_ready', severity: 'attention', title: '演示电子：按您的持仓和资金拟定的计划草案待确认', created_at: '2026-11-02T10:12:30+08:00', read: false, link: '#/suggestions/300001.SZ' },
  { id: 'n3', kind: 'invalidation', severity: 'important', title: '演示医药：接近失效条件（止损位）', created_at: '2026-11-02T10:05:00+08:00', read: false, link: '#/suggestions/600002.SH' },
  { id: 'n4', kind: 'reason_released', severity: 'info', title: '演示材料：“非交易时段”原因已解除，已重新检查', created_at: '2026-11-02T09:30:02+08:00', read: false, link: '#/suggestions/002001.SZ' },
  { id: 'n5', kind: 'strategy_health', severity: 'attention', title: '超跌修复（示例）进入观察期，优先级权重 0.55', created_at: '2026-11-02T08:30:00+08:00', read: false },
  { id: 'n6', kind: 'daily_report', severity: 'info', title: '2026-10-30 盘后日报已生成', created_at: '2026-10-30T17:42:00+08:00', read: true, link: '#/reports/2026-10-30' },
];

// ---------------- 盘后日报 ----------------
export const DAILY_REPORT: DailyReport = (() => {
  const mv = positionsRaw.reduce((a, p) => a + p.mv, 0);
  return {
    date: REPORT_DATE, generated_at: '2026-10-30T17:42:00+08:00',
    data_status: 'partial', data_as_of: '2026-10-30T17:30:00+08:00',
    gaps: [
      { key: 'news', reason: 'no_source', message: '本产品不提供新闻资讯；消息维度仅基于公告类型与标题' },
      { key: 'capital.600002.SH', reason: 'not_yet_published', message: '演示医药当日资金流在 17:30 前未发布，资金维度标为“未知”' },
      { key: 'quote.601001.SH', reason: 'quota_deferred', message: '演示能源日 K 补数排队中（配额顺延），次日 08:30 前补齐' },
      { key: 'trades', reason: 'user_input_missing', message: '10-29 至 10-30 的交割单尚未导入，持仓按上次导入快照估算' },
    ],
    account: {
      total_assets: f2(TOTAL), cash: f2(CASH), market_value: f2(mv), position_pct: f2((mv / TOTAL) * 100),
      day_pnl: '1864.00', day_pnl_pct: '0.48', market_regime: 'range', regime_exposure_range_pct: ['40', '60'],
      reconciliation: 'diff', exposure: PORTFOLIO.exposure,
      risk_flags: [
        { control: 'total_exposure', level: 'info', message: `总仓位 ${((mv / TOTAL) * 100).toFixed(1)}%，接近震荡环境区间上沿 60%`, gated_actions: [], quantity_cap: null, evidence_ids: [] },
        { control: 'position_cap', level: 'warning', message: '演示银行占总资产约 22%（上限 20%）', gated_actions: ['buy', 'add'], quantity_cap: '0', evidence_ids: [] },
        { control: 'loss_streak_drawdown', level: 'info', message: '账户净值自高点回撤 3.2%（预警线 10%）', gated_actions: [], quantity_cap: null, evidence_ids: [] },
      ],
    },
    stocks: SPECS.map((s) => {
      const sg = suggestionOf(s.code);
      const ev = sg.evidence;
      const facts: TextWithEvidence[] = [
        { text: `收盘 ${f2(s.prev_close)}，量比 ${ev[4].value}`, expr: null, evidence_ids: ['E1', 'E5'] },
        { text: `近 5 日主力净额 ${ev[5].value} 万元`, expr: null, evidence_ids: ['E6'] },
        { text: ev[10].value === '无' ? '近期无新公告' : `公告：${ev[10].value}`, expr: null, evidence_ids: ['E11'] },
      ];
      const cs = CANDIDATE_SIGNALS.filter((c) => c.security_code === s.code);
      return {
        security_code: s.code, name: s.name, suggestion_id: sg.id, close: f2(s.prev_close),
        change_pct: f2(((s.seed % 7) - 3) * 0.83),
        facts, position: positionOf(s.code), consensus: sg.consensus,
        strategies: sg.strategies.map((x) => ({ strategy_key: x.strategy_key, horizon: x.horizon, action: x.action, score: x.score, confidence: x.confidence, stop_loss: x.stop_loss, take_profit: x.take_profit, invalidation: x.invalidation })),
        risk_flags: sg.risk_flags,
        blocked_reason_codes: REASONS.filter((rr) => cs.some((c) => c.id === rr.signal_id)).map((rr) => rr.code).filter((v, i, a) => a.indexOf(v) === i),
        data_status: s.code === '601001.SH' ? 'stale' : s.code === '600002.SH' ? 'partial' : 'fresh',
        gaps: s.code === '600002.SH' ? [{ key: 'capital', reason: 'not_yet_published', message: '当日资金流未发布' }] : s.code === '601001.SH' ? [{ key: 'quote', reason: 'quota_deferred', message: '日 K 补数排队中' }] : [],
      };
    }),
    summary: {
      source: 'template',
      text: '账户总仓位接近当前震荡环境的区间上沿；演示银行单只仓位超上限，买入方向的候选信号暂不可执行。共 9 只持仓/自选，其中 4 只各策略结论存在分歧（并列展示，未合并）；2 只数据不完整，见“数据缺口”。',
    },
  };
})();
