import { Link, useSearchParams } from 'react-router';
import { Alert, Segmented, Select, Space, Table, Tag, Tooltip } from 'antd';
import { useAdminSecurityReconciliation, type ReconFilter } from '../../api/adminQueries';
import type { SecurityReconciliationDiff } from '../../api/adminTypes';
import { ENUMS, type SecurityReconciliationKind, type SecurityReconciliationSource } from '../../api/enums';
import { parseReconFilter } from '../../lib/reconFilter';
import { CursorPager } from '../../components/CursorPager';
import { ErrorBox } from '../../components/common';
import { RECON_KIND, RECON_SOURCE, reconFieldText, reconKindHint, reconKindText, reconSourceText } from '../../i18n/reconLabels';

const PAGE_SIZE = 50;
const KINDS = ENUMS.security_reconciliation_kind;
const SOURCES = ENUMS.security_reconciliation_source;
const valueText = (v: string | null) => (v === null ? '（空）' : v);

/**
 * 证券主数据对账差异（T-F25；契约 v0.2.9 内 T-A04 #33 ③④，§7.9 GET /admin/securities/reconciliation）。
 * 只读：按服务端顺序（最近出现日倒序）列出，§1.2 游标“加载更多”；筛选只用契约给的 status / kind / source。
 * 页面不显示证书值、行情数值或快照内容；quote_conflict 只有代码与天数。
 * 前端路由 /admin/securities/reconciliation 与接口同名（前端自定）。
 */
export function AdminSecurityReconciliationPage() {
  const [sp, setSp] = useSearchParams();
  const { filter, ignored } = parseReconFilter(sp);
  const list = useAdminSecurityReconciliation(filter, PAGE_SIZE);

  const update = (next: Partial<ReconFilter>) => {
    const f = { ...filter, ...next };
    const out = new URLSearchParams();
    if (f.status !== 'open') out.set('status', f.status);
    if (f.kinds.length) out.set('kind', f.kinds.join(','));
    if (f.source) out.set('source', f.source);
    setSp(out, { replace: true });
  };

  const columns = [
    { title: '最近出现', dataIndex: 'last_seen_on', key: 'last', width: 110, render: (v: string) => <span className="mono">{v}</span> },
    {
      title: '差异类型', key: 'kind', width: 200,
      render: (_: unknown, r: SecurityReconciliationDiff) => {
        const hint = reconKindHint(r.kind);
        const tag = <Tag data-testid={`recon-kind-${r.id}`}>{reconKindText(r.kind)}</Tag>;
        return hint ? <Tooltip title={hint}>{tag}</Tooltip> : tag;
      },
    },
    {
      title: '证券', key: 'sec',
      render: (_: unknown, r: SecurityReconciliationDiff) => (
        <span data-testid={`recon-sec-${r.id}`}>
          <span className="mono">{r.security_code}</span>{' '}
          {r.name ?? <span className="muted small">主数据无此代码</span>}
          {r.source_name !== null && r.source_name !== r.name ? <div className="muted small">对方简称：{r.source_name}</div> : null}
        </span>
      ),
    },
    {
      title: '来源', key: 'src', width: 190,
      render: (_: unknown, r: SecurityReconciliationDiff) => (
        <span data-testid={`recon-src-${r.id}`}>
          {reconSourceText(r.source)}
          {r.licence_owner ? (
            <div className="muted small">
              证书：<Link to={`/admin/data-licences?user=${encodeURIComponent(r.licence_owner.user_id)}`}><span className="mono">{r.licence_owner.username}</span></Link>
            </div>
          ) : null}
        </span>
      ),
    },
    {
      title: '差异内容', key: 'diff',
      render: (_: unknown, r: SecurityReconciliationDiff) => {
        if (r.field === null && r.master_value === null && r.source_value === null) return <span className="muted">—</span>;
        return (
          <span data-testid={`recon-diff-${r.id}`}>
            {r.field !== null ? <span>{reconFieldText(r.field)}：</span> : null}
            主数据 {valueText(r.master_value)} ／ 对方 {valueText(r.source_value)}
          </span>
        );
      },
    },
    {
      title: '持续', key: 'seen', width: 190,
      render: (_: unknown, r: SecurityReconciliationDiff) => (
        <span data-testid={`recon-seen-${r.id}`}>
          {r.seen_days} 个工作日
          <div className="muted small mono">{r.first_seen_on} 起</div>
        </span>
      ),
    },
    {
      title: '状态', key: 'status', width: 130,
      render: (_: unknown, r: SecurityReconciliationDiff) => (r.status === 'open'
        ? <Tag color="orange" data-testid={`recon-status-${r.id}`}>未关闭</Tag>
        : (
          <span data-testid={`recon-status-${r.id}`}>
            <Tag>已关闭</Tag>
            {r.resolved_on ? <div className="muted small mono">{r.resolved_on}</div> : null}
          </span>
        )),
    },
  ];

  return (
    <div className="page-scroll page" data-testid="admin-securities-recon">
      <h2 className="page-title">证券主数据对账（管理）</h2>
      <p className="muted small">
        交易所名单与麦蕊、巨潮、AKShare 之间的差异，只读。差异在下一次同类对账中消失即关闭；“持续”按工作日计。
        不显示证书值、行情数值或快照内容。相关告警见 <Link to="/admin/ingest">采集状态（管理）</Link>。
      </p>
      <Space wrap style={{ marginBottom: 12 }}>
        <Segmented
          value={filter.status}
          onChange={(v) => update({ status: v as ReconFilter['status'] })}
          options={[{ value: 'open', label: '未关闭' }, { value: 'resolved', label: '已关闭' }, { value: 'all', label: '全部' }]}
          data-testid="recon-status"
        />
        <Select
          mode="multiple"
          allowClear
          placeholder="差异类型（全部）"
          style={{ minWidth: 260 }}
          value={filter.kinds}
          onChange={(v: SecurityReconciliationKind[]) => update({ kinds: v })}
          options={KINDS.map((k) => ({ value: k, label: RECON_KIND[k].text }))}
          data-testid="recon-kind"
        />
        <Select
          allowClear
          placeholder="来源（全部）"
          style={{ minWidth: 160 }}
          value={filter.source ?? undefined}
          onChange={(v: SecurityReconciliationSource | undefined) => update({ source: v ?? null })}
          options={SOURCES.map((s) => ({ value: s, label: RECON_SOURCE[s] }))}
          data-testid="recon-source"
        />
      </Space>
      {ignored.length ? (
        <Alert type="warning" showIcon style={{ marginBottom: 8 }} data-testid="recon-ignored"
          title={`地址里有不认识的筛选值，已忽略：${ignored.join('，')}`} />
      ) : null}
      {list.isError ? <ErrorBox error={list.error} /> : null}
      <Table<SecurityReconciliationDiff>
        size="small"
        rowKey="id"
        loading={list.isPending}
        dataSource={list.items}
        pagination={false}
        columns={columns}
        locale={{ emptyText: filter.status === 'open' ? '没有未关闭的差异' : '没有符合条件的差异' }}
        data-testid="recon-table"
      />
      <CursorPager query={list} loaded={list.items.length} unit="条差异" testId="recon-pager" />
    </div>
  );
}
