/**
 * T-F02 / T-F02a / T-F04 / T-F05 用到的类型：契约 v0.2.5 §5.1 ImportFinding、§7.1 认证与账号、§7.2 账户/成交/导入、§7.9 管理端。
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
export interface RegisterRequest {
  /** 4–32 位，^[a-z0-9_]{4,32}$，前端输入即转小写（v0.2.3 #24） */
  username: string;
  /** 10–128 位 */
  password: string;
  /** 1–32 */
  display_name: string;
  invite_code: string | null;
  /** ≤200 字（v0.2.4 #2）；invite 模式必填 */
  apply_note: string | null;
  // v0.2.5：agreements 已删除（提交注册即视为已知悉固定免责提示）
}

export interface RegisterResponse { id: Uuid; username: string; status: 'pending' }
/** 403 ACCOUNT_NOT_APPROVED 的 details（plan 3.6：rejected 附驳回理由） */
export interface NotApprovedDetails { status: Exclude<AccountStatus, 'approved'>; reason?: string | null }

export type Effort = 'low' | 'medium' | 'high';
export type Experience = 'novice' | 'intermediate' | 'advanced';
/**
 * PUT /me/profile 请求体（契约 §7.1，v0.2.5 #6）：全部由用户自报；effort / risk_tolerance / experience 为 null 表示未填写
 * （分类器不封顶、不提示）；max_single_position_pct 为 5–50、最多 2 位小数。
 */
export interface ProfileInput {
  horizon_pref: Horizon[];
  effort: Effort | null;
  risk_tolerance: number | null;
  experience: Experience | null;
  max_single_position_pct: Decimal;
}
/** GET/PUT /me/profile 响应；还没有画像时 GET 返回 404 NOT_FOUND */
export interface Profile extends ProfileInput { version_no: number }

// ---------- §7.9 管理端：用户审核 ----------
/** GET /admin/users 列表元素（v0.2.4 #12）。`same_ip_flag` 由服务端按 `admin.same_ip_highlight_threshold` 计算，只作提示 */
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
  same_ip_flag: boolean;
  last_login_at: DateTime | null;
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
/** GET /imports 列表元素 ImportBatchSummary（v0.2.4 #12；评审 s4）。详情字段一律走 GET /imports/{batch_id} */
export interface ImportBatchSummary {
  batch_id: Uuid;
  account_id: Uuid;
  kind: ImportKind;
  status: ImportStatus;
  parser_id: string | null;
  stats: ImportStats;
  created_at: DateTime;
  committed_at: DateTime | null;
  reverted_at: DateTime | null;
}
/** GET /imports/{batch_id} */
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

/** GET /trades 列表元素 Trade（v0.2.4 #12）。导入撤销造成的作废 `void_reason` 为 `batch_reverted:{batch_id}` */
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
  net_amount: Decimal | null;
  source: 'import' | 'manual';
  batch_id: Uuid | null;
  voided: boolean;
  void_reason: string | null;
  voided_at: DateTime | null;
  corrects_trade_id: Uuid | null;
  created_at: DateTime;
}
/** POST /trades 手工录入请求体 TradeCreate（v0.2.4 #12）；corrects_trade_id 非空时 reason 必填 */
export interface TradeCreate {
  account_id: Uuid;
  trade_date: DateStr;
  trade_time: string | null;
  security_code: string;
  side: TradeSide;
  qty: Decimal;
  price: Decimal;
  fee_total: Decimal | null;
  corrects_trade_id?: Uuid | null;
  reason?: string | null;
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
