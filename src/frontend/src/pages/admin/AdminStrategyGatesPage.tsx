import { useState } from 'react';
import { Alert, Button, Checkbox, Input, Select, Table, Tag } from 'antd';
import { useSearchParams } from 'react-router';
import { useMe } from '../../api/queries';
import { ApiError } from '../../api/client';
import { useApprovePromotion, usePromotionReport, usePromotions, useStrategyLifecycle } from '../../api/promotionQueries';
import { useStrategyTemplates } from '../../api/strategyQueries';
import { ErrorBox, Loading } from '../../components/common';
import { StatValue } from '../../components/StatValue';
import { isUuid } from '../../lib/uuid';
import type { AutomaticGateId, GateResultEntry, PromotionFilters, PromotionReport, PromotionSummary } from '../../api/promotionTypes';

const GATES = ['G1', 'G2', 'G3', 'G4', 'G5', 'G6'] as const;
const RESULT = { pass: '通过', fail: '未通过', warn: '警告', skipped: '未执行' };
const COLORS = { pass: 'green', fail: 'red', warn: 'orange', skipped: 'default' };
const DECISION = { pending: '待审核', approved: '已批准', rejected: '已拒绝', changes_requested: '需修改' };
const NULL_REASON = { no_history: '近 120 日历史不足或未体检', no_comparable_set: '没有可比较的其他模板命中集合' };

/** null 不填 0；夹具失败不能被覆盖成 warn；缺报告不造 pass。 */
export function promotionRows(report: PromotionReport): GateResultEntry[] {
  return GATES.map((gate) => {
    const row = report.gate_results.find((g) => g.gate === gate) ?? { gate, result: 'skipped' as const, detail: '报告缺少该门禁结果' };
    if (gate === 'G6' && report.g6_report.max_jaccard === null) {
      const reason = report.g6_report.max_jaccard_null_reason;
      return { ...row, result: row.result === 'pass' ? 'warn' : row.result,
        detail: `${row.detail}；${reason ? `${reason}：${NULL_REASON[reason]}` : '缺少 max_jaccard_null_reason'}（重合度未通过验证）` };
    }
    return row;
  });
}
function WriteError({ error }: { error: unknown }) {
  if (!error) return null;
  if (error instanceof ApiError && error.code === 'PROMOTION_STALE') return <Alert type="warning" showIcon title="审核绑定的版本或内容哈希已变化，审核作废（PROMOTION_STALE）；请刷新列表并查看最新版本报告。" description={typeof error.details?.current_version_id === 'string' ? `当前版本：${error.details.current_version_id}` : undefined} />;
  if (error instanceof ApiError && error.code === 'HUMAN_SESSION_REQUIRED') return <Alert type="warning" showIcon title="G7 只能由管理员本人批准：只接受浏览器交互登录会话（cookie 会话 + CSRF），API token、服务账号、脚本或代理凭据一律 403 HUMAN_SESSION_REQUIRED。请管理员本人重新登录后操作。" />;
  if (error instanceof ApiError && error.status === 403) return <Alert type="warning" showIcon title="没有审批权限（403），未完成操作；请管理员核实当前登录身份。" />;
  return <ErrorBox error={error} prefix="操作未完成" />;
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
        { title: '决定', render: (_, r) => <>{DECISION[r.decision]}{r.stale ? <Tag color="orange">审核已作废 · 只读</Tag> : null}</> },
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
  const approve = useApprovePromotion(id);
  const lifecycle = useStrategyLifecycle();
  const rows = report.data ? promotionRows(report.data) : [];
  const template = templates.data?.items.find((t) => t.id === target);
  const blocked = rows.length !== 6 || rows.some((g) => g.result === 'fail' || g.result === 'skipped') ||
    (report.data?.g6_report.max_jaccard === null && !report.data.g6_report.max_jaccard_null_reason);
  const warnings = rows.filter((g) => g.result === 'warn').map((g) => g.gate as AutomaticGateId);
  const warnUnacknowledged = warnings.some((g) => !ack.includes(g));
  const writeBlocked = report.data?.stale || [approve.error, lifecycle.error].some((e) => e instanceof ApiError && (e.code === 'PROMOTION_STALE' || e.code === 'HUMAN_SESSION_REQUIRED'));
  const matchingTemplates = (templates.data?.items ?? []).filter((t) => t.current_version.lifecycle === 'draft' && t.current_version.id === report.data?.version_id);
  const boundTemplate = template && matchingTemplates.some((t) => t.id === template.id);
  return <>
    {report.isFetching ? <Loading /> : null}
    {report.isError ? <ErrorBox error={report.error} /> : null}
    {report.data ? <>
      {report.data.stale ? <Alert type="warning" title="审核已作废，仅供只读查看；请查看最新版本报告。" /> : null}
      <p className="muted">绑定版本：{report.data.version_id} · v{report.data.version_no} · 内容哈希：{report.data.content_sha256}</p>
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
          <div><label>每分钟配额增量</label>{report.data.g6_report.quota_delta_per_min}</div>
        </div>
        <h4>夹具回放</h4>
        {report.data.fixture_runs.length ? report.data.fixture_runs.map((f) => <div key={f.fixture_id}>{f.fixture_id} · {f.passed ? '通过' : '未通过'}<pre>{JSON.stringify(f.diff, null, 2)}</pre></div>) : <p className="muted">暂无夹具回放记录</p>}
      </section>
      <section className="panel" style={{ padding: 12 }}>
        <h3>G7 人工批准</h3>
        <Input.TextArea aria-label="G7 审核意见" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="请本人填写审核意见；警告项需核实" maxLength={500} />
        {warnings.map((gate) => <div key={gate}><Checkbox checked={ack.includes(gate)} disabled={!!writeBlocked || report.data?.decision !== 'pending'} onChange={(e) => setAck(e.target.checked ? [...ack, gate] : ack.filter((g) => g !== gate))}>本人已核实并确认 {gate} 警告</Checkbox></div>)}
        <Button style={{ marginTop: 12 }} type="primary" data-testid="approve-g7" loading={approve.isPending} disabled={blocked || warnUnacknowledged || !!writeBlocked || report.isFetching || report.isError || report.data.decision !== 'pending' || !comment.trim()} onClick={() => approve.mutate({ comment: comment.trim(), ack_warn_gates: warnings.filter((g) => ack.includes(g)) })}>本人批准 G7</Button>
        {blocked ? <p className="muted">存在未通过、未执行或缺失结果，暂不可批准。</p> : null}
        {approve.isSuccess ? <Alert type="success" title="已提交 G7 批准；尚未自动变更生命周期" /> : null}
        <WriteError error={approve.error} />
      </section>
    </> : null}
    <section className="panel" style={{ padding: 12, marginTop: 12 }}>
      <h3>生命周期 · 转入模拟中</h3>
      <p className="muted">与批准保持两步；绑定当前报告的 review_id，仅可选择绑定版本，仍须本人另行点击。服务端校验内容哈希和全部门禁。</p>
      {templates.isError ? <ErrorBox error={templates.error} /> : null}
      <Select aria-label="目标策略版本" placeholder="明确选择目标策略版本" value={target} style={{ width: 420 }} onChange={setTarget} options={matchingTemplates.map((t) => ({ value: t.id, label: `${t.name} · v${t.current_version.version_no}` }))} />
      {report.data && templates.isSuccess && !matchingTemplates.length ? <p className="muted">当前策略列表未提供与审核绑定版本一致的可晋级版本；不推测版本映射，暂不可晋级。</p> : null}
      <Input aria-label="生命周期变更原因" placeholder="本人填写变更原因" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} style={{ margin: '12px 0' }} />
      <Button data-testid="to-simulating" disabled={!boundTemplate || lifecycle.isSuccess || !reason.trim() || !!writeBlocked || report.data?.decision !== 'approved' || report.isFetching || report.isError || templates.isFetching || templates.isError} loading={lifecycle.isPending} onClick={() => template && lifecycle.mutate({ id: template.id, vid: template.current_version.id, reason: reason.trim(), review_id: id })}>本人将所选版本转入模拟中</Button>
      {lifecycle.isSuccess ? <Alert type="success" title="所选版本已转入模拟中" /> : null}
      <WriteError error={lifecycle.error} />
    </section>
  </>;
}
