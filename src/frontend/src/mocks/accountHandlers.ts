/**
 * MSW 处理器（T-F02 / T-F02a / T-F04）：认证、画像、管理端用户审核、券商账户、成交、导入、对账。
 * 后端目前只实现了 /health* 与 /meta/enums（src/backend/app/api/v1），其余都在这里按契约 v0.2.8 模拟（v0.2.6 加本人数据证书；v0.2.5 起无同意流程与风险测评，§1.3 只剩登录与审核状态两道门槛）。
 */
import { http, HttpResponse } from 'msw';
import type {
  AdminUserPatch, BrokerAccountCreate, ImportConfirmRequest, ImportOptions, LoginRequest, ProfileInput, RegisterRequest,
  ImportBatchSummary, ResolveFindingRequest, Trade, TradeCreate,
} from '../api/accountTypes';
import { ADMIN_REASON_MAX, type AdminDataLicence, type AdminIngestStatus, type IngestLicenceStatus } from '../api/adminTypes';
import type { DataLicenceStatus } from '../api/licenceTypes';
import { ENUMS } from '../api/enums';
import { LICENCE_RE, type DataLicencePatch, type DataLicencePut } from '../api/licenceTypes';
import { OVERRIDE_CHOICES } from '../i18n/importLabels';
import {
  MOCK_INVITE_CODES, MOCK_REGISTER_IP_PER_HOUR, computeStats, emptyStats, finding, applyParse, currentUser, publicBatch, reconciliationFor, requestCookies, rotateCsrf, setSessionCsrf, state, toAdminUser, toMe,
  type MockBatch, type MockUser,
} from './session';
import { errorBody, page } from './handlerUtils';
import { adminPause, adminResume, deleteLicence, licenceEntries, licenceEntryOf, licenceOf, licenceState, mockIngestPaused, mockLicenceSettingsEnabled, patchLicence, putLicence, rateHit, testLicence } from './licenceStore';
import { NOW, uid } from './fixtures';
import { ingestAlerts, mockIngestHeartbeat } from './ingestAlerts';
import { addMockNotification, setNotificationViewer } from './notificationStore';

const API = '/api/v1';
const REGISTER_KEYS = new Set(['username', 'password', 'display_name', 'invite_code', 'apply_note', 'website', 'form_started_at']);
/** 契约 v0.2.8 #11：固定 3000 毫秒，不进配置 */
const HONEYPOT_MIN_FILL_MS = 3000;
const json = (body: unknown, status = 200) => HttpResponse.json(body as Record<string, unknown>, { status });
const err = (status: number, code: string, message: string, details: Record<string, unknown> | null = null) => json(errorBody(code, message, details), status);
export const validationError = (fields: { field: string; issue: string }[]) => err(400, 'VALIDATION_ERROR', '参数校验失败', { fields });
const notFound = (what: string) => err(404, 'NOT_FOUND', `${what} 不存在（示例数据）`);
const badTransition = (from: string, to: string) => err(409, 'INVALID_STATE_TRANSITION', `不能从 ${from} 变为 ${to}`, { from, to });
const noContent = (status = 204) => new HttpResponse(null, { status });
/** 契约 §2 限速：429 RATE_LIMITED + Retry-After 头 + details.retry_after_s */
const rateLimited = (s: number) =>
  HttpResponse.json(errorBody('RATE_LIMITED', '操作过于频繁（示例）', { retry_after_s: s }) as unknown as Record<string, unknown>, { status: 429, headers: { 'Retry-After': String(s) } });

/** 登录前可读的公开端点（只读） */
const PUBLIC_READ = [/^\/meta\//, /^\/health/];
/**
 * 契约 v0.2.9 #30 ④、§1.3：CSRF 登录前白名单只有 POST /auth/login、POST /auth/register（不校验 X-CSRF-Token，带了也忽略），
 * 改为 Origin 校验：带 Origin 头且不是本站源 → 403 CSRF_FAILED；不带 Origin 照常处理。
 * 其余所有写请求（含 /auth/logout、/auth/password、multipart 上传、/admin/*）没有会话 → 401 AUTH_REQUIRED，有会话按双提交校验。
 */
export const CSRF_WHITELIST: readonly string[] = ['POST /auth/login', 'POST /auth/register'];
/** 示例全局请求体上限（契约 §1.3 ①、#22：实际值为 plan 6.1 imports.max_request_bytes，这里只是示例） */
export const MOCK_MAX_REQUEST_BYTES = 25 * 1024 * 1024;
function foreignOrigin(request: Request): boolean {
  const o = request.headers.get('Origin');
  return o !== null && o !== new URL(request.url).origin;
}

/**
 * 契约 §1.3 CSRF 双提交：POST/PUT/PATCH/DELETE 须带请求头 X-CSRF-Token，且与 Cookie csrf_token、会话内令牌三者一致，否则 403 CSRF_FAILED。
 */
const WRITE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
function csrfFailed(request: Request): boolean {
  if (!WRITE_METHODS.has(request.method.toUpperCase())) return false;
  const header = request.headers.get('X-CSRF-Token');
  const cookie = requestCookies(request).csrf_token;
  return !header || !cookie || header !== cookie || cookie !== state.csrfToken;
}

const me = () => currentUser()!;
const myAccount = (id: string | null) => state.accounts.find((a) => a.id === id);
const myBatch = (id: string) => state.batches.find((b) => b.batch_id === id && !!myAccount(b.account_id));

let seq = 1000;
const nextId = () => uid(++seq);

const USERNAME_RE = /^[a-z0-9_]{4,32}$/; // 契约 #24
const RESERVED = ['admin', 'root', 'system'];

/** 示例调用量与队列：/admin/ingest/status 与 /admin/data-licences 共用，保证同一证书数值一致（契约 §9 v0.2.8 第 2 条） */
function licenceMetrics(s: DataLicenceStatus, i: number) {
  const live = s.status === 'active';
  return {
    calls_today: s.status === 'quota_exceeded' ? 200 : live ? 1180 + 37 * i : 0,
    per_minute_limit: s.tier === 'diamond' ? 300 : s.tier === 'free' ? 30 : 120,
    calls_last_minute: live ? 12 + 5 * i : 0,
    queue_depth: live ? { p0: 0, p1: 3 + i, p2: 40 + 10 * i } : { p0: 0, p1: 0, p2: 0 },
  };
}

// 示例通知按当前登录用户过滤（#26 ⑤ 的通知只发给证书所有者）
setNotificationViewer(() => state.currentUserId);

export const accountHandlers = [
  // —— 统一前置：鉴权与审核状态（契约 §1.3）。返回 undefined 时继续交给后续处理器 ——
  // —— 统一前置（契约 v0.2.9 #30 ⑤ §1.3 判定顺序）：413 → 404/405（各处理器）→ 认证 401/403 → CSRF 403 → 503 → 400 → 端点自身。
  // 前置在请求体解析之前返回，所以未登录发非法 JSON → 401，已登录缺 CSRF 发非法 JSON → 403。返回 undefined 时继续交给后续处理器 ——
  http.all(`${API}/*`, ({ request }) => {
    const path = new URL(request.url).pathname.slice(API.length);
    const method = request.method.toUpperCase();
    const len = Number(request.headers.get('Content-Length') ?? 0);
    if (Number.isFinite(len) && len > MOCK_MAX_REQUEST_BYTES) return err(413, 'PAYLOAD_TOO_LARGE', '请求体超过上限', { max_bytes: MOCK_MAX_REQUEST_BYTES });
    const user = currentUser();
    if (path.startsWith('/admin')) {
      // §1.3 / §7.9：不是已登录的 admin 一律 404，与不存在的路径无法区分（含缺 CSRF 的请求）
      if (!user || user.role !== 'admin' || user.status !== 'approved') return err(404, 'NOT_FOUND', `示例数据未覆盖该端点：${new URL(request.url).pathname}`);
      return csrfFailed(request) ? err(403, 'CSRF_FAILED', 'CSRF 令牌缺失或不符') : undefined;
    }
    if (CSRF_WHITELIST.includes(`${method} ${path}`)) {
      // ⑤ 注册关闭的 503 先于 Origin 校验（#16）
      if (path === '/auth/register' && state.registrationMode === 'closed') return undefined;
      return foreignOrigin(request) ? err(403, 'CSRF_FAILED', '请求来源不是本站') : undefined;
    }
    if (!WRITE_METHODS.has(method) && PUBLIC_READ.some((re) => re.test(path))) return undefined;
    if (!user) return err(401, 'AUTH_REQUIRED', '请先登录');
    if (user.status !== 'approved') return err(403, 'ACCOUNT_NOT_APPROVED', '账号未通过审核', { status: user.status });
    if (csrfFailed(request)) return err(403, 'CSRF_FAILED', 'CSRF 令牌缺失或不符');
    return undefined;
  }),

  // ---------------- §7.1 认证 ----------------
  // v0.2.8 #11：前端用响应头 Date 校正 form_started_at 的时钟
  http.get(`${API}/meta/registration`, () => HttpResponse.json({ mode: state.registrationMode }, { headers: { Date: new Date().toUTCString() } })),
  http.post(`${API}/auth/login`, async ({ request }) => {
    const body = (await request.json()) as Partial<LoginRequest>;
    const user = state.users.find((x) => x.username === body.username);
    if (!user || !body.password || body.password.length < 10) return err(401, 'INVALID_CREDENTIALS', '用户名或密码错误');
    if (user.locked) return err(403, 'ACCOUNT_LOCKED', '连续登录失败，账号已临时锁定', { retry_after_s: 900 });
    if (user.status !== 'approved') {
      return err(403, 'ACCOUNT_NOT_APPROVED', '账号未通过审核', { status: user.status, ...(user.review_reason ? { reason: user.review_reason } : {}) });
    }
    // §1.3：登录轮换会话与 CSRF 令牌；响应体与 Cookie 给出同一个值
    state.currentUserId = user.id;
    const token = rotateCsrf();
    setSessionCsrf(token);
    return HttpResponse.json({ user: toMe(user), csrf_token: token }, { headers: { 'Set-Cookie': `csrf_token=${token}; Path=/; SameSite=Lax` } });
  }),
  http.post(`${API}/auth/logout`, () => {
    state.currentUserId = null;
    setSessionCsrf(null);
    return noContent();
  }),
  // 契约 §7.1：改密 → 204 + 轮换 csrf_token（示例不存口令：旧口令不足 10 位按“旧密码错误”处理）
  http.post(`${API}/auth/password`, async ({ request }) => {
    const raw = (await request.json().catch(() => null)) as { old_password?: unknown; new_password?: unknown } | null;
    if (!raw || typeof raw.old_password !== 'string' || typeof raw.new_password !== 'string') return err(400, 'VALIDATION_ERROR', '请求体格式不正确', { fields: [{ field: 'body', issue: 'invalid' }] });
    if (raw.old_password.length < 10) return err(400, 'VALIDATION_ERROR', '旧密码错误', { field: 'old_password', fields: [{ field: 'old_password', issue: 'invalid' }] });
    const pwd = raw.new_password;
    if (pwd.length < 10 || pwd.length > 128 || !/[a-zA-Z]/.test(pwd) || !/\d/.test(pwd)) return err(400, 'VALIDATION_ERROR', '新密码至少 10 位，且包含字母和数字', { field: 'new_password', fields: [{ field: 'new_password', issue: 'invalid' }] });
    const token = rotateCsrf();
    setSessionCsrf(token);
    return new HttpResponse(null, { status: 204, headers: { 'Set-Cookie': `csrf_token=${token}; Path=/; SameSite=Lax` } });
  }),
  http.post(`${API}/auth/register`, async ({ request }) => {
    // §7.1 判定顺序：注册模式 → IP 限速（每次尝试都计，含校验失败与蜜罐命中）→ 字段与邀请码 400 → 409 → 待审核数上限 503 → 蜜罐
    if (state.registrationMode === 'closed') return err(503, 'REGISTRATION_CLOSED', '暂未开放注册');
    const now = Date.now();
    state.registerHits = state.registerHits.filter((t) => now - t < 3_600_000);
    if (state.registerHits.length >= MOCK_REGISTER_IP_PER_HOUR) return rateLimited(Math.max(1, Math.ceil((state.registerHits[0] + 3_600_000 - now) / 1000)));
    state.registerHits.push(now);
    const raw = (await request.json()) as Record<string, unknown>;
    const b = raw as Partial<RegisterRequest>;
    const fields: { field: string; issue: string }[] = [];
    // §7.1 extra=forbid：未知字段 400；agreements（v0.2.5 旧客户端）忽略；website、form_started_at 是正式字段（v0.2.8 #11）
    for (const k of Object.keys(raw)) if (!REGISTER_KEYS.has(k) && k !== 'agreements') fields.push({ field: k, issue: 'extra_forbidden' });
    const fsa = raw.form_started_at;
    // 契约 §7.1：website 类型为 string | null，不校验内容与长度；类型不对按 400（与后端 RegisterIn.website: str | None 一致）
    if (raw.website !== undefined && raw.website !== null && typeof raw.website !== 'string') fields.push({ field: 'website', issue: 'invalid' });
    if (fsa !== undefined && fsa !== null && !Number.isInteger(fsa)) fields.push({ field: 'form_started_at', issue: 'invalid' });
    const name = b.username ?? '';
    if (!USERNAME_RE.test(name)) fields.push({ field: 'username', issue: '4–32 位小写字母、数字或下划线' });
    else if (RESERVED.some((r) => name.includes(r))) fields.push({ field: 'username', issue: '包含保留字' });
    const pwd = b.password ?? '';
    if (pwd.length < 10 || !/[a-zA-Z]/.test(pwd) || !/\d/.test(pwd)) fields.push({ field: 'password', issue: '至少 10 位，且包含字母和数字' });
    else if (pwd === name) fields.push({ field: 'password', issue: '不能与用户名相同' });
    if (!b.display_name?.trim()) fields.push({ field: 'display_name', issue: '必填' });
    if (pwd.length > 128) fields.push({ field: 'password', issue: 'too_long' });
    if (state.registrationMode === 'invite') {
      if (!b.invite_code?.trim()) fields.push({ field: 'invite_code', issue: 'required' });
      else if (!MOCK_INVITE_CODES.includes(b.invite_code.trim())) fields.push({ field: 'invite_code', issue: 'invalid' });
      if (!b.apply_note?.trim()) fields.push({ field: 'apply_note', issue: 'required' });
    }
    if ((b.apply_note ?? '').length > 200) fields.push({ field: 'apply_note', issue: 'too_long' });
    if ((b.display_name ?? '').trim().length > 32) fields.push({ field: 'display_name', issue: 'too_long' });
    // v0.2.5 #1：旧客户端仍发 agreements 时服务端忽略（不报错、不记录）
    if (fields.length) return validationError(fields);
    if (state.users.some((x) => x.username === name)) return err(409, 'CONFLICT', '用户名已被使用');
    if (state.users.filter((x) => x.status === 'pending').length >= state.pendingCap) return err(503, 'REGISTRATION_CLOSED', '暂未开放注册');
    // v0.2.8 #11 蜜罐：website 去空白后非空，或填写不足 3000 毫秒（含未来时间）→ 返回与正常注册相同的 201，但不建用户、不消耗邀请码
    const hpWebsite = typeof raw.website === 'string' && raw.website.trim() !== '';
    const hpFast = typeof fsa === 'number' && Date.now() - fsa < HONEYPOT_MIN_FILL_MS;
    if (hpWebsite || hpFast) {
      state.honeypotHits.push(hpWebsite && hpFast ? 'both' : hpWebsite ? 'website' : 'too_fast');
      return json({ id: crypto.randomUUID(), username: name, status: 'pending' }, 201);
    }
    const id = nextId();
    state.users.push({
      id, username: name, display_name: b.display_name!.trim(), role: 'user', status: 'pending', apply_note: b.apply_note?.trim() || null, created_at: NOW, reviewed_at: null,
      review_reason: null, register_ip_region: '上海（示例）', same_ip_registrations: 1,
    });
    return json({ id, username: name, status: 'pending' }, 201);
  }),
  http.get(`${API}/me`, () => json(toMe(me()))),
  http.get(`${API}/me/profile`, () => {
    const p = state.profiles.get(me().id);
    return p ? json(p) : notFound('投资画像');
  }),
  http.put(`${API}/me/profile`, async ({ request }) => {
    const b = (await request.json()) as Partial<ProfileInput>;
    const fields: { field: string; issue: string }[] = [];
    if (!b.horizon_pref?.length || !b.horizon_pref.every((h) => (ENUMS.horizon as readonly string[]).includes(h))) fields.push({ field: 'horizon_pref', issue: '至少选择一个周期' });
    // v0.2.5 #6：三个自报字段可为 null（未填写）；无 exceeds_assessment 校验
    if (b.effort != null && !['low', 'medium', 'high'].includes(b.effort)) fields.push({ field: 'effort', issue: '取值不合法' });
    if (b.risk_tolerance != null && (!Number.isInteger(b.risk_tolerance) || b.risk_tolerance < 1 || b.risk_tolerance > 5)) fields.push({ field: 'risk_tolerance', issue: '1–5' });
    if (b.experience != null && !['novice', 'intermediate', 'advanced'].includes(b.experience)) fields.push({ field: 'experience', issue: '取值不合法' });
    const pct = Number(b.max_single_position_pct);
    if (!(pct >= 5 && pct <= 50)) fields.push({ field: 'max_single_position_pct', issue: '5–50' });
    if (fields.length) return validationError(fields);
    const prev = state.profiles.get(me().id);
    const p = { ...(b as ProfileInput), effort: b.effort ?? null, risk_tolerance: b.risk_tolerance ?? null, experience: b.experience ?? null, version_no: (prev?.version_no ?? 0) + 1 };
    state.profiles.set(me().id, p);
    return json(p);
  }),

  // ---------------- §7.1 数据证书（v0.2.6，T-F22）：任何响应都不含证书值 ----------------
  http.get(`${API}/me/data-licence`, () => json(licenceOf(me().id))),
  // 顺序（契约 §7.1 v0.2.8 补充，与后端一致）：请求体格式 400 → 设置开关 503 → 限速 429 → 409 等
  http.put(`${API}/me/data-licence`, async ({ request }) => {
    const b = (await request.json()) as Partial<DataLicencePut>;
    const licence = typeof b.licence === 'string' ? b.licence.trim() : '';
    const fields: { field: string; issue: string }[] = [];
    // 消息不含输入值（契约 §7.1）
    if (!LICENCE_RE.test(licence)) fields.push({ field: 'licence', issue: '格式不符：应为 16–64 位字母、数字或连字符' });
    if (!b.tier || !(ENUMS.data_licence_tier as readonly string[]).includes(b.tier)) fields.push({ field: 'tier', issue: '取值不合法' });
    if (typeof b.has_quant_pro !== 'boolean') fields.push({ field: 'has_quant_pro', issue: '必须为布尔值' });
    if (b.expires_on != null && !/^\d{4}-\d{2}-\d{2}$/.test(b.expires_on)) fields.push({ field: 'expires_on', issue: '日期格式 YYYY-MM-DD' });
    if (fields.length) return validationError(fields);
    if (!mockLicenceSettingsEnabled()) return err(503, 'MAINTENANCE', '设置暂未开放（示例）');
    const wait = rateHit('put', me().id);
    if (wait) return rateLimited(wait);
    const r = putLicence(me().id, licence, { tier: b.tier!, has_quant_pro: b.has_quant_pro!, expires_on: b.expires_on ?? null });
    if (!r.ok) return err(409, 'DATA_LICENCE_IN_USE', '该证书已绑定到另一个账号');
    return json(r.s, 202);
  }),
  http.patch(`${API}/me/data-licence`, async ({ request }) => {
    const b = (await request.json()) as DataLicencePatch & { licence?: unknown };
    const fields: { field: string; issue: string }[] = [];
    if ('licence' in b) fields.push({ field: 'licence', issue: 'PATCH 不能修改证书，请用 PUT' });
    if (b.tier !== undefined && !(ENUMS.data_licence_tier as readonly string[]).includes(b.tier)) fields.push({ field: 'tier', issue: '取值不合法' });
    if (b.has_quant_pro !== undefined && typeof b.has_quant_pro !== 'boolean') fields.push({ field: 'has_quant_pro', issue: '必须为布尔值' });
    if (b.expires_on != null && !/^\d{4}-\d{2}-\d{2}$/.test(b.expires_on)) fields.push({ field: 'expires_on', issue: '日期格式 YYYY-MM-DD' });
    if (fields.length) return validationError(fields);
    if (!mockLicenceSettingsEnabled()) return err(503, 'MAINTENANCE', '设置暂未开放（示例）');
    const patch: DataLicencePatch = {};
    if (b.tier !== undefined) patch.tier = b.tier;
    if (b.has_quant_pro !== undefined) patch.has_quant_pro = b.has_quant_pro;
    if (b.expires_on !== undefined) patch.expires_on = b.expires_on;
    const s = patchLicence(me().id, patch);
    return s ? json(s) : err(409, 'DATA_LICENCE_NOT_SET', '尚未设置数据证书');
  }),
  http.delete(`${API}/me/data-licence`, () => {
    deleteLicence(me().id);
    return noContent();
  }),
  http.post(`${API}/me/data-licence/test`, () => {
    if (!mockLicenceSettingsEnabled()) return err(503, 'MAINTENANCE', '设置暂未开放（示例）');
    // 顺序与后端 test_licence 一致（评审 9547181 m4）：暂停 409 → 未设置 409 → 限速 429 → 采集暂停 503
    // v0.2.8 #14：管理员暂停期间测试 → 409 DATA_LICENCE_UNAVAILABLE{status:"paused_by_admin"}
    if (licenceState(me().id) === 'paused_by_admin') return err(409, 'DATA_LICENCE_UNAVAILABLE', '管理员已暂停该证书，暂不能测试', { status: 'paused_by_admin' });
    if (licenceState(me().id) === 'not_set') return err(409, 'DATA_LICENCE_NOT_SET', '尚未设置数据证书');
    const wait = rateHit('test', me().id);
    if (wait) return rateLimited(wait);
    if (mockIngestPaused()) return err(503, 'INGEST_PAUSED', '采集服务已暂停（示例）');
    testLicence(me().id);
    return json({ verification_id: uid(4100 + Math.floor(Math.random() * 1000)) }, 202);
  }),

  // ---------------- §7.9 管理端：用户审核 ----------------
  // v0.2.8 #1：/admin/ingest/status 按证书一行（示例数值；不含证书值、密文、HMAC 或其片段）
  http.get(`${API}/admin/ingest/status`, () => {
    const order = ['invalid', 'ip_limited', 'quota_exceeded', 'expired', 'paused_by_admin', 'pending_verification', 'active'];
    const rows: IngestLicenceStatus[] = licenceEntries()
      .filter((e) => e.s.status !== 'not_set')
      .map((e, i) => {
        const u = state.users.find((x) => x.id === e.userId);
        return {
          licence_id: e.licence_id, user_id: e.userId, username: u?.username ?? '—', display_name: u?.display_name ?? '—',
          status: e.s.status, tier: e.s.tier, has_quant_pro: e.s.has_quant_pro, expires_on: e.s.expires_on, days_left: e.s.days_to_expiry,
          ...licenceMetrics(e.s, i),
          daily_limit: e.s.status === 'quota_exceeded' ? 200 : null,
          paused_until: e.s.paused_until, last_error_code: e.s.last_error_code, last_error_at: e.s.last_error_at,
        };
      })
      .sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status)
        || (a.days_left ?? Infinity) - (b.days_left ?? Infinity)
        || a.username.localeCompare(b.username));
    // v0.2.9 内 T-B47 裁定：freshness 固定 6 行（顺序固定，data_status 只取 fresh/stale/pending/unavailable）；alerts 永不为 null
    const base: Omit<AdminIngestStatus, 'alerts'> = {
      leader: { instance_id: 'ingest-示例-1', egress_ip_masked: '203.0.113.x', lease_expires_at: '2026-11-02T10:00:30+08:00' },
      budget: { per_minute_limit: rows.reduce((t, r) => t + r.per_minute_limit, 0), used_last_minute: rows.reduce((t, r) => t + r.calls_last_minute, 0) },
      queues: [
        { priority: 'p0_intraday', depth: 0, oldest_age_s: 0 },
        { priority: 'p1_daily', depth: rows.reduce((t, r) => t + r.queue_depth.p1, 0), oldest_age_s: 42 },
        { priority: 'p2_backfill', depth: rows.reduce((t, r) => t + r.queue_depth.p2, 0), oldest_age_s: 1260 },
      ],
      errors_24h: [{ upstream_code: '101', count: 1 }, { upstream_code: 'http_5xx', count: 3 }],
      ip_limit_alerts_24h: 1,
      freshness: [
        { dataset: 'quotes', data_as_of: '2026-11-02T09:59:57+08:00', data_status: 'fresh' },
        { dataset: 'minute_bars', data_as_of: '2026-11-02T09:59:00+08:00', data_status: 'fresh' },
        { dataset: 'daily_bars', data_as_of: '2026-10-30', data_status: 'fresh' },
        { dataset: 'financials', data_as_of: '2026-06-30', data_status: 'stale' },
        { dataset: 'announcements', data_as_of: '2026-10-30', data_status: 'fresh' },
        { dataset: 'security_master', data_as_of: '2026-10-30', data_status: 'fresh' },
      ],
      licences: rows.slice(0, 500),
      licences_truncated: rows.length > 500,
      heartbeat: mockIngestHeartbeat(),
    };
    const body: AdminIngestStatus = { ...base, alerts: ingestAlerts(base) };
    return json(body);
  }),
  // §7.9 管理端证书列表（v0.2.6，分页；v0.2.8 加 licence_id）：每位用户一行，含未设置证书的用户；按注册时间倒序（示例）
  http.get(`${API}/admin/data-licences`, ({ request }) => {
    const idx = new Map(licenceEntries().map((e, i) => [e.licence_id, i]));
    const items: AdminDataLicence[] = state.users
      .slice()
      .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id))
      .map((u) => {
        const e = licenceEntryOf(u.id);
        const s: DataLicenceStatus = e ? e.s : licenceOf(u.id);
        return {
          ...s, licence_id: e?.licence_id ?? null, user_id: u.id, username: u.username, display_name: u.display_name,
          ...(e ? licenceMetrics(s, idx.get(e.licence_id) ?? 0) : { calls_today: 0, per_minute_limit: 0, calls_last_minute: 0, queue_depth: { p0: 0, p1: 0, p2: 0 } }),
        };
      });
    return json(page(items, new URL(request.url)));
  }),
  http.post(`${API}/admin/data-licences/:id/:op`, async ({ params, request }) => {
    const op = params.op;
    if (op !== 'pause' && op !== 'resume') return err(404, 'NOT_FOUND', '示例数据未覆盖该端点');
    const id = String(params.id);
    if (!state.users.some((x) => x.id === id)) return notFound('用户');
    const b = (await request.json().catch(() => ({}))) as { reason?: unknown };
    // 评审 d26e1d3 m3：先去掉首尾空白再按 1–200 校验（纯空格视为未填）
    const reason = typeof b.reason === 'string' ? b.reason.trim() : '';
    if (reason.length < 1 || reason.length > ADMIN_REASON_MAX) return validationError([{ field: 'reason', issue: reason.length ? 'too_long' : 'required' }]);
    const before = licenceState(id);
    const r = op === 'pause' ? adminPause(id, reason) : adminResume(id, reason);
    // 契约 v0.2.9 #26 ⑤：暂停、恢复成功且状态确实变化时给证书所有者发通知（kind=data_licence、target none、正文不含管理员填写的理由）；幂等重复调用不发
    if (r === 'ok' && licenceState(id) !== before) {
      const paused = op === 'pause';
      addMockNotification({
        id: nextId(), kind: 'data_licence', severity: paused ? 'important' : 'info',
        title: paused ? '数据证书已被管理员暂停' : '数据证书已被管理员恢复',
        body: paused ? '暂停期间不会用你的证书取数，已有缓存照常展示（示例文案）' : '证书将重新验证，验证通过后继续取数（示例文案）',
        created_at: new Date().toISOString(), read_at: null, security_code: null, name: null,
        target: { type: 'none', id: null, route: null },
      }, id);
    }
    return r === 'ok' ? noContent() : err(409, 'DATA_LICENCE_NOT_SET', '该用户尚未设置数据证书');
  }),
  http.get(`${API}/admin/users`, ({ request }) => {
    const url = new URL(request.url);
    const status = url.searchParams.get('status');
    const q = url.searchParams.get('q')?.toLowerCase();
    const items = state.users
      .filter((x) => (!status || x.status === status) && (!q || x.username.includes(q) || x.display_name.toLowerCase().includes(q)))
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .map(toAdminUser);
    return json(page(items, url));
  }),
  http.get(`${API}/admin/users/:id`, ({ params }) => {
    const x = state.users.find((y) => y.id === params.id);
    return x ? json(toAdminUser(x)) : notFound('用户');
  }),
  http.patch(`${API}/admin/users/:id`, async ({ params, request }) => {
    const x = state.users.find((y) => y.id === params.id);
    if (!x) return notFound('用户');
    const b = (await request.json()) as Partial<AdminUserPatch>;
    if (!b.status || !['approved', 'rejected', 'disabled'].includes(b.status)) return validationError([{ field: 'status', issue: '取值不合法' }]);
    if ((b.status === 'rejected' || b.status === 'disabled' || x.status === 'disabled') && !b.reason?.trim()) return validationError([{ field: 'reason', issue: 'required' }]);
    if (x.id === state.currentUserId) return badTransition(x.status, b.status);
    const allowed: Record<MockUser['status'], string[]> = { pending: ['approved', 'rejected'], approved: ['disabled'], rejected: ['approved'], disabled: ['approved'] };
    if (!allowed[x.status].includes(b.status)) return badTransition(x.status, b.status);
    x.status = b.status;
    x.review_reason = b.reason?.trim() || null;
    x.reviewed_at = NOW;
    return json(toAdminUser(x));
  }),

  // ---------------- §7.2 券商账户 ----------------
  http.get(`${API}/accounts`, ({ request }) => json(page(state.accounts, new URL(request.url)))),
  http.post(`${API}/accounts`, async ({ request }) => {
    const b = (await request.json()) as Partial<BrokerAccountCreate>;
    const fields = [
      ...(!b.alias?.trim() ? [{ field: 'alias', issue: '必填' }] : []),
      ...(!b.broker_name?.trim() ? [{ field: 'broker_name', issue: '必填' }] : []),
    ];
    if (fields.length) return validationError(fields);
    const a = { id: nextId(), alias: b.alias!.trim(), broker_name: b.broker_name!.trim(), shareholder_code_masked: null, fund_account_masked: null, created_at: NOW };
    state.accounts.push(a);
    return json(a, 201);
  }),

  // ---------------- 成交 ----------------
  http.get(`${API}/trades`, ({ request }) => {
    const url = new URL(request.url);
    const acc = url.searchParams.get('account_id');
    const items = state.trades.filter((t) => !acc || t.account_id === acc).sort((a, b) => b.trade_date.localeCompare(a.trade_date) || b.created_at.localeCompare(a.created_at));
    return json(page(items, url));
  }),
  http.get(`${API}/trades/:id`, ({ params }) => {
    const t = state.trades.find((x) => x.id === params.id);
    return t ? json(t) : notFound('成交');
  }),
  http.post(`${API}/trades`, async ({ request }) => {
    // v0.2.4 #12：支持 Idempotency-Key（同一键重放返回第一次的结果）
    const key = request.headers.get('Idempotency-Key');
    if (key && state.tradeIdem.has(key)) return json(state.tradeIdem.get(key), 201);
    const b = (await request.json()) as Partial<TradeCreate>;
    const fields: { field: string; issue: string }[] = [];
    const orig = b.corrects_trade_id ? state.trades.find((x) => x.id === b.corrects_trade_id && !!myAccount(x.account_id)) : undefined;
    if (b.corrects_trade_id && !orig) fields.push({ field: 'corrects_trade_id', issue: 'not_found' });
    if (b.corrects_trade_id && !b.reason?.trim()) fields.push({ field: 'reason', issue: 'required' });
    if (!myAccount(b.account_id ?? null)) fields.push({ field: 'account_id', issue: '账户不存在' });
    if (!b.trade_date || !/^\d{4}-\d{2}-\d{2}$/.test(b.trade_date)) fields.push({ field: 'trade_date', issue: '日期格式 YYYY-MM-DD' });
    if (!b.security_code || !/^\d{6}\.(SH|SZ|BJ)$/.test(b.security_code)) fields.push({ field: 'security_code', issue: '格式如 600000.SH' });
    if (!b.side || !['buy', 'sell'].includes(b.side)) fields.push({ field: 'side', issue: '取值不合法' });
    if (!(Number(b.qty) > 0)) fields.push({ field: 'qty', issue: '必须大于 0' });
    if (!(Number(b.price) > 0)) fields.push({ field: 'price', issue: '必须大于 0' });
    if (fields.length) return validationError(fields);
    const t: Trade = {
      id: nextId(), account_id: b.account_id!, trade_date: b.trade_date!, trade_time: b.trade_time ?? null, security_code: b.security_code!, name: '（手动录入）',
      side: b.side!, qty: String(b.qty), price: Number(b.price).toFixed(2), amount: (Number(b.qty) * Number(b.price)).toFixed(2), fee_total: b.fee_total ?? null,
      net_amount: null, source: 'manual', batch_id: null, voided: false, void_reason: null, voided_at: null, corrects_trade_id: b.corrects_trade_id ?? null, created_at: NOW,
    };
    if (orig) Object.assign(orig, { voided: true, void_reason: b.reason!.trim(), voided_at: NOW });
    state.trades.push(t);
    if (key) state.tradeIdem.set(key, t);
    return json(t, 201);
  }),
  http.post(`${API}/trades/:id/void`, async ({ params, request }) => {
    const t = state.trades.find((x) => x.id === params.id && !!myAccount(x.account_id));
    if (!t) return notFound('成交');
    const b = (await request.json()) as { reason?: string };
    const reason = b.reason?.trim() ?? '';
    if (!reason || reason.length > 200) return validationError([{ field: 'reason', issue: reason ? 'too_long' : 'required' }]);
    if (t.voided) return badTransition('voided', 'voided');
    Object.assign(t, { voided: true, void_reason: reason, voided_at: NOW });
    return json(t);
  }),

  // ---------------- 导入 ----------------
  http.post(`${API}/imports`, async ({ request }) => {
    const form = await request.formData();
    const file = form.get('file');
    const accountId = String(form.get('account_id') ?? '');
    const kind = String(form.get('kind') ?? '');
    const asOf = form.get('snapshot_as_of');
    const fields = [
      ...(!(file instanceof Blob) ? [{ field: 'file', issue: '必填' }] : []),
      ...(!myAccount(accountId) ? [{ field: 'account_id', issue: '账户不存在' }] : []),
      ...(!['trades', 'positions'].includes(kind) ? [{ field: 'kind', issue: '取值为 trades|positions' }] : []),
    ];
    if (fields.length) return validationError(fields);
    const f = file as File;
    const filename = f.name || 'upload.txt';
    const fileErrors = [];
    if (!/\.(txt|csv)$/i.test(filename)) fileErrors.push(finding('IMPORT_UNSUPPORTED_FILE_TYPE'));
    else if (f.size === 0) fileErrors.push(finding('IMPORT_EMPTY_FILE'));
    else if (f.size > 5 * 1024 * 1024) fileErrors.push(finding('IMPORT_FILE_TOO_LARGE', { params: { limit_mb: 5 } }));
    if (fileErrors.length) return err(422, 'IMPORT_FILE_ERRORS', '文件无法导入', { findings: fileErrors });
    const dup = state.batches.find((b) => b.account_id === accountId && b.filename === filename && b.status === 'committed');
    const b: MockBatch = {
      batch_id: nextId(), account_id: accountId, kind: kind as MockBatch['kind'], status: 'parsing', parser_id: null, parser_version: null,
      detected_encoding: null, encoding_override: null, encoding_confidence: null, format_score: null, detected_columns: [], mapping: null,
      snapshot_as_of: typeof asOf === 'string' && asOf ? asOf : null,
      file_findings: dup ? [finding('IMPORT_DUPLICATE_FILE', { params: { imported_at: dup.committed_at?.slice(0, 16).replace('T', ' '), batch_id: dup.batch_id } })] : [],
      stats: emptyStats(), created_at: NOW, committed_at: null, reverted_at: null,
      filename, rows_data: [], parse_polls_left: 1, parse_target: 'previewed', idem: new Map(),
    };
    state.batches.unshift(b);
    return json({ batch_id: b.batch_id, status: 'uploaded', file_findings: b.file_findings }, 201);
  }),
  http.get(`${API}/imports`, ({ request }) => {
    const url = new URL(request.url);
    const acc = url.searchParams.get('account_id');
    const st = url.searchParams.get('status');
    const items = state.batches.filter((b) => myAccount(b.account_id) && (!acc || b.account_id === acc) && (!st || b.status === st))
      .map(({ batch_id, account_id, kind, status, parser_id, stats, created_at, committed_at, reverted_at }): ImportBatchSummary => ({ batch_id, account_id, kind, status, parser_id, stats, created_at, committed_at, reverted_at }));
    return json(page(items, url));
  }),
  http.get(`${API}/imports/:id`, ({ params }) => {
    const b = myBatch(String(params.id));
    if (!b) return notFound('导入批次');
    if (b.status === 'parsing') {
      if (b.parse_polls_left > 0) b.parse_polls_left -= 1;
      else {
        applyParse(b);
        b.status = b.parse_target;
      }
    }
    return json(publicBatch(b));
  }),
  http.get(`${API}/imports/:id/rows`, ({ params, request }) => {
    const b = myBatch(String(params.id));
    if (!b) return notFound('导入批次');
    const url = new URL(request.url);
    const st = url.searchParams.get('status');
    const code = url.searchParams.get('code');
    const dd = url.searchParams.get('dedup_status');
    // #35：discarded / failed → 200、items: []、next_cursor: null（不新增 410）
    if (b.status === 'discarded' || b.status === 'failed') return json({ items: [], next_cursor: null });
    const items = b.rows_data.filter((r) => (!st || r.status === st) && (!code || r.findings.some((f) => f.code === code)) && (!dd || r.dedup_status === dd));
    return json(page(items, url));
  }),
  http.put(`${API}/imports/:id/options`, async ({ params, request }) => {
    const b = myBatch(String(params.id));
    if (!b) return notFound('导入批次');
    if (b.status !== 'previewed' && b.status !== 'failed') return badTransition(b.status, 'parsing');
    const o = (await request.json()) as Partial<ImportOptions>;
    // T-B66：后端拒绝与批次 kind 不同的解析器
    if (o.parser_id && !o.parser_id.startsWith(`tdx_${b.kind}`)) return err(400, 'VALIDATION_ERROR', '解析器与文件类型不一致', { fields: [{ field: 'parser_id', issue: 'kind_mismatch' }] });
    b.encoding_override = o.encoding_override ?? null;
    b.parser_id = o.parser_id ?? b.parser_id;
    b.mapping = o.mapping ?? b.mapping;
    b.snapshot_as_of = o.snapshot_as_of ?? b.snapshot_as_of;
    b.status = 'parsing';
    b.parse_polls_left = 1;
    return json({ status: 'parsing' }, 202);
  }),
  http.post(`${API}/imports/:id/findings/:fid/resolve`, async ({ params, request }) => {
    const b = myBatch(String(params.id));
    if (!b) return notFound('导入批次');
    // #35：discarded 批次的行级提示已随预览行删除，resolve 一律 409 INVALID_STATE_TRANSITION
    if (b.status === 'discarded') return badTransition(b.status, 'previewed');
    const all = [...b.file_findings, ...b.rows_data.flatMap((r) => r.findings)];
    const f = all.find((x) => x.id === params.fid);
    if (!f) return notFound('提示');
    if (b.status !== 'previewed') return badTransition(b.status, 'previewed');
    const body = (await request.json()) as Partial<ResolveFindingRequest>;
    if (!body.choice || !f.resolution_choices.includes(body.choice)) return validationError([{ field: 'choice', issue: '须在 resolution_choices 中' }]);
    if (OVERRIDE_CHOICES.has(body.choice) && !body.reason?.trim()) return validationError([{ field: 'reason', issue: '覆盖类处理必须填写理由' }]);
    if ((body.reason ?? '').length > 200) return validationError([{ field: 'reason', issue: 'too_long' }]);
    f.resolution = { choice: body.choice, reason: body.reason?.trim() || null, by: me().id, at: NOW };
    return json(f);
  }),
  http.post(`${API}/imports/:id/confirm`, async ({ params, request }) => {
    const b = myBatch(String(params.id));
    if (!b) return notFound('导入批次');
    const key = request.headers.get('Idempotency-Key');
    if (key && b.idem.has(key)) return json(b.idem.get(key));
    if (b.status !== 'previewed') return badTransition(b.status, 'committed');
    const body = (await request.json()) as Partial<ImportConfirmRequest>;
    const fileErrors = b.file_findings.filter((f) => f.severity === 'error');
    if (fileErrors.length) return err(422, 'IMPORT_FILE_ERRORS', '文件级错误未解决', { findings: fileErrors });
    const errorRows = b.rows_data.filter((r) => r.status === 'error').length;
    if (body.mode === 'all' && errorRows) return err(422, 'IMPORT_ROW_ERRORS', `还有 ${errorRows} 行错误`, { error_rows: errorRows });
    const open = [...b.file_findings, ...b.rows_data.flatMap((r) => r.findings)].filter((f) => f.needs_action && !f.resolution);
    if (open.length && body.acknowledge_warnings !== true) {
      return err(422, 'IMPORT_WARNINGS_UNACKNOWLEDGED', '有需处理的警告尚未确认', { codes: [...new Set(open.map((f) => f.code))], count: open.length });
    }
    const forced = (r: MockBatch['rows_data'][number]) => r.findings.some((f) => f.resolution && OVERRIDE_CHOICES.has(f.resolution.choice));
    const skippedByChoice = (r: MockBatch['rows_data'][number]) => r.findings.some((f) => f.resolution?.choice === 'skip_row' || (!f.resolution && f.default_resolution === 'skip_import_row') || f.resolution?.choice === 'skip_import_row');
    const writable = b.rows_data.filter((r) => (r.status === 'ok' || r.status === 'warning' || forced(r)) && (r.dedup_status === 'new' || r.dedup_status === null || forced(r)) && !skippedByChoice(r));
    if (!writable.length) return err(422, 'IMPORT_NOTHING_TO_COMMIT', '没有可写入的行');
    const tradesRows = writable.filter((r) => r.kind === 'trade' && r.normalized);
    if (b.kind === 'trades') {
      for (const r of tradesRows) {
        const n = r.normalized!;
        state.trades.push({
          id: nextId(), account_id: b.account_id, trade_date: n.trade_date, trade_time: n.trade_time, security_code: n.security_code, name: n.name,
          side: n.side ?? 'buy', qty: n.qty, price: n.price, amount: n.amount, fee_total: n.fee_total, net_amount: n.net_amount, source: 'import', batch_id: b.batch_id,
          voided: false, void_reason: null, voided_at: null, corrects_trade_id: null, created_at: NOW,
        });
      }
    }
    b.status = 'committed';
    b.committed_at = NOW;
    state.reconciled.add(b.account_id);
    const res = {
      status: 'committed',
      written: {
        trades: b.kind === 'trades' ? tradesRows.length : 0,
        events: writable.filter((r) => r.kind === 'event').length,
        snapshot_positions: b.kind === 'positions' ? tradesRows.length : 0,
      },
      reconciliation: { status: 'diff', diff_count: reconciliationFor(b.account_id).items.length },
    };
    if (key) b.idem.set(key, res);
    return json(res);
  }),
  http.post(`${API}/imports/:id/discard`, ({ params }) => {
    const b = myBatch(String(params.id));
    if (!b) return notFound('导入批次');
    if (b.status !== 'previewed' && b.status !== 'failed') return badTransition(b.status, 'discarded');
    // #35：同一事务删除全部预览行，批次头（stats、file_findings）保留
    b.stats_frozen = computeStats(b);
    b.status = 'discarded';
    b.rows_data = [];
    return json({ status: 'discarded' });
  }),
  http.post(`${API}/imports/:id/revert`, ({ params }) => {
    const b = myBatch(String(params.id));
    if (!b) return notFound('导入批次');
    if (b.status !== 'committed') return badTransition(b.status, 'reverted');
    b.status = 'reverted';
    b.reverted_at = NOW;
    state.trades.forEach((t) => {
      if (t.batch_id === b.batch_id && !t.voided) Object.assign(t, { voided: true, void_reason: `batch_reverted:${b.batch_id}`, voided_at: NOW });
    });
    return json({ status: 'reverted' });
  }),
  http.get(`${API}/imports/:id/errors.csv`, ({ params }) => {
    const b = myBatch(String(params.id));
    if (!b) return notFound('导入批次');
    const esc = (v: unknown) => `"${String(v ?? '').replaceAll('"', '""')}"`;
    const lines = ['row_no,code,severity,field,message,raw_masked'];
    // #35：discarded / failed 批次只有表头
    if (b.status !== 'discarded' && b.status !== 'failed') for (const f of b.file_findings) lines.push([f.row_no, f.code, f.severity, f.field, f.message, ''].map(esc).join(','));
    for (const r of b.rows_data) for (const f of r.findings) lines.push([r.row_no, f.code, f.severity, f.field, f.message, r.raw_masked].map(esc).join(','));
    return new HttpResponse(`\uFEFF${lines.join('\r\n')}\r\n`, { headers: { 'Content-Type': 'text/csv; charset=utf-8' } });
  }),

  // ---------------- 对账 ----------------
  http.get(`${API}/reconciliation`, ({ request }) => {
    const acc = new URL(request.url).searchParams.get('account_id');
    if (!acc) return validationError([{ field: 'account_id', issue: '必填' }]);
    if (!myAccount(acc)) return notFound('账户');
    return json(reconciliationFor(acc));
  }),
];
