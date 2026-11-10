/**
 * T-F33 自选股：GET /watchlist、POST /watchlist（Idempotency-Key + CSRF）、DELETE /watchlist/{security_code}。
 * 契约 docs/contracts/watchlist.md（T-A129 4c89336）。CSRF 由 api/client 对所有写请求统一带 X-CSRF-Token。
 * 写成功、409（已在自选）、404（已不在自选）后都重拉列表与依赖自选的聚合（/terminal、/today）。
 */
import { useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, apiDelete, apiGet, apiPost, newIdempotencyKey } from './client';
import type { WatchlistCreate, WatchlistIssue, WatchlistLimitDetails, WatchlistItem, WatchlistResponse } from './watchlistTypes';

export const wlk = { all: ['watchlist'] as const };

export const fetchWatchlist = (signal?: AbortSignal) => apiGet<WatchlistResponse>('/watchlist', undefined, signal);
export const addWatchlist = (body: WatchlistCreate, idempotencyKey: string) => apiPost<WatchlistItem>('/watchlist', body, { idempotencyKey });
export const removeWatchlist = (code: string) => apiDelete<void>(`/watchlist/${encodeURIComponent(code)}`);

export const useWatchlist = (enabled = true) =>
  useQuery({ queryKey: wlk.all, queryFn: ({ signal }) => fetchWatchlist(signal), enabled });

/** 规范代码比较：入口传入的都是 6 位 + 交易所后缀，统一转大写后比较 */
export const sameCode = (a: string, b: string) => a.trim().toUpperCase() === b.trim().toUpperCase();
export const inWatchlist = (data: WatchlistResponse | undefined, code: string) => !!data?.items.some((x) => sameCode(x.security_code, code));

const refreshAfterWrite = (qc: ReturnType<typeof useQueryClient>) =>
  Promise.all([
    qc.invalidateQueries({ queryKey: wlk.all }),
    qc.invalidateQueries({ queryKey: ['terminal'] }),
    qc.invalidateQueries({ queryKey: ['today'] }),
  ]);

/** 已有确定结果、刷新列表就能纠正状态的错误：409 已在自选、404 已不在自选 */
const settles = (e: unknown) => e instanceof ApiError && ((e.status === 409 && e.code === 'CONFLICT') || (e.status === 404 && e.code === 'NOT_FOUND'));

/**
 * 加自选：同一代码的网络错误 / 5xx 重试复用同一个 Idempotency-Key（服务端可能已处理完）；
 * 成功或得到明确 4xx 后换键，避免同键异体 409 IDEMPOTENCY_CONFLICT。
 */
export function useAddWatchlist() {
  const qc = useQueryClient();
  const key = useRef(newIdempotencyKey());
  const lastBody = useRef<string | null>(null);
  return useMutation({
    mutationFn: (body: WatchlistCreate) => {
      const text = JSON.stringify(body);
      if (lastBody.current !== null && lastBody.current !== text) key.current = newIdempotencyKey();
      lastBody.current = text;
      return addWatchlist(body, key.current);
    },
    onSuccess: async () => {
      key.current = newIdempotencyKey();
      lastBody.current = null;
      await refreshAfterWrite(qc);
    },
    onError: async (e) => {
      if (e instanceof ApiError && e.code !== 'NETWORK_ERROR' && e.status >= 400 && e.status < 500) {
        key.current = newIdempotencyKey();
        lastBody.current = null;
      }
      if (settles(e)) await refreshAfterWrite(qc);
    },
  });
}

export function useRemoveWatchlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => removeWatchlist(code),
    onSuccess: () => refreshAfterWrite(qc),
    onError: async (e) => {
      if (settles(e)) await refreshAfterWrite(qc);
    },
  });
}

const ISSUE_TEXT: Record<WatchlistIssue, string> = {
  invalid: '证券代码格式不正确',
  unknown_security: '证券主数据中没有该代码',
  security_type_not_supported: '指数不能加入自选',
  delisted: '已退市证券不能加入自选',
  superseded: '该代码已变更',
  too_long: '分组或备注过长',
};

function limitOf(d: Record<string, unknown> | null): WatchlistLimitDetails | null {
  if (!d || typeof d.limit !== 'number') return null;
  return { key: 'watchlist.per_user_cap', limit: d.limit, current: typeof d.current === 'number' ? d.current : d.limit };
}

/** 加入 / 移出自选失败时给用户看的一句话（按契约 ②③⑤⑩） */
export function watchlistErrorText(e: unknown, op: 'add' | 'remove'): string {
  if (!(e instanceof ApiError)) return op === 'add' ? '加入自选失败' : '移出自选失败';
  if (e.status === 409 && e.code === 'CONFLICT') return '已在自选';
  if (e.status === 409 && e.code === 'IDEMPOTENCY_CONFLICT') return '重复提交，请稍后刷新查看';
  if (e.status === 403 && e.code === 'ENTITLEMENT_LIMIT_REACHED') {
    const l = limitOf(e.details);
    return l ? `自选已达上限（${l.current}/${l.limit} 只），请先移出部分自选` : '自选已达上限，请先移出部分自选';
  }
  if (e.status === 404 && op === 'remove') return '该证券已不在自选中';
  if (e.status === 400 && e.code === 'VALIDATION_ERROR') {
    const f = (e.details?.fields as { field?: string; issue?: string; superseded_by?: string }[] | undefined)?.[0];
    const issue = f?.issue as WatchlistIssue | undefined;
    if (issue === 'superseded' && f?.superseded_by) return `该代码已变更为 ${f.superseded_by}`;
    if (issue && issue in ISSUE_TEXT) return ISSUE_TEXT[issue];
  }
  return `${op === 'add' ? '加入自选失败' : '移出自选失败'}：${e.message}`;
}
