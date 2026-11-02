import { Input, Select, Space, Table, Tag } from 'antd';
import { Link, useSearchParams } from 'react-router';
import { ENUMS, type PlanDraftStatus } from '../../api/enums';
import { usePlanDrafts, type PlanDraftFilter } from '../../api/planQueries';
import type { PlanDraft } from '../../api/planTypes';
import { CursorPager } from '../../components/CursorPager';
import { ActionBadge, ErrorBox } from '../../components/common';
import { CardDisclaimer } from '../../components/RiskDisclosure';
import { PLAN_DRAFT_STATUS } from '../../i18n/labels';
import { fmtNum, fmtTime } from '../../lib/format';
import { parseStatuses } from '../../lib/planDraft';

const STATUSES = ENUMS.plan_draft_status as readonly PlanDraftStatus[];

/** 计划草案列表（契约 v0.2.8 §7.7）：URL 驱动筛选，?status= 可多值（逗号分隔），默认全部 */
export function PlanDraftsPage() {
  const [sp, setSp] = useSearchParams();
  const f: PlanDraftFilter = {
    status: parseStatuses(sp.get('status')),
    security_code: (sp.get('security_code') ?? '').trim(),
    signal_id: (sp.get('signal_id') ?? '').trim(),
  };
  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v);
    else next.delete(k);
    setSp(next, { replace: true });
  };
  const list = usePlanDrafts(f);
  const rows = list.items;
  return (
    <div className="page-scroll page" data-testid="plan-drafts-page">
      <h2 className="page-title">计划草案</h2>
      <div className="muted small" style={{ marginBottom: 8 }}>
        计划草案由候选信号按你的持仓与资金拟定，只是待你判断的草稿：需要你逐项回答判断清单并确认风险后才会生成交易计划；交易由你在券商端自行完成。
      </div>
      <Space wrap style={{ marginBottom: 12 }}>
        <Select<PlanDraftStatus[]>
          mode="multiple"
          allowClear
          style={{ minWidth: 240 }}
          placeholder="全部状态"
          value={f.status}
          onChange={(v) => setParam('status', v.join(','))}
          options={STATUSES.map((s) => ({ value: s, label: PLAN_DRAFT_STATUS[s].text }))}
          data-testid="filter-status"
        />
        <Input.Search
          key={f.security_code}
          allowClear
          defaultValue={f.security_code}
          placeholder="证券代码，如 600000.SH"
          style={{ width: 220 }}
          onSearch={(v) => setParam('security_code', v.trim().toUpperCase())}
          data-testid="filter-code"
        />
        {f.signal_id ? <Tag closable onClose={() => setParam('signal_id', '')} data-testid="filter-signal">候选信号 {f.signal_id.slice(-6)}</Tag> : null}
      </Space>
      {list.isError ? <ErrorBox error={list.error} /> : null}
      <Table<PlanDraft>
        size="small"
        rowKey="id"
        loading={list.isPending}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: '没有符合条件的计划草案' }}
        data-testid="drafts-table"
        columns={[
          {
            title: '证券', key: 'sec', width: 170,
            render: (_v, r) => <Link to={`/plan-drafts/${r.id}`} data-testid={`draft-link-${r.id}`}>{r.name} <span className="mono muted">{r.security_code}</span></Link>,
          },
          { title: '规则信号', dataIndex: 'action', width: 90, render: (_v, r) => <ActionBadge action={r.action} /> },
          {
            title: '状态', dataIndex: 'status', width: 100,
            render: (s: PlanDraftStatus) => <Tag color={PLAN_DRAFT_STATUS[s].color} data-testid="draft-status">{PLAN_DRAFT_STATUS[s].text}</Tag>,
          },
          { title: '数量区间（股）', key: 'qty', width: 140, align: 'right', render: (_v, r) => <span className="mono">{r.qty_range.min}–{r.qty_range.max}</span> },
          { title: '价格区间', key: 'px', width: 130, align: 'right', render: (_v, r) => <span className="mono">{r.price_range.low}–{r.price_range.high}</span> },
          {
            title: '最大亏损（估算）', key: 'loss', width: 150, align: 'right',
            render: (_v, r) => <span className="mono">{fmtNum(r.max_loss_amount)} <span className="muted">({r.max_loss_pct}%)</span></span>,
          },
          { title: '有效至', dataIndex: 'valid_until', width: 130, render: (v: string | null) => <span className="mono small">{v ? fmtTime(v).slice(5) : '—'}</span> },
          { title: '生成时间', dataIndex: 'created_at', width: 130, render: (v: string) => <span className="mono small">{fmtTime(v).slice(5)}</span> },
        ]}
      />
      <CursorPager query={list} loaded={rows.length} testId="drafts-pager" />
      <CardDisclaimer />
    </div>
  );
}
