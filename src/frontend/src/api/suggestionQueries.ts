/**
 * 候选信号卡补全（T-F12，契约 §7 /suggestions*）：跟踪统计、用户动作、手动刷新。
 * 只用契约已给出的结构；actions 响应体契约未定，不读取；refresh 按契约 #36 读取响应体。
 */
import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';
import type { Stat, Suggestion } from './types';
import { qk } from './queries';

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
 * 契约 v0.2.9 #36：POST /suggestions/refresh 同步处理，200 响应体。
 * 新建 → changed=true、superseded_id=null；取代旧卡 → changed=true、superseded_id=旧卡 id；
 * 无变化 → changed=false，suggestion 为当前有效的那条（当前没有任何建议时为 null）。
 */
export interface RefreshSuggestionResponse {
  suggestion: Suggestion | null;
  changed: boolean;
  superseded_id: string | null;
  data_as_of: string;
}

/**
 * 手动刷新：POST /suggestions/refresh {security_code}，一律以响应体为准（#36），不再另发 GET 查当前卡。
 * 响应里的卡直接写入详情缓存，再让列表、终端、今日页按需重拉。
 */
export function useRefreshSuggestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (security_code: string) => apiPost<RefreshSuggestionResponse>('/suggestions/refresh', { security_code }),
    onSuccess: async (res) => {
      if (res.suggestion) qc.setQueryData(qk.suggestion(res.suggestion.id), res.suggestion);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['suggestions'] }),
        // 被取代的旧卡状态变了；契约允许刷新后再 GET（结果一致），详情缓存统一失效
        qc.invalidateQueries({ queryKey: ['suggestion'] }),
        qc.invalidateQueries({ queryKey: ['terminal'] }),
        qc.invalidateQueries({ queryKey: ['today'] }),
      ]);
    },
  });
}
