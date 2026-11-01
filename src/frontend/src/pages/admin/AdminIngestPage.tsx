import { Alert, Card, Descriptions, Space, Table, Tag } from 'antd';
import { useAdminIngestStatus } from '../../api/adminQueries';
import type { IngestLicenceStatus } from '../../api/adminTypes';
import { ErrorBox } from '../../components/common';
import { DATA_STATUS } from '../../i18n/labels';
import { LICENCE_ERROR, LICENCE_STATUS, LICENCE_TIER } from '../../i18n/licenceLabels';
import { fmtTime } from '../../lib/format';

const PRIORITY: Record<string, string> = { p0_intraday: 'P0 盘中', p1_daily: 'P1 日频', p2_backfill: 'P2 回补' };
const dash = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : String(v));

/**
 * 管理端采集状态（契约 v0.2.8 #1、§7.9 GET /admin/ingest/status）：顶层为全部证书合计，下表每张证书一行。
 * 行顺序直接用服务端排序（异常状态在前）；页面不显示、也拿不到证书值。
 */
export function AdminIngestPage() {
  const q = useAdminIngestStatus();
  if (q.isPending) return <div className="page" data-testid="admin-ingest">加载中…</div>;
  if (q.isError) return <div className="page" data-testid="admin-ingest"><ErrorBox error={q.error} /></div>;
  const d = q.data;
  const columns = [
    { title: '用户', key: 'user', render: (_: unknown, r: IngestLicenceStatus) => <span>{r.display_name}<span className="muted small">（{r.username}）</span></span> },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (s: IngestLicenceStatus['status']) => <Tag color={LICENCE_STATUS[s].color} data-testid={`ingest-status-${s}`}>{LICENCE_STATUS[s].text}</Tag>,
    },
    { title: '档位', key: 'tier', render: (_: unknown, r: IngestLicenceStatus) => <span>{r.tier ? LICENCE_TIER[r.tier] : '—'}{r.has_quant_pro ? <Tag style={{ marginLeft: 4 }}>量化Pro</Tag> : null}</span> },
    { title: '到期', key: 'exp', render: (_: unknown, r: IngestLicenceStatus) => (r.expires_on ? `${r.expires_on}（剩 ${r.days_left} 天）` : '未填') },
    { title: '今日调用', key: 'today', align: 'right' as const, render: (_: unknown, r: IngestLicenceStatus) => `${r.calls_today}${r.daily_limit !== null ? ` / ${r.daily_limit}` : ''}` },
    { title: '近 1 分钟 / 上限', key: 'min', align: 'right' as const, render: (_: unknown, r: IngestLicenceStatus) => `${r.calls_last_minute} / ${r.per_minute_limit}` },
    { title: '队列 P0/P1/P2', key: 'queue', align: 'right' as const, render: (_: unknown, r: IngestLicenceStatus) => `${r.queue_depth.p0} / ${r.queue_depth.p1} / ${r.queue_depth.p2}` },
    { title: '熔断至', dataIndex: 'paused_until', key: 'pu', render: (v: string | null) => (v ? fmtTime(v) : '—') },
    {
      title: '最近错误', key: 'err',
      render: (_: unknown, r: IngestLicenceStatus) => (r.last_error_code ? <span>{LICENCE_ERROR[r.last_error_code]}{r.last_error_at ? <span className="muted small">（{fmtTime(r.last_error_at)}）</span> : null}</span> : '—'),
    },
  ];
  return (
    <div className="page" data-testid="admin-ingest">
      <h2>采集状态（管理）</h2>
      <Space orientation="vertical" style={{ width: '100%' }} size={12}>
        <Card size="small" title="全部证书合计">
          <Descriptions size="small" column={3}>
            <Descriptions.Item label="采集主实例">{d.leader ? `${d.leader.instance_id}（出口 ${d.leader.egress_ip_masked}，租约到 ${fmtTime(d.leader.lease_expires_at)}）` : '无'}</Descriptions.Item>
            <Descriptions.Item label="近 1 分钟调用 / 上限">{d.budget.used_last_minute} / {d.budget.per_minute_limit}</Descriptions.Item>
            <Descriptions.Item label="24 小时 IP 受限告警">{d.ip_limit_alerts_24h}</Descriptions.Item>
            <Descriptions.Item label="队列">{d.queues.map((x) => `${PRIORITY[x.priority] ?? x.priority} ${x.depth}（最久 ${x.oldest_age_s} 秒）`).join('；')}</Descriptions.Item>
            <Descriptions.Item label="24 小时上游错误">{d.errors_24h.length ? d.errors_24h.map((x) => `${x.upstream_code} × ${x.count}`).join('；') : '无'}</Descriptions.Item>
            <Descriptions.Item label="数据新鲜度">
              {d.freshness.map((f) => <Tag key={f.dataset} color={DATA_STATUS[f.data_status].color}>{f.dataset} {dash(f.data_as_of)} {DATA_STATUS[f.data_status].text}</Tag>)}
            </Descriptions.Item>
          </Descriptions>
        </Card>
        <Card size="small" title={`按证书（${d.licences.length} 张；未设置证书的用户不列出）`}>
          {d.licences_truncated ? (
            <Alert type="info" showIcon data-testid="ingest-truncated" style={{ marginBottom: 8 }} title="只显示前 500 张证书" description="完整列表见管理端证书列表（/admin/data-licences）。" />
          ) : null}
          <Table<IngestLicenceStatus> rowKey="licence_id" size="small" pagination={false} dataSource={d.licences} columns={columns} data-testid="ingest-licences" />
        </Card>
      </Space>
    </div>
  );
}
