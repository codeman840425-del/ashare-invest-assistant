import type { QueryClient } from '@tanstack/react-query';
import type { NotificationRef } from '../api/types';
import { safeInternalRoute } from '../pages/today/todayRoutes';
import { ENUMS } from '../api/enums';
/** P2N-05f：只合并服务端同id版本，不在客户端计算10分钟合并窗/计数。 */
import type { Notification } from '../api/types';
export type NotificationInput = Omit<Notification, 'version' | 'merged_count' | 'updated_at' | 'refs'> & Partial<Pick<Notification, 'version' | 'merged_count' | 'updated_at' | 'refs'>>;
/** 契约明确的旧记录读取投影；不是补算新通知。 */
export function projectNotification(n: NotificationInput): Notification {
  return { ...n, version: n.version ?? 1, merged_count: n.merged_count ?? 1, updated_at: n.updated_at ?? n.created_at, refs: n.refs ?? [] };
}
/** 保留created_at排序的亚毫秒精度；此函数绝不用于通知版本比较。 */
export function compareNotificationTime(a: string, b: string): number {
  const delta = Date.parse(a) - Date.parse(b);
  if (delta !== 0) return delta;
  const tail = (s: string) => (s.match(/\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/)?.[1] ?? '').padEnd(9, '0').slice(3);
  return tail(a).localeCompare(tail(b));
}
export function latestNotifications(rows: readonly NotificationInput[]): Notification[] {
  const byId = new Map<string, Notification>();
  for (const raw of rows) {
    const n = projectNotification(raw); const old = byId.get(n.id);
    if (!old || n.version > old.version) byId.set(n.id, n);
  }
  return [...byId.values()].sort((a, b) => compareNotificationTime(b.created_at, a.created_at) || b.id.localeCompare(a.id));
}

/** SSE边界只接收契约结构；旧版本只允许省略四个新增键，不接受伪造枚举或畸形refs。 */
export function isNotificationInput(value: unknown): value is NotificationInput {
  if (!value || typeof value !== 'object') return false;
  const n = value as Record<string, unknown>;
  const text = (v: unknown): v is string => typeof v === 'string';
  const nullableText = (v: unknown) => v === null || text(v);
  const date = (v: unknown) => text(v) && Number.isFinite(Date.parse(v));
  const target = n.target && typeof n.target === 'object' ? n.target as Record<string, unknown> : null;
  return text(n.id) && text(n.title) && nullableText(n.body) && date(n.created_at) && (n.read_at === null || date(n.read_at))
    && nullableText(n.security_code) && nullableText(n.name) && ENUMS.notification_kind.some((k) => k === n.kind) && ENUMS.severity.some((k) => k === n.severity)
    && !!target && ENUMS.notification_target_type.some((k) => k === target.type) && nullableText(target.id) && nullableText(target.route)
    && (n.version === undefined || typeof n.version === 'number' && Number.isInteger(n.version) && n.version >= 1)
    && (n.updated_at === undefined || date(n.updated_at)) && (n.merged_count === undefined || typeof n.merged_count === 'number' && Number.isInteger(n.merged_count) && n.merged_count >= 1)
    && (n.refs === undefined || Array.isArray(n.refs) && n.refs.length <= 20 && n.refs.every((raw: unknown) => {
      if (!raw || typeof raw !== 'object') return false; const ref = raw as Record<string, unknown>;
      return ENUMS.notification_ref_type.some((t) => t === ref.type) && text(ref.id) && LOWER_UUID.test(ref.id) && date(ref.at)
        && nullableText(ref.route) && (ref.type !== 'signal' || ref.route === null);
    }));
}

export const LOWER_UUID = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/;
/** 只验证服务端深链，不拼路由；signal无单事件页且route=null。 */
export function notificationRefRoute(ref: NotificationRef): string | null {
  const route = safeInternalRoute(ref.route);
  return ref.type === 'plan_condition' && route?.startsWith('/plans/') && LOWER_UUID.test(route.slice('/plans/'.length)) ? route : null;
}
/** 每个QueryClient内保存通知最新version，不写浏览器持久化；退出清空查询时一并清空。 */
const remembered = new WeakMap<QueryClient, Map<string, Notification>>();
function versions(qc: QueryClient) {
  let rows = remembered.get(qc);
  if (!rows) {
    rows = new Map(); remembered.set(qc, rows);
    const state = rows; qc.getQueryCache().subscribe((event) => { if (event.type === 'removed' && !qc.getQueryCache().getAll().length) state.clear(); });
  }
  return rows;
}
export const notificationVersion = (qc: QueryClient, id: string) => versions(qc).get(id)?.version ?? 0;
export function rememberNotificationVersions(qc: QueryClient, rows: readonly NotificationInput[]): Notification[] {
  const latest = versions(qc);
  return latestNotifications(rows.map((raw) => {
    const n = projectNotification(raw); const old = latest.get(n.id);
    if (!old || n.version > old.version) latest.set(n.id, n);
    return latest.get(n.id)!;
  }));
}
