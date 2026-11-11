/**
 * F-04：策略知识卡模拟（契约 §7.4 GET /strategy-cards、/{id}、/{id}/versions、/versions/{no}，§7.10 /feature-catalog）。
 * 名称、标题、出处编号均为合成示例；不搬真实研究员文档内容。
 * 门禁字段 `gates_missing` 照后端当前实现形态（`G<n>:promotion_review_pending`），不在这里假装门禁已过。
 */
import { http, HttpResponse } from 'msw';
import type { FeatureCatalogItem, StrategyCardDetail, StrategyCardListItem, StrategyCardVersion } from '../api/cardTypes';
import { errorBody, page } from './handlerUtils';

const API = '/api/v1';
const json = (body: unknown, status = 200) => HttpResponse.json(body as Record<string, unknown>, { status });

const cardId = (n: number) => `0000000${n}-0000-4000-8000-00000000000${n}`;

/** 三张合成卡片：已晋级 / 可运行候选 / 草稿，覆盖 completeness 三档 */
const LIST: StrategyCardListItem[] = [
  {
    id: cardId(1), key: 'sw_synthetic_trend', name: '合成趋势跟随卡', category: 'trend', horizons: ['swing'],
    completeness: 'promoted', current_version_no: 2, source_kind: 'builtin', performance: null,
  },
  {
    id: cardId(2), key: 'st_synthetic_momo', name: '合成短线动量卡', category: 'momentum', horizons: ['short'],
    completeness: 'runnable_candidate', current_version_no: 1, source_kind: 'builtin', performance: null,
  },
  {
    id: cardId(3), key: 'lt_synthetic_value', name: '合成价值草稿卡', category: 'value', horizons: ['long'],
    completeness: 'draft', current_version_no: 1, source_kind: 'user', performance: null,
  },
];

const rule = (text: string, expr: string | null, status: 'quantified' | 'to_quantify') => ({ text, expr, status });

/** 详情：字段按 plan §2.5.14 B 节集合，内容全部为合成示例 */
function detailOf(id: string, versionNo?: number): StrategyCardDetail | null {
  const base = LIST.find((x) => x.id === id);
  if (!base) return null;
  const no = versionNo ?? base.current_version_no;
  return {
    id: base.id,
    key: base.key,
    name: base.name,
    version_no: no,
    category: base.category,
    horizons: base.horizons,
    hypothesis: {
      why_it_works: '合成示例：趋势延续时顺势持有，回避逆势抄底。',
      falsified_by: ['合成示例：连续两个周期趋势指标失效即证伪。'],
    },
    dimensions: [
      { dimension: 'technical', role: 'core' },
      { dimension: 'capital', role: 'auxiliary' },
    ],
    entry: [rule('合成示例：收盘价上穿中期均线', 'close > ma(close, 20)', 'quantified')],
    counter_evidence: [rule('合成示例：量能萎缩时降低权重', 'volume_ratio < 0.5', 'to_quantify')],
    invalidation: [rule('合成示例：收盘价跌破中期均线', 'close < ma(close, 20)', 'quantified')],
    exit: [rule('合成示例：固定止损', 'close < entry_price * 0.92', 'quantified')],
    data_needs: [
      { feature_key: 'close', frequency: 'daily', adjust: 'qfq', available_at: '盘后 17:00' },
      { feature_key: 'volume_ratio', frequency: 'daily', adjust: 'qfq', available_at: '盘后 17:00' },
    ],
    epistemic: { hypothesis: 'hypothesis' },
    completeness: base.completeness,
    source_kind: base.source_kind,
    applicability: null,
    universe: null,
    risk_suggestions: ['RC1', 'RC2'],
    pitfalls: ['合成示例：高波动区间易被反复打止损'],
    fit: { effort: 'medium', risk_tolerance_min: 3, experience_min: 'intermediate' },
    sources: null,
    compliance_variants: null,
    field_epistemic: { 'entry[0].text': 'hypothesis' },
    refs: [{ ref: 'R12', title: '合成出处（示例）', url: null }],
    validation_summary: null,
    risk_level: base.key === 'st_synthetic_momo' ? 'high' : 'normal',
    gates_missing: ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7'].map((g) => `${g}:promotion_review_pending`),
  };
}

const VERSIONS: Record<string, StrategyCardVersion[]> = {
  [cardId(1)]: [
    { id: `${cardId(1)}-v2`, version_no: 2, created_at: '2026-11-02T10:00:00+08:00' },
    { id: `${cardId(1)}-v1`, version_no: 1, created_at: '2026-10-20T10:00:00+08:00' },
  ],
  [cardId(2)]: [{ id: `${cardId(2)}-v1`, version_no: 1, created_at: '2026-10-25T10:00:00+08:00' }],
  [cardId(3)]: [{ id: `${cardId(3)}-v1`, version_no: 1, created_at: '2026-11-01T10:00:00+08:00' }],
};

const CATALOG: FeatureCatalogItem[] = [
  { feature_key: 'close', description: '收盘价（合成示例）', dimension: 'technical', frequency: 'daily', adjust: 'qfq', unit: 'CNY', warmup_bars: 20, available_at: '盘后 17:00', status: 'active', epistemic_type: 'fact' },
  { feature_key: 'volume_ratio', description: '量比（合成示例）', dimension: 'technical', frequency: 'daily', adjust: 'qfq', unit: 'ratio', warmup_bars: 5, available_at: '盘后 17:00', status: 'active', epistemic_type: 'estimate' },
];

const notFound = () => json(errorBody('NOT_FOUND', '策略卡不存在（示例数据）'), 404);

export const cardHandlers = [
  http.get(`${API}/strategy-cards`, ({ request }) => {
    const url = new URL(request.url);
    const completeness = url.searchParams.get('completeness');
    const horizon = url.searchParams.get('horizon');
    const category = url.searchParams.get('category');
    const items = LIST.filter(
      (x) => (!completeness || x.completeness === completeness) && (!horizon || x.horizons.includes(horizon as never)) && (!category || x.category === category),
    );
    return json(page(items, url));
  }),
  // 注意顺序：更具体的 /versions 路由必须先注册，否则会被 /:id 吃掉
  http.get(`${API}/strategy-cards/:id/versions/:no`, ({ params }) => {
    const d = detailOf(String(params.id), Number(params.no));
    return d ? json(d) : notFound();
  }),
  http.get(`${API}/strategy-cards/:id/versions`, ({ params }) => {
    const v = VERSIONS[String(params.id)];
    return v ? json(v) : notFound();
  }),
  http.get(`${API}/strategy-cards/:id`, ({ params }) => {
    const d = detailOf(String(params.id));
    return d ? json(d) : notFound();
  }),
  http.get(`${API}/feature-catalog`, () => json(CATALOG)),
];
