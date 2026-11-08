import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';
import type { AutomaticGateId, PromotionFilters, PromotionReport, PromotionSummary } from './promotionTypes';
import type { Lifecycle } from './enums';
import type { Paged } from './types';
import { sk } from './strategyQueries';
export function usePromotions(filters: PromotionFilters, cursor: string | null) {
  return useQuery({ queryKey: ['promotions', filters, cursor],
    queryFn: ({ signal }) => apiGet<Paged<PromotionSummary>>('/admin/promotions', { ...filters, cursor, limit: 20 }, signal) });
}
export function usePromotionReport(id: string, enabled: boolean) {
  return useQuery({ queryKey: ['promotion-report', id], enabled: enabled && !!id,
    queryFn: ({ signal }) => apiGet<PromotionReport>(`/promotion-requests/${encodeURIComponent(id)}`, undefined, signal) });
}
/** 密码在请求发出时从非受控输入读取并清空，不放入 mutation variables/cache。 */
export function useApprovePromotion(id: string, takePassword: () => string) {
  const qc = useQueryClient();
  return useMutation({ retry: false, mutationFn: (body: { comment: string; ack_warn_gates: AutomaticGateId[] }) =>
    apiPost<PromotionSummary>(`/admin/promotions/${encodeURIComponent(id)}/decision`, { decision: 'approved', ...body, password: takePassword() }),
    onSuccess: async () => {
      await Promise.all([qc.invalidateQueries({ queryKey: ['promotion-report', id] }), qc.invalidateQueries({ queryKey: ['promotions'] })]);
    } });
}
export function useStrategyLifecycle(takePassword: () => string) {
  const qc = useQueryClient();
  return useMutation({ retry: false, mutationFn: ({ id, vid, reason, review_id }: { id: string; vid: string; reason: string; review_id: string }) =>
    apiPost<{ from: Lifecycle; to: Lifecycle }>(`/admin/strategies/${encodeURIComponent(id)}/versions/${encodeURIComponent(vid)}/lifecycle`, { to: 'simulating', reason, review_id, password: takePassword() }),
    onSuccess: async () => { await Promise.all([qc.invalidateQueries({ queryKey: sk.templates }), qc.invalidateQueries({ queryKey: ['promotions'] })]); } });
}
