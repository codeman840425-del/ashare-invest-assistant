import { keepPreviousData, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { apiGet } from './client';
import type { BarAdjust, BarFreq, SectorSort } from './enums';
import type { BarsResponse, MarketOverview, QuoteItem } from './types';
import type {
  AnnouncementsResponse, FactorsResponse, FinancialsResponse, FundFlowsResponse, SecurityProfile, SecuritySearchResponse, SectorFlowsResponse, SectorKind,
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
  sectors: (kind: SectorKind, sort: SectorSort) => ['sector-flows', kind, sort] as const,
  search: (q: string) => ['securities-search', q] as const,
};

const opt = (code: string | undefined) => !!code && CODE_RE.test(code);

/** 契约 §7.3 GET /securities/{code}（v0.2.7 SecurityProfile） */
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

/**
 * v0.2.7 §5.1 adjust_as_of：同一证券、同一复权方式的基准日变了（除权除息后重算），之前缓存的日/周 K 价格口径已不一致，
 * 丢弃这些缓存（当前这次请求除外），让它们下次使用时重新拉取。返回是否发生了变化。
 */
export function syncAdjustAsOf(qc: QueryClient, code: string, adjust: BarAdjust, freq: BarFreq, limit: number, asOf: string | null): boolean {
  if (adjust === 'none' || asOf === null) return false;
  let changed = false;
  for (const q of qc.getQueryCache().findAll({ queryKey: ['bars', code] })) {
    const [, , f, a, l] = q.queryKey as ReturnType<typeof mk.bars>;
    const prev = (q.state.data as BarsResponse | undefined)?.adjust_as_of;
    if (a !== adjust || (f === freq && l === limit) || !prev || prev === asOf) continue;
    changed = true;
    qc.removeQueries({ queryKey: q.queryKey, exact: true });
  }
  return changed;
}

/** 契约 §7.3 /securities/{code}/bars；日/周默认前复权，1m 只能不复权 */
export const useBarsOf = (code: string | undefined, freq: BarFreq, limit: number, opts: { keepPrevious?: boolean } = {}) => {
  const adjust: BarAdjust = freq === '1m' ? 'none' : 'qfq';
  const qc = useQueryClient();
  return useQuery({
    queryKey: mk.bars(code ?? '', freq, adjust, limit),
    queryFn: async ({ signal }) => {
      const res = await apiGet<BarsResponse>(`/securities/${enc(code!)}/bars`, { freq, adjust, limit }, signal);
      syncAdjustAsOf(qc, code!, adjust, freq, limit, res.adjust_as_of);
      return res;
    },
    enabled: opt(code),
    // 评审 T-F22a m17：同一证券切换周期时保留旧图；换证券时不沿用（key 第二段是证券代码）
    // v0.2.7：复权基准日不同的旧图不能当占位（价格口径不同）——由 syncAdjustAsOf 清掉旧缓存后自然不再沿用
    placeholderData: opts.keepPrevious ? (prev, prevQuery) => (prevQuery?.queryKey[1] === code ? prev : undefined) : undefined,
    refetchInterval: freq === '1m' ? 60_000 : false,
  });
};

/** 契约 §7.3 GET /securities/{code}/financials（默认 8 期） */
export const useFinancials = (code: string | undefined, enabled = true) =>
  useQuery({
    queryKey: mk.financials(code ?? ''),
    queryFn: ({ signal }) => apiGet<FinancialsResponse>(`/securities/${enc(code!)}/financials`, { limit: 8 }, signal),
    enabled: enabled && opt(code),
  });

/** 契约 §7.3 GET /securities/{code}/fund-flows（days 默认 60，最大 250） */
export const useFundFlows = (code: string | undefined, days = 60, enabled = true) =>
  useQuery({
    queryKey: mk.fundFlows(code ?? '', days),
    queryFn: ({ signal }) => apiGet<FundFlowsResponse>(`/securities/${enc(code!)}/fund-flows`, { days }, signal),
    enabled: enabled && opt(code),
  });

/** 契约 §7.3 GET /securities/{code}/factors */
export const useFactors = (code: string | undefined, enabled = true) =>
  useQuery({
    queryKey: mk.factors(code ?? ''),
    queryFn: ({ signal }) => apiGet<FactorsResponse>(`/securities/${enc(code!)}/factors`, undefined, signal),
    enabled: enabled && opt(code),
  });

/** 契约 §7.3 GET /securities/{code}/announcements（首屏 30 条） */
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

/** 契约 §7.3 GET /market/sector-flows（v0.2.7：盘后数据，每日更新一次，不轮询；弱 ETag） */
export const useSectorFlows = (kind: SectorKind, sort: SectorSort = 'main_net_desc') =>
  useQuery({
    queryKey: mk.sectors(kind, sort),
    queryFn: ({ signal }) => apiGet<SectorFlowsResponse>('/market/sector-flows', { kind, sort, limit: 20 }, signal),
    placeholderData: keepPreviousData,
    staleTime: 10 * 60_000,
  });

/** 契约 §7.3 GET /securities/search（v0.2.7；不分页，默认 stock,cdr，最多 20 条；/securities?q= 只是旧别名） */
export const useSecuritySearch = (raw: string) => {
  // 评审 T-F22a m13：queryKey 与请求参数都用去空格后的 q
  const q = raw.trim();
  return useQuery({
    queryKey: mk.search(q),
    queryFn: ({ signal }) => apiGet<SecuritySearchResponse>('/securities/search', { q, limit: 20 }, signal),
    enabled: q.length > 0,
    staleTime: 60_000,
  });
};
