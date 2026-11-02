import { useCallback, useEffect, useMemo } from 'react';
import { hashKey, keepPreviousData, useInfiniteQuery, useQuery, useQueryClient, type InfiniteData, type QueryClient, type QueryKey } from '@tanstack/react-query';
import { apiGet } from './client';
import { useCursorPages } from '../lib/cursorPaging';
import type { BarAdjust, BarFreq, SectorSort } from './enums';
import type { Bar, BarsResponse, MarketOverview, QuoteItem } from './types';
import type {
  Announcement, AnnouncementsResponse, FactorsResponse, FinancialsResponse, FundFlowsResponse, SecurityProfile, SecuritySearchResponse, SectorFlowsResponse, SectorKind,
} from './marketTypes';

const enc = encodeURIComponent;
/** 证券代码格式（契约 §1：6 位代码 + .SH/.SZ/.BJ；指数同格式） */
export const CODE_RE = /^\d{6}\.(SH|SZ|BJ)$/;

export const mk = {
  profile: (code: string) => ['security', code] as const,
  quote: (code: string) => ['quotes', code] as const,
  bars: (code: string, freq: BarFreq, adjust: BarAdjust, limit: number) => ['bars', code, freq, adjust, limit] as const,
  barsWindow: (code: string, freq: BarFreq, adjust: BarAdjust, pageSize: number) => ['bars', code, freq, adjust, `window:${pageSize}`] as const,
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
export function syncAdjustAsOf(
  qc: QueryClient, code: string, adjust: BarAdjust, freq: BarFreq, limit: number, asOf: string | null, self?: QueryKey,
): boolean {
  if (adjust === 'none' || asOf === null) return false;
  let changed = false;
  const selfHash = self ? hashKey(self) : null;
  for (const q of qc.getQueryCache().findAll({ queryKey: ['bars', code] })) {
    const [, , f, a, l] = q.queryKey as ReturnType<typeof mk.bars>;
    // 窗口加载（T-F21）的缓存是 InfiniteData：取最新一页（pages[0]）的基准日
    const data = q.state.data as BarsResponse | InfiniteData<BarsResponse> | undefined;
    const prev = data && 'pages' in data ? data.pages[0]?.adjust_as_of : data?.adjust_as_of;
    const isSelf = selfHash ? q.queryHash === selfHash : f === freq && l === limit;
    if (a !== adjust || isSelf || !prev || prev === asOf) continue;
    changed = true;
    qc.removeQueries({ queryKey: q.queryKey, exact: true });
  }
  return changed;
}

/** 窗口内各页合并为升序 K 线（pages[0] 是最新一页，后面依次更早）；按 t 去重 */
export function mergeBarPages(pages: readonly BarsResponse[]): Bar[] {
  const out: Bar[] = [];
  const seen = new Set<string>();
  for (let i = pages.length - 1; i >= 0; i--) {
    for (const b of pages[i].items) {
      if (seen.has(b.t)) continue;
      seen.add(b.t);
      out.push(b);
    }
  }
  return out.sort((x, y) => (x.t < y.t ? -1 : x.t > y.t ? 1 : 0));
}

/** 只保留与最新一页复权基准日一致的页（更早的页基准日不同 → 口径不一致，不能拼接） */
export function consistentPages(pages: readonly BarsResponse[]): BarsResponse[] {
  if (pages.length === 0) return [];
  const base = pages[0].adjust_as_of;
  const out: BarsResponse[] = [];
  for (const p of pages) {
    if (p.adjust_as_of !== base) break;
    out.push(p);
  }
  return out;
}

/**
 * T-F21 K 线窗口加载（契约 §7.3 bars `before` + `limit`，§6.2 周 K 同规则）：
 * 先取最近 `pageSize` 根；图表向左拖到窗口边缘（或点“更早”）时用上一页的 `next_before` 取更早一页，拼在左侧。
 * `next_before=null` 表示已到最早。v0.2.7：翻页时发现 `adjust_as_of` 与已缓存的不同 → 丢弃整个窗口，从最新一页重新加载。
 */
export function useBarsWindow(code: string | undefined, freq: Exclude<BarFreq, '1m'>, pageSize: number, opts: { keepPrevious?: boolean; enabled?: boolean } = {}) {
  const adjust: BarAdjust = 'qfq';
  const qc = useQueryClient();
  const key = mk.barsWindow(code ?? '', freq, adjust, pageSize);
  const query = useInfiniteQuery({
    queryKey: key,
    initialPageParam: null as string | null,
    queryFn: async ({ signal, pageParam }) => {
      const res = await apiGet<BarsResponse>(`/securities/${enc(code!)}/bars`, { freq, adjust, limit: pageSize, before: pageParam }, signal);
      if (pageParam === null) syncAdjustAsOf(qc, code!, adjust, freq, pageSize, res.adjust_as_of, key);
      return res;
    },
    getNextPageParam: (last) => last.next_before ?? undefined,
    enabled: (opts.enabled ?? true) && opt(code),
    placeholderData: opts.keepPrevious ? (prev, prevQuery) => (prevQuery?.queryKey[1] === code ? prev : undefined) : undefined,
  });
  const pages = query.data?.pages;
  const good = useMemo(() => consistentPages(pages ?? []), [pages]);
  const stale = !!pages && good.length < pages.length;
  // 更早一页的基准日与最新一页不同：整窗重载（resetQueries 只会重取第一页）
  useEffect(() => {
    if (stale) void qc.resetQueries({ queryKey: key, exact: true });
    // key 由 code/freq/pageSize 决定，已在依赖里
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stale, qc, code, freq, pageSize]);
  const bars = useMemo(() => mergeBarPages(good), [good]);
  const { hasNextPage, isFetching, fetchNextPage } = query;
  const { isFetchNextPageError } = query;
  /**
   * 取更早一页；正在请求时不重复发（fetchNextPage 默认会取消进行中的请求）。
   * 拖动触发的自动加载在上次失败后不再自动重试（避免每次拖动都打请求），由“重试”按钮传 force。
   */
  const loadOlder = useCallback((force = false) => {
    if (hasNextPage && !isFetching && (force || !isFetchNextPageError)) void fetchNextPage({ cancelRefetch: false });
  }, [hasNextPage, isFetching, isFetchNextPageError, fetchNextPage]);
  const loadOlderAuto = useCallback(() => loadOlder(false), [loadOlder]);
  return { ...query, first: good[0], bars, loadOlder, loadOlderAuto, reachedStart: !!pages && !hasNextPage };
}

/** 契约 §7.3 /securities/{code}/bars；日/周默认前复权，1m 只能不复权 */
export const useBarsOf = (code: string | undefined, freq: BarFreq, limit: number, opts: { keepPrevious?: boolean; enabled?: boolean } = {}) => {
  const adjust: BarAdjust = freq === '1m' ? 'none' : 'qfq';
  const qc = useQueryClient();
  return useQuery({
    queryKey: mk.bars(code ?? '', freq, adjust, limit),
    queryFn: async ({ signal }) => {
      const res = await apiGet<BarsResponse>(`/securities/${enc(code!)}/bars`, { freq, adjust, limit }, signal);
      syncAdjustAsOf(qc, code!, adjust, freq, limit, res.adjust_as_of);
      return res;
    },
    // enabled=false 时同一 key 的缓存仍返回，只是不请求、不轮询（T-F21：切到别的周期时分时停止轮询）
    enabled: (opts.enabled ?? true) && opt(code),
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

/** 契约 §7.3 GET /securities/{code}/announcements（§1.2 游标分页；首屏 30 条，“加载更多”取更早的，T-F21） */
const announcementId = (a: Announcement) => a.id;
export const useAnnouncements = (code: string | undefined, enabled = true) =>
  useCursorPages<Announcement, AnnouncementsResponse>({
    queryKey: mk.announcements(code ?? ''), path: `/securities/${enc(code ?? '')}/announcements`, limit: 30, enabled: enabled && opt(code), idOf: announcementId,
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

/** 契约 §7.3：q 归一化（NFKC、去空白）后长度 1–20，超出服务端返回 400；前端先拦下，不发请求 */
export const SEARCH_Q_MAX = 20;
export const searchQLength = (raw: string) => raw.normalize('NFKC').replace(/\s+/g, '').length;

/**
 * 契约 §7.3 GET /securities/search（v0.2.7；不分页，默认 stock,cdr,etf，最多 20 条；/securities?q= 只是旧别名）。
 * v0.2.9 #41：响应 `Cache-Control: private, no-store` → staleTime 0（不当作新鲜缓存复用），不写本地存储；
 * 429 不自动重试（shouldRetry 不重试 4xx），由调用方按 retry_after_s 暂停（paused）。
 */
export const useSecuritySearch = (raw: string, opts: { paused?: boolean } = {}) => {
  // 评审 T-F22a m13：queryKey 与请求参数都用去空格后的 q
  const q = raw.trim();
  return useQuery({
    queryKey: mk.search(q),
    queryFn: ({ signal }) => apiGet<SecuritySearchResponse>('/securities/search', { q, limit: 20 }, signal),
    enabled: q.length > 0 && searchQLength(q) <= SEARCH_Q_MAX && !opts.paused,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
};
