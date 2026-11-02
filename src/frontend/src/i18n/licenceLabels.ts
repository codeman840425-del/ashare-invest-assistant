/** T-F22：数据证书文案（契约 v0.2.6 data_licence_status / data_licence_tier；plan 2.1B 降级表） */
import type { DataLicenceState, DataLicenceTier } from '../api/enums';
import type { DataLicenceErrorCode } from '../api/licenceTypes';

export const LICENCE_STATUS: Record<DataLicenceState, { text: string; color: string }> = {
  not_set: { text: '未设置', color: 'default' },
  pending_verification: { text: '验证中', color: 'processing' },
  active: { text: '可用', color: 'green' },
  invalid: { text: '无效', color: 'red' },
  expired: { text: '已过期', color: 'red' },
  quota_exceeded: { text: '今日额度已用完', color: 'orange' },
  ip_limited: { text: 'IP 受限，暂停中', color: 'orange' },
  paused_by_admin: { text: '管理员已暂停', color: 'orange' },
};
/** 档位为用户自报，决定默认每分钟上限（plan 2.1B） */
export const LICENCE_TIER: Record<DataLicenceTier, string> = {
  free: '免费版', trial: '体验版', monthly: '包月版', annual: '包年版', diamond: '钻石版', other: '其他',
};
export const LICENCE_ERROR: Record<DataLicenceErrorCode, string> = {
  '101': '额度已用完（次日 00:01 恢复）',
  '102': '证书无效或已失效',
  '103': '同一证书短时间内来自多个 IP，已暂停',
  '429': '请求过于频繁，已暂停',
  '503': '数据源暂时不可用',
  network: '网络错误',
  http_5xx: '数据源服务错误',
};
/** 这些状态下行情接口返回 stale / unavailable（gaps: data_licence_unavailable），全站显示横幅 */
export const LICENCE_UNAVAILABLE: readonly DataLicenceState[] = ['invalid', 'expired', 'quota_exceeded', 'ip_limited', 'paused_by_admin'];
export const LICENCE_BANNER_TEXT = '你的数据证书不可用：行情与候选信号可能停在旧数据，不会用他人的证书补齐。';
export const LICENCE_NOT_SET_TEXT = '你还没有设置数据证书：行情数据只能用你本人的麦蕊证书获取。';

/** 到期剩余天数的文案（评审 9547181 m5）：过期后显示“已过期”，不显示“剩 -N 天” */
export function expiryLeftText(days: number | null): string | null {
  if (days == null) return null;
  if (days < 0) return '已过期';
  if (days === 0) return '今天到期';
  return `剩 ${days} 天`;
}
