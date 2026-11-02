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
type Cooldown = { digest: string; s: Pick<DataLicenceStatus, 'status' | 'paused_until' | 'last_error_code' | 'last_error_at'> };
/** v0.2.8 #13 补充：冷却中 DELETE 时记下（摘要 + 删除前状态），到期前重提同一证书时恢复；只在内存，不出现在任何响应中 */
const cooldowns = new Map<string, Cooldown>();

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
/** 管理端操作记录（示例：只在内存里，供测试核对；真实后端写审计） */
export const adminLicenceLog: { userId: string; op: 'pause' | 'resume'; reason: string; changed: boolean }[] = [];
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
  cooldowns.clear();
  ingestPaused = false;
  settingsEnabled = true;
  adminPaused.clear();
  adminLicenceLog.length = 0;
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
  // 管理端证书列表示例：已驳回用户在管理员暂停期间删除了证书（GET 仍为 paused_by_admin，licence_id 为 null；恢复后为 not_set）
  adminPaused.add(uid(7));
  store.set(uid(9), {
    s: { ...active('free', '2026-11-20'), status: 'quota_exceeded', last_error_code: '101', last_error_at: '2026-11-02T09:41:00+08:00', paused_until: '2026-11-03T00:01:00+08:00' },
    digest: 'seed-9', pollsLeft: 0, verdict: 'active', licence_id: nextLicenceId(),
  });
}
resetLicences();

/** GET：验证中的状态在下一次读取后落定（模拟 ingest 验证） */
export function licenceOf(userId: string): DataLicenceStatus {
  const e = store.get(userId);
  // v0.2.8：暂停期间 DELETE 后，GET 仍为 paused_by_admin（证书相关字段为 null），暂停记录保留
  if (!e) return { ...NOT_SET, status: adminPaused.has(userId) ? 'paused_by_admin' : 'not_set' };
  if (e.s.status === 'pending_verification') {
    if (e.pollsLeft > 0) e.pollsLeft--;
    else if (e.verdict === 'active') e.s = { ...e.s, status: 'active', last_verified_at: NOW, last_error_code: null, last_error_at: null };
    else e.s = { ...e.s, status: 'invalid', last_error_code: '102', last_error_at: NOW };
  }
  return { ...e.s };
}
/** 只读当前状态（不推进验证），供 Me.data_licence_status 使用 */
export const licenceState = (userId: string) => store.get(userId)?.s.status ?? (adminPaused.has(userId) ? 'paused_by_admin' : 'not_set');

export type PutResult = { ok: true; s: DataLicenceStatus } | { ok: false; code: 'IN_USE' };
/** 上游冷却状态（与后端 COOLDOWN_STATUSES 一致） */
const COOLDOWN_STATUSES: readonly string[] = ['quota_exceeded', 'ip_limited'];
/** 契约 #13：quota_exceeded / ip_limited，或 paused_until 未到期 → 重复提交同一证书保留当前状态、不验证 */
const keepsState = (s: DataLicenceStatus) => COOLDOWN_STATUSES.includes(s.status) || (!!s.paused_until && Date.parse(s.paused_until) > Date.parse(NOW));
function takeCooldown(userId: string, d: string): Cooldown['s'] | null {
  const rec = cooldowns.get(userId);
  cooldowns.delete(userId); // 取出即作废：换证、到期或不匹配都不再保留
  if (!rec || rec.digest !== d) return null;
  if (rec.s.paused_until) return Date.parse(rec.s.paused_until) > Date.parse(NOW) ? rec.s : null;
  return COOLDOWN_STATUSES.includes(rec.s.status) ? rec.s : null;
}
/**
 * PUT /me/data-licence（契约 §7.1，v0.2.8 #12/#13 及补充，对齐后端 be607b3 set_licence）：
 * - 同一证书且（管理员暂停 / 冷却中）→ 原证书原状态，只更新 tier/has_quant_pro/expires_on，不验证，licence_id 不变；
 * - 冷却中删除后、到期前重提同一证书 → 恢复删除前的 status 与 paused_until，不验证；
 * - 管理员暂停期间 → 新行仍为 paused_by_admin，不验证；
 * - 其余 → pending_verification 并验证。
 */
export function putLicence(userId: string, licence: string, meta: { tier: DataLicenceTier; has_quant_pro: boolean; expires_on: string | null }): PutResult {
  const d = digest(licence);
  for (const [owner, e] of store) if (owner !== userId && e.digest === d) return { ok: false, code: 'IN_USE' };
  const old = store.get(userId);
  const held = adminPaused.has(userId) || old?.s.status === 'paused_by_admin';
  if (old && old.digest === d && (held || keepsState(old.s))) {
    old.s = { ...old.s, ...meta, days_to_expiry: daysTo(meta.expires_on), ...(held ? { status: 'paused_by_admin' as const } : {}) };
    return { ok: true, s: { ...old.s } };
  }
  const restored = old ? null : takeCooldown(userId, d);
  if (old) cooldowns.delete(userId);
  // 示例约定：以 “X-INVALID-” 开头的虚构证书验证结果为无效（102）
  const verdict = licence.startsWith('X-INVALID-') ? 'invalid' : 'active';
  const status = held ? 'paused_by_admin' : restored ? restored.status : 'pending_verification';
  const s: DataLicenceStatus = {
    ...NOT_SET, status, ...meta, days_to_expiry: daysTo(meta.expires_on), set_at: NOW,
    ...(restored ? { paused_until: restored.paused_until, last_error_code: restored.last_error_code, last_error_at: restored.last_error_at } : {}),
  };
  store.set(userId, { s, digest: d, pollsLeft: status === 'pending_verification' ? 1 : 0, verdict, licence_id: nextLicenceId() });
  return { ok: true, s: { ...s } };
}
export function patchLicence(userId: string, b: Partial<Pick<DataLicenceStatus, 'tier' | 'has_quant_pro' | 'expires_on'>>): DataLicenceStatus | null {
  const e = store.get(userId);
  if (!e) return null;
  e.s = { ...e.s, ...b };
  e.s.days_to_expiry = daysTo(e.s.expires_on);
  return { ...e.s };
}
/** DELETE：冷却中（active/quota_exceeded/ip_limited 且 keepsState）记下摘要与删除前状态，否则清除旧记录（后端 _remember_cooldown） */
export function deleteLicence(userId: string) {
  const e = store.get(userId);
  cooldowns.delete(userId);
  if (e && e.digest && ['active', ...COOLDOWN_STATUSES].includes(e.s.status) && keepsState(e.s)) {
    const { status, paused_until, last_error_code, last_error_at } = e.s;
    cooldowns.set(userId, { digest: e.digest, s: { status, paused_until, last_error_code, last_error_at } });
  }
  store.delete(userId);
}
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

/** 管理端证书列表用：某用户的证书行（未设置为 null）；只含状态元数据 */
export function licenceEntryOf(userId: string): { licence_id: string; s: DataLicenceStatus } | null {
  const e = store.get(userId);
  return e ? { licence_id: e.licence_id, s: { ...e.s } } : null;
}


/**
 * §7.9 pause（v0.2.8 + 补充⑤ 重复暂停幂等）：
 * 已暂停（不论证书是否已删除）→ ok，状态与暂停记录不变；未暂停且未设置 → not_set（409）；否则转 paused_by_admin。
 */
export function adminPause(userId: string, reason: string): 'ok' | 'not_set' {
  const e = store.get(userId);
  if (adminPaused.has(userId) || e?.s.status === 'paused_by_admin') {
    adminPaused.add(userId);
    return 'ok';
  }
  if (!e) return 'not_set';
  adminPaused.add(userId);
  e.s = { ...e.s, status: 'paused_by_admin' };
  adminLicenceLog.push({ userId, op: 'pause', reason, changed: true });
  return 'ok';
}
/**
 * §7.9 resume：解除暂停记录；证书已在暂停期间删除 → ok，状态为 not_set；
 * 证书为 paused_by_admin → pending_verification 并重新验证；既未暂停也未设置 → not_set（409）。
 * 未暂停但已设置时契约未定义，示例按后端现状返回 204 且状态不变（见报告遗留问题）。
 */
export function adminResume(userId: string, reason: string): 'ok' | 'not_set' {
  const held = adminPaused.delete(userId);
  const e = store.get(userId);
  if (!e) {
    if (!held) return 'not_set';
    adminLicenceLog.push({ userId, op: 'resume', reason, changed: true });
    return 'ok';
  }
  const changed = e.s.status === 'paused_by_admin';
  if (changed) {
    e.s = { ...e.s, status: 'pending_verification', paused_until: null };
    e.pollsLeft = 1;
  }
  adminLicenceLog.push({ userId, op: 'resume', reason, changed });
  return 'ok';
}
