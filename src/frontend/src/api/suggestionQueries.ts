/**
 * 候选信号卡补全（T-F12，契约 §7 /suggestions*）：跟踪统计、用户动作、手动刷新。
 * 只用契约已给出的请求结构；响应体契约未定的（actions、refresh）一律不读取响应内容。
 */
import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';
import type { Paged, Stat, SuggestionListItem } from './types';

export interface SuggestionTracking { t1: Stat; t5: Stat; t20: Stat }

export const useSuggestionTracking = (id: string | undefined) =>
  useQuery({
    queryKey: ['suggestion-tracking', id ?? ''] as const,
    queryFn: ({ signal }) => apiGet<SuggestionTracking>(`/suggestions/${encodeURIComponent(id!)}/tracking`, undefined, signal),
    enabled: !!id,
  });

/** 契约：kind 只有 viewed / dismissed / acted_trade_linked；草案相关动作由服务端自动写入，前端不发 */
export type SuggestionActionKind = 'viewed' | 'dismissed';

const postAction = (id: string, kind: SuggestionActionKind, note: string | null) =>
  apiPost<unknown>(`/suggestions/${encodeURIComponent(id)}/actions`, { kind, trade_id: null, note });

export const useSuggestionAction = (id: string) =>
  useMutation({ mutationFn: ({ kind, note }: { kind: SuggestionActionKind; note: string | null }) => postAction(id, kind, note) });

/** 本页会话内每张卡只记一次 viewed（失败不重试、不打扰用户） */
const viewedOnce = new Set<string>();
export function resetViewedOnce() {
  viewedOnce.clear();
}
export function useMarkViewed(id: string | undefined) {
  useEffect(() => {
    if (!id || viewedOnce.has(id)) return;
    viewedOnce.add(id);
    postAction(id, 'viewed', null).catch(() => undefined);
  }, [id]);
}

/**
 * 手动刷新：POST /suggestions/refresh {security_code}。响应结构契约未定，刷新后按
 * GET /suggestions?security_code=&status=active 取当前卡（同一证券至多 1 张），返回其 id（没有则 null）。
 */
export function useRefreshSuggestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (security_code: string) => {
      await apiPost<unknown>('/suggestions/refresh', { security_code });
      const list = await apiGet<Paged<SuggestionListItem>>('/suggestions', { security_code, status: 'active', limit: 1 });
      return list.items[0]?.id ?? null;
    },
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['suggestions'] }),
        qc.invalidateQueries({ queryKey: ['suggestion'] }),
        qc.invalidateQueries({ queryKey: ['terminal'] }),
        qc.invalidateQueries({ queryKey: ['today'] }),
      ]);
    },
  });
}
