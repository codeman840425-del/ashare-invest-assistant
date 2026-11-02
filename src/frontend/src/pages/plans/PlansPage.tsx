import { useState } from 'react';
import { Button, Checkbox, Form, Input, Modal, Select, Space, Table, Tag } from 'antd';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { ENUMS, type Action, type PlanOrigin, type PlanStatus } from '../../api/enums';
import { DEFAULT_PLAN_STATUS, PLAN_STATUSES, parseStatusParam, useCreatePlan, usePlans, type PlanFilter } from '../../api/planAlertQueries';
import type { PlanSummary } from '../../api/planAlertTypes';
import { CursorPager } from '../../components/CursorPager';
import { ErrorBox } from '../../components/common';
import { CardDisclaimer } from '../../components/RiskDisclosure';
import { PlanFormFields, PlanWriteError } from '../../features/plans/PlanForm';
import { applyPlanErrors, toBody, type PlanFormValues } from '../../features/plans/planFormModel';
import { ACTION_SHORT } from '../../i18n/labels';
import { PLAN_ORIGIN, PLAN_STATUS } from '../../i18n/planAlertLabels';
import { fmtTime } from '../../lib/format';

const ORIGINS = ENUMS.plan_origin as readonly PlanOrigin[];

/** T-F23 裁定跟进：操作计划列表（契约 v0.2.9 §7.7B GET /plans）。URL 驱动筛选，默认 active,triggered */
export function PlansPage() {
  const [sp, setSp] = useSearchParams();
  const [creating, setCreating] = useState(false);
  const status = parseStatusParam(sp.get('status'), PLAN_STATUSES, DEFAULT_PLAN_STATUS);
  const originRaw = sp.get('origin') ?? '';
  const f: PlanFilter = {
    status,
    origin: (ORIGINS as readonly string[]).includes(originRaw) ? (originRaw as PlanOrigin) : '',
    security_code: (sp.get('security_code') ?? '').trim(),
  };
  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v);
    else next.delete(k);
    setSp(next, { replace: true });
  };
  const list = usePlans(f);
  const rows = list.items;
  return (
    <div className="page-scroll page" data-testid="plans-page">
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <h2 className="page-title">操作计划</h2>
        <Button type="primary" size="small" onClick={() => setCreating(true)} data-testid="plan-new-btn">手工新建计划</Button>
      </Space>
      <div className="muted small" style={{ marginBottom: 8 }}>
        计划是你自己的记录：计划条件由你设定，满足时系统只把计划标为“条件已满足”并生成提醒，不会下单，也不会自动关闭计划；是否完成或取消由你决定。
      </div>
      <Space wrap style={{ marginBottom: 12 }}>
        <Checkbox checked={status === 'all'} onChange={(e) => setParam('status', e.target.checked ? 'all' : '')} data-testid="plan-filter-all">全部状态（含已完成、已取消）</Checkbox>
        <Select<PlanStatus[]>
          mode="multiple"
          allowClear
          disabled={status === 'all'}
          style={{ minWidth: 240 }}
          placeholder="默认：进行中、条件已满足"
          value={status === 'all' ? [] : status}
          onChange={(v) => setParam('status', v.join(','))}
          options={PLAN_STATUSES.map((s) => ({ value: s, label: PLAN_STATUS[s].text }))}
          data-testid="plan-filter-status"
        />
        <Select<PlanOrigin | ''>
          style={{ width: 150 }}
          value={f.origin ?? ''}
          onChange={(v) => setParam('origin', v)}
          options={[{ value: '', label: '全部来源' }, ...ORIGINS.map((o) => ({ value: o, label: PLAN_ORIGIN[o] }))]}
          data-testid="plan-filter-origin"
        />
        <Input.Search key={f.security_code} allowClear defaultValue={f.security_code} placeholder="证券代码，如 600000.SH" style={{ width: 220 }}
          onSearch={(v) => setParam('security_code', v.trim().toUpperCase())} data-testid="plan-filter-code" />
      </Space>
      {list.isError ? <ErrorBox error={list.error} /> : null}
      <Table<PlanSummary>
        size="small"
        rowKey="id"
        loading={list.isPending}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: '没有符合条件的计划' }}
        data-testid="plans-table"
        columns={[
          { title: '证券', key: 'sec', width: 180, render: (_v, r) => <Link to={`/plans/${r.id}`} data-testid={`plan-link-${r.id}`}>{r.name} <span className="mono muted">{r.security_code}</span></Link> },
          { title: '状态', dataIndex: 'status', width: 110, render: (s: PlanStatus) => <Tag color={PLAN_STATUS[s].color} data-testid="plan-status">{PLAN_STATUS[s].text}</Tag> },
          { title: '计划动作', dataIndex: 'action', width: 90, render: (a: Action) => ACTION_SHORT[a] },
          { title: '来源', dataIndex: 'origin', width: 120, render: (o: PlanOrigin) => PLAN_ORIGIN[o] },
          { title: '当前版本', dataIndex: 'current_version_no', width: 90, align: 'right', render: (n: number) => <span className="mono">第 {n} 版</span> },
          { title: '条件满足时间', dataIndex: 'triggered_at', width: 140, render: (v: string | null) => (v ? <span className="mono small">{fmtTime(v).slice(5)}</span> : <span className="muted">—</span>) },
          { title: '创建时间', dataIndex: 'created_at', width: 140, render: (v: string) => <span className="mono small">{fmtTime(v).slice(5)}</span> },
        ]}
      />
      <CursorPager query={list} loaded={rows.length} testId="plans-pager" />
      <div className="muted small">时间均为北京时间。示例数据。</div>
      <CardDisclaimer />
      {creating ? <CreatePlanModal onClose={() => setCreating(false)} /> : null}
    </div>
  );
}

function CreatePlanModal({ onClose }: { onClose: () => void }) {
  const [form] = Form.useForm<PlanFormValues>();
  const m = useCreatePlan();
  const nav = useNavigate();
  const submit = (v: PlanFormValues) => {
    m.mutate(
      { security_code: (v.security_code ?? '').trim().toUpperCase(), account_id: null, ...toBody(v), candidate_id: null },
      { onSuccess: (p) => nav(`/plans/${p.id}`), onError: (e) => applyPlanErrors(form, e) },
    );
  };
  return (
    <Modal open title="手工新建计划" onCancel={onClose} onOk={() => form.submit()} okText="创建计划" confirmLoading={m.isPending} width={860} destroyOnHidden
      okButtonProps={{ 'data-testid': 'plan-create-ok' } as never}>
      {m.isError ? <PlanWriteError error={m.error} /> : null}
      <Form<PlanFormValues> form={form} layout="vertical" initialValues={{ action: 'buy', conditions: [] }} onFinish={submit} data-testid="plan-create-form">
        <PlanFormFields create />
      </Form>
    </Modal>
  );
}
