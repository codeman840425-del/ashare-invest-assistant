import { NULL_REASON, promotionRows } from './promotionPresentation';
import { useState } from 'react';
import { Alert, Button, Checkbox, Input, Modal, Select, Table, Tag } from 'antd';
import { useSearchParams } from 'react-router';
import { useMe } from '../../api/queries';
import { ApiError } from '../../api/client';
import { useApprovePromotion, usePromotionReport, usePromotions, useStrategyLifecycle } from '../../api/promotionQueries';
import { useStrategyTemplates } from '../../api/strategyQueries';
import { ErrorBox, Loading } from '../../components/common';
import { StatValue } from '../../components/StatValue';
import { useTransientPassword } from './useTransientPassword';
import { isUuid } from '../../lib/uuid';
import type { AutomaticGateId, GateResultEntry, PromotionFilters, PromotionReport, PromotionSummary } from '../../api/promotionTypes';

const RESULT = { pass: '通过', fail: '未通过', warn: '警告', skipped: '未执行' };
const COLORS = { pass: 'green', fail: 'red', warn: 'orange', skipped: 'default' };
const DECISION = { pending: '待审核', approved: '已批准', rejected: '已拒绝', changes_requested: '需修改' };

function WriteError({ error }: { error: unknown }) {
  if (!error) return null;
  if (error instanceof ApiError && error.code === 'REAUTH_FAILED') return <Alert type="error" showIcon title="本次密码复核失败，请重新输入本人密码；当前会话未退出。" />;
  if (error instanceof ApiError && error.code === 'PROMOTION_STALE') return <Alert type="warning" showIcon title="审核绑定的版本或内容哈希已变化，审核作废（PROMOTION_STALE）；请刷新列表并查看最新版本报告。" description={typeof error.details?.current_version_id === 'string' ? `当前版本：${error.details.current_version_id}` : undefined} />;
  if (error instanceof ApiError && error.code === 'HUMAN_SESSION_REQUIRED') return <Alert type="warning" showIcon title="G7 只能由管理员本人批准：只接受浏览器交互登录会话（cookie 会话 + CSRF），API token、服务账号、脚本或代理凭据一律 403 HUMAN_SESSION_REQUIRED。请管理员本人重新登录后操作。" />;
  if (error instanceof ApiError && error.status === 403) return <Alert type="warning" showIcon title="没有审批权限（403），未完成操作；请管理员核实当前登录身份。" />;
  return <ErrorBox error={error} prefix="操作未完成" />;
}
function staleText(reason: PromotionReport['stale_reason']) {
  if (reason === 'legacy_unbound') return '历史审核只读展示，要晋级须重新申请（legacy_unbound：历史审核未绑定版本及内容哈希）。';
  if (reason === 'new_version') return '审核绑定版本已不是最新版本（new_version）；审核只读，请重新申请。';
  if (reason === 'content_changed') return '审核绑定的内容哈希已变化（content_changed）；审核只读，请重新申请。';
  return '审核已作废，仅供只读查看；请查看最新版本报告。';
}
export function AdminStrategyGatesPage() {
  const me = useMe();
  if (me.isPending) return <Loading />;
  if (me.data?.role !== 'admin') return <Alert type="info" title="此页仅供管理员查看" />;
  return <GatesContent />;
}
function GatesContent() {
  const [params, setParams] = useSearchParams();
  const id = params.get('review_id') ?? '';
  const [draftId, setDraftId] = useState(id);
  const [filters, setFilters] = useState<PromotionFilters>({ stale: false });
  const [cursor, setCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<(string | null)[]>([]);
  const list = usePromotions(filters, cursor);
  function filter(next: PromotionFilters) { setFilters(next); setCursor(null); setHistory([]); }
  function open(reviewId: string) { setDraftId(reviewId); setParams({ review_id: reviewId }); }
  return <div className="page-scroll"><div className="page" data-testid="strategy-gates-page">
    <h2 className="page-title">策略门禁报告 · 管理</h2>
    <p className="muted">G1–G6 为服务端报告；G7 仅在本人点击时提交，不自动批准或晋级。</p>
    <section className="panel" style={{ padding: 12 }}>
      <h3>审核列表</h3>
      <Select aria-label="审核决定筛选" mode="multiple" placeholder="全部决定" style={{ width: 260 }} value={filters.decision ? filters.decision.split(',') : []} onChange={(v: string[]) => filter({ ...filters, decision: v.join(',') })} options={Object.entries(DECISION).map(([value, label]) => ({ value, label }))} />
      <Input aria-label="卡片编号筛选" placeholder="卡片编号" style={{ width: 250 }} value={filters.card_id ?? ''} onChange={(e) => filter({ ...filters, card_id: e.target.value.trim() })} />
      <Input aria-label="版本编号筛选" placeholder="版本编号" style={{ width: 250 }} value={filters.version_id ?? ''} onChange={(e) => filter({ ...filters, version_id: e.target.value.trim() })} />
      <Checkbox checked={filters.stale} onChange={(e) => filter({ ...filters, stale: e.target.checked })}>仅看已作废审核</Checkbox>
      <Button onClick={() => void list.refetch()}>刷新列表</Button>
      {list.isError ? <ErrorBox error={list.error} /> : null}
      <Table<PromotionSummary> size="small" rowKey="review_id" pagination={false} loading={list.isFetching} dataSource={list.data?.items ?? []} columns={[
        { title: '卡片 / 版本', render: (_, r) => <>{r.card_key} · v{r.version_no}{r.lifecycle === 'simulating' ? <Tag>模拟中</Tag> : null}</> },
        { title: '决定', render: (_, r) => <>{DECISION[r.decision]}{r.stale || r.stale_reason === 'legacy_unbound' ? <Tag color="orange">{staleText(r.stale_reason)}</Tag> : null}</> },
        { title: 'G1–G6', render: (_, r) => r.gates.map((g) => <Tag key={g.gate} color={COLORS[g.result]}>{g.gate} {RESULT[g.result]}</Tag>) },
        { title: 'G7', render: (_, r) => DECISION[r.g7] },
        { title: '操作', render: (_, r) => <Button onClick={() => open(r.review_id)}>查看报告</Button> },
      ]} />
      <Button disabled={!history.length || list.isFetching} onClick={() => { setCursor(history[history.length - 1]); setHistory(history.slice(0, -1)); }}>上一页</Button>
      <Button disabled={!list.data?.next_cursor || list.isFetching || list.isError} onClick={() => { setHistory([...history, cursor]); setCursor(list.data!.next_cursor); }}>下一页</Button>
    </section>
    <section className="panel" style={{ padding: 12 }}>
      <label htmlFor="review-id">审核编号</label>
      <Input id="review-id" value={draftId} onChange={(e) => setDraftId(e.target.value)} placeholder="输入审核 UUID" style={{ width: 360, margin: '0 12px' }} />
      <Button onClick={() => open(draftId.trim())} disabled={!isUuid(draftId.trim())}>按编号查看</Button>
    </section>
    {id && !isUuid(id) ? <Alert type="warning" title="审核编号格式不正确" /> : null}
    {isUuid(id) ? <ReportContent key={id} id={id} /> : null}
  </div></div>;
}
function ReportContent({ id }: { id: string }) {
  const [comment, setComment] = useState('');
  const [target, setTarget] = useState<string>();
  const [reason, setReason] = useState('');
  const [ack, setAck] = useState<AutomaticGateId[]>([]);
  const report = usePromotionReport(id, isUuid(id));
  const templates = useStrategyTemplates();
  const [dialog, setDialog] = useState<'decision' | 'lifecycle' | null>(null);
  const { ref: decisionPasswordRef, onChange: decisionPasswordOnChange, ...decisionPassword } = useTransientPassword();
  const { ref: lifecyclePasswordRef, onChange: lifecyclePasswordOnChange, ...lifecyclePassword } = useTransientPassword();
  const approve = useApprovePromotion(id, decisionPassword.take);
  const lifecycle = useStrategyLifecycle(lifecyclePassword.take);
  const rows = report.data ? promotionRows(report.data) : [];
  const template = templates.data?.items.find((t) => t.id === target);
  const blocked = rows.length !== 6 || rows.some((g) => g.result === 'fail' || g.result === 'skipped') ||
    (report.data?.g6_report.max_jaccard === null && !report.data.g6_report.max_jaccard_null_reason);
  const warnings = rows.filter((g) => g.result === 'warn').map((g) => g.gate as AutomaticGateId);
  const warnUnacknowledged = warnings.some((g) => !ack.includes(g));
  const writeBlocked = report.data?.stale || report.data?.stale_reason === 'legacy_unbound' || !report.data?.version_id || !report.data?.content_sha256 || [approve.error, lifecycle.error].some((e) => e instanceof ApiError && (e.code === 'PROMOTION_STALE' || e.code === 'HUMAN_SESSION_REQUIRED'));
  const matchingTemplates = (templates.data?.items ?? []).filter((t) => t.current_version.lifecycle === 'draft' && t.current_version.id === report.data?.version_id);
  const boundTemplate = template && matchingTemplates.some((t) => t.id === template.id);
  return <>
    {report.isFetching ? <Loading /> : null}
    {report.isError ? <ErrorBox error={report.error} /> : null}
    {report.data ? <>
      {report.data.stale || report.data.stale_reason === 'legacy_unbound' ? <Alert type="warning" title={staleText(report.data.stale_reason)} /> : null}
      <p className="muted">绑定版本：{report.data.version_id ?? '—（历史审核未绑定版本）'} · v{report.data.version_no} · 内容哈希：{report.data.content_sha256 ?? '—（历史审核未绑定内容哈希，不补算）'}</p>
      <div className="panel-head"><span className="panel-title">逐项结果</span><Tag>{DECISION[report.data.decision]}</Tag></div>
      <Table<GateResultEntry> size="small" rowKey="gate" pagination={false} dataSource={rows} columns={[
        { title: '门禁', dataIndex: 'gate', width: 80 },
        { title: '结果', width: 100, render: (_, g) => <Tag color={COLORS[g.result]}>{RESULT[g.result]}</Tag> },
        { title: '说明 / 缺口', dataIndex: 'detail' },
      ]} />
      <section className="panel" style={{ padding: 12 }}>
        <h3>G6 触发率与覆盖</h3>
        <div className="stat-grid">
          <div><label>触发率</label><StatValue s={report.data.g6_report.trigger_rate} kind="raw" /></div>
          <div><label>覆盖率</label><StatValue s={report.data.g6_report.coverage} kind="raw" /></div>
          <div><label>最大 Jaccard</label><span data-testid="max-jaccard">{report.data.g6_report.max_jaccard ?? `—（${report.data.g6_report.max_jaccard_null_reason ? NULL_REASON[report.data.g6_report.max_jaccard_null_reason] : '原因缺失'}）`}</span></div>
          <div><label>每分钟配额增量</label><span data-testid="quota-delta-per-min">{report.data.g6_report.quota_delta_per_min ?? '—'}</span></div>
        </div>
        <h4>夹具回放</h4>
        {report.data.fixture_runs.length ? report.data.fixture_runs.map((f) => <div key={f.fixture_id}>{f.fixture_id} · {f.passed ? '通过' : '未通过'}<div>{f.diff == null ? <span className="muted">未提供差异详情</span> : <pre>{JSON.stringify(f.diff, null, 2)}</pre>}</div></div>) : <p className="muted">暂无夹具回放记录</p>}
      </section>
      <section className="panel" style={{ padding: 12 }}>
        <h3>G7 人工批准</h3>
        <Input.TextArea disabled={!!writeBlocked || report.data.decision !== 'pending'} aria-label="G7 审核意见" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="请本人填写审核意见；警告项需核实" maxLength={500} />
        {warnings.map((gate) => <div key={gate}><Checkbox checked={ack.includes(gate)} disabled={!!writeBlocked || report.data?.decision !== 'pending'} onChange={(e) => setAck(e.target.checked ? [...ack, gate] : ack.filter((g) => g !== gate))}>本人已核实并确认 {gate} 警告</Checkbox></div>)}
        <Button style={{ marginTop: 12 }} type="primary" data-testid="approve-g7" loading={approve.isPending} disabled={blocked || warnUnacknowledged || !!writeBlocked || report.isFetching || report.isError || report.data.decision !== 'pending' || !comment.trim()} onClick={() => { decisionPassword.clear(); approve.reset(); setDialog('decision'); }}>本人批准 G7</Button>
        {blocked ? <p className="muted">存在未通过、未执行或缺失结果，暂不可批准。</p> : null}
        {approve.isSuccess ? <Alert type="success" title="已提交 G7 批准；尚未自动变更生命周期" /> : null}
      </section>
    </> : null}
    <section className="panel" style={{ padding: 12, marginTop: 12 }}>
      <h3>生命周期 · 转入模拟中</h3>
      <p className="muted">与批准保持两步；绑定当前报告的 review_id，仅可选择绑定版本，仍须本人另行点击。服务端校验内容哈希和全部门禁。</p>
      {templates.isError ? <ErrorBox error={templates.error} /> : null}
      <Select disabled={!!writeBlocked || report.data?.decision !== 'approved'} aria-label="目标策略版本" placeholder="明确选择目标策略版本" value={target} style={{ width: 420 }} onChange={setTarget} options={matchingTemplates.map((t) => ({ value: t.id, label: `${t.name} · v${t.current_version.version_no}` }))} />
      {report.data && templates.isSuccess && !matchingTemplates.length ? <p className="muted">当前策略列表未提供与审核绑定版本一致的可晋级版本；不推测版本映射，暂不可晋级。</p> : null}
      <Input disabled={!!writeBlocked || report.data?.decision !== 'approved'} aria-label="生命周期变更原因" placeholder="本人填写变更原因" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} style={{ margin: '12px 0' }} />
      <Button data-testid="to-simulating" disabled={!boundTemplate || lifecycle.isSuccess || !reason.trim() || !!writeBlocked || report.data?.decision !== 'approved' || report.isFetching || report.isError || templates.isFetching || templates.isError} loading={lifecycle.isPending} onClick={() => { lifecyclePassword.clear(); lifecycle.reset(); setDialog('lifecycle'); }}>本人将所选版本转入模拟中</Button>
      {lifecycle.isSuccess ? <Alert type="success" title="所选版本已转入模拟中" /> : null}
    </section>
    <Modal title="审核决定 · 本人密码复核" open={dialog === 'decision'} destroyOnHidden confirmLoading={approve.isPending} closable={!approve.isPending} mask={{ closable: !approve.isPending }}
      okText="确认批准 G7" cancelText="取消" okButtonProps={{ disabled: !decisionPassword.filled || blocked || warnUnacknowledged || !!writeBlocked || report.isFetching || report.isError || report.data?.decision !== 'pending' || !comment.trim() }}
      onCancel={() => { if (!approve.isPending) { decisionPassword.clear(); setDialog(null); } }}
      onOk={() => approve.mutate({ comment: comment.trim(), ack_warn_gates: warnings.filter((g) => ack.includes(g)) }, { onSuccess: () => setDialog(null), onSettled: decisionPassword.clear })}>
      <p>请管理员本人重新输入密码并确认。审核意见：{comment}</p>
      <input type="password" className="ant-input" style={{ width: '100%', padding: 8, background: '#141b24', color: 'inherit', border: '1px solid #314155' }} ref={decisionPasswordRef} aria-label="审核复核密码" autoComplete="new-password" onChange={decisionPasswordOnChange} disabled={approve.isPending} />
      <WriteError error={approve.error} />
    </Modal>
    <Modal title="晋级 · 本人密码复核" open={dialog === 'lifecycle'} destroyOnHidden confirmLoading={lifecycle.isPending} closable={!lifecycle.isPending} mask={{ closable: !lifecycle.isPending }}
      okText="确认转入模拟中" cancelText="取消" okButtonProps={{ disabled: !lifecyclePassword.filled || !boundTemplate || !!writeBlocked || report.isFetching || report.isError || report.data?.decision !== 'approved' || !reason.trim() }}
      onCancel={() => { if (!lifecycle.isPending) { lifecyclePassword.clear(); setDialog(null); } }}
      onOk={() => template && lifecycle.mutate({ id: template.id, vid: template.current_version.id, reason: reason.trim(), review_id: id }, { onSuccess: () => setDialog(null), onSettled: lifecyclePassword.clear })}>
      <p>请管理员本人重新输入密码。目标：{template?.name}；审核编号：{id}。此操作独立于 G7 批准。</p>
      <input type="password" className="ant-input" style={{ width: '100%', padding: 8, background: '#141b24', color: 'inherit', border: '1px solid #314155' }} ref={lifecyclePasswordRef} aria-label="晋级复核密码" autoComplete="new-password" onChange={lifecyclePasswordOnChange} disabled={lifecycle.isPending} />
      <WriteError error={lifecycle.error} />
    </Modal>
  </>;
}
