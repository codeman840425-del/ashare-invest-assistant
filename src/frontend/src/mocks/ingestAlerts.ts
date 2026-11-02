/**
 * 示例：/admin/ingest/status 的 alerts[]（契约 §7.9，v0.2.9 内 T-B47 裁定③；阈值取 plan 6.1 `admin_alerts` 初值，问题 78）。
 * 真实口径由后端计算；本 mock 只按响应中已有字段复刻能复刻的部分，示例时刻按盘中处理，心跳不建模（只看 leader 是否为 null）。
 * message 为示例文案（契约只规定“固定中文文案”，未给原文），不含证书值、IP 全文或管理员理由。
 */
import type { AdminIngestStatus, IngestAlert, IngestDataset } from '../api/adminTypes';

export const ADMIN_ALERTS = {
  queue_p0_warning_s: 60,
  queue_p0_critical_s: 300,
  queue_p1_warning_s: 3600,
  budget_warning_ratio: 0.9,
  ip_limit_critical_count: 1,
  upstream_error_warning_count: 20,
  licence_days_left_warning: 14,
} as const;

const DATASET_TEXT: Record<IngestDataset, string> = {
  quotes: '实时行情', minute_bars: '分钟线', daily_bars: '日线', financials: '财务数据', announcements: '公告', security_master: '证券主数据',
};

export function ingestAlerts(d: Omit<AdminIngestStatus, 'alerts'>): IngestAlert[] {
  const out: IngestAlert[] = [];
  const add = (level: IngestAlert['level'], key: string, message: string) => {
    if (!out.some((a) => a.key === key)) out.push({ level, key, message });
  };
  if (!d.leader) add('critical', 'leader', '没有采集主实例（示例）');
  for (const q of d.queues) {
    if (q.priority === 'p0_intraday' && q.oldest_age_s > ADMIN_ALERTS.queue_p0_critical_s) add('critical', 'queue.p0_intraday', '盘中队列等待超过 300 秒（示例）');
    else if (q.priority === 'p0_intraday' && q.oldest_age_s > ADMIN_ALERTS.queue_p0_warning_s) add('warning', 'queue.p0_intraday', '盘中队列等待超过 60 秒（示例）');
    else if (q.priority === 'p1_daily' && q.oldest_age_s > ADMIN_ALERTS.queue_p1_warning_s) add('warning', 'queue.p1_daily', '日频队列等待超过 3600 秒（示例）');
  }
  if (d.budget.per_minute_limit > 0 && d.budget.used_last_minute >= ADMIN_ALERTS.budget_warning_ratio * d.budget.per_minute_limit) {
    add('warning', 'budget', '近 1 分钟调用量达到上限的 90%（示例）');
  }
  if (d.ip_limit_alerts_24h >= ADMIN_ALERTS.ip_limit_critical_count) add('critical', 'ip_limit', '24 小时内出现 IP 受限（示例）');
  for (const e of d.errors_24h) {
    if (e.count >= ADMIN_ALERTS.upstream_error_warning_count) add('warning', `errors.${e.upstream_code}`, '单个上游错误码 24 小时内超过 20 次（示例）');
  }
  for (const f of d.freshness) {
    if (f.dataset === 'quotes' && (f.data_status === 'stale' || f.data_status === 'unavailable')) add('critical', 'freshness.quotes', '盘中实时行情过期或不可用（示例）');
    else if (f.dataset !== 'quotes' && f.data_status === 'stale') add('warning', `freshness.${f.dataset}`, `${DATASET_TEXT[f.dataset]}已过期（示例）`);
  }
  for (const l of d.licences) {
    if (l.status === 'invalid' || l.status === 'ip_limited') add('critical', `licence.${l.status}`, '有证书无效或 IP 受限（示例）');
  }
  for (const l of d.licences) {
    if (l.status === 'expired' || l.status === 'quota_exceeded') add('warning', `licence.${l.status}`, '有证书已过期或今日额度已用完（示例）');
    // 待定：days_left ≤ 14 的告警 key 契约未单列，示例按 licence.<status> 处理
    else if (l.days_left !== null && l.days_left <= ADMIN_ALERTS.licence_days_left_warning) add('warning', `licence.${l.status}`, '有证书 14 天内到期（示例）');
  }
  return out;
}
