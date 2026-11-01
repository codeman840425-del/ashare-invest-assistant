/** T-F22：本人数据证书的查询与变更（契约 v0.2.6 §7.1）。证书值只出现在 PUT 请求体里，不进查询缓存。 */
import { useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from './client';
import type { DataLicencePatch, DataLicencePut, DataLicenceStatus, DataLicenceTestResponse } from './licenceTypes';
import { qk } from './queries';

export const lk = { status: ['me', 'data-licence'] as const };

export const useDataLicence = (opts: { pollWhilePending?: boolean } = {}) =>
  useQuery({
    queryKey: lk.status,
    queryFn: ({ signal }) => apiGet<DataLicenceStatus>('/me/data-licence', undefined, signal),
    // 验证中时轮询（结果也会经 SSE data_licence 推送；SSE 由通知模块统一接入）
    refetchInterval: (q) => (opts.pollWhilePending && q.state.data?.status === 'pending_verification' ? 3000 : false),
  });

function useAfterChange() {
  const qc = useQueryClient();
  return (s?: DataLicenceStatus) => {
    if (s) qc.setQueryData(lk.status, s);
    else void qc.invalidateQueries({ queryKey: lk.status });
    // Me.data_licence_status 驱动全站横幅
    void qc.invalidateQueries({ queryKey: qk.me });
  };
}

/**
 * 设置 / 替换证书。证书值**不进** mutation 变量（变量会留在 MutationCache 里）：
 * 调用方 `submit(licence, meta)`，证书暂存在 ref，发请求时取出并立刻清空；缓存里只有档位等元数据。
 */
export function usePutDataLicence() {
  const after = useAfterChange();
  const pending = useRef<string | null>(null);
  const m = useMutation({
    mutationFn: (meta: Omit<DataLicencePut, 'licence'>) => {
      const licence = pending.current ?? '';
      pending.current = null;
      return apiPut<DataLicenceStatus>('/me/data-licence', { licence, ...meta });
    },
    onSuccess: (s) => after(s),
  });
  const submit = (licence: string, meta: Omit<DataLicencePut, 'licence'>, opts?: Parameters<typeof m.mutate>[1]) => {
    pending.current = licence;
    m.mutate(meta, opts);
  };
  return { ...m, submit };
}
export function usePatchDataLicence() {
  const after = useAfterChange();
  return useMutation({ mutationFn: (b: DataLicencePatch) => apiPatch<DataLicenceStatus>('/me/data-licence', b), onSuccess: (s) => after(s) });
}
export function useDeleteDataLicence() {
  const after = useAfterChange();
  return useMutation({ mutationFn: () => apiDelete<void>('/me/data-licence'), onSuccess: () => after() });
}
export function useTestDataLicence() {
  const after = useAfterChange();
  return useMutation({ mutationFn: () => apiPost<DataLicenceTestResponse>('/me/data-licence/test'), onSuccess: () => after() });
}
