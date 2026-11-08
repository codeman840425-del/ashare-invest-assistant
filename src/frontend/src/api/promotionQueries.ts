import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';
import type { PromotionReport } from './promotionTypes';
import type { Lifecycle } from './enums';
import { sk } from './strategyQueries';
export function usePromotionReport(id: string, enabled: boolean) {
  return useQuery({ queryKey: ['promotion-report', id], enabled: enabled && !!id,
    queryFn: ({ signal }) => apiGet<PromotionReport>(`/promotion-requests/${encodeURIComponent(id)}`, undefined, signal) });
}
export function useApprovePromotion(id: string) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (comment: string) => apiPost(`/admin/promotions/${encodeURIComponent(id)}/decision`, { decision: 'approved', comment }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['promotion-report', id] }) });
}
export function useStrategyLifecycle() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: ({ id, vid, reason }: { id: string; vid: string; reason: string }) =>
    apiPost<{ from: Lifecycle; to: Lifecycle }>(`/admin/strategies/${encodeURIComponent(id)}/versions/${encodeURIComponent(vid)}/lifecycle`, { to: 'simulating', reason }),
    onSuccess: () => qc.invalidateQueries({ queryKey: sk.templates }) });
}
