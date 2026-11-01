/**
 * 通用游标分页（契约 §1.2，T-F21）：`?limit=&cursor=` → `{items, next_cursor}`，`next_cursor=null` 为最后一页。
 * 基于 useInfiniteQuery：已加载的页全部保留在同一个缓存项里，“加载更多”只请求下一页，不重拉前面的页。
 * 配合 components/CursorPager 使用（按钮、已加载条数、下一页失败时就地重试）。
 */
import { useMemo } from 'react';
import { useInfiniteQuery, type QueryKey } from '@tanstack/react-query';
import { apiGet, type QueryParams } from '../api/client';
import type { Paged } from '../api/types';

/** 契约 §1.2：limit 默认 50、最大 200 */
export const CURSOR_LIMIT_MAX = 200;
export const clampLimit = (n: number) => Math.min(Math.max(Math.trunc(n) || 50, 1), CURSOR_LIMIT_MAX);

/** 合并各页；跨页重复的 id（翻页期间有新数据插入导致的错位）只保留第一次出现的那条 */
export function flattenPages<T>(pages: readonly { items: readonly T[] }[] | undefined, idOf?: (row: T) => string): T[] {
  if (!pages) return [];
  const all = pages.flatMap((p) => p.items);
  if (!idOf) return all;
  const seen = new Set<string>();
  return all.filter((r) => {
    const id = idOf(r);
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

export interface CursorPagesOptions<T> {
  queryKey: QueryKey;
  path: string;
  params?: QueryParams;
  limit?: number;
  enabled?: boolean;
  idOf?: (row: T) => string;
  retry?: boolean | number;
}

export function useCursorPages<T, P extends Paged<T> = Paged<T>>({ queryKey, path, params, limit = 50, enabled = true, idOf, retry }: CursorPagesOptions<T>) {
  const lim = clampLimit(limit);
  const query = useInfiniteQuery({
    queryKey: [...queryKey, { limit: lim }],
    initialPageParam: null as string | null,
    queryFn: ({ signal, pageParam }) => apiGet<P>(path, { ...params, limit: lim, cursor: pageParam }, signal),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled,
    ...(retry === undefined ? {} : { retry }),
  });
  const pages = query.data?.pages;
  const items = useMemo(() => flattenPages<T>(pages, idOf), [pages, idOf]);
  /** 第一页（附带 data_status / disclaimer 等页级字段的接口用它） */
  const first = pages?.[0];
  return { ...query, items, first };
}
