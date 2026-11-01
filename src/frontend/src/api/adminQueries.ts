/** 管理端只读查询（契约 v0.2.8 §7.9）。非管理员 404，不重试。 */
import { useQuery } from '@tanstack/react-query';
import { apiGet } from './client';
import type { AdminIngestStatus } from './adminTypes';

export const useAdminIngestStatus = () =>
  useQuery({ queryKey: ['admin', 'ingest', 'status'], queryFn: () => apiGet<AdminIngestStatus>('/admin/ingest/status'), retry: false, refetchInterval: 30_000 });
