/**
 * 示例：/admin/ingest/status 的 alerts[]（契约 §7.9，v0.2.9 内 T-B47 裁定③ + #31 ②–④；阈值取 plan 6.1 `admin_alerts` 初值，问题 78）。
 * 真实口径由后端计算；本 mock 只按响应中已有字段复刻能复刻的部分，示例时刻按盘中处理。
 * #31：每个 key 最多一条（按证书聚合；同一 key 同时满足两级只出 critical）；key/level/message 用契约固定表；
 * 排序 critical 在前，同级按固定 key 顺序（errors.* 按 upstream_code 升序，freshness.* 按 freshness 固定顺序）。
 * v0.2.9 #38：响应顶层有 heartbeat（ingest_health，不返回心跳时间）；mock 用 setMockIngestHeartbeat() 写这个字段（示例场景），
 *   leader 不为 null 且 heartbeat 为 stale/unknown 时出 heartbeat 告警，paused 不出。
 * v0.2.9 #39（§7.9 ⑥ ⑧）：另有 5 个 master.* 键，message 用契约固定表；同级排序 #31 ② 的键在前、master.* 在后，
 *   master.* 之间按 ⑥ 所列顺序。mock 用 setMockMasterAlerts() 指定哪些键出现、什么级别（示例场景）。
 */
import { INGEST_DATASETS, type AdminIngestStatus, type IngestAlert, type IngestDataset } from '../api/adminTypes';
import type { IngestHealth } from '../api/enums';
import { INGEST_DATASET_NAME } from '../i18n/ingestLabels';

export const ADMIN_ALERTS = {
  queue_p0_warning_s: 60,
  queue_p0_critical_s: 300,
  queue_p1_warning_s: 3600,
  budget_warning_ratio: 0.9,
  ip_limit_critical_count: 1,
  upstream_error_warning_count: 20,
  licence_days_left_warning: 14,
} as const;

/** #31 ② 固定文案（只允许 {upstream_code}、{dataset_name} 两个占位） */
export const INGEST_ALERT_TEXT = {
  leader: '没有采集主实例（无未过期的租约）',
  heartbeat: '采集主实例心跳超时',
  'queue.p0_intraday': '盘中队列（P0）等待过久',
  'queue.p1_daily': '日频队列（P1）等待过久',
  budget: '近 1 分钟调用量接近上限',
  ip_limit: '24 小时内出现 IP 受限',
  errors: (code: string) => `上游错误码 ${code} 24 小时内次数过多`,
  'freshness.quotes': '实时行情过期或不可用',
  freshness: (d: IngestDataset) => `${INGEST_DATASET_NAME[d]}已过期`,
  'licence.invalid': '有证书无效',
  'licence.ip_limited': '有证书 IP 受限',
  'licence.expired': '有证书已过期',
  'licence.quota_exceeded': '有证书今日额度已用完',
  'licence.expiring': '有证书即将到期',
  // v0.2.9 #39：§7.9 ⑥ 新文案（不带代码、数量或用户名）
  'master.snapshot_rejected': '证券名单更新失败，暂时沿用上一版',
  'master.vendor_stale_listed': '行情源仍列着已退市的证券',
  'master.vendor_unknown': '行情源出现交易所名单里没有的证券，暂不收录',
  'master.quote_missing': '部分证券在行情源中暂时没有数据',
  'master.field_mismatch': '部分证券的名称或上市信息与其他来源不一致，待核对',
} as const;

/** §7.9 ⑥ 所列顺序（#39 ⑧：master.* 之间按此排） */
export const MASTER_KEYS = ['master.snapshot_rejected', 'master.vendor_stale_listed', 'master.vendor_unknown', 'master.quote_missing', 'master.field_mismatch'] as const;

/** #31 ② 的 key 顺序（同级排序用；errors.* / freshness.* 各占一个位置） */
const KEY_ORDER = ['leader', 'heartbeat', 'queue.p0_intraday', 'queue.p1_daily', 'budget', 'ip_limit', 'errors', 'freshness',
  'licence.invalid', 'licence.ip_limited', 'licence.expired', 'licence.quota_exceeded', 'licence.expiring',
  ...MASTER_KEYS];

/** #38：响应的 heartbeat 字段（示例场景，默认 ok） */
let heartbeat: IngestHealth = 'ok';
export const mockIngestHeartbeat = () => heartbeat;
export const setMockIngestHeartbeat = (v: IngestHealth) => { heartbeat = v; };

/** #39：master.* 各键在示例场景中的级别（缺省 = 不出）；snapshot_rejected 可为 warning/critical，其余只有 warning */
export type MasterAlertKey = (typeof MASTER_KEYS)[number];
export type MockMasterAlerts = Partial<Record<MasterAlertKey, IngestAlert['level']>>;
let masterAlerts: MockMasterAlerts = {};
export const mockMasterAlerts = () => masterAlerts;
export const setMockMasterAlerts = (v: MockMasterAlerts) => { masterAlerts = v; };
export const resetIngestAlertsMock = () => { heartbeat = 'ok'; masterAlerts = {}; };

function rank(a: IngestAlert): [number, number, string | number] {
  const [head, ...rest] = a.key.split('.');
  const tail = rest.join('.');
  const group = head === 'errors' || head === 'freshness' ? head : a.key;
  const sub = head === 'freshness' ? INGEST_DATASETS.indexOf(tail as IngestDataset) : head === 'errors' ? tail : 0;
  return [a.level === 'critical' ? 0 : 1, KEY_ORDER.indexOf(group), sub];
}

export function ingestAlerts(d: Omit<AdminIngestStatus, 'alerts'>, master: MockMasterAlerts = masterAlerts): IngestAlert[] {
  const byKey = new Map<string, IngestAlert>();
  const add = (level: IngestAlert['level'], key: string, message: string) => {
    const prev = byKey.get(key);
    if (!prev || (prev.level === 'warning' && level === 'critical')) byKey.set(key, { level, key, message });
  };
  if (!d.leader) add('critical', 'leader', INGEST_ALERT_TEXT.leader);
  else if (d.heartbeat === 'stale' || d.heartbeat === 'unknown') add('critical', 'heartbeat', INGEST_ALERT_TEXT.heartbeat);
  for (const q of d.queues) {
    if (q.priority === 'p0_intraday' && q.oldest_age_s > ADMIN_ALERTS.queue_p0_critical_s) add('critical', 'queue.p0_intraday', INGEST_ALERT_TEXT['queue.p0_intraday']);
    else if (q.priority === 'p0_intraday' && q.oldest_age_s > ADMIN_ALERTS.queue_p0_warning_s) add('warning', 'queue.p0_intraday', INGEST_ALERT_TEXT['queue.p0_intraday']);
    else if (q.priority === 'p1_daily' && q.oldest_age_s > ADMIN_ALERTS.queue_p1_warning_s) add('warning', 'queue.p1_daily', INGEST_ALERT_TEXT['queue.p1_daily']);
  }
  if (d.budget.per_minute_limit > 0 && d.budget.used_last_minute >= ADMIN_ALERTS.budget_warning_ratio * d.budget.per_minute_limit) {
    add('warning', 'budget', INGEST_ALERT_TEXT.budget);
  }
  if (d.ip_limit_alerts_24h >= ADMIN_ALERTS.ip_limit_critical_count) add('critical', 'ip_limit', INGEST_ALERT_TEXT.ip_limit);
  for (const e of d.errors_24h) {
    if (e.count >= ADMIN_ALERTS.upstream_error_warning_count) add('warning', `errors.${e.upstream_code}`, INGEST_ALERT_TEXT.errors(e.upstream_code));
  }
  for (const f of d.freshness) {
    if (f.dataset === 'quotes' && (f.data_status === 'stale' || f.data_status === 'unavailable')) add('critical', 'freshness.quotes', INGEST_ALERT_TEXT['freshness.quotes']);
    else if (f.dataset !== 'quotes' && f.data_status === 'stale') add('warning', `freshness.${f.dataset}`, INGEST_ALERT_TEXT.freshness(f.dataset));
  }
  for (const l of d.licences) {
    if (l.status === 'invalid' || l.status === 'ip_limited' || l.status === 'expired' || l.status === 'quota_exceeded') {
      const key = `licence.${l.status}` as const;
      add(l.status === 'invalid' || l.status === 'ip_limited' ? 'critical' : 'warning', key, INGEST_ALERT_TEXT[key]);
    }
    // #31 ②：状态不是 expired 且 0 ≤ days_left ≤ 14 → licence.expiring（不再用 licence.<status>）
    if (l.status !== 'expired' && l.days_left !== null && l.days_left >= 0 && l.days_left <= ADMIN_ALERTS.licence_days_left_warning) {
      add('warning', 'licence.expiring', INGEST_ALERT_TEXT['licence.expiring']);
    }
  }
  for (const k of MASTER_KEYS) {
    const lv = master[k];
    if (lv) add(k === 'master.snapshot_rejected' ? lv : 'warning', k, INGEST_ALERT_TEXT[k]);
  }
  return [...byKey.values()].sort((a, b) => {
    const [x, y] = [rank(a), rank(b)];
    return x[0] - y[0] || x[1] - y[1] || (typeof x[2] === 'number' && typeof y[2] === 'number' ? x[2] - y[2] : String(x[2]).localeCompare(String(y[2])));
  });
}
