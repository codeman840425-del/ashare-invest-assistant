import { latestNotifications, projectNotification, type NotificationInput } from '../lib/notifications';
import type { Notification } from '../api/types';
import { NOTIFICATIONS, NOW, uid } from './fixtures';

/**
 * 示例通知的会话内状态（T-F14）：已读时间 + SSE mock 推送新增的通知。
 * 已读幂等（契约 §7.8）：已读过的不改 read_at；read-all 只动未读项。
 */
const readAt = new Map<string, string>();
const rowVersions = new Map<string, number>();
let pushed: Notification[] = [];
/** 只属于某个用户的示例通知（如管理员暂停证书后发给证书所有者）；未登记的通知对示例用户都可见 */
const owners = new Map<string, string>();
let viewer: () => string | null = () => null;
/** 由会话模块注入当前登录用户（避免循环依赖） */
export function setNotificationViewer(fn: () => string | null) {
  viewer = fn;
}

export const allNotifications = (): Notification[] =>
  latestNotifications([...pushed, ...NOTIFICATIONS.filter(() => viewer() === uid(2))])
    .filter((n) => !owners.has(n.id) || owners.get(n.id) === viewer())
    .map((n) => ({ ...n, version: rowVersions.get(n.id) ?? n.version, read_at: n.read_at ?? readAt.get(n.id) ?? null }));

export const findNotification = (id: string) => allNotifications().find((n) => n.id === id) ?? null;

export function markNotificationRead(id: string, at = NOW) {
  const n = findNotification(id);
  if (n && n.read_at === null) { readAt.set(id, at); rowVersions.set(id, n.version + 1); }
}

export function markAllNotificationsRead(at = NOW) {
  for (const n of allNotifications()) if (n.read_at === null) { readAt.set(n.id, at); rowVersions.set(n.id, n.version + 1); }
}

/** SSE mock 推送 notification 事件时同步写入列表（最新在前） */
export function addMockNotification(input: NotificationInput, ownerId?: string) {
  const n = projectNotification(input);
  const old = [...pushed, ...NOTIFICATIONS].find((x) => x.id === n.id);
  if (old && n.version <= (rowVersions.get(n.id) ?? old.version)) return;
  // 只有确实较新的事件才能把整行重新未读；重放旧/相同版本不清除已读。
  readAt.delete(n.id); rowVersions.delete(n.id);
  pushed = [n, ...pushed.filter((x) => x.id !== n.id)];
  const owner = ownerId ?? viewer();
  if (owner) owners.set(n.id, owner);
}

export function resetNotificationStore() {
  readAt.clear(); rowVersions.clear();
  owners.clear();
  pushed = [];
}
