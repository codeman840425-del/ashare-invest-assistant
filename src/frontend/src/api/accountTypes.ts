/**
 * T-F02 / T-F02a / T-F04 用到的类型：契约 v0.2.3 §5.1 ImportFinding、§7.1 认证与账号、§7.2 账户/成交/导入、§7.9 管理端。
 * 契约没写清结构的地方按前端判断补齐，并标注 `// [待契约确认]`（清单见 reports/T-F02.md「遗留问题」）。
 */
import type {
  AccountStatus, DedupStatus, Horizon, ImportRowStatus, ImportScope, ImportSeverity, ImportStatus,
  ReconciliationItemKind, ReconciliationStatus, Role, TradeSide,
} from './enums';
import type { DateStr, DateTime, Decimal, Me, Uuid } from './types';

// ---------- §7.1 认证 ----------
export interface LoginRequest { username: string; password: string }
export interface LoginResponse { user: Me; csrf_token: string }
/** 契约 §7.1：agreements 取值未定义，前端按 /me/consents 的 key 填写 // [待契约确认] */
export type ConsentKey = 'signal_risk_disclosure' | 'privacy' | 'terms';
export interface RegisterRequest {
  username: string;
  password: string;
  display_name: string;
  invite_code: string | null;
  agreements: ConsentKey[];
}
export interface RegisterResponse { id: Uuid; username: string; status: 'pending' }
/** 403 ACCOUNT_NOT_APPROVED 的 details（plan 3.6：rejected 附驳回理由） */
export interface NotApprovedDetails { status: Exclude<AccountStatus, 'approved'>; reason?: string | null }

export type Effort = 'low' | 'medium' | 'high';
export type Experience = 'novice' | 'intermediate' | 'advanced';
/** PUT /me/profile 请求体（契约 §7.1，T-A02：画像表单只用这五个契约字段） */
export interface ProfileInput {
  horizon_pref: Horizon[];
  effort: Effort;
  risk_tolerance: number;
  experience: Experience;
  max_single_position_pct: Decimal;
}
/** GET/PUT /me/profile 响应：`{version_no, ...}`；还没有画像时 GET 返回 404 NOT_FOUND // [待契约确认] */
export interface Profile extends ProfileInput { version_no: number }

export interface ConsentRequest { key: ConsentKey; version: string }
export interface RiskAnswer { q_id: string; choice: string }
export interface RiskAssessmentRequest { answers: RiskAnswer[] }
export interface RiskAssessmentResult { level: number; assessed_at: DateTime }

// ---------- §7.9 管理端：用户审核 ----------
/**
 * GET /admin/users 列表元素。契约只写了“审核和停用账号”，未给结构；字段取自 plan 3.6 管理员能力
 * （用户名、申请说明、注册时间、注册 IP 属地粗粒度、同 IP 注册数）与 users 表。 // [待契约确认]
 */
export interface AdminUser {
  id: Uuid;
  username: string;
  display_name: string;
  role: Role;
  status: AccountStatus;
  apply_note: string | null;
  created_at: DateTime;
  reviewed_at: DateTime | null;
  review_reason: string | null;
  register_ip_region: string | null;
  same_ip_registrations: number;
}
export interface AdminUserPatch { status: 'approved' | 'rejected' | 'disabled'; reason: string | null }

// ---------- §7.2 账户、成交、导入 ----------
export interface BrokerAccount {
  id: Uuid;
  broker_name: string;
  alias: string;
  shareholder_code_masked: string | null;
  fund_account_masked: string | null;
  created_at: DateTime;
}
export interface BrokerAccountCreate { alias: string; broker_name: string }

export type ImportKind = 'trades' | 'positions';

export interface ImportFindingResolution { choice: string; reason: string | null; by: Uuid; at: DateTime }
/** §5.1 ImportFinding */
export interface ImportFinding {
  id: string;
  code: string;
  severity: ImportSeverity;
  scope: ImportScope;
  row_no: number | null;
  field: string | null;
  message: string;
  params: Record<string, unknown>;
  needs_action: boolean;
  resolution_choices: string[];
  default_resolution: string | null;
  resolution: ImportFindingResolution | null;
}
export interface ImportUploadResponse { batch_id: Uuid; status: 'uploaded'; file_findings: ImportFinding[] }
export interface ImportStats {
  rows: number;
  ok: number;
  warning: number;
  error: number;
  skipped: number;
  new: number;
  duplicate_in_db: number;
  duplicate_in_file: number;
  possible_duplicate_of_manual: number;
  needs_action_open: number;
}
/** GET /imports/{batch_id}（GET /imports 列表元素沿用同一结构 // [待契约确认]） */
export interface ImportBatch {
  batch_id: Uuid;
  account_id: Uuid;
  kind: ImportKind;
  status: ImportStatus;
  parser_id: string | null;
  parser_version: string | null;
  detected_encoding: string | null;
  encoding_override: string | null;
  encoding_confidence: number | null;
  format_score: number | null;
  detected_columns: string[];
  mapping: Record<string, string> | null;
  snapshot_as_of: DateTime | null;
  file_findings: ImportFinding[];
  stats: ImportStats;
  created_at: DateTime;
  committed_at: DateTime | null;
  reverted_at: DateTime | null;
}
export interface ImportRowNormalized {
  trade_date: DateStr;
  trade_time: string | null;
  security_code: string;
  name: string;
  side: TradeSide | null;
  qty: Decimal;
  price: Decimal;
  amount: Decimal;
  fee_total: Decimal | null;
  net_amount: Decimal | null;
  biz_type_raw: string;
}
export interface ImportRow {
  row_no: number;
  status: ImportRowStatus;
  kind: 'trade' | 'event' | 'ignored';
  dedup_status: DedupStatus | null;
  findings: ImportFinding[];
  raw_masked: string;
  normalized: ImportRowNormalized | null;
}
export interface ImportOptions {
  encoding_override: string | null;
  parser_id: string | null;
  mapping: Record<string, string> | null;
  snapshot_as_of: DateTime | null;
}
export interface ImportConfirmRequest { mode: 'all' | 'valid_rows_only'; acknowledge_warnings: boolean }
export interface ImportConfirmResponse {
  status: 'committed';
  written: { trades: number; events: number; snapshot_positions: number };
  reconciliation: { status: ReconciliationStatus; diff_count: number } | null;
}
export interface ResolveFindingRequest { choice: string; reason: string | null }

/**
 * GET /trades 列表元素。契约只写“成交列表和手工录入；原记录不可修改，更正时写更正记录”，未给结构；
 * 字段取自 plan 3.3 trades 表与 §7.2 预览行 normalized。 // [待契约确认]
 */
export interface Trade {
  id: Uuid;
  account_id: Uuid;
  trade_date: DateStr;
  trade_time: string | null;
  security_code: string;
  name: string;
  side: TradeSide;
  qty: Decimal;
  price: Decimal;
  amount: Decimal;
  fee_total: Decimal | null;
  source: 'import' | 'manual';
  batch_id: Uuid | null;
  voided: boolean;
  created_at: DateTime;
}
/** POST /trades 手工录入请求体 // [待契约确认] */
export interface TradeCreate {
  account_id: Uuid;
  trade_date: DateStr;
  trade_time: string | null;
  security_code: string;
  side: TradeSide;
  qty: Decimal;
  price: Decimal;
  fee_total: Decimal | null;
}

/** GET /reconciliation?account_id= */
export interface ReconciliationItem {
  kind: ReconciliationItemKind;
  security_code: string | null;
  name: string | null;
  ours: Decimal | null;
  broker: Decimal | null;
  diff: Decimal | null;
  important: boolean;
  note: string;
}
export interface Reconciliation { status: ReconciliationStatus; as_of: DateTime | null; items: ReconciliationItem[] }
