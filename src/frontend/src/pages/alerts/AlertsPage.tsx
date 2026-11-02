import { Checkbox, Input, Select, Space, Table, Tag } from 'antd';
import { Link, useSearchParams } from 'react-router';
import { ENUMS, type AlertOrigin, type AlertStatus, type Severity } from '../../api/enums';
import { ALERT_STATUSES, DEFAULT_ALERT_STATUS, parseStatusParam, useAlerts, type AlertFilter } from '../../api/planAlertQueries';
import type { Alert } from '../../api/planAlertTypes';
import { CursorPager } from '../../components/CursorPager';
import { ErrorBox } from '../../components/common';
import { ALERT_ORIGIN, ALERT_STATUS, SEVERITY, SEVERITY_TEXT } from '../../i18n/labels';
import { ALERT_STATUS_COLOR } from '../../i18n/planAlertLabels';
import { fmtTime } from '../../lib/format';

const ORIGINS = ENUMS.alert_origin as readonly AlertOrigin[];
const SEVERITIES = ENUMS.severity as readonly Severity[];

/** T-F23 裁定跟进：提醒中心（契约 v0.2.9 §7.7B GET /alerts）。默认 new,read；含 origin=plan_condition 的提醒 */
export function AlertsPage() {
  const [sp, setSp] = useSearchParams();
  const status = parseStatusParam(sp.get('status'), ALERT_STATUSES, DEFAULT_ALERT_STATUS);
  const originRaw = sp.get('origin') ?? '';
  const sevRaw = sp.get('severity') ?? '';
  const f: AlertFilter = {
    status,
    origin: (ORIGINS as readonly string[]).includes(originRaw) ? (originRaw as AlertOrigin) : '',
    severity: (SEVERITIES as readonly string[]).includes(sevRaw) ? (sevRaw as Severity) : '',
    security_code: (sp.get('security_code') ?? '').trim(),
    plan_id: (sp.get('plan_id') ?? '').trim(),
  };
  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v);
    else next.delete(k);
    setSp(next, { replace: true });
  };
  const list = useAlerts(f);
  const rows = list.items;
  return (
    <div className="page-scroll page" data-testid="alerts-page">
      <h2 className="page-title">提醒中心</h2>
      <div className="muted small" style={{ marginBottom: 8 }}>
        提醒只陈述“发生了什么”和数据来源。打开详情不会改变状态；核对、处理、忽略都由你手动标记，标为“已处理”不会生成交易或修改计划。
      </div>
      <Space wrap style={{ marginBottom: 12 }}>
        <Checkbox checked={status === 'all'} onChange={(e) => setParam('status', e.target.checked ? 'all' : '')} data-testid="alert-filter-all">全部状态</Checkbox>
        <Select<AlertStatus[]>
          mode="multiple"
          allowClear
          disabled={status === 'all'}
          style={{ minWidth: 220 }}
          placeholder="默认：未读、已读"
          value={status === 'all' ? [] : status}
          onChange={(v) => setParam('status', v.join(','))}
          options={ALERT_STATUSES.map((s) => ({ value: s, label: ALERT_STATUS[s] }))}
          data-testid="alert-filter-status"
        />
        <Select<AlertOrigin | ''> style={{ width: 140 }} value={f.origin ?? ''} onChange={(v) => setParam('origin', v)} data-testid="alert-filter-origin"
          options={[{ value: '', label: '全部来源' }, ...ORIGINS.map((o) => ({ value: o, label: ALERT_ORIGIN[o] }))]} />
        <Select<Severity | ''> style={{ width: 120 }} value={f.severity ?? ''} onChange={(v) => setParam('severity', v)} data-testid="alert-filter-severity"
          options={[{ value: '', label: '全部级别' }, ...SEVERITIES.map((s) => ({ value: s, label: SEVERITY_TEXT[s] }))]} />
        <Input.Search key={f.security_code} allowClear defaultValue={f.security_code} placeholder="证券代码" style={{ width: 180 }}
          onSearch={(v) => setParam('security_code', v.trim().toUpperCase())} data-testid="alert-filter-code" />
        {f.plan_id ? <Tag closable onClose={() => setParam('plan_id', '')} data-testid="alert-filter-plan">计划 {f.plan_id.slice(-6)}</Tag> : null}
      </Space>
      {list.isError ? <ErrorBox error={list.error} /> : null}
      <Table<Alert>
        size="small"
        rowKey="id"
        loading={list.isPending}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: '没有符合条件的提醒' }}
        data-testid="alerts-table"
        columns={[
          { title: '级别', dataIndex: 'severity', width: 70, render: (s: Severity) => <Tag color={SEVERITY[s]}>{SEVERITY_TEXT[s]}</Tag> },
          { title: '提醒', key: 't', render: (_v, a) => <Link to={`/alerts/${a.id}`} data-testid={`alert-link-${a.id}`}>{a.title}</Link> },
          { title: '证券', key: 's', width: 160, render: (_v, a) => (a.security_code ? <>{a.name} <span className="mono muted">{a.security_code}</span></> : <span className="muted">账户级</span>) },
          { title: '来源', dataIndex: 'origin', width: 100, render: (o: AlertOrigin) => ALERT_ORIGIN[o] },
          { title: '状态', dataIndex: 'status', width: 90, render: (s: AlertStatus) => <Tag color={ALERT_STATUS_COLOR[s]} data-testid="alert-status">{ALERT_STATUS[s]}</Tag> },
          { title: '触发时间', dataIndex: 'triggered_at', width: 130, render: (v: string) => <span className="mono small">{fmtTime(v).slice(5)}</span> },
        ]}
      />
      <CursorPager query={list} loaded={rows.length} testId="alerts-pager" />
      <div className="muted small">时间均为北京时间。示例数据。</div>
    </div>
  );
}
