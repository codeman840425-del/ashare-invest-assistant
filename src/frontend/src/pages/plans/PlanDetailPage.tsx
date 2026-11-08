import { useState } from 'react';
import { Alert, Button, Descriptions, Drawer, Form, Input, Modal, Radio, Space, Tag } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { Link, useNavigate, useParams } from 'react-router';
import { ApiError } from '../../api/client';
import { useClosePlan, useCreatePlanVersion, usePlan, usePlanVersions } from '../../api/planAlertQueries';
import { isTerminalPlan, type Plan, type PlanCondition, type PlanVersion } from '../../api/planAlertTypes';
import { CursorPager } from '../../components/CursorPager';
import { ErrorBox, Loading } from '../../components/common';
import { CardDisclaimer } from '../../components/RiskDisclosure';
import { PlanConditionRules, PlanFormFields, PlanWriteError } from '../../features/plans/PlanForm';
import { applyPlanErrors, fromVersion, toBody, type PlanFormValues } from '../../features/plans/planFormModel';
import { ACTION_SHORT, EPISTEMIC, PLAN_CONDITION_KIND } from '../../i18n/labels';
import { PLAN_CONDITION_TYPE, PLAN_ORIGIN, PLAN_STATUS } from '../../i18n/planAlertLabels';
import { fmtTime } from '../../lib/format';

function paramText(c: PlanCondition): string {
  const p = c.params as Record<string, string | undefined>;
  if (c.type === 'price_above' || c.type === 'price_below') return `${PLAN_CONDITION_TYPE[c.type]} ${p.price ?? '—'}`;
  if (c.type === 'pct_change') return `${PLAN_CONDITION_TYPE[c.type]} ${p.pct ?? '—'}%`;
  if (c.type === 'date') return `${PLAN_CONDITION_TYPE[c.type]} ${p.on ?? '—'}`;
  return PLAN_CONDITION_TYPE[c.type];
}

function VersionBody({ v }: { v: PlanVersion }) {
  return (
    <>
      <Descriptions size="small" column={2} bordered items={[
        { key: 'a', label: '计划动作', children: ACTION_SHORT[v.action] },
        { key: 'q', label: '数量', children: v.qty ?? '—' },
        { key: 'p', label: '价格', children: v.price ?? '—' },
        { key: 'r', label: '复核日期', children: v.review_date ?? '—' },
        { key: 's', label: '止损 / 止盈 / 时间止损', children: v.stops ? `${v.stops.stop_loss ?? '—'} / ${v.stops.take_profit ?? '—'} / ${v.stops.time_stop_days ?? '—'} 天` : '—' },
        { key: 'm', label: '最大亏损金额', children: v.max_loss_amount ?? '—' },
        { key: 'ra', label: '计划依据', span: 2, children: v.rationale },
        { key: 'ri', label: '风险', span: 2, children: v.risks ?? '—' },
        ...(v.change_reason ? [{ key: 'cr', label: '修改原因', span: 2, children: v.change_reason }] : []),
      ]} />
      <div className="muted small" style={{ margin: '8px 0 4px' }}>计划条件（假设，不是预测）</div>
      {v.conditions.length ? (
        <ul style={{ listStyle: 'none', padding: 0, margin: 0 }} data-testid="plan-conditions">
          {v.conditions.map((c) => (
            <li key={c.id} data-testid="plan-condition">
              <Tag color={c.kind === 'invalidation' ? 'orange' : 'blue'}>{PLAN_CONDITION_KIND[c.kind]}</Tag>
              <Tag color={EPISTEMIC[c.epistemic_type].color}>{EPISTEMIC[c.epistemic_type].text}</Tag>
              <span className="mono small">{paramText(c)}</span> · {c.description}
            </li>
          ))}
        </ul>
      ) : <div className="muted small">没有计划条件</div>}
      {v.checklist_answers.length ? (
        <div className="small" style={{ marginTop: 6 }} data-testid="plan-checklist">
          <div className="muted">确认草案时的判断清单回答</div>
          {v.checklist_answers.map((a) => <div key={a.id}>{a.question}：{{ yes: '是', no: '否', unsure: '不确定' }[a.answer]}{a.note ? `（${a.note}）` : ''}</div>)}
        </div>
      ) : null}
    </>
  );
}

/** T-F23 裁定跟进：操作计划详情（契约 v0.2.9 §7.7B）：当前版本、已满足条件、版本历史、新建版本、关闭 */
export function PlanDetailPage() {
  const { id = '' } = useParams();
  const q = usePlan(id);
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [closing, setClosing] = useState(false);
  if (q.isPending) return <div className="page-scroll page" data-testid="plan-detail"><Loading /></div>;
  if (q.isError || !q.data) {
    const nf = q.error instanceof ApiError && q.error.status === 404;
    return (
      <div className="page-scroll page" data-testid="plan-detail">
        {nf ? <div data-testid="plan-not-found">计划不存在或不属于你。<Link to="/plans">返回计划列表</Link></div> : <ErrorBox error={q.error} />}
      </div>
    );
  }
  const p = q.data;
  const terminal = isTerminalPlan(p.status);
  const evById = new Map(p.evidence.map((e) => [e.id, e]));
  return (
    <div className="page-scroll page" data-testid="plan-detail">
      <div className="detail-head">
        <Button size="small" icon={<ArrowLeftOutlined />} onClick={() => navigate('/plans')}>操作计划</Button>
        <Link to={`/stocks/${p.security_code}`} className="q-name">{p.name}</Link>
        <span className="mono muted">{p.security_code}</span>
        <Tag color={PLAN_STATUS[p.status].color} data-testid="plan-detail-status">{PLAN_STATUS[p.status].text}</Tag>
        <span className="muted small">
          来源 {PLAN_ORIGIN[p.origin]}
          {p.plan_draft_id ? <> · <Link to={`/plan-drafts/${p.plan_draft_id}`}>来源计划草案</Link></> : null}
          {' '}· 第 {p.current_version_no} 版 / 共 {p.version_count} 版 · 创建 {fmtTime(p.created_at)}（北京时间）
        </span>
        <span style={{ flex: 1 }} />
        <Space>
          <Button size="small" disabled={terminal} onClick={() => setEditing(true)} data-testid="plan-edit-btn">修改计划（新建版本）</Button>
          <Button size="small" disabled={terminal} onClick={() => setClosing(true)} data-testid="plan-close-btn">关闭计划</Button>
        </Space>
      </div>
      {terminal ? <Alert type="info" showIcon style={{ margin: '8px 0' }} data-testid="plan-terminal-note" title={`计划${PLAN_STATUS[p.status].text}：不能再修改或关闭，版本历史保留可回看。`} /> : null}
      {p.pending_triggers.length ? (
        <section className="panel" style={{ margin: '8px 0' }} data-testid="plan-pending">
          <div className="panel-head"><span className="panel-title">已满足的条件</span><span className="muted small">满足只代表事实已发生；系统不会下单，也不会自动关闭计划</span></div>
          {p.pending_triggers.map((t) => (
            <div key={t.condition_id} className="small" data-testid="plan-pending-item">
              <Tag color={t.condition_kind === 'invalidation' ? 'orange' : 'blue'}>{PLAN_CONDITION_KIND[t.condition_kind]}</Tag>
              {t.condition_text} · <span className="mono">{fmtTime(t.triggered_at)}</span>
              {t.alert_id ? <> · <Link to={`/alerts/${t.alert_id}`} data-testid="plan-pending-alert">查看提醒</Link></> : null}
              {t.evidence_ids.map((eid) => {
                const e = evById.get(eid);
                return e ? <span key={eid} className="muted small"> · {e.key} {String(e.value)}{e.unit ? ` ${e.unit}` : ''}（{fmtTime(e.data_as_of ?? e.fetched_at)}）</span> : null;
              })}
            </div>
          ))}
        </section>
      ) : null}
      <section className="panel" style={{ margin: '8px 0' }} data-testid="plan-current">
        <div className="panel-head"><span className="panel-title">当前版本（第 {p.current_version.version_no} 版）</span><span className="muted small">{fmtTime(p.current_version.created_at)}</span></div>
        <VersionBody v={p.current_version} />
      </section>
      <PlanConditionRules />
      <VersionHistory plan={p} />
      <CardDisclaimer />
      {editing ? <NewVersionDrawer plan={p} onClose={() => setEditing(false)} onReload={() => void q.refetch()} /> : null}
      {closing ? <CloseModal plan={p} onClose={() => setClosing(false)} /> : null}
    </div>
  );
}

function VersionHistory({ plan }: { plan: Plan }) {
  const vs = usePlanVersions(plan.id);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <section className="panel" data-testid="plan-versions">
      <div className="panel-head"><span className="panel-title">版本历史</span><span className="muted small">版本不可修改，按版本号倒序</span></div>
      {vs.isError ? <ErrorBox error={vs.error} /> : null}
      {vs.items.map((v) => (
        <div key={v.version_no} className="small" data-testid="plan-version-row">
          <Button type="link" size="small" onClick={() => setOpen(open === v.version_no ? null : v.version_no)}>第 {v.version_no} 版</Button>
          <span className="mono muted">{fmtTime(v.created_at)}</span> · {ACTION_SHORT[v.action]} · {v.change_reason ?? '首版'}
          {open === v.version_no ? <div style={{ margin: '4px 0 8px' }}><VersionBody v={v} /></div> : null}
        </div>
      ))}
      <CursorPager query={vs} loaded={vs.items.length} testId="plan-versions-pager" />
    </section>
  );
}

function NewVersionDrawer({ plan, onClose, onReload }: { plan: Plan; onClose: () => void; onReload: () => void }) {
  const [form] = Form.useForm<PlanFormValues>();
  const m = useCreatePlanVersion(plan.id);
  const submit = (v: PlanFormValues) => {
    m.mutate(
      { base_version_no: plan.current_version_no, change_reason: (v.change_reason ?? '').trim(), ...toBody(v), stops: plan.current_version.stops,
        size_pct_of_assets: plan.current_version.size_pct_of_assets, max_loss_amount: plan.current_version.max_loss_amount },
      { onSuccess: onClose, onError: (e) => applyPlanErrors(form, e) },
    );
  };
  return (
    <Drawer open title={`修改计划：新建第 ${plan.current_version_no + 1} 版`} size={760} onClose={onClose} destroyOnHidden
      extra={<Button type="primary" size="small" loading={m.isPending} onClick={() => form.submit()} data-testid="plan-version-ok">保存为新版本</Button>}>
      <div className="muted small" style={{ marginBottom: 8 }}>
        新版本整体替换计划内容（证券、账户、来源不可改）。{plan.status === 'triggered' ? '计划当前为“条件已满足”，保存后回到“进行中”，新版本的条件重新生效。' : ''}
      </div>
      {m.isError ? <PlanWriteError error={m.error} onReload={() => { onReload(); onClose(); }} /> : null}
      <Form<PlanFormValues> form={form} layout="vertical" initialValues={fromVersion(plan.current_version)} onFinish={submit} data-testid="plan-version-form">
        <PlanFormFields versioning />
      </Form>
    </Drawer>
  );
}

function CloseModal({ plan, onClose }: { plan: Plan; onClose: () => void }) {
  const [status, setStatus] = useState<'done' | 'cancelled'>('done');
  const [note, setNote] = useState('');
  const m = useClosePlan(plan.id);
  return (
    <Modal open title="关闭计划" onCancel={onClose} okText="确认关闭" confirmLoading={m.isPending} destroyOnHidden
      okButtonProps={{ 'data-testid': 'plan-close-ok' } as never}
      onOk={() => m.mutate({ status, note: note.trim() || null }, { onSuccess: onClose })}>
      {m.isError ? <PlanWriteError error={m.error} /> : null}
      <div className="muted small" style={{ marginBottom: 8 }}>关闭后计划不能再修改或重新打开（终态）。关闭只是记录，不会下单。</div>
      <Radio.Group value={status} onChange={(e) => setStatus(e.target.value as 'done' | 'cancelled')} data-testid="plan-close-status">
        <Radio value="done">已完成</Radio>
        <Radio value="cancelled">已取消</Radio>
      </Radio.Group>
      <Input.TextArea style={{ marginTop: 8 }} rows={2} maxLength={200} placeholder="备注（可空，最多 200 字）" value={note} onChange={(e) => setNote(e.target.value)} />
    </Modal>
  );
}
