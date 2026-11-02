/**
 * 管理端类型（契约 v0.2.8 §5.1、§7.9）。/admin/* 不进 openapi.json（v0.2.8 #15，架构师裁定），
 * 因此按契约手写，不从 openapi 生成。只含状态元数据，不含证书值或其任何片段。
 */
import type { DataLicenceState, DataLicenceTier, DataStatus, IngestHealth } from './enums';
import type { DataLicenceErrorCode, DataLicenceStatus } from './licenceTypes';

/** §5.1 IngestLicenceStatus：/admin/ingest/status 的 licences[] 元素，每张证书一行 */
export interface IngestLicenceStatus {
  licence_id: string;
  user_id: string;
  username: string;
  display_name: string;
  status: DataLicenceState;
  tier: DataLicenceTier | null;
  has_quant_pro: boolean | null;
  expires_on: string | null;
  days_left: number | null;
  calls_today: number;
  daily_limit: number | null;
  per_minute_limit: number;
  calls_last_minute: number;
  queue_depth: { p0: number; p1: number; p2: number };
  paused_until: string | null;
  last_error_code: DataLicenceErrorCode | null;
  last_error_at: string | null;
}

/** §7.9 /admin/ingest/status freshness：v0.2.9 内 T-B47 裁定固定 6 行，顺序即下列顺序 */
export const INGEST_DATASETS = ['quotes', 'minute_bars', 'daily_bars', 'financials', 'announcements', 'security_master'] as const;
export type IngestDataset = (typeof INGEST_DATASETS)[number];
/** T-B47 裁定：freshness.data_status 只取 fresh / stale / pending / unavailable（没有 partial） */
export type IngestFreshnessStatus = Exclude<DataStatus, 'partial'>;
/** T-B47 裁定：alerts[] 元素；message 是服务端的固定中文文案，前端原样显示 */
export interface IngestAlert { level: 'warning' | 'critical'; key: string; message: string }

/** §7.9 GET /admin/ingest/status（v0.2.8：删除全站 licence，改为按证书的 licences[]；v0.2.9 内 T-B47：leader 可为 null、freshness 6 行、加 alerts） */
export interface AdminIngestStatus {
  /** v0.2.9 #38：ingest 心跳状态（ingest_health，契约不为 null；判定同 /health/ready.ingest；不返回心跳时间）。
   *  前端对缺失或不认识的取值按 unknown 显示，不据此自行生成告警 */
  heartbeat: IngestHealth;
  /** 没有未过期的租约时为 null（不返回各字段为 null 的对象） */
  leader: { instance_id: string; egress_ip_masked: string | null; lease_expires_at: string } | null;
  budget: { per_minute_limit: number; used_last_minute: number };
  queues: { priority: 'p0_intraday' | 'p1_daily' | 'p2_backfill'; depth: number; oldest_age_s: number }[];
  errors_24h: { upstream_code: string; count: number }[];
  ip_limit_alerts_24h: number;
  freshness: { dataset: IngestDataset; data_as_of: string | null; data_status: IngestFreshnessStatus }[];
  licences: IngestLicenceStatus[];
  licences_truncated: boolean;
  /** 永不为 null，无告警为 [] */
  alerts: IngestAlert[];
}

/**
 * §5.1 AdminDataLicence：GET /admin/data-licences 元素（v0.2.6；v0.2.8 加 licence_id）。
 * 每位用户一行（含未设置证书的用户）；与 IngestLicenceStatus 同名字段同义。不含证书值或其任何片段。
 */
export interface AdminDataLicence extends DataLicenceStatus {
  /** v0.2.8：未设置（含管理员暂停期间用户删除了证书）为 null */
  licence_id: string | null;
  user_id: string;
  username: string;
  display_name: string;
  per_minute_limit: number;
  calls_last_minute: number;
  calls_today: number;
  queue_depth: { p0: number; p1: number; p2: number };
}

/** §7.9 POST /admin/data-licences/{user_id}/pause · /resume 请求体 → 204 */
export interface AdminLicenceAction { reason: string }
export const ADMIN_REASON_MAX = 200;
