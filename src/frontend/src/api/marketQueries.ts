import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { apiGet } from './client';
import type { BarAdjust, BarFreq } from './enums';
import type { BarsResponse, MarketOverview, QuoteItem } from './types';
import type {
  AnnouncementsResponse, FactorsResponse, FinancialsResponse, FundFlowsResponse, SecurityHit, SecurityProfile, SectorFlowsResponse, SectorKind,
} from './marketTypes';

const enc = encodeURIComponent;
/** 证券代码格式（契约 §1：6 位代码 + .SH/.SZ/.BJ；指数同格式） */
export const CODE_RE = /^\d{6}\.(SH|SZ|BJ)$/;

export const mk = {
  profile: (code: string) => ['security', code] as const,
  quote: (code: string) => ['quotes', code] as const,
  bars: (code: string, freq: BarFreq, adjust: BarAdjust, limit: number) => ['bars', code, freq, adjust, limit] as const,
  financials: (code: string) => ['financials', code] as const,
  fundFlows: (code: string, days: number) => ['fund-flows', code, days] as const,
  factors: (code: string) => ['factors', code] as const,
  announcements: (code: string) => ['announcements', code] as const,
  overview: ['market-overview'] as const,
  sectors: (kind: SectorKind) => ['sector-flows', kind] as const,
  search: (q: string) => ['securities-search', q] as const,
};

const opt = (code: string | undefined) => !!code && CODE_RE.test(code);

/** [待契约确认] GET /securities/{code} */
export const useSecurityProfile = (code: string | undefined) =>
  useQuery({
    queryKey: mk.profile(code ?? ''),
    queryFn: ({ signal }) => apiGet<SecurityProfile>(`/securities/${enc(code!)}`, undefined, signal),
    enabled: opt(code),
  });

/** 契约 §7.3 /quotes（只读缓存）；单只证券取 items[0] */
export const useQuote = (code: string | undefined) =>
  useQuery({
    queryKey: mk.quote(code ?? ''),
    queryFn: ({ signal }) => apiGet<{ items: QuoteItem[] }>('/quotes', { codes: code }, signal).then((r) => r.items.find((q) => q.security_code === code) ?? null),
    enabled: opt(code),
    refetchInterval: 15_000,
  });

/** 契约 §7.3 /securities/{code}/bars；日/周默认前复权，1m 只能不复权 */
export const useBarsOf = (code: string | undefined, freq: BarFreq, limit: number, opts: { keepPrevious?: boolean } = {}) => {
  const adjust: BarAdjust = freq === '1m' ? 'none' : 'qfq';
  return useQuery({
    queryKey: mk.bars(code ?? '', freq, adjust, limit),
    queryFn: ({ signal }) => apiGet<BarsResponse>(`/securities/${enc(code!)}/bars`, { freq, adjust, limit }, signal),
    enabled: opt(code),
    // 评审 T-F22a m17：同一证券切换周期时保留旧图；换证券时不沿用（key 第二段是证券代码）
    placeholderData: opts.keepPrevious ? (prev, prevQuery) => (prevQuery?.queryKey[1] === code ? prev : undefined) : undefined,
    refetchInterval: freq === '1m' ? 60_000 : false,
  });
};

/** [待契约确认] GET /securities/{code}/financials */
export const useFinancials = (code: string | undefined, enabled = true) =>
  useQuery({
    queryKey: mk.financials(code ?? ''),
    queryFn: ({ signal }) => apiGet<FinancialsResponse>(`/securities/${enc(code!)}/financials`, { limit: 8 }, signal),
    enabled: enabled && opt(code),
  });

/** [待契约确认] GET /securities/{code}/fund-flows */
export const useFundFlows = (code: string | undefined, days = 60, enabled = true) =>
  useQuery({
    queryKey: mk.fundFlows(code ?? '', days),
    queryFn: ({ signal }) => apiGet<FundFlowsResponse>(`/securities/${enc(code!)}/fund-flows`, { days }, signal),
    enabled: enabled && opt(code),
  });

/** [待契约确认] GET /securities/{code}/factors */
export const useFactors = (code: string | undefined, enabled = true) =>
  useQuery({
    queryKey: mk.factors(code ?? ''),
    queryFn: ({ signal }) => apiGet<FactorsResponse>(`/securities/${enc(code!)}/factors`, undefined, signal),
    enabled: enabled && opt(code),
  });

/** [待契约确认] GET /securities/{code}/announcements（首屏 30 条） */
export const useAnnouncements = (code: string | undefined, enabled = true) =>
  useQuery({
    queryKey: mk.announcements(code ?? ''),
    queryFn: ({ signal }) => apiGet<AnnouncementsResponse>(`/securities/${enc(code!)}/announcements`, { limit: 30 }, signal),
    enabled: enabled && opt(code),
  });

/** 契约 §7.3 /market/overview（最小结构） */
export const useMarketOverview = () =>
  useQuery({
    queryKey: mk.overview,
    queryFn: ({ signal }) => apiGet<MarketOverview>('/market/overview', undefined, signal),
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });

/** [待契约确认] GET /market/sector-flows */
export const useSectorFlows = (kind: SectorKind) =>
  useQuery({
    queryKey: mk.sectors(kind),
    queryFn: ({ signal }) => apiGet<SectorFlowsResponse>('/market/sector-flows', { kind, limit: 20 }, signal),
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });

/** 契约 §7.3 /securities?q=（不分页，最多 20 条） */
export const useSecuritySearch = (raw: string) => {
  // 评审 T-F22a m13：queryKey 与请求参数都用去空格后的 q
  const q = raw.trim();
  return useQuery({
    queryKey: mk.search(q),
    queryFn: ({ signal }) => apiGet<SecurityHit[]>('/securities', { q }, signal),
    enabled: q.length > 0,
    staleTime: 60_000,
  });
};
