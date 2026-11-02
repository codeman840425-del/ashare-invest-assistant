/** T-F23：研究候选查询与写操作（契约 v0.2.9 §7.7A）。写操作后整体失效重拉，没有 SSE 与通知 */
import { useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, apiGet, apiPost, newIdempotencyKey } from './client';
import { ENUMS, type ResearchCandidateOrigin, type ResearchCandidateStatus } from './enums';
import type {
  CandidateCreate, CandidateVersion, CandidateVersionCreate, ResearchCandidate, ResearchCandidateSummary,
} from './candidateTypes';
import { useCursorPages } from '../lib/cursorPaging';

/** 契约默认：researching,watching,planned（不含 dropped） */
export const DEFAULT_CANDIDATE_STATUS: ResearchCandidateStatus[] = ['researching', 'watching', 'planned'];

export interface CandidateFilter {
  /** 'all' 不按状态过滤；空数组表示用服务端默认 */
  status: ResearchCandidateStatus[] | 'all';
  origin?: ResearchCandidateOrigin | '';
  security_code?: string;
  suggestion_id?: string;
}
export const rck = {
  all: ['candidates'] as const,
  list: (f: CandidateFilter) => ['candidates', 'list', f] as const,
  one: (id: string) => ['candidates', 'one', id] as const,
  versions: (id: string) => ['candidates', 'versions', id] as const,
  version: (id: string, n: number) => ['candidates', 'version', id, n] as const,
};

export const candidateParams = (f: CandidateFilter) => ({
  status: f.status === 'all' ? 'all' : f.status.length ? f.status.join(',') : undefined,
  origin: f.origin || undefined,
  security_code: f.security_code || undefined,
  suggestion_id: f.suggestion_id || undefined,
});

export const useCandidates = (f: CandidateFilter, opts: { enabled?: boolean; limit?: number } = {}) =>
  useCursorPages<ResearchCandidateSummary>({
    queryKey: rck.list(f),
    path: '/candidates',
    params: candidateParams(f),
    idOf: (c) => c.id,
    enabled: opts.enabled,
    limit: opts.limit,
  });

export const useCandidate = (id: string) =>
  useQuery({
    queryKey: rck.one(id),
    queryFn: ({ signal }) => apiGet<ResearchCandidate>(`/candidates/${encodeURIComponent(id)}`, undefined, signal),
    enabled: !!id,
  });

export const useCandidateVersions = (id: string) =>
  useCursorPages<CandidateVersion>({
    queryKey: rck.versions(id),
    path: `/candidates/${encodeURIComponent(id)}/versions`,
    idOf: (v) => v.id,
    enabled: !!id,
  });

export const useCandidateVersion = (id: string, n: number | null) =>
  useQuery({
    queryKey: rck.version(id, n ?? 0),
    queryFn: ({ signal }) => apiGet<CandidateVersion>(`/candidates/${encodeURIComponent(id)}/versions/${n}`, undefined, signal),
    enabled: !!id && n !== null,
  });

/**
 * 创建类 POST 带 Idempotency-Key：同一次操作的网络重试复用同一个键；
 * 请求体变了或服务端已给出明确结果就换键（避免同键异体 409 IDEMPOTENCY_CONFLICT）。
 */
function useIdemMutation<B, R>(post: (body: B, key: string) => Promise<R>) {
  const qc = useQueryClient();
  const key = useRef(newIdempotencyKey());
  const lastBody = useRef<string | null>(null);
  return useMutation({
    mutationFn: (body: B) => {
      const text = JSON.stringify(body);
      if (lastBody.current !== null && lastBody.current !== text) key.current = newIdempotencyKey();
      lastBody.current = text;
      return post(body, key.current);
    },
    onSuccess: async () => {
      key.current = newIdempotencyKey();
      lastBody.current = null;
      await qc.invalidateQueries({ queryKey: rck.all });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code !== 'NETWORK_ERROR') {
        key.current = newIdempotencyKey();
        lastBody.current = null;
      }
    },
  });
}

export const useCreateCandidate = () =>
  useIdemMutation<CandidateCreate, ResearchCandidate>((body, idempotencyKey) => apiPost<ResearchCandidate>('/candidates', body, { idempotencyKey }));

export const useCreateCandidateVersion = (id: string) =>
  useIdemMutation<CandidateVersionCreate, ResearchCandidate>((body, idempotencyKey) =>
    apiPost<ResearchCandidate>(`/candidates/${encodeURIComponent(id)}/versions`, body, { idempotencyKey }));

export const CANDIDATE_STATUSES = ENUMS.research_candidate_status as readonly ResearchCandidateStatus[];

/** ?status= 解析：all → 不按状态过滤；非法值丢弃；空 → 契约默认（不含已放弃） */
export function parseCandidateStatus(raw: string | null): ResearchCandidateStatus[] | 'all' {
  if (raw === 'all') return 'all';
  const xs = (raw ?? '').split(',').map((x) => x.trim()).filter((x): x is ResearchCandidateStatus => (CANDIDATE_STATUSES as readonly string[]).includes(x));
  return xs.length ? xs : DEFAULT_CANDIDATE_STATUS;
}
