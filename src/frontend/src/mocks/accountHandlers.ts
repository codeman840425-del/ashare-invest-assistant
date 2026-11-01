/**
 * MSW 处理器（T-F02 / T-F02a / T-F04）：认证、同意与风险测评、画像、管理端用户审核、券商账户、成交、导入、对账。
 * 后端目前只实现了 /health* 与 /meta/enums（src/backend/app/api/v1），其余都在这里按契约 v0.2.3 模拟。
 */
import { http, HttpResponse } from 'msw';
import type {
  AdminUserPatch, BrokerAccountCreate, ConsentRequest, ImportConfirmRequest, ImportOptions, LoginRequest, ProfileInput, RegisterRequest,
  ResolveFindingRequest, RiskAssessmentRequest, Trade, TradeCreate,
} from '../api/accountTypes';
import { ENUMS } from '../api/enums';
import { OVERRIDE_CHOICES } from '../i18n/importLabels';
import { emptyStats, finding, applyParse, currentUser, hasCompliance, publicBatch, reconciliationFor, state, toAdminUser, toMe, type MockBatch, type MockUser } from './session';
import { errorBody, page } from './handlerUtils';
import { NOW, uid } from './fixtures';

const API = '/api/v1';
const json = (body: unknown, status = 200) => HttpResponse.json(body as Record<string, unknown>, { status });
const err = (status: number, code: string, message: string, details: Record<string, unknown> | null = null) => json(errorBody(code, message, details), status);
export const validationError = (fields: { field: string; issue: string }[]) => err(400, 'VALIDATION_ERROR', '参数校验失败', { fields });
const notFound = (what: string) => err(404, 'NOT_FOUND', `${what} 不存在（示例数据）`);
const badTransition = (from: string, to: string) => err(409, 'INVALID_STATE_TRANSITION', `不能从 ${from} 变为 ${to}`, { from, to });
const noContent = (status = 204) => new HttpResponse(null, { status });

const PUBLIC = [/^\/meta\//, /^\/health/, /^\/auth\/login$/, /^\/auth\/register$/];
const GATED = [/^\/today/, /^\/suggestions/, /^\/daily-reports/, /^\/signals/, /^\/candidate-signals/, /^\/plan-drafts/];

const me = () => currentUser()!;
const myAccount = (id: string | null) => state.accounts.find((a) => a.id === id);
const myBatch = (id: string) => state.batches.find((b) => b.batch_id === id && !!myAccount(b.account_id));

let seq = 1000;
const nextId = () => uid(++seq);

const USERNAME_RE = /^[a-z0-9_]{4,32}$/; // [待契约确认] 契约 3–32，plan 3.6 为 4–32 且限定字符集；按 plan 校验
const RESERVED = ['admin', 'root', 'system'];

export const accountHandlers = [
  // —— 统一前置：鉴权与合规门槛（契约 §1.3）。返回 undefined 时继续交给后续处理器 ——
  http.all(`${API}/*`, ({ request }) => {
    const path = new URL(request.url).pathname.slice(API.length);
    const user = currentUser();
    if (path.startsWith('/admin')) {
      // §1.3 / §7.9：不是已登录的 admin 一律 404，与不存在的路径无法区分
      if (!user || user.role !== 'admin' || user.status !== 'approved') return err(404, 'NOT_FOUND', `示例数据未覆盖该端点：${new URL(request.url).pathname}`);
      return undefined;
    }
    if (PUBLIC.some((re) => re.test(path))) return undefined;
    if (!user) return err(401, 'AUTH_REQUIRED', '请先登录');
    if (user.status !== 'approved') return err(403, 'ACCOUNT_NOT_APPROVED', '账号未通过审核', { status: user.status });
    if (GATED.some((re) => re.test(path)) && !hasCompliance(user)) {
      const required = [...(!user.consents.signal_risk_disclosure ? ['signal_risk_disclosure'] : []), ...(!user.risk_assessment ? ['risk_assessment'] : [])];
      return err(403, 'CONSENT_REQUIRED', '请先阅读并同意风险揭示、完成风险测评', { required });
    }
    return undefined;
  }),

  // ---------------- §7.1 认证 ----------------
  http.get(`${API}/meta/registration`, () => json({ mode: state.registrationMode })),
  http.post(`${API}/auth/login`, async ({ request }) => {
    const body = (await request.json()) as Partial<LoginRequest>;
    const user = state.users.find((x) => x.username === body.username);
    if (!user || !body.password || body.password.length < 10) return err(401, 'INVALID_CREDENTIALS', '用户名或密码错误');
    if (user.locked) return err(403, 'ACCOUNT_LOCKED', '连续登录失败，账号已临时锁定', { retry_after_s: 900 });
    if (user.status !== 'approved') {
      return err(403, 'ACCOUNT_NOT_APPROVED', '账号未通过审核', { status: user.status, ...(user.review_reason ? { reason: user.review_reason } : {}) });
    }
    state.currentUserId = user.id;
    return json({ user: toMe(user), csrf_token: 'mock-csrf' });
  }),
  http.post(`${API}/auth/logout`, () => {
    state.currentUserId = null;
    return noContent();
  }),
  http.post(`${API}/auth/register`, async ({ request }) => {
    if (state.registrationMode === 'closed') return err(503, 'REGISTRATION_CLOSED', '暂未开放注册');
    const b = (await request.json()) as Partial<RegisterRequest>;
    const fields: { field: string; issue: string }[] = [];
    const name = b.username ?? '';
    if (!USERNAME_RE.test(name)) fields.push({ field: 'username', issue: '4–32 位小写字母、数字或下划线' });
    else if (RESERVED.some((r) => name.includes(r))) fields.push({ field: 'username', issue: '包含保留字' });
    const pwd = b.password ?? '';
    if (pwd.length < 10 || !/[a-zA-Z]/.test(pwd) || !/\d/.test(pwd)) fields.push({ field: 'password', issue: '至少 10 位，且包含字母和数字' });
    else if (pwd === name) fields.push({ field: 'password', issue: '不能与用户名相同' });
    if (!b.display_name?.trim()) fields.push({ field: 'display_name', issue: '必填' });
    if (state.registrationMode === 'invite' && !b.invite_code?.trim()) fields.push({ field: 'invite_code', issue: '邀请制下必填' });
    const need = ['terms', 'privacy', 'signal_risk_disclosure'];
    if (!need.every((k) => b.agreements?.includes(k as never))) fields.push({ field: 'agreements', issue: '须同意用户协议、隐私政策和风险揭示' });
    if (fields.length) return validationError(fields);
    if (state.users.some((x) => x.username === name)) return err(409, 'CONFLICT', '用户名已被使用');
    const id = nextId();
    state.users.push({
      id, username: name, display_name: b.display_name!.trim(), role: 'user', status: 'pending', apply_note: null, created_at: NOW, reviewed_at: null,
      review_reason: null, register_ip_region: '上海（示例）', same_ip_registrations: 1, consents: {}, risk_assessment: null,
    });
    return json({ id, username: name, status: 'pending' }, 201);
  }),
  http.get(`${API}/me`, () => json(toMe(me()))),
  http.post(`${API}/me/consents`, async ({ request }) => {
    const b = (await request.json()) as Partial<ConsentRequest>;
    if (!b.key || !['signal_risk_disclosure', 'privacy', 'terms'].includes(b.key) || !b.version) return validationError([{ field: 'key', issue: '取值不合法' }]);
    me().consents = { ...me().consents, [b.key]: { version: b.version, accepted_at: NOW } };
    return noContent(201);
  }),
  http.post(`${API}/me/risk-assessment`, async ({ request }) => {
    const b = (await request.json()) as Partial<RiskAssessmentRequest>;
    if (!b.answers?.length) return validationError([{ field: 'answers', issue: '必填' }]);
    const score = b.answers.reduce((a, x) => a + Math.max(0, 'abcd'.indexOf(x.choice)), 0);
    const level = Math.min(5, Math.max(1, Math.round((score / (b.answers.length * 3)) * 4) + 1));
    me().risk_assessment = { level, assessed_at: NOW };
    return json({ level, assessed_at: NOW });
  }),
  http.get(`${API}/me/profile`, () => {
    const p = state.profiles.get(me().id);
    return p ? json(p) : notFound('投资画像');
  }),
  http.put(`${API}/me/profile`, async ({ request }) => {
    const b = (await request.json()) as Partial<ProfileInput>;
    const fields: { field: string; issue: string }[] = [];
    if (!b.horizon_pref?.length || !b.horizon_pref.every((h) => (ENUMS.horizon as readonly string[]).includes(h))) fields.push({ field: 'horizon_pref', issue: '至少选择一个周期' });
    if (!b.effort || !['low', 'medium', 'high'].includes(b.effort)) fields.push({ field: 'effort', issue: '取值不合法' });
    if (!Number.isInteger(b.risk_tolerance) || b.risk_tolerance! < 1 || b.risk_tolerance! > 5) fields.push({ field: 'risk_tolerance', issue: '1–5' });
    if (!b.experience || !['novice', 'intermediate', 'advanced'].includes(b.experience)) fields.push({ field: 'experience', issue: '取值不合法' });
    const pct = Number(b.max_single_position_pct);
    if (!(pct >= 5 && pct <= 50)) fields.push({ field: 'max_single_position_pct', issue: '5–50' });
    if (fields.length) return validationError(fields);
    const prev = state.profiles.get(me().id);
    const p = { ...(b as ProfileInput), version_no: (prev?.version_no ?? 0) + 1 };
    state.profiles.set(me().id, p);
    return json(p);
  }),

  // ---------------- §7.9 管理端：用户审核 ----------------
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
    if ((b.status === 'rejected' || b.status === 'disabled') && !b.reason?.trim()) return validationError([{ field: 'reason', issue: '驳回或停用必须填写理由' }]);
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
    const b = (await request.json()) as Partial<TradeCreate>;
    const fields: { field: string; issue: string }[] = [];
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
      source: 'manual', batch_id: null, voided: false, created_at: NOW,
    };
    state.trades.push(t);
    return json(t, 201);
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
    const items = state.batches.filter((b) => myAccount(b.account_id) && (!acc || b.account_id === acc) && (!st || b.status === st)).map(publicBatch);
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
    const items = b.rows_data.filter((r) => (!st || r.status === st) && (!code || r.findings.some((f) => f.code === code)) && (!dd || r.dedup_status === dd));
    return json(page(items, url));
  }),
  http.put(`${API}/imports/:id/options`, async ({ params, request }) => {
    const b = myBatch(String(params.id));
    if (!b) return notFound('导入批次');
    if (b.status !== 'previewed' && b.status !== 'failed') return badTransition(b.status, 'parsing');
    const o = (await request.json()) as Partial<ImportOptions>;
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
    const all = [...b.file_findings, ...b.rows_data.flatMap((r) => r.findings)];
    const f = all.find((x) => x.id === params.fid);
    if (!f) return notFound('提示');
    if (b.status !== 'previewed') return badTransition(b.status, 'previewed');
    const body = (await request.json()) as Partial<ResolveFindingRequest>;
    if (!body.choice || !f.resolution_choices.includes(body.choice)) return validationError([{ field: 'choice', issue: '须在 resolution_choices 中' }]);
    if (OVERRIDE_CHOICES.has(body.choice) && !body.reason?.trim()) return validationError([{ field: 'reason', issue: '覆盖类处理必须填写理由' }]);
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
          side: n.side ?? 'buy', qty: n.qty, price: n.price, amount: n.amount, fee_total: n.fee_total, source: 'import', batch_id: b.batch_id, voided: false, created_at: NOW,
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
    b.status = 'discarded';
    return json({ status: 'discarded' });
  }),
  http.post(`${API}/imports/:id/revert`, ({ params }) => {
    const b = myBatch(String(params.id));
    if (!b) return notFound('导入批次');
    if (b.status !== 'committed') return badTransition(b.status, 'reverted');
    b.status = 'reverted';
    b.reverted_at = NOW;
    state.trades.forEach((t) => {
      if (t.batch_id === b.batch_id) t.voided = true;
    });
    return json({ status: 'reverted' });
  }),
  http.get(`${API}/imports/:id/errors.csv`, ({ params }) => {
    const b = myBatch(String(params.id));
    if (!b) return notFound('导入批次');
    const esc = (v: unknown) => `"${String(v ?? '').replaceAll('"', '""')}"`;
    const lines = ['row_no,code,severity,field,message,raw_masked'];
    for (const f of b.file_findings) lines.push([f.row_no, f.code, f.severity, f.field, f.message, ''].map(esc).join(','));
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
