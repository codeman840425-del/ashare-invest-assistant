/** T-F22：策略库最小查询（契约 §7.5）。 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';
import type { Paged } from './types';
import type { StrategyInstance, StrategyInstanceCreate, StrategyInstanceCreated, StrategyTemplate } from './strategyTypes';

export const sk = { templates: ['strategies'] as const, instances: ['strategy-instances'] as const };

/** 每页条数（契约上限 200）与最多翻页数；翻到上限仍有 next_cursor 时 truncated = true，页面提示（评审 T-F22a m9） */
export const PAGE_LIMIT = 200;
export const MAX_PAGES = 10;
export interface AllPages<T> { items: T[]; truncated: boolean }

/** 跟随 next_cursor 取完整列表 */
export async function fetchAllPages<T>(path: string, signal?: AbortSignal, limit = PAGE_LIMIT, maxPages = MAX_PAGES): Promise<AllPages<T>> {
  const items: T[] = [];
  let cursor: string | null = null;
  for (let i = 0; i < maxPages; i++) {
    const params: Record<string, string | number> = { limit };
    if (cursor) params.cursor = cursor;
    const p: Paged<T> = await apiGet<Paged<T>>(path, params, signal);
    items.push(...p.items);
    cursor = p.next_cursor;
    if (!cursor) return { items, truncated: false };
  }
  return { items, truncated: true };
}

export const useStrategyTemplates = () =>
  useQuery({ queryKey: sk.templates, queryFn: ({ signal }) => fetchAllPages<StrategyTemplate>('/strategies', signal) });
export const useStrategyInstances = () =>
  useQuery({ queryKey: sk.instances, queryFn: ({ signal }) => fetchAllPages<StrategyInstance>('/strategy-instances', signal) });

export function useCreateStrategyInstance() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: StrategyInstanceCreate) => apiPost<StrategyInstanceCreated>('/strategy-instances', b),
    onSuccess: () => qc.invalidateQueries({ queryKey: sk.instances }),
  });
}
/** 停用 = pause；再次启用已暂停的实例 = resume；已有 proposed 实例时启用 = confirm（契约 §7.5，评审 m6） */
export type InstanceOp = 'pause' | 'resume' | 'confirm';
export function useInstanceTransition() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, to }: { id: string; to: InstanceOp }) => apiPost<StrategyInstance>(`/strategy-instances/${encodeURIComponent(id)}/${to}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: sk.instances }),
  });
}
