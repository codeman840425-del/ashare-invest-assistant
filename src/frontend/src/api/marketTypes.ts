/**
 * T-F03 个股档案 / 市场概览用到、但契约 v0.2.6 仍未定义的端点与结构。
 * 字段取自 plan 3（market.securities / financial_reports / fund_flows / factor_values / announcements）与 2.3 能力 1，
 * 全部标注 `// [待契约确认]`，清单见 reports/T-F03.md「遗留问题」。契约已定义的（/quotes、/securities/{code}/bars、
 * /market/overview、/horizon-assessments、/securities?q=）仍用 types.ts 中的类型。
 */
import type { DataStatusBlock, DateStr, DateTime, Decimal, Paged } from './types';

/** 板块（plan 3 market.securities.board） // [待契约确认] 取值 */
export type Board = 'main' | 'chinext' | 'star' | 'bse';
/** // [待契约确认] 取值 */
export type ListingStatus = 'listed' | 'suspended' | 'delisted';

/** GET /securities/{code}：证券主数据 // [待契约确认] 端点与结构 */
export interface SecurityProfile extends DataStatusBlock {
  security_code: string;
  name: string;
  exchange: 'SH' | 'SZ' | 'BJ';
  board: Board;
  industry: string | null;
  concepts: string[];
  list_date: DateStr | null;
  status: ListingStatus;
  /** 风险警示（ST / *ST） */
  risk_warning: boolean;
  total_shares: Decimal | null;
  float_shares: Decimal | null;
}

/** 搜索结果（契约 §7.3 已定义） */
export interface SecurityHit { security_code: string; name: string }

/** GET /securities/{code}/financials：按报告期的主要指标（金额单位元） // [待契约确认] 端点、指标集与口径 */
export interface FinancialPeriod {
  period_end: DateStr;
  /** 公告日（plan 3 announce_date，【待 T003 验证】） */
  announce_date: DateStr | null;
  revenue: Decimal | null;
  revenue_yoy_pct: Decimal | null;
  net_profit: Decimal | null;
  net_profit_yoy_pct: Decimal | null;
  eps: Decimal | null;
  roe_pct: Decimal | null;
  gross_margin_pct: Decimal | null;
  debt_ratio_pct: Decimal | null;
  operating_cash_flow: Decimal | null;
}
export interface FinancialsResponse extends DataStatusBlock { security_code: string; name: string; items: FinancialPeriod[] }

/** GET /securities/{code}/fund-flows?days=：日度资金流（元，净流入为正） // [待契约确认] 分档口径以麦蕊实测为准 */
export interface FundFlowDay {
  trade_date: DateStr;
  main_net: Decimal;
  super_large_net: Decimal;
  large_net: Decimal;
  medium_net: Decimal;
  small_net: Decimal;
  main_net_pct: Decimal | null;
}
export interface FundFlowsResponse extends DataStatusBlock { security_code: string; name: string; items: FundFlowDay[] }

/** GET /securities/{code}/factors：最新因子截面（plan 2.5 所需因子） // [待契约确认] 端点、分组与分位口径 */
export type FactorGroup = 'value' | 'quality' | 'growth' | 'momentum' | 'volatility' | 'liquidity';
export interface FactorValue {
  factor_id: string;
  name: string;
  group: FactorGroup;
  value: Decimal | null;
  unit: string | null;
  /** 全市场分位（0–100） */
  pct_rank_market: Decimal | null;
  /** 申万一级行业内分位（0–100） */
  pct_rank_industry: Decimal | null;
}
export interface FactorsResponse extends DataStatusBlock {
  security_code: string;
  name: string;
  trade_date: DateStr;
  calc_version: string;
  items: FactorValue[];
}

/** GET /securities/{code}/announcements（游标分页）：只给标题与原文外链，正文不转存（plan 4 方案 A） // [待契约确认] */
export interface Announcement {
  id: string;
  published_at: DateTime;
  title: string;
  category: string | null;
  /** 原文链接（交易所/巨潮 PDF）；前端只当外链使用，不取内容 */
  url: string | null;
}
export type AnnouncementsResponse = Paged<Announcement> & DataStatusBlock;

/** GET /market/sector-flows?kind=industry|concept：板块涨跌与主力资金（plan 2.3 能力 1） // [待契约确认] 端点与结构 */
export type SectorKind = 'industry' | 'concept';
export interface SectorFlow {
  sector_id: string;
  name: string;
  change_pct: Decimal | null;
  main_net: Decimal | null;
  up_count: number | null;
  down_count: number | null;
  leader: { security_code: string; name: string; change_pct: Decimal | null } | null;
}
export interface SectorFlowsResponse extends DataStatusBlock { kind: SectorKind; trade_date: DateStr; items: SectorFlow[] }
