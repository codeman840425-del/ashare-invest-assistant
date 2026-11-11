/**
 * 个股档案 / 市场概览的类型（契约 v0.2.7 §5.1 v0.2.7 新增对象、§7.3）。
 * T-A08 之前这些端点未定义（T-F03 按 plan 自拟）；v0.2.7 起逐字照契约。
 */
import type {
  AnnouncementCategory, Board, DataProvider, IndustryTaxonomy, ListingStatus, ReportPeriod, SectorKind, SecurityMatchKind,
  SecurityRiskFlag, SecurityType,
} from './enums';
import type { DataStatusBlock, DateStr, DateTime, Decimal, Paged } from './types';

export type { Board, ListingStatus, SectorKind };
export type Exchange = 'SH' | 'SZ' | 'BJ';

/** §5.1 ProviderRef：展示类接口的来源说明 */
export interface ProviderRef { provider: DataProvider; endpoint: string | null; fetched_at: DateTime | null }
interface Sourced extends DataStatusBlock { sources: ProviderRef[] }

/** §5.1 SecurityHit（GET /securities/search） */
export interface SecurityHit {
  security_code: string;
  name: string;
  type: SecurityType;
  exchange: Exchange;
  board: Board | null;
  listing_status: ListingStatus | null;
  risk_flag: SecurityRiskFlag | null;
  match_kind: SecurityMatchKind;
  matched_text: string | null;
  quote_missing: boolean | null;
}
export interface SecuritySearchResponse { items: SecurityHit[]; master_as_of: DateStr }

/** §5.1 SecurityProfile（GET /securities/{code}）：公开主数据 + 本人证书取到的行业、概念、股本。不提供公司全称 */
export interface SecurityProfile extends Sourced {
  security_code: string;
  name: string;
  type: SecurityType;
  exchange: Exchange;
  board: Board | null;
  list_date: DateStr | null;
  list_date_basis: 'listing' | 'neeq_select' | null;
  delist_date: DateStr | null;
  listing_status: ListingStatus;
  risk_flag: SecurityRiskFlag | null;
  former_names: { name: string; until: DateStr | null }[];
  code_history: { security_code: string; until: DateStr | null }[];
  master_as_of: DateStr;
  /** 固定来源说明，前端原样展示 */
  attribution: string;
  industry: { taxonomy: IndustryTaxonomy; code: string; name: string } | null;
  concepts: { code: string; name: string }[];
  /** 单位：股 */
  total_shares: Decimal | null;
  float_shares: Decimal | null;
  suspended: boolean | null;
}

/** §5.1 FinancialPeriod：累计口径，金额单位元，*_pct 为百分数 */
export interface FinancialPeriod {
  period_end: DateStr;
  report_period: ReportPeriod;
  announce_date: DateStr | null;
  available_from: DateStr | null;
  is_restated: boolean;
  revenue: Decimal | null;
  revenue_yoy_pct: Decimal | null;
  net_profit: Decimal | null;
  net_profit_yoy_pct: Decimal | null;
  deducted_net_profit: Decimal | null;
  eps: Decimal | null;
  bvps: Decimal | null;
  roe_pct: Decimal | null;
  gross_margin_pct: Decimal | null;
  debt_ratio_pct: Decimal | null;
  operating_cash_flow: Decimal | null;
}
export interface FinancialsResponse extends Sourced { security_code: string; name: string; items: FinancialPeriod[] }

/** §5.1 FundFlowDay：除 trade_date、is_final 外均可为 null；单位元 */
export interface FundFlowDay {
  trade_date: DateStr;
  amount: Decimal | null;
  main_net: Decimal | null;
  super_large_net: Decimal | null;
  large_net: Decimal | null;
  medium_net: Decimal | null;
  small_net: Decimal | null;
  main_net_pct: Decimal | null;
  is_final: boolean;
}
export interface FundFlowsResponse extends Sourced { security_code: string; name: string; items: FundFlowDay[] }

/**
 * §3 factor_category：麦蕊因子的 11 个分类，键名【待 T003 补测】；定稿前按字符串处理（遗留问题见 T-A08-frontend.md）
 */
export type FactorCategory = string;
/** §5.1 FactorValue：只有全市场排名，没有行业内分位（v0.2.7 Q4） */
export interface FactorValue {
  factor_id: string;
  feature_key: string | null;
  name: string;
  category: FactorCategory;
  value: Decimal | null;
  unit: string | null;
  market_rank: number | null;
  market_rank_pct: Decimal | null;
}
export interface FactorsResponse extends Sourced {
  security_code: string;
  name: string;
  /** T-A158 ①：请求带 ?trade_date= 时原样返回；未指定且无可用批次时为 null（不造「最新」日期） */
  trade_date: DateStr | null;
  /** T-A158 ②：无真实因子集批次时为 null（合成夹具版本不得进生产响应）；前端显示「—」，不编造版本号 */
  factor_set_version: string | null;
  counts: { total: number; by_category: Record<FactorCategory, number> };
  items: FactorValue[];
}

/** §5.1 Announcement：只给元数据与白名单外链，不给正文和摘要 */
export interface Announcement {
  id: string;
  published_at: DateTime;
  title: string;
  category: AnnouncementCategory;
  category_raw: string | null;
  level_raw: string | null;
  url: string | null;
  url_host: string | null;
  file_format: 'pdf' | 'html' | 'other' | null;
  first_seen_at: DateTime;
}
export type AnnouncementsResponse = Paged<Announcement> & Sourced & { disclaimer: string };

/** §5.1 SectorFlow（GET /market/sector-flows，盘后数据） */
export interface SectorFlow {
  sector_code: string;
  name: string;
  change_pct: Decimal | null;
  main_net: Decimal | null;
  amount: Decimal | null;
  up_count: number | null;
  down_count: number | null;
  leader: { security_code: string; name: string; change_pct: Decimal | null } | null;
}
export interface SectorFlowsResponse extends Sourced {
  kind: SectorKind;
  taxonomy: IndustryTaxonomy | null;
  trade_date: DateStr;
  items: SectorFlow[];
}
