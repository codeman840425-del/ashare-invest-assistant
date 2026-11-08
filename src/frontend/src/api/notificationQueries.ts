import { latestNotifications } from '../lib/notifications';
/**
 * 通知中心（契约 §7.8，T-F14）：GET /notifications（?unread=&kind=，§1.2 游标分页）、
 * POST /notifications/{id}/read、POST /notifications/read-all（均 204，幂等）。
 * 列表、未读数共用 ['notifications'] 前缀：标记已读后整组失效，未读数随之刷新（§7.8 “客户端随后刷新 unread-count”）。
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';
import type { NotificationKind } from './enums';
import type { Notification, Paged } from './types';
import { useCursorPages } from '../lib/cursorPaging';

export interface NotificationFilter { unread: boolean; kind: NotificationKind | null }

export const nk = {
  all: ['notifications'] as const,
  catchup: ['notifications', 'catch-up'] as const,
  catchupCount: ['notifications', 'catch-up-count'] as const,
  pages: (f: NotificationFilter) => ['notifications', 'pages', f] as const,
};

/** 与列表相同的游标协议；游标不解析、不伪造，补读到末页才算完成。 */
export async function readUnreadNotifications(signal?: AbortSignal): Promise<Notification[]> {
  const rows: Notification[] = []; const seen = new Set<string>(); let cursor: string | null = null;
  do {
    const page: Paged<Notification> = await apiGet('/notifications', { unread: 'true', limit: 50, ...(cursor ? { cursor } : {}) }, signal);
    rows.push(...page.items); cursor = page.next_cursor;
    if (cursor) { if (seen.has(cursor)) throw new Error('补读游标重复，未完成补读'); seen.add(cursor); }
  } while (cursor);
  return latestNotifications(rows);
}
export const useNotificationPages = (f: NotificationFilter) => {
  const q = useCursorPages<Notification>({ queryKey: nk.pages(f), path: '/notifications', params: { unread: f.unread ? 'true' : undefined, kind: f.kind ?? undefined } });
  return { ...q, items: latestNotifications(q.data?.pages.flatMap((page) => page.items) ?? []) };
};

export function useMarkAllNotificationsRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<void>('/notifications/read-all'),
    onSuccess: () => qc.invalidateQueries({ queryKey: nk.all }),
  });
}
