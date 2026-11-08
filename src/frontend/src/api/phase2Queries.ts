/** P2N-05a：只走既有同源API；mock阶段不配置真实后端，不拉取外部行情。 */
import { useMutation, useQuery, useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPut } from './client';
import type { RiskControlSetting, RiskEvaluation, RiskEvent } from './phase2Types';
import type { Paged } from './types';
export const useRiskSettings = () => useQuery({ queryKey: ['risk-settings'], queryFn: ({ signal }) => apiGet<RiskControlSetting[]>('/risk-controls', undefined, signal) });
export function useSaveRiskSettings() {
  const client = useQueryClient();
  return useMutation({ mutationFn: (item: RiskControlSetting) => apiPut<RiskControlSetting[]>('/risk-controls', [{ control: item.control, enabled: item.enabled, params: item.params }]),
    onSuccess: async (data) => { client.setQueryData(['risk-settings'], data); await client.invalidateQueries({ queryKey: ['risk-evaluation'] }); } });
}
export const useRiskEvaluation = (code: string) => useQuery({ queryKey: ['risk-evaluation', code], enabled: !!code,
  queryFn: ({ signal }) => apiGet<RiskEvaluation>('/risk-controls/evaluation', { security_code: code }, signal) });
export function useRiskEvents(status: string, control: string, code: string, since: string) {
  return useInfiniteQuery({ queryKey: ['risk-events', status, control, code, since], initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => apiGet<Paged<RiskEvent>>('/risk-controls/events', { status: status || undefined, control: control || undefined, security_code: code || undefined, since: since || undefined, cursor: pageParam, limit: 20 }, signal),
    getNextPageParam: (last) => last.next_cursor ?? undefined });
}
