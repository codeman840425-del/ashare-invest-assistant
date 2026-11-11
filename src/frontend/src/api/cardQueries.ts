/** F-04：策略知识卡查询（契约 §7.4 GET /strategy-cards、/{id}、/{id}/versions、/versions/{no}） */
import { useQuery } from '@tanstack/react-query';
import { apiGet } from './client';
import type { Paged } from './types';
import type { CardCompleteness, Horizon } from './enums';
import type { FeatureCatalogItem, StrategyCardDetail, StrategyCardListItem, StrategyCardVersion } from './cardTypes';

export const ck = {
  cards: (f: CardFilters) => ['strategy-cards', f.completeness ?? null, f.horizon ?? null, f.category ?? null] as const,
  card: (id: string) => ['strategy-card', id] as const,
  cardVersion: (id: string, no: number) => ['strategy-card', id, 'v', no] as const,
  versions: (id: string) => ['strategy-card', id, 'versions'] as const,
  featureCatalog: ['feature-catalog'] as const,
};

export interface CardFilters {
  completeness?: CardCompleteness;
  horizon?: Horizon;
  category?: string;
}

/** 列表：§1.2 游标分页。卡片数量有限（知识卡不是海量数据），按页取到上限即止 */
export async function fetchCards(f: CardFilters, signal?: AbortSignal, limit = 100, maxPages = 5): Promise<{ items: StrategyCardListItem[]; truncated: boolean }> {
  const items: StrategyCardListItem[] = [];
  let cursor: string | null = null;
  for (let i = 0; i < maxPages; i++) {
    const params: Record<string, string | number> = { limit };
    if (cursor) params.cursor = cursor;
    if (f.completeness) params.completeness = f.completeness;
    if (f.horizon) params.horizon = f.horizon;
    if (f.category) params.category = f.category;
    const p: Paged<StrategyCardListItem> = await apiGet<Paged<StrategyCardListItem>>('/strategy-cards', params, signal);
    items.push(...p.items);
    cursor = p.next_cursor;
    if (!cursor) return { items, truncated: false };
  }
  return { items, truncated: true };
}

export const useStrategyCards = (f: CardFilters = {}) =>
  useQuery({ queryKey: ck.cards(f), queryFn: ({ signal }) => fetchCards(f, signal) });

export const useStrategyCard = (id: string | undefined) =>
  useQuery({
    queryKey: ck.card(id ?? ''),
    queryFn: ({ signal }) => apiGet<StrategyCardDetail>(`/strategy-cards/${encodeURIComponent(id!)}`, undefined, signal),
    enabled: Boolean(id),
  });

/** 历史版本内容（`/versions/{no}` 与详情端点同结构） */
export const useStrategyCardVersion = (id: string | undefined, no: number | undefined) =>
  useQuery({
    queryKey: ck.cardVersion(id ?? '', no ?? 0),
    queryFn: ({ signal }) =>
      apiGet<StrategyCardDetail>(`/strategy-cards/${encodeURIComponent(id!)}/versions/${no}`, undefined, signal),
    enabled: Boolean(id) && typeof no === 'number',
  });

export const useStrategyCardVersions = (id: string | undefined) =>
  useQuery({
    queryKey: ck.versions(id ?? ''),
    queryFn: ({ signal }) => apiGet<StrategyCardVersion[]>(`/strategy-cards/${encodeURIComponent(id!)}/versions`, undefined, signal),
    enabled: Boolean(id),
  });

export const useFeatureCatalog = () =>
  useQuery({ queryKey: ck.featureCatalog, queryFn: ({ signal }) => apiGet<FeatureCatalogItem[]>('/feature-catalog', undefined, signal) });
