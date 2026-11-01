/**
 * T-F22：数据证书的 MSW 模拟状态（契约 v0.2.6 §7.1）。
 * 证书值只用于判断“同一证书已绑定其他账号”：模块内只留一个不可逆摘要，任何响应、日志与导出都不含证书值、摘要或其片段。
 */
import type { DataLicenceTier } from '../api/enums';
import type { DataLicenceStatus } from '../api/licenceTypes';
import { NOW, uid } from './fixtures';

interface Entry { s: DataLicenceStatus; digest: string | null; pollsLeft: number; verdict: 'active' | 'invalid'; licence_id: string }

export const NOT_SET: DataLicenceStatus = {
  status: 'not_set', tier: null, has_quant_pro: null, expires_on: null, days_to_expiry: null, set_at: null,
  last_verified_at: null, last_error_code: null, last_error_at: null, paused_until: null,
};
const store = new Map<string, Entry>();

/** FNV-1a 两轮，只在内存里比对是否重复；不导出 */
function digest(v: string) {
  let a = 0x811c9dc5, b = 0x01000193;
  for (let i = 0; i < v.length; i++) {
    a = Math.imul(a ^ v.charCodeAt(i), 16777619) >>> 0;
    b = Math.imul(b ^ v.charCodeAt(v.length - 1 - i), 2246822519) >>> 0;
  }
  return `${a.toString(36)}.${b.toString(36)}.${v.length}`;
}
const today = NOW.slice(0, 10);
export function daysTo(d: string | null) {
  if (!d) return null;
  return Math.round((Date.parse(`${d}T00:00:00+08:00`) - Date.parse(`${today}T00:00:00+08:00`)) / 86400000);
}
const active = (tier: DataLicenceTier, expires_on: string | null): DataLicenceStatus => ({
  ...NOT_SET, status: 'active', tier, has_quant_pro: false, expires_on, days_to_expiry: daysTo(expires_on),
  set_at: '2026-10-08T21:10:00+08:00', last_verified_at: '2026-10-20T09:00:00+08:00',
});

/** 契约 §7.1 限速：PUT 10 次/小时，POST /test 5 次/小时（评审 T-F22a m4） */
export const LICENCE_RATE = { put: 10, test: 5 } as const;
const HOUR_MS = 3600 * 1000;
const hits = new Map<string, number[]>();
let ingestPaused = false;
let settingsEnabled = true;
/** 管理员暂停按用户记录（v0.2.8 #12）：与证书行分离，DELETE 后再 PUT 也不解除 */
const adminPaused = new Set<string>();
let licenceSeq = 0;
const nextLicenceId = () => uid(8800 + ++licenceSeq);
/** 计一次调用；超限时返回需要等待的秒数，否则 null */
export function rateHit(kind: keyof typeof LICENCE_RATE, userId: string, now = Date.now()): number | null {
  const k = `${kind}:${userId}`;
  const list = (hits.get(k) ?? []).filter((t) => now - t < HOUR_MS);
  if (list.length >= LICENCE_RATE[kind]) {
    hits.set(k, list);
    return Math.max(1, Math.ceil((list[0] + HOUR_MS - now) / 1000));
  }
  list.push(now);
  hits.set(k, list);
  return null;
}
/** 测试/演示开关：模拟管理员暂停采集（/test → 503 INGEST_PAUSED） */
export const setMockIngestPaused = (on: boolean) => void (ingestPaused = on);
export const mockIngestPaused = () => ingestPaused;
/** v0.2.8 补充裁定③：DATA_LICENCE_SETTINGS_ENABLED=false → PUT/PATCH/test 返回 503 MAINTENANCE（GET、DELETE 照常） */
export const setMockLicenceSettingsEnabled = (on: boolean) => void (settingsEnabled = on);
export const mockLicenceSettingsEnabled = () => settingsEnabled;
export const isAdminPaused = (userId: string) => adminPaused.has(userId);

export function resetLicences() {
  store.clear();
  hits.clear();
  ingestPaused = false;
  settingsEnabled = true;
  adminPaused.clear();
  licenceSeq = 0;
  // 示例：演示用户、管理员与新手用户已设置并可用；其余账号未设置
  store.set(uid(2), { s: active('diamond', '2027-03-31'), digest: 'seed-2', pollsLeft: 0, verdict: 'active', licence_id: nextLicenceId() });
  store.set(uid(3), { s: active('annual', null), digest: 'seed-3', pollsLeft: 0, verdict: 'active', licence_id: nextLicenceId() });
  store.set(uid(13), { s: active('free', '2026-11-05'), digest: 'seed-13', pollsLeft: 0, verdict: 'active', licence_id: nextLicenceId() });
  // v0.2.8 管理端采集表示例：已停用用户的证书被管理员暂停，锁定用户今日额度用完（这两个账号不能登录，不影响其他页面）
  store.set(uid(8), { s: { ...active('monthly', '2026-12-31'), status: 'paused_by_admin' }, digest: 'seed-8', pollsLeft: 0, verdict: 'active', licence_id: nextLicenceId() });
  adminPaused.add(uid(8));
  store.set(uid(14), { s: { ...active('annual', '2027-06-30'), status: 'paused_by_admin' }, digest: 'seed-14', pollsLeft: 0, verdict: 'active', licence_id: nextLicenceId() });
  adminPaused.add(uid(14));
  store.set(uid(9), {
    s: { ...active('free', '2026-11-20'), status: 'quota_exceeded', last_error_code: '101', last_error_at: '2026-11-02T09:41:00+08:00', paused_until: '2026-11-03T00:01:00+08:00' },
    digest: 'seed-9', pollsLeft: 0, verdict: 'active', licence_id: nextLicenceId(),
  });
}
resetLicences();

/** GET：验证中的状态在下一次读取后落定（模拟 ingest 验证） */
export function licenceOf(userId: string): DataLicenceStatus {
  const e = store.get(userId);
  if (!e) return { ...NOT_SET };
  if (e.s.status === 'pending_verification') {
    if (e.pollsLeft > 0) e.pollsLeft--;
    else if (e.verdict === 'active') e.s = { ...e.s, status: 'active', last_verified_at: NOW, last_error_code: null, last_error_at: null };
    else e.s = { ...e.s, status: 'invalid', last_error_code: '102', last_error_at: NOW };
  }
  return { ...e.s };
}
/** 只读当前状态（不推进验证），供 Me.data_licence_status 使用 */
export const licenceState = (userId: string) => store.get(userId)?.s.status ?? 'not_set';

export type PutResult = { ok: true; s: DataLicenceStatus } | { ok: false; code: 'IN_USE' };
export function putLicence(userId: string, licence: string, meta: { tier: DataLicenceTier; has_quant_pro: boolean; expires_on: string | null }): PutResult {
  const d = digest(licence);
  for (const [owner, e] of store) if (owner !== userId && e.digest === d) return { ok: false, code: 'IN_USE' };
  // 示例约定：以 “X-INVALID-” 开头的虚构证书验证结果为无效（102）
  const verdict = licence.startsWith('X-INVALID-') ? 'invalid' : 'active';
  // v0.2.8 #12：管理员暂停期间 PUT → 202，状态仍为 paused_by_admin，不验证
  const paused = adminPaused.has(userId);
  const s: DataLicenceStatus = {
    ...NOT_SET, status: paused ? 'paused_by_admin' : 'pending_verification', ...meta, days_to_expiry: daysTo(meta.expires_on), set_at: NOW,
  };
  store.set(userId, { s, digest: d, pollsLeft: paused ? 0 : 1, verdict, licence_id: nextLicenceId() });
  return { ok: true, s: { ...s } };
}
export function patchLicence(userId: string, b: Partial<Pick<DataLicenceStatus, 'tier' | 'has_quant_pro' | 'expires_on'>>): DataLicenceStatus | null {
  const e = store.get(userId);
  if (!e) return null;
  e.s = { ...e.s, ...b };
  e.s.days_to_expiry = daysTo(e.s.expires_on);
  return { ...e.s };
}
export const deleteLicence = (userId: string) => void store.delete(userId);
export function testLicence(userId: string): boolean {
  const e = store.get(userId);
  if (!e) return false;
  e.s = { ...e.s, status: 'pending_verification' };
  e.pollsLeft = 1;
  return true;
}
/** 测试辅助：直接设定某用户的证书状态（不涉及证书值） */
export function setMockLicence(userId: string, patch: Partial<DataLicenceStatus>) {
  const e = store.get(userId) ?? { s: active('diamond', null), digest: `seed-${userId}`, pollsLeft: 0, verdict: 'active' as const, licence_id: nextLicenceId() };
  e.s = { ...e.s, ...patch };
  store.set(userId, e);
  if (patch.status === 'paused_by_admin') adminPaused.add(userId);
  else if (patch.status) adminPaused.delete(userId);
}

/** 管理端采集表用：已设置证书的用户（not_set 不列出）；只含状态元数据，不含证书值或摘要 */
export function licenceEntries(): { userId: string; licence_id: string; s: DataLicenceStatus }[] {
  return [...store.entries()].map(([userId, e]) => ({ userId, licence_id: e.licence_id, s: { ...e.s } }));
}
