/**
 * T-F22：本人数据证书（契约 v0.2.6 §5.1 DataLicenceStatus、§7.1 /me/data-licence*；plan 2.1B）。
 * 任何响应都**不含证书值或其任何片段**；前端也不保存、不回显证书值。
 */
import type { DataLicenceState, DataLicenceTier } from './enums';
import type { DateStr, DateTime, Uuid } from './types';

export type DataLicenceErrorCode = '101' | '102' | '103' | '429' | '503' | 'network' | 'http_5xx';

export interface DataLicenceStatus {
  status: DataLicenceState;
  tier: DataLicenceTier | null;
  has_quant_pro: boolean | null;
  /** 用户填写 */
  expires_on: DateStr | null;
  days_to_expiry: number | null;
  set_at: DateTime | null;
  last_verified_at: DateTime | null;
  last_error_code: DataLicenceErrorCode | null;
  last_error_at: DateTime | null;
  paused_until: DateTime | null;
}

/** PUT /me/data-licence → 202 DataLicenceStatus（status: pending_verification） */
export interface DataLicencePut {
  licence: string;
  tier: DataLicenceTier;
  has_quant_pro: boolean;
  expires_on: DateStr | null;
}
/** PATCH /me/data-licence：只改元数据 */
export type DataLicencePatch = Partial<Omit<DataLicencePut, 'licence'>>;
/** POST /me/data-licence/test → 202 */
export interface DataLicenceTestResponse { verification_id: Uuid }

/**
 * 证书格式（契约 §7.1：去首尾空白后 16–64 位，^[A-Za-z0-9-]+$，【待核实 T-B05】）。
 * 前端只做同样的预检；提示文字不包含输入值。
 */
export const LICENCE_RE = /^[A-Za-z0-9-]{16,64}$/;
