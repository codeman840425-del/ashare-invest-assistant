/** T-F18：计划草案（契约 v0.2.8 §7.7） */
import { useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, apiGet, apiPost, newIdempotencyKey } from './client';
import type { PlanDraftStatus } from './enums';
import type { PlanDraft, PlanDraftConfirm, PlanDraftConfirmResult } from './planTypes';
import { qk } from './queries';
import { useCursorPages } from '../lib/cursorPaging';

export interface PlanDraftFilter { status: PlanDraftStatus[]; security_code: string; signal_id: string }
export const pdk = {
  list: (f: PlanDraftFilter) => ['plan-drafts', 'list', f] as const,
  one: (id: string) => ['plan-drafts', 'one', id] as const,
};

export const usePlanDrafts = (f: PlanDraftFilter) =>
  useCursorPages<PlanDraft>({
    queryKey: pdk.list(f),
    path: '/plan-drafts',
    params: { status: f.status.join(','), security_code: f.security_code, signal_id: f.signal_id },
    idOf: (d) => d.id,
  });

export const usePlanDraft = (id: string) =>
  useQuery({
    queryKey: pdk.one(id),
    queryFn: ({ signal }) => apiGet<PlanDraft>(`/plan-drafts/${encodeURIComponent(id)}`, undefined, signal),
    enabled: !!id,
  });

function useInvalidateDrafts() {
  const qc = useQueryClient();
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ['plan-drafts'] }),
      qc.invalidateQueries({ queryKey: ['candidate-signal'] }),
      qc.invalidateQueries({ queryKey: ['candidate-signals'] }),
      qc.invalidateQueries({ queryKey: ['suggestion'] }),
      qc.invalidateQueries({ queryKey: qk.today }),
    ]);
}

/**
 * 生成草案 / 重新生成（stale 后用原 signal_ids 再 POST）。
 * 创建类 POST 带 Idempotency-Key：同一次操作的重试复用同一个键，成功后换新键。
 */
export function useCreatePlanDraft() {
  const inv = useInvalidateDrafts();
  const key = useRef(newIdempotencyKey());
  const lastBody = useRef<string | null>(null);
  return useMutation({
    mutationFn: (signal_ids: string[]) => {
      // 请求体变了（换了信号）就换键，避免同键异体 409 IDEMPOTENCY_CONFLICT
      const body = JSON.stringify(signal_ids);
      if (lastBody.current !== null && lastBody.current !== body) key.current = newIdempotencyKey();
      lastBody.current = body;
      return apiPost<PlanDraft>('/plan-drafts', { signal_ids }, { idempotencyKey: key.current });
    },
    onSuccess: async () => {
      key.current = newIdempotencyKey();
      await inv();
    },
    /** 评审 53468a5 m1：与确认一致，服务端已给出明确结果（如 409 SIGNAL_NOT_EXECUTABLE）就换键；只有网络错误才复用同键重试 */
    onError: (e) => {
      if (e instanceof ApiError && e.code !== 'NETWORK_ERROR') key.current = newIdempotencyKey();
    },
  });
}

export function useConfirmPlanDraft(id: string) {
  const inv = useInvalidateDrafts();
  const key = useRef(newIdempotencyKey());
  return useMutation({
    mutationFn: (body: PlanDraftConfirm) =>
      apiPost<PlanDraftConfirmResult>(`/plan-drafts/${encodeURIComponent(id)}/confirm`, body, { idempotencyKey: key.current }),
    onSuccess: async () => {
      key.current = newIdempotencyKey();
      await inv();
    },
    /** 请求体变了（例如改了数量）要换键，否则服务端会按同键异体返回 409 IDEMPOTENCY_CONFLICT */
    onError: (e) => {
      if (e instanceof ApiError && e.code !== 'NETWORK_ERROR') key.current = newIdempotencyKey();
    },
  });
}

export function useDiscardPlanDraft(id: string) {
  const inv = useInvalidateDrafts();
  return useMutation({
    // v0.2.9 #11（不兼容）：请求体为 {}，不再带 note
    mutationFn: () => apiPost<PlanDraft>(`/plan-drafts/${encodeURIComponent(id)}/discard`, {}),
    onSuccess: inv,
  });
}
