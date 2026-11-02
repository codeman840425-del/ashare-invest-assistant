/** T-F23 裁定跟进：操作计划与提醒的查询与写操作（契约 v0.2.9 §7.7B）。写操作后整体失效重拉 */
import { useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, apiGet, apiPatch, apiPost, newIdempotencyKey } from './client';
import { ENUMS, type AlertOrigin, type AlertStatus, type PlanOrigin, type PlanStatus, type Severity } from './enums';
import type { Alert, AlertPatchStatus, Plan, PlanClose, PlanCreate, PlanSummary, PlanVersion, PlanVersionCreate } from './planAlertTypes';
import { useCursorPages } from '../lib/cursorPaging';

/** 契约默认：active,triggered（不含已完成、已取消） */
export const DEFAULT_PLAN_STATUS: PlanStatus[] = ['active', 'triggered'];
/** 契约默认：new,read */
export const DEFAULT_ALERT_STATUS: AlertStatus[] = ['new', 'read'];
export const PLAN_STATUSES = ENUMS.plan_status as readonly PlanStatus[];
export const ALERT_STATUSES = ENUMS.alert_status as readonly AlertStatus[];

/** ?status= 解析：all → 不按状态过滤；非法值丢弃；空 → 契约默认 */
export function parseStatusParam<T extends string>(raw: string | null, all: readonly T[], dflt: T[]): T[] | 'all' {
  if (raw === 'all') return 'all';
  const xs = (raw ?? '').split(',').map((x) => x.trim()).filter((x): x is T => (all as readonly string[]).includes(x));
  return xs.length ? xs : dflt;
}
const statusParam = (s: string[] | 'all') => (s === 'all' ? 'all' : s.length ? s.join(',') : undefined);

export interface PlanFilter { status: PlanStatus[] | 'all'; origin?: PlanOrigin | ''; security_code?: string; account_id?: string }
export interface AlertFilter { status: AlertStatus[] | 'all'; origin?: AlertOrigin | ''; severity?: Severity | ''; security_code?: string; plan_id?: string }

export const pak = {
  plans: ['plans'] as const,
  planList: (f: PlanFilter) => ['plans', 'list', f] as const,
  plan: (id: string) => ['plans', 'one', id] as const,
  versions: (id: string) => ['plans', 'versions', id] as const,
  alerts: ['alerts'] as const,
  alertList: (f: AlertFilter) => ['alerts', 'list', f] as const,
  alert: (id: string) => ['alerts', 'one', id] as const,
};

export const usePlans = (f: PlanFilter) =>
  useCursorPages<PlanSummary>({
    queryKey: pak.planList(f),
    path: '/plans',
    params: { status: statusParam(f.status), origin: f.origin || undefined, security_code: f.security_code || undefined, account_id: f.account_id || undefined },
    idOf: (p) => p.id,
  });

export const usePlan = (id: string) =>
  useQuery({ queryKey: pak.plan(id), queryFn: ({ signal }) => apiGet<Plan>(`/plans/${encodeURIComponent(id)}`, undefined, signal), enabled: !!id });

export const usePlanVersions = (id: string) =>
  useCursorPages<PlanVersion>({ queryKey: pak.versions(id), path: `/plans/${encodeURIComponent(id)}/versions`, idOf: (v) => String(v.version_no), enabled: !!id });

export const useAlerts = (f: AlertFilter) =>
  useCursorPages<Alert>({
    queryKey: pak.alertList(f),
    path: '/alerts',
    params: {
      status: statusParam(f.status), origin: f.origin || undefined, severity: f.severity || undefined,
      security_code: f.security_code || undefined, plan_id: f.plan_id || undefined,
    },
    idOf: (a) => a.id,
  });

/** 读取详情不会自动改状态（§7.7B）；页面需要时显式 PATCH read */
export const useAlert = (id: string) =>
  useQuery({ queryKey: pak.alert(id), queryFn: ({ signal }) => apiGet<Alert>(`/alerts/${encodeURIComponent(id)}`, undefined, signal), enabled: !!id });

/** 创建类 POST 带 Idempotency-Key：网络重试复用同一个键；请求体变了或服务端已有明确结果就换键 */
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
      await qc.invalidateQueries({ queryKey: pak.plans });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code !== 'NETWORK_ERROR') {
        key.current = newIdempotencyKey();
        lastBody.current = null;
      }
    },
  });
}

export const useCreatePlan = () =>
  useIdemMutation<PlanCreate, Plan>((body, idempotencyKey) => apiPost<Plan>('/plans', body, { idempotencyKey }));

export const useCreatePlanVersion = (id: string) =>
  useIdemMutation<PlanVersionCreate, Plan>((body, idempotencyKey) => apiPost<Plan>(`/plans/${encodeURIComponent(id)}/versions`, body, { idempotencyKey }));

export function useClosePlan(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PlanClose) => apiPost<Plan>(`/plans/${encodeURIComponent(id)}/close`, body),
    onSettled: () => qc.invalidateQueries({ queryKey: pak.plans }),
  });
}

export function usePatchAlert(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (status: AlertPatchStatus) => apiPatch<Alert>(`/alerts/${encodeURIComponent(id)}`, { status }),
    onSuccess: (a) => qc.setQueryData(pak.alert(id), a),
    onSettled: async () => {
      await qc.invalidateQueries({ queryKey: pak.alerts });
      await qc.invalidateQueries({ queryKey: ['today'] });
    },
  });
}
