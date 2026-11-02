/** 管理端查询（契约 v0.2.8 §7.9）。非管理员 404，不重试。 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';
import type { AdminDataLicence, AdminIngestStatus } from './adminTypes';
import { useCursorPages } from '../lib/cursorPaging';

export const useAdminIngestStatus = () =>
  useQuery({ queryKey: ['admin', 'ingest', 'status'], queryFn: () => apiGet<AdminIngestStatus>('/admin/ingest/status'), retry: false, refetchInterval: 30_000 });

const licenceUserId = (r: AdminDataLicence) => r.user_id;
/** GET /admin/data-licences：§1.2 游标分页；契约未定义筛选参数，只传 limit/cursor */
export const useAdminDataLicences = (limit = 50) =>
  useCursorPages<AdminDataLicence>({ queryKey: ['admin', 'data-licences'], path: '/admin/data-licences', limit, retry: false, idOf: licenceUserId });

export type AdminLicenceOp = 'pause' | 'resume';
/**
 * POST /admin/data-licences/{user_id}/pause|resume {reason} → 204。
 * 重复暂停幂等（v0.2.8 补充⑤）：已暂停再 pause 也是 204，所以成功后一律重新拉取列表与采集状态，以服务端状态为准。
 */
export function useAdminLicenceAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, op, reason }: { userId: string; op: AdminLicenceOp; reason: string }) =>
      apiPost<void>(`/admin/data-licences/${encodeURIComponent(userId)}/${op}`, { reason }),
    onSettled: () => Promise.all([
      qc.invalidateQueries({ queryKey: ['admin', 'data-licences'] }),
      qc.invalidateQueries({ queryKey: ['admin', 'ingest'] }),
    ]),
  });
}
