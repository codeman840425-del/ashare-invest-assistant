/**
 * 示例数据（全部虚构）：会话与账号、画像、券商账户、成交、导入批次、对账的可变状态。
 * 只在 MSW 内使用；resetSession() 在每个测试后恢复初始状态。
 * 登录按用户名决定结果，夹具里不出现任何密码（密码只校验长度 ≥ 10）。
 */
import type { AccountStatus, Role } from '../api/enums';
import type {
  AdminUser, BrokerAccount, ImportBatch, ImportFinding, ImportKind, ImportRow, Profile, Reconciliation, Trade,
} from '../api/accountTypes';
import type { Me } from '../api/types';
import { IMPORT_CODE_MAP, renderTemplate } from '../api/importCodes';
import { ACCOUNT_ID, NOW, uid } from './fixtures';
import { licenceState, resetLicences } from './licenceStore';

export interface MockUser {
  id: string;
  username: string;
  display_name: string;
  role: Role;
  status: AccountStatus;
  apply_note: string | null;
  created_at: string;
  reviewed_at: string | null;
  review_reason: string | null;
  register_ip_region: string | null;
  same_ip_registrations: number;
  /** 登录时返回 ACCOUNT_LOCKED */
  locked?: boolean;
  last_login_at?: string | null;
}

const u = (n: number, username: string, display_name: string, status: AccountStatus, extra: Partial<MockUser> = {}): MockUser => ({
  id: uid(n), username, display_name, role: 'user', status, apply_note: null, created_at: '2026-10-20T20:15:00+08:00',
  reviewed_at: status === 'pending' ? null : '2026-10-21T09:00:00+08:00', review_reason: null, register_ip_region: '浙江（示例）',
  same_ip_registrations: 1, last_login_at: null, ...extra,
});

function initialUsers(): MockUser[] {
  return [
    u(2, 'demo_user', '示例用户', 'approved', { created_at: '2026-09-28T10:00:00+08:00' }),
    u(3, 'admin', '管理员（示例）', 'approved', { role: 'admin', created_at: '2026-09-01T10:00:00+08:00' }),
    u(4, 'new_user', '新用户（示例）', 'approved', { created_at: '2026-10-30T10:00:00+08:00' }),
    u(5, 'pending_user', '待审核用户（示例）', 'pending', { apply_note: '同事推荐，想用来整理交割单（示例）', created_at: '2026-11-01T21:40:00+08:00' }),
    u(6, 'pending_two', '申请人乙（示例）', 'pending', { apply_note: null, register_ip_region: '广东（示例）', same_ip_registrations: 3, created_at: '2026-11-01T22:05:00+08:00' }),
    u(7, 'rejected_user', '已驳回用户（示例）', 'rejected', { review_reason: '申请说明不完整，请补充用途后重新提交（示例）' }),
    u(8, 'disabled_user', '已停用用户（示例）', 'disabled', { review_reason: '账号长期未使用，已停用（示例）' }),
    u(9, 'locked_user', '锁定用户（示例）', 'approved', { locked: true }),
    // 自报经验为新手：短线、日内做T 只出提示（v0.2.5 #2，SH0C / IT0C 进 hints，不封顶）
    u(13, 'novice_user', '新手用户（示例）', 'approved'),
    // v0.2.8 #12/#14：证书被管理员暂停（演示“测试证书”禁用）
    u(14, 'paused_user', '证书被暂停用户（示例）', 'approved', { created_at: '2026-10-25T10:00:00+08:00' }),
  ];
}

const DEMO_PROFILE: Profile = {
  version_no: 2, horizon_pref: ['swing', 'long'], effort: 'medium', risk_tolerance: 3, experience: 'intermediate', max_single_position_pct: '20',
};

export const SECOND_ACCOUNT_ID = uid(11);
function initialAccounts(): BrokerAccount[] {
  return [
    { id: ACCOUNT_ID, broker_name: '示例证券', alias: '主账户（示例）', shareholder_code_masked: 'A1****89', fund_account_masked: '3100****21', created_at: '2026-09-28T10:10:00+08:00' },
    { id: SECOND_ACCOUNT_ID, broker_name: '演示证券', alias: '备用账户（示例）', shareholder_code_masked: null, fund_account_masked: null, created_at: '2026-10-15T10:10:00+08:00' },
  ];
}

// ---------------- 提示码构造 ----------------
let findingSeq = 0;
export function finding(code: string, opts: { row_no?: number | null; field?: string | null; params?: Record<string, unknown> } = {}): ImportFinding {
  const spec = IMPORT_CODE_MAP.get(code);
  if (!spec) throw new Error(`unknown import code ${code}`);
  findingSeq += 1;
  const params = opts.params ?? {};
  const choices = RESOLUTION_CHOICES[code] ?? [];
  return {
    id: `f_${String(findingSeq).padStart(4, '0')}`, code, severity: spec.severity, scope: spec.scope, row_no: opts.row_no ?? null,
    field: opts.field ?? null, message: renderTemplate(spec.template, { row_no: opts.row_no, ...params }), params, needs_action: spec.needs_action,
    resolution_choices: choices, default_resolution: choices[0] ?? null, resolution: null,
  };
}
/** resolution_choices 按契约 v0.2.4 §4.1“处理选项”表生成；第一个为默认处理，表中没有的码为 [] */
export const RESOLUTION_CHOICES: Record<string, string[]> = {
  IMPORT_ACCOUNT_MISMATCH: ['confirm_new_holder_code'],
  IMPORT_ENCODING_LOW_CONFIDENCE: ['confirm'],
  IMPORT_FORMAT_LOW_CONFIDENCE: ['confirm'],
  IMPORT_SNAPSHOT_AS_OF_ASSUMED: ['confirm'],
  IMPORT_UNKNOWN_SECURITY: ['import_as_is', 'skip_row'],
  IMPORT_MARKET_INFERRED_CONFLICT: ['use_master_data'],
  IMPORT_UNKNOWN_BIZ_TYPE: ['keep_skipped', 'manual_entry'],
  IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL: ['skip_import_row', 'keep_import_void_manual'],
  IMPORT_DUPLICATE_IN_DB: ['keep_skipped', 'force_import'],
  IMPORT_DUPLICATE_IN_FILE: ['keep_skipped', 'force_import'],
};

// ---------------- 导入场景 ----------------
// 示例表头：明显的假列名（“示例列·…”），不模仿任何券商导出文件的真实表头（仓库扫描 S7）
const col = (s: string) => `示例列·${s}`;
const TRADE_COLS: [string, string | null][] = [
  ['日期', 'trade_date'], ['时间', 'trade_time'], ['代码', 'security_code'], ['名称', 'name'], ['操作', 'biz_type_raw'], ['数量', 'qty'],
  ['均价', 'price'], ['金额', 'amount'], ['手续费', null], ['印花税', null], ['过户费', null], ['净额', 'net_amount'], ['余额', 'balance'],
  ['流水号', 'trade_no'], ['持有人代码', 'shareholder_code'], ['备注', null],
];
export const TRADE_COLUMNS = TRADE_COLS.map(([c]) => col(c));
export const TRADE_MAPPING: Record<string, string> = Object.fromEntries(TRADE_COLS.filter(([, f]) => f).map(([c, f]) => [col(c), f as string]));
/** “缺少必填列”场景：价格列改名后默认映射认不出 */
export const PRICE_COL = col('均价');
export const PRICE_COL_RENAMED = col('价');
const POSITION_COLS: [string, string | null][] = [
  ['代码', 'security_code'], ['名称', 'name'], ['数量', 'qty'], ['可卖数量', null], ['成本价', 'cost_price'], ['当前价', null],
  ['市值', 'market_value'], ['浮动盈亏', null], ['持有人代码', 'shareholder_code'],
];
export const POSITION_COLUMNS = POSITION_COLS.map(([c]) => col(c));
export const POSITION_MAPPING: Record<string, string> = Object.fromEntries(POSITION_COLS.filter(([, f]) => f).map(([c, f]) => [col(c), f as string]));

type RowSpec = [date: string, time: string | null, code: string, name: string, side: 'buy' | 'sell' | null, qty: number, price: number, biz: string];
const mkNorm = ([date, time, code, name, side, qty, price, biz]: RowSpec, fee = 5) => {
  const amount = qty * price;
  const sign = side === 'buy' ? -1 : 1;
  return {
    trade_date: date, trade_time: time, security_code: code, name, side, qty: String(qty), price: price.toFixed(2), amount: amount.toFixed(2),
    fee_total: fee.toFixed(2), net_amount: (sign * amount - fee).toFixed(2), biz_type_raw: biz,
  };
};
const rawOf = (n: ImportRow['normalized'] | null, fallback: string) =>
  n ? `${n.trade_date.replaceAll('-', '')}\t${n.trade_time ?? ''}\t${n.security_code.slice(0, 6)}\t${n.name}\t${n.biz_type_raw}\t${n.qty}\t${n.price}\t${n.amount}\tA1****89` : fallback;

function row(row_no: number, status: ImportRow['status'], kind: ImportRow['kind'], dedup: ImportRow['dedup_status'], spec: RowSpec | null, findings: ImportFinding[], raw?: string): ImportRow {
  const normalized = spec ? mkNorm(spec) : null;
  return { row_no, status, kind, dedup_status: dedup, findings, raw_masked: raw ?? rawOf(normalized, ''), normalized };
}

/** 交割单场景：覆盖大多数行级提示码 */
export function tradeRows(prevBatchId: string): ImportRow[] {
  let n = 0;
  const next = () => ++n;
  const r: ImportRow[] = [];
  const add = (status: ImportRow['status'], kind: ImportRow['kind'], dedup: ImportRow['dedup_status'], spec: RowSpec | null, f: (no: number) => ImportFinding[], raw?: string) => {
    const no = next();
    r.push(row(no, status, kind, dedup, spec, f(no), raw));
  };
  add('ok', 'trade', 'new', ['2026-10-26', '09:35:12', '600000.SH', '示例银行', 'buy', 1000, 10.02, '证券买入'], () => []);
  add('ok', 'trade', 'new', ['2026-10-26', '10:02:40', '000001.SZ', '演示科技', 'sell', 500, 23.5, '证券卖出'], () => []);
  add('warning', 'trade', 'new', ['2026-10-27', '13:15:03', '300001.SZ', '演示电子', 'buy', 200, 41.3, '证券买入'],
    (no) => [finding('IMPORT_NET_AMOUNT_MISMATCH', { row_no: no, field: 'net_amount', params: { diff: '0.05' } })]);
  add('skipped', 'trade', 'duplicate_in_db', ['2026-10-20', '09:41:00', '002001.SZ', '演示材料', 'buy', 300, 12.6, '证券买入'],
    (no) => [finding('IMPORT_DUPLICATE_IN_DB', { row_no: no, params: { batch_id: prevBatchId } })]);
  add('skipped', 'trade', 'duplicate_in_file', ['2026-10-26', '10:02:40', '000001.SZ', '演示科技', 'sell', 500, 23.5, '证券卖出'],
    (no) => [finding('IMPORT_DUPLICATE_IN_FILE', { row_no: no, params: { other_row_no: 2 } })]);
  add('warning', 'trade', 'possible_duplicate_of_manual', ['2026-10-27', '14:20:00', '600002.SH', '演示医药', 'buy', 400, 17.9, '证券买入'],
    (no) => [finding('IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL', { row_no: no, params: { trade_id: uid(901) } })]);
  add('warning', 'trade', 'new', ['2026-10-27', '14:31:10', '600999.SH', '演示新股', 'buy', 500, 6.12, '证券买入'],
    (no) => [finding('IMPORT_UNKNOWN_SECURITY', { row_no: no, field: 'security_code', params: { code: '600999.SH' } })]);
  add('skipped', 'ignored', null, null, (no) => [finding('IMPORT_UNKNOWN_BIZ_TYPE', { row_no: no, field: 'biz_type_raw', params: { biz: '担保品划入' } })],
    '20261028\t\t600000\t示例银行\t担保品划入\t200\t0.00\t0.00\tA1****89');
  add('skipped', 'ignored', null, null, (no) => [finding('IMPORT_ROW_CANCELLED', { row_no: no })], '20261028\t09:31:00\t000002\t演示消费\t撤单\t0\t0.00\t0.00\tA1****89');
  add('skipped', 'ignored', null, null, (no) => [finding('IMPORT_ROW_REJECTED', { row_no: no })], '20261028\t09:31:05\t000002\t演示消费\t废单\t100\t56.20\t0.00\tA1****89');
  add('error', 'trade', null, null, (no) => [finding('IMPORT_INVALID_DATE', { row_no: no, field: 'trade_date', params: { value: '20261341' } })],
    '20261341\t10:00:00\t600000\t示例银行\t证券买入\t100\t10.10\t1010.00\tA1****89');
  add('error', 'trade', null, ['2026-10-28', '10:11:00', '000002.SZ', '演示消费', 'buy', 100, 56.2, '证券买入'],
    (no) => [finding('IMPORT_AMOUNT_MISMATCH', { row_no: no, field: 'amount', params: { diff: '12.00' } })]);
  add('error', 'trade', null, ['2026-10-28', '10:20:00', '688001.SH', '演示芯片', 'sell', 200, 87.1, '证券卖出'],
    (no) => [finding('IMPORT_SIDE_QTY_SIGN_MISMATCH', { row_no: no, field: 'qty' })]);
  add('warning', 'trade', 'new', ['2026-10-29', '09:50:00', '600000.SH', '示例银行', 'buy', 500, 10.11, '证券买入'],
    (no) => [finding('IMPORT_NAME_MISMATCH', { row_no: no, field: 'name', params: { name_raw: '示例银行Ａ', name: '示例银行' } })]);
  add('warning', 'trade', 'new', ['2026-10-29', '10:30:00', '601001.SH', '演示能源', 'sell', 800, 15.2, '证券卖出'],
    (no) => [finding('IMPORT_MISSING_OPENING_POSITION', { row_no: no, field: 'qty' })]);
  add('warning', 'trade', 'new', ['2026-10-29', '13:40:00', '002001.SZ', '演示材料', 'sell', 300, 12.95, '证券卖出'],
    (no) => [finding('IMPORT_CASH_CHAIN_BREAK', { row_no: no, field: 'balance', params: { diff: '300.00' } })]);
  add('warning', 'trade', 'new', ['2026-10-03', '10:00:00', '000001.SZ', '演示科技', 'buy', 100, 23.0, '证券买入'],
    (no) => [finding('IMPORT_NON_TRADING_DAY', { row_no: no, field: 'trade_date', params: { date: '2026-10-03' } })]);
  add('warning', 'trade', 'new', ['2026-10-30', '12:10:00', '300001.SZ', '演示电子', 'sell', 100, 42.5, '证券卖出'],
    (no) => [finding('IMPORT_TIME_OUTSIDE_SESSION', { row_no: no, field: 'trade_time' })]);
  add('warning', 'trade', 'new', ['2026-10-30', '14:01:00', '600002.SH', '演示医药', 'buy', 150, 17.75, '证券买入'],
    (no) => [finding('IMPORT_LOT_SIZE_IRREGULAR', { row_no: no, field: 'qty' })]);
  add('error', 'trade', null, null, (no) => [finding('IMPORT_INVALID_TIME', { row_no: no, field: 'trade_time', params: { value: '930' } })],
    '20261030\t930\t600000\t示例银行\t证券买入\t100\t10.20\t1020.00\tA1****89');
  add('error', 'trade', null, null, (no) => [finding('IMPORT_INVALID_SECURITY_CODE', { row_no: no, field: 'security_code', params: { value: '60000' } })],
    '20261030\t10:40:00\t60000\t示例银行\t证券买入\t100\t10.20\t1020.00\tA1****89');
  add('warning', 'trade', 'new', ['2026-10-30', '14:20:00', '830001.BJ', '演示精工', 'buy', 100, 9.66, '证券买入'],
    (no) => [finding('IMPORT_MARKET_INFERRED_CONFLICT', { row_no: no, field: 'security_code' })]);
  add('ok', 'event', null, ['2026-10-30', null, '600000.SH', '示例银行', null, 1500, 0.3, '红利入账'], () => []);
  add('ok', 'event', null, ['2026-10-31', null, '600000.SH', '示例银行', null, 1500, 0.03, '股息红利差异扣税'], () => []);
  add('error', 'trade', null, null, (no) => [finding('IMPORT_ROW_TRUNCATED', { row_no: no })], '20261031\t10:05:00\t000001\t演示科');
  return r;
}

export function positionRows(asOf: string): ImportRow[] {
  const d = asOf.slice(0, 10);
  const mk = (no: number, code: string, name: string, qty: number, cost: number, status: ImportRow['status'], f: ImportFinding[] = []): ImportRow => ({
    row_no: no, status, kind: 'trade', dedup_status: 'new', findings: f,
    raw_masked: `${code.slice(0, 6)}\t${name}\t${qty}\t${qty}\t${cost.toFixed(3)}\t\t\t\tA1****89`,
    normalized: { trade_date: d, trade_time: null, security_code: code, name, side: null, qty: String(qty), price: cost.toFixed(3), amount: (qty * cost).toFixed(2), fee_total: null, net_amount: null, biz_type_raw: '持仓' },
  });
  return [
    mk(1, '600000.SH', '示例银行', 2500, 9.812, 'ok'),
    mk(2, '000001.SZ', '演示科技', 800, 21.305, 'ok'),
    mk(3, '300001.SZ', '演示电子', 300, 38.92, 'ok'),
    mk(4, '002001.SZ', '演示材料', 600, 12.31, 'warning', [finding('IMPORT_NAME_MISMATCH', { row_no: 4, field: 'name', params: { name_raw: '演示材 料', name: '演示材料' } })]),
    mk(5, '688001.SH', '演示芯片', 200, 80.45, 'ok'),
  ];
}

export interface MockBatch extends ImportBatch {
  filename: string;
  rows_data: ImportRow[];
  /** 解析阶段：被 GET 轮询几次后转为终态 */
  parse_polls_left: number;
  parse_target: 'previewed' | 'failed';
  idem: Map<string, unknown>;
  /** #35：放弃时预览行被删除，批次头 stats 按删除前的计数保留 */
  stats_frozen?: ImportBatch['stats'];
}

export const emptyStats = (): ImportBatch['stats'] => ({
  rows: 0, ok: 0, warning: 0, error: 0, skipped: 0, new: 0, duplicate_in_db: 0, duplicate_in_file: 0, possible_duplicate_of_manual: 0, needs_action_open: 0,
});
export function computeStats(b: MockBatch): ImportBatch['stats'] {
  if (b.stats_frozen) return b.stats_frozen;
  const s = emptyStats();
  if (b.status === 'uploaded' || b.status === 'parsing') return s;
  for (const r of b.rows_data) {
    s.rows += 1;
    s[r.status] += 1;
    if (r.dedup_status) s[r.dedup_status] += 1;
  }
  const all = [...b.file_findings, ...b.rows_data.flatMap((r) => r.findings)];
  s.needs_action_open = all.filter((f) => f.needs_action && !f.resolution).length;
  return s;
}

export function publicBatch(b: MockBatch): ImportBatch {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { filename, rows_data, parse_polls_left, parse_target, idem, stats_frozen, ...rest } = b;
  return { ...rest, stats: computeStats(b) };
}

/** 依据文件名、类型、当前选项生成解析结果 */
export function applyParse(b: MockBatch) {
  const name = b.filename.toLowerCase();
  const fixedMapping = b.mapping && Object.values(b.mapping).includes('price');
  if (b.kind === 'trades' && name.includes('missing') && !fixedMapping) {
    // 缺少必填列：表头是“均价”，默认映射认不出 → failed，用户手工映射后重新解析
    b.detected_columns = TRADE_COLUMNS.map((c) => (c === PRICE_COL ? PRICE_COL_RENAMED : c));
    b.mapping = Object.fromEntries(Object.entries(TRADE_MAPPING).filter(([k]) => k !== PRICE_COL));
    b.parser_id = 'tdx_trades_v1';
    b.format_score = 0.71;
    b.file_findings = [finding('IMPORT_REQUIRED_COLUMN_MISSING', { field: 'price', params: { columns: '成交价格（price）' } })];
    b.rows_data = [];
    b.parse_target = 'failed';
    return;
  }
  if (name.includes('unknown') && !b.parser_id) {
    b.detected_columns = ['col1', 'col2', 'col3', 'col4'];
    b.mapping = null;
    b.format_score = 0.31;
    b.file_findings = [finding('IMPORT_UNRECOGNIZED_FORMAT', { params: { candidates: 'tdx_trades_v1, tdx_positions_v1' } })];
    b.rows_data = [];
    b.parse_target = 'failed';
    return;
  }
  b.parse_target = 'previewed';
  b.parser_version = '1.0.0';
  const keep = b.file_findings.filter((f) => f.code === 'IMPORT_DUPLICATE_FILE');
  if (b.kind === 'positions') {
    b.parser_id = 'tdx_positions_v1';
    b.detected_columns = POSITION_COLUMNS;
    b.mapping = b.mapping ?? POSITION_MAPPING;
    b.detected_encoding = 'GB18030';
    b.encoding_confidence = 0.99;
    b.format_score = 0.97;
    const assumed = !b.snapshot_as_of;
    if (assumed) b.snapshot_as_of = '2026-10-31T15:00:00+08:00';
    b.file_findings = [
      ...keep,
      ...(assumed ? [finding('IMPORT_SNAPSHOT_AS_OF_ASSUMED', { params: { as_of: '2026-10-31 15:00' } })] : []),
      finding('IMPORT_SNAPSHOT_TOTALS_MISMATCH'),
      finding('IMPORT_UNSUPPORTED_CURRENCY', { params: { currency: '美元' } }),
    ];
    b.rows_data = positionRows(b.snapshot_as_of!);
    return;
  }
  b.parser_id = 'tdx_trades_v1';
  b.detected_columns = TRADE_COLUMNS;
  b.mapping = b.mapping ?? TRADE_MAPPING;
  b.detected_encoding = 'GB18030';
  const lowConf = !b.encoding_override;
  b.encoding_confidence = lowConf ? 0.82 : 1;
  b.format_score = 0.98;
  b.file_findings = [
    ...keep,
    ...(lowConf ? [finding('IMPORT_ENCODING_LOW_CONFIDENCE', { params: { encoding: 'GB18030', confidence: '0.82' } })] : []),
    finding('IMPORT_UNKNOWN_COLUMN', { params: { columns: '备注' } }),
    finding('IMPORT_FILE_POSSIBLY_TRUNCATED'),
  ];
  b.rows_data = tradeRows(uid(820));
}

// ---------------- 状态 ----------------
/** 示例邀请码（只在 MSW 中有效；契约 #27 的无效码返回 400 invite_code invalid） */
export const MOCK_INVITE_CODES = ['DEMO-INVITE-OK'];
/** 同 IP 高亮阈值（示例；真实值是服务端配置 admin.same_ip_highlight_threshold） */
export const MOCK_SAME_IP_THRESHOLD = 3;
/** 注册 IP 限速（与后端默认 auth_abuse.register_ip_per_hour 一致，示例只模拟小时窗口） */
export const MOCK_REGISTER_IP_PER_HOUR = 5;
export const MOCK_PENDING_CAP = 200;
export interface SessionState {
  currentUserId: string | null;
  /** 契约 §1.3 CSRF：当前会话内的令牌（未登录为 null）；与 Cookie `csrf_token`、请求头 `X-CSRF-Token` 三者须一致 */
  csrfToken: string | null;
  registrationMode: 'closed' | 'invite' | 'open';
  /** v0.2.8 #11：蜜罐命中记录（模拟审计 auth.register_honeypot，只记 trigger，不记表单内容） */
  honeypotHits: ('website' | 'too_fast' | 'both')[];
  /** §7.1 注册 IP 限速：本 IP（mock 只有一个）每次尝试的时间戳，含校验失败与蜜罐命中 */
  registerHits: number[];
  /** §7.1 待审核数上限（服务端配置 pending_cap，默认 200）；全站 pending 数 ≥ 它 → 503 REGISTRATION_CLOSED */
  pendingCap: number;
  users: MockUser[];
  profiles: Map<string, Profile>;
  accounts: BrokerAccount[];
  trades: Trade[];
  batches: MockBatch[];
  reconciled: Set<string>;
  /** POST /trades 的幂等键 → 第一次的结果 */
  tradeIdem: Map<string, Trade>;
}

function initialTrades(): Trade[] {
  const t = (n: number, date: string, code: string, name: string, side: 'buy' | 'sell', qty: number, price: number, source: Trade['source'], batch: string | null): Trade => ({
    id: uid(n), account_id: ACCOUNT_ID, trade_date: date, trade_time: '10:00:00', security_code: code, name, side, qty: String(qty), price: price.toFixed(2),
    amount: (qty * price).toFixed(2), fee_total: '5.00', net_amount: (side === 'buy' ? -(qty * price + 5) : qty * price - 5).toFixed(2), source, batch_id: batch,
    voided: false, void_reason: null, voided_at: null, corrects_trade_id: null, created_at: `${date}T16:00:00+08:00`,
  });
  return [
    t(901, '2026-10-27', '600002.SH', '演示医药', 'buy', 400, 17.9, 'manual', null),
    t(902, '2026-10-20', '002001.SZ', '演示材料', 'buy', 300, 12.6, 'import', uid(820)),
    t(903, '2026-10-16', '600000.SH', '示例银行', 'buy', 1500, 9.7, 'import', uid(820)),
    t(904, '2026-10-15', '000001.SZ', '演示科技', 'buy', 1300, 21.2, 'import', uid(820)),
    t(905, '2026-10-14', '688001.SH', '演示芯片', 'buy', 200, 80.3, 'import', uid(820)),
    // 已撤销批次 819 写入过的成交：保留记录、标记作废（v0.2.4 #12：void_reason = batch_reverted:{batch_id}）
    { ...t(906, '2026-10-13', '300001.SZ', '演示电子', 'buy', 300, 39.8, 'import', uid(819)), voided: true, void_reason: `batch_reverted:${uid(819)}`, voided_at: '2026-10-18T21:10:00+08:00' },
  ];
}

function initialBatches(): MockBatch[] {
  const committed: MockBatch = {
    batch_id: uid(820), account_id: ACCOUNT_ID, kind: 'trades', status: 'committed', parser_id: 'tdx_trades_v1', parser_version: '1.0.0',
    detected_encoding: 'GB18030', encoding_override: null, encoding_confidence: 0.99, format_score: 0.99, detected_columns: TRADE_COLUMNS,
    mapping: TRADE_MAPPING, snapshot_as_of: null, file_findings: [], stats: emptyStats(), created_at: '2026-10-20T20:30:00+08:00',
    committed_at: '2026-10-20T20:32:00+08:00', reverted_at: null, filename: '交割单_202610上.txt', rows_data: [], parse_polls_left: 0,
    parse_target: 'previewed', idem: new Map(),
  };
  committed.rows_data = tradeRows(uid(800)).filter((r) => r.status === 'ok');
  const reverted: MockBatch = {
    ...committed, batch_id: uid(819), status: 'reverted', created_at: '2026-10-18T21:00:00+08:00', committed_at: '2026-10-18T21:02:00+08:00',
    reverted_at: '2026-10-18T21:10:00+08:00', filename: '交割单_错误账户.txt', idem: new Map(),
  };
  return [committed, reverted];
}

/** 示例会话的初始 CSRF 令牌（不是密钥，只是示例字符串） */
export const MOCK_CSRF = 'mock-csrf';
let csrfSeq = 0;
/** 登录、改密时轮换（契约 §1.3）：新令牌 */
export const rotateCsrf = () => `mock-csrf-${++csrfSeq}`;
/**
 * 设置会话令牌并模拟浏览器应用 Set-Cookie: csrf_token（非 HttpOnly）。
 * MSW 不会把模拟响应的 Set-Cookie 写进 document.cookie，所以示例环境在这里直接写；null = 清除 Cookie。
 */
export function setSessionCsrf(token: string | null) {
  state.csrfToken = token;
  if (typeof document === 'undefined') return;
  document.cookie = token ? `csrf_token=${encodeURIComponent(token)}; Path=/; SameSite=Lax` : 'csrf_token=; Path=/; Max-Age=0';
}
/**
 * 请求实际会带上的 Cookie：请求头 Cookie，加上 credentials 不为 omit 时浏览器附带的 document.cookie
 * （同源相对路径，same-origin 与 include 都会带）。
 */
export function requestCookies(request: Request): Record<string, string> {
  const out: Record<string, string> = {};
  const add = (raw: string | null) => {
    for (const part of (raw ?? '').split(';')) {
      const i = part.indexOf('=');
      if (i > 0) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
    }
  };
  if (request.credentials !== 'omit' && typeof document !== 'undefined') add(document.cookie);
  add(request.headers.get('cookie'));
  return out;
}

export const state: SessionState = {
  currentUserId: uid(2), csrfToken: null, registrationMode: 'invite', honeypotHits: [], registerHits: [], pendingCap: MOCK_PENDING_CAP, users: [], profiles: new Map(), accounts: [], trades: [], batches: [], reconciled: new Set(), tradeIdem: new Map(),
};

export function resetSession() {
  findingSeq = 0;
  state.currentUserId = uid(2);
  setSessionCsrf(MOCK_CSRF);
  state.registrationMode = 'invite';
  state.honeypotHits = [];
  state.registerHits = [];
  state.pendingCap = MOCK_PENDING_CAP;
  state.users = initialUsers();
  state.profiles = new Map([
    [uid(2), { ...DEMO_PROFILE }], [uid(3), { ...DEMO_PROFILE, version_no: 1 }],
    [uid(13), { ...DEMO_PROFILE, version_no: 1, horizon_pref: ['short'], experience: 'novice', effort: 'medium', risk_tolerance: 3 }],
  ]);
  state.accounts = initialAccounts();
  state.trades = initialTrades();
  state.batches = initialBatches();
  state.reconciled = new Set([ACCOUNT_ID]);
  state.tradeIdem = new Map();
  resetLicences();
}
resetSession();

export const currentUser = (): MockUser | null => state.users.find((x) => x.id === state.currentUserId) ?? null;
export const toMe = (x: MockUser): Me => ({
  id: x.id, username: x.username, display_name: x.display_name, role: x.role, status: x.status,
  entitlements: { 'watchlist.per_user_cap': 50 }, data_licence_status: licenceState(x.id),
});
export const toAdminUser = (x: MockUser): AdminUser => ({
  id: x.id, username: x.username, display_name: x.display_name, role: x.role, status: x.status, apply_note: x.apply_note, created_at: x.created_at,
  reviewed_at: x.reviewed_at, review_reason: x.review_reason, register_ip_region: x.register_ip_region, same_ip_registrations: x.same_ip_registrations,
  same_ip_flag: x.same_ip_registrations >= MOCK_SAME_IP_THRESHOLD, last_login_at: x.last_login_at ?? null,
});
/** 测试辅助：切换当前登录用户（null = 未登录）；登录态同时给出 CSRF 令牌与 Cookie */
export function mockLoginAs(username: string | null) {
  state.currentUserId = username ? (state.users.find((x) => x.username === username)?.id ?? null) : null;
  setSessionCsrf(state.currentUserId ? MOCK_CSRF : null);
}
export function setRegistrationMode(m: SessionState['registrationMode']) {
  state.registrationMode = m;
}
// ---------------- 对账（示例） ----------------
export function reconciliationFor(accountId: string): Reconciliation {
  if (!state.reconciled.has(accountId)) return { status: 'not_imported', as_of: null, items: [] };
  return {
    status: 'diff',
    as_of: NOW,
    items: [
      { kind: 'cost_differs', security_code: '600000.SH', name: '示例银行', ours: '9.792', broker: '9.812', diff: '-0.020', important: false, note: '红利入账已冲减我方成本；券商成本价可能未计入同期红利税补缴（示例）' },
      { kind: 'quantity_mismatch', security_code: '601001.SH', name: '演示能源', ours: '-800', broker: '0', diff: '-800', important: true, note: '卖出 800 股前没有买入记录（示例）' },
      { kind: 'missing_in_ours', security_code: '300001.SZ', name: '演示电子', ours: null, broker: '300', diff: '-300', important: true, note: '券商快照有持仓，我方没有对应成交（示例）' },
      { kind: 'missing_in_broker', security_code: '600002.SH', name: '演示医药', ours: '400', broker: null, diff: '400', important: false, note: '我方有持仓，券商快照中没有（示例）' },
      { kind: 'cash_gap', security_code: null, name: null, ours: '52310.40', broker: '52610.40', diff: '-300.00', important: false, note: '资金余额相差 300.00 元（示例）' },
      { kind: 'cash_chain_break', security_code: null, name: null, ours: null, broker: null, diff: '300.00', important: false, note: '2026-10-29 资金余额链断开（示例）' },
    ],
  };
}
export type { ImportKind };
