/**
 * 通知中心（契约 §7.8，T-F14）：GET /notifications（?unread=&kind=，§1.2 游标分页）、
 * POST /notifications/{id}/read、POST /notifications/read-all（均 204，幂等）。
 * 列表、未读数共用 ['notifications'] 前缀：标记已读后整组失效，未读数随之刷新（§7.8 “客户端随后刷新 unread-count”）。
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiPost } from './client';
import type { NotificationKind } from './enums';
import type { Notification } from './types';
import { useCursorPages } from '../lib/cursorPaging';

export interface NotificationFilter { unread: boolean; kind: NotificationKind | null }

export const nk = {
  all: ['notifications'] as const,
  pages: (f: NotificationFilter) => ['notifications', 'pages', f] as const,
};

const notificationId = (n: Notification) => n.id;
export const useNotificationPages = (f: NotificationFilter) =>
  useCursorPages<Notification>({
    queryKey: nk.pages(f),
    path: '/notifications',
    params: { unread: f.unread ? 'true' : undefined, kind: f.kind ?? undefined },
    idOf: notificationId,
  });

export function useMarkAllNotificationsRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<void>('/notifications/read-all'),
    onSuccess: () => qc.invalidateQueries({ queryKey: nk.all }),
  });
}
