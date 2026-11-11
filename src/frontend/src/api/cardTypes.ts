/**
 * 策略知识卡类型（契约 §7.4 GET /strategy-cards、/strategy-cards/{id}、/versions；
 * 字段全集见 plan §2.5.14 B 节「卡片块 strategy-card」）。
 *
 * 只描述后端已返回的结构：`GET /strategy-cards` 列表项按 contract §7.4 的 9 个字段；
 * 详情端点返回卡片当前版本字段全集 + `field_epistemic` / `refs` / `validation_summary` /
 * `risk_level` / `gates_missing`（后端 app/api/v1/strategy_cards.py card_detail）。
 */
import type { CardCompleteness, CardRiskLevel, CardSourceKind, Dimension, Horizon } from './enums';
import type { Stat } from './types';

/** plan 2.5.14 B 节 category 取值（新增取值需架构师裁定） */
export const CARD_CATEGORIES = [
  'trend', 'momentum', 'reversal', 'breakout', 'value', 'quality', 'dividend', 'low_vol', 'event', 'intraday_t', 'risk',
] as const;
export type CardCategory = (typeof CARD_CATEGORIES)[number];

/** plan 2.5.14 B 节：一条规则条目（entry / counter / invalidation / exit 通用） */
export interface CardRuleLine {
  text: string;
  /** 量化后的 DSL 表达式；to_quantify 时为 null */
  expr: string | null;
  status: 'quantified' | 'to_quantify';
}

/** plan 2.5.14 B 节：维度 + 角色 */
export interface CardDimensionEntry {
  dimension: Dimension;
  role: 'core' | 'auxiliary' | 'veto';
}

/** plan 2.5.14 B 节：数据需求 */
export interface CardDataNeed {
  feature_key: string;
  frequency: '1m' | 'daily' | 'quarterly' | 'event';
  adjust: 'none' | 'qfq' | 'hfq';
  available_at: string;
}

/** plan 2.5.14 B 节：来源（许可证规则见 plan §7.6） */
export interface CardSource {
  title: string;
  kind: string;
  url_or_ref: string | null;
  source_version: string | null;
  license: string | null;
  license_status: string | null;
}

/** plan 2.5.14 B 节：研究员文档的出处编号（如 `R12`；不是列表项里引用规则的 ref） */
export interface CardRef {
  ref: string;
  title: string;
  url: string | null;
}

/** plan 2.5.14 H②：研究员文档中的外部验证信息，产品不做回测 */
export interface CardValidationSummary {
  type: string;
  window: string | null;
  benchmark: string | null;
  cost_model: string | null;
  oos_result: string | null;
  trade_log_ref: string | null;
}

/** 契约 §7.4 GET /strategy-cards 列表项（9 个字段，后端 card_list 逐一对齐） */
export interface StrategyCardListItem {
  id: string;
  key: string;
  name: string;
  category: CardCategory | string;
  horizons: Horizon[];
  completeness: CardCompleteness;
  current_version_no: number;
  source_kind: CardSourceKind;
  /** 后端当前恒返回 null（业绩未接入）；类型保留契约形状 */
  performance: { win_rate_5d: Stat; avg_excess_5d: Stat } | null;
}

/**
 * 契约 §7.4 GET /strategy-cards/{id} 与 /versions/{no}：卡片当前版本字段全集 + 展示附加字段。
 * 卡片正文各块按 plan B 节定义；未列出的选填块按 `unknown` 承接，避免为了展示捏造结构。
 */
export interface StrategyCardDetail {
  id: string;
  key: string;
  name: string;
  version_no: number;
  category: CardCategory | string;
  horizons: Horizon[];
  hypothesis: { why_it_works: string; falsified_by: string[] };
  dimensions: CardDimensionEntry[];
  entry: CardRuleLine[];
  counter_evidence: CardRuleLine[];
  invalidation: CardRuleLine[];
  exit: CardRuleLine[];
  data_needs: CardDataNeed[];
  epistemic: Record<string, 'fact' | 'estimate' | 'hypothesis'>;
  completeness?: CardCompleteness;
  source_kind?: CardSourceKind;
  applicability?: Record<string, unknown> | null;
  universe?: Record<string, unknown> | null;
  risk_suggestions?: string[] | null;
  pitfalls?: string[] | null;
  fit?: { effort: string | null; risk_tolerance_min: number | null; experience_min: string | null } | null;
  sources?: CardSource[] | null;
  compliance_variants?: unknown[] | null;
  /** 以下为详情端点附加字段（后端 card_detail） */
  field_epistemic: Record<string, 'fact' | 'estimate' | 'hypothesis'> | null;
  refs: CardRef[];
  validation_summary: CardValidationSummary | null;
  risk_level: CardRiskLevel;
  /** 未通过的门禁项，形如 `G1:stop_loss_to_quantify` */
  gates_missing: string[];
}

/** 契约 §7.4 GET /strategy-cards/{id}/versions 元素（不可变版本历史） */
export interface StrategyCardVersion {
  id: string;
  version_no: number;
  created_at: string;
}

/** 契约 §7.10 GET /feature-catalog 元素（后端 strategy/cards/models.py FeatureCatalogItem 逐字段） */
export interface FeatureCatalogItem {
  feature_key: string;
  description: string | null;
  dimension: Dimension | null;
  frequency: '1m' | 'daily' | 'quarterly' | 'event';
  adjust: 'none' | 'qfq' | 'hfq';
  unit: string;
  warmup_bars: number | null;
  available_at: unknown;
  status: string;
  epistemic_type: string | null;
}
