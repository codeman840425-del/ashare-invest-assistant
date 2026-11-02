/**
 * T-F17：候选信号与不可执行原因（契约 v0.2.7 §7.6）。
 * 列表走 §1.2 游标分页；按 signal_ids 取原因时不分页（返回 {items}）。
 */
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';
import type { CandidateSignalEventCause, CandidateSignalState, Horizon } from './enums';
import type { CandidateSignal, NonExecutableReason } from './types';
import type { StrategyTracking } from './strategyTypes';
import { qk } from './queries';
import { useCursorPages } from '../lib/cursorPaging';

export interface SignalFilter { state: CandidateSignalState | ''; security_code: string; horizon: Horizon | ''; instance_id: string }
/** 契约 v0.2.9 #6：`/candidate-signals/{id}/events` 元素；不返回 detail */
export interface SignalEvent { id: string; from: CandidateSignalState | null; to: CandidateSignalState; cause: CandidateSignalEventCause; at: string }

export const sgk = {
  list: (f: SignalFilter) => ['candidate-signals', 'list', f] as const,
  events: (id: string) => ['candidate-signal', id, 'events'] as const,
  reasonsAll: (id: string) => ['non-executable-reasons', 'signal-all', id] as const,
  released: (since: string) => ['non-executable-reasons', 'released', since] as const,
  tracking: (sid: string, vid: string) => ['strategy-tracking', sid, vid] as const,
};

const signalId = (c: CandidateSignal) => c.id;
const reasonId = (r: NonExecutableReason) => r.id;

export const useSignalList = (f: SignalFilter) =>
  useCursorPages<CandidateSignal>({ queryKey: sgk.list(f), path: '/candidate-signals', params: { ...f }, idOf: signalId });

export const useSignal = (id: string) =>
  useQuery({
    queryKey: qk.candidateSignal(id),
    queryFn: ({ signal }) => apiGet<CandidateSignal>(`/candidate-signals/${encodeURIComponent(id)}`, undefined, signal),
    enabled: !!id,
  });

/** 契约 v0.2.9 #6（不兼容）：§1.2 分页 `{items, next_cursor}`，排序 `at desc, id desc` */
const eventId = (e: SignalEvent) => e.id;
export const useSignalEvents = (id: string) =>
  useCursorPages<SignalEvent>({
    queryKey: sgk.events(id),
    path: `/candidate-signals/${encodeURIComponent(id)}/events`,
    enabled: !!id,
    idOf: eventId,
  });

/** 该信号的全部原因（含已解除、已作废），用来显示自动重评状态 */
export const useSignalReasonsAll = (id: string) =>
  useQuery({
    queryKey: sgk.reasonsAll(id),
    // v0.2.9 #12：默认只返回 active，自动重评状态要显示已解除/已作废，须传 status=all
    queryFn: ({ signal }) => apiGet<{ items: NonExecutableReason[] }>('/non-executable-reasons', { signal_ids: id, status: 'all' }, signal),
    enabled: !!id,
  });

/**
 * 列表页方向冲突（契约 v0.2.9 #7）：不在前端比较方向，改看服务端写入的 STRATEGY_CONFLICT 原因（默认 status=active）。
 * signal_ids 每批 ≤ 100（超出 400），带 signal_ids 时不分页。
 */
export function useConflictSignalIds(ids: readonly string[]) {
  const batches: string[][] = [];
  for (let i = 0; i < ids.length; i += 100) batches.push(ids.slice(i, i + 100));
  return useQueries({
    queries: batches.map((b) => ({
      queryKey: ['non-executable-reasons', 'conflict', b.join(',')] as const,
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        apiGet<{ items: NonExecutableReason[] }>('/non-executable-reasons', { signal_ids: b.join(','), code: 'STRATEGY_CONFLICT' }, signal),
    })),
    combine: (rs) => new Set(rs.flatMap((r) => (r.data?.items ?? []).filter((x) => x.code === 'STRATEGY_CONFLICT' && x.status === 'active').map((x) => x.signal_id))),
  });
}

/** 今日已解除（/today “查看全部” → ?tab=released）：status=released&released_since={trade_date}T00:00:00+08:00 */
export const releasedSince = (tradeDate: string) => `${tradeDate}T00:00:00+08:00`;
export const useReleasedReasons = (tradeDate: string | undefined) =>
  useCursorPages<NonExecutableReason>({
    queryKey: sgk.released(tradeDate ?? ''),
    path: '/non-executable-reasons',
    params: { status: 'released', released_since: tradeDate ? releasedSince(tradeDate) : '' },
    enabled: !!tradeDate,
    idOf: reasonId,
  });

/** 写操作后统一失效：原因、信号详情、信号列表、建议卡、首页 */
function useInvalidateSignals() {
  const qc = useQueryClient();
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ['non-executable-reasons'] }),
      qc.invalidateQueries({ queryKey: ['candidate-signal'] }),
      qc.invalidateQueries({ queryKey: ['candidate-signals'] }),
      qc.invalidateQueries({ queryKey: ['suggestion'] }),
      qc.invalidateQueries({ queryKey: qk.today }),
    ]);
}

export function useDismissSignal() {
  const inv = useInvalidateSignals();
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note: string | null }) => apiPost<CandidateSignal>(`/candidate-signals/${encodeURIComponent(id)}/dismiss`, { note }),
    onSuccess: inv,
  });
}

/** 仅 machine_checkable=false 的原因可手动解除；否则 409 REASON_NOT_MANUALLY_RELEASABLE */
export function useReleaseReason() {
  const inv = useInvalidateSignals();
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note: string | null }) =>
      apiPost<NonExecutableReason>(`/non-executable-reasons/${encodeURIComponent(id)}/release`, { confirm: true, note }),
    onSuccess: inv,
  });
}

export const useStrategyTracking = (strategyId: string | undefined, versionId: string) =>
  useQuery({
    queryKey: sgk.tracking(strategyId ?? '', versionId),
    queryFn: ({ signal }) =>
      // v0.2.9 #10：信号详情只看本人（scope=mine，也是默认值）；全站汇总只在策略页展示
      apiGet<StrategyTracking>(`/strategies/${encodeURIComponent(strategyId!)}/versions/${encodeURIComponent(versionId)}/tracking`, { scope: 'mine' }, signal),
    enabled: !!strategyId && !!versionId,
  });
