import type { Notification } from '../api/types';
import { NOTIFICATIONS, NOW } from './fixtures';

/**
 * 示例通知的会话内状态（T-F14）：已读时间 + SSE mock 推送新增的通知。
 * 已读幂等（契约 §7.8）：已读过的不改 read_at；read-all 只动未读项。
 */
const readAt = new Map<string, string>();
let pushed: Notification[] = [];

export const allNotifications = (): Notification[] =>
  [...pushed, ...NOTIFICATIONS].map((n) => ({ ...n, read_at: n.read_at ?? readAt.get(n.id) ?? null }));

export const findNotification = (id: string) => allNotifications().find((n) => n.id === id) ?? null;

export function markNotificationRead(id: string, at = NOW) {
  const n = findNotification(id);
  if (n && n.read_at === null) readAt.set(id, at);
}

export function markAllNotificationsRead(at = NOW) {
  for (const n of allNotifications()) if (n.read_at === null) readAt.set(n.id, at);
}

/** SSE mock 推送 notification 事件时同步写入列表（最新在前） */
export function addMockNotification(n: Notification) {
  pushed = [n, ...pushed.filter((x) => x.id !== n.id)];
}

export function resetNotificationStore() {
  readAt.clear();
  pushed = [];
}
