import { useState } from 'react';
import { Alert, Button, Input, Modal, Space, Table, Tag, Timeline, Tooltip, type ButtonProps } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { Link, useNavigate, useParams } from 'react-router';
import { useCandidateSignals } from '../../api/queries';
import { useCreatePlanDraft } from '../../api/planQueries';
import { useDismissSignal, useReleaseReason, useSignal, useSignalEvents, useSignalReasonsAll, useStrategyTracking } from '../../api/signalQueries';
import { useStrategyTemplates } from '../../api/strategyQueries';
import { errorText } from '../../api/errorPolicy';
import type { CandidateSignal, Evidence, NonExecutableReason, RuleRef } from '../../api/types';
import { ActionBadge, ConfidenceTag, DataStatusTag, ErrorBox, GapNote, Loading } from '../../components/common';
import { EvidenceChips } from '../../components/EvidenceChips';
import { CardDisclaimer } from '../../components/RiskDisclosure';
import { StatValue } from '../../components/StatValue';
import { DIMENSION, HORIZON, REASON_CODE, RISK_CONTROL, RISK_LEVEL, RULE_ROLE, SIGNAL_STATE } from '../../i18n/labels';
import { causeText } from '../../i18n/signalLabels';
import { fmtTime } from '../../lib/format';
import { canDraft, conflictsOf, isTerminal } from '../../lib/signals';
import { LifecycleBadge } from './LifecycleBadge';
import { ReasonCard } from './ReasonCard';

/** RuleRef.passed 三态：true 满足 / false 不满足 / null 数据缺失无法求值 */
export function PassedTag({ passed }: { passed: boolean | null }) {
  if (passed === null) return <Tag data-testid="passed-null">无法求值</Tag>;
  return passed ? <Tag color="green" data-testid="passed-true">满足</Tag> : <Tag color="red" data-testid="passed-false">不满足</Tag>;
}

/** 候选信号详情（契约 v0.2.7 §7.6）：原因与自动重评状态、手动解除、状态历史、忽略、同股冲突并列 */
export function CandidateSignalDetailPage() {
  const { id = '' } = useParams();
  const nav = useNavigate();
  const q = useSignal(id);
  if (q.isPending) return <div className="page-scroll page"><Loading /></div>;
  if (q.isError || !q.data) return <div className="page-scroll page"><ErrorBox error={q.error} /></div>;
  const cs = q.data;
  return (
    <div className="page-scroll page sig-detail" data-testid="signal-detail">
      <div className="sig-head">
        <Button size="small" icon={<ArrowLeftOutlined />} onClick={() => nav('/candidate-signals')}>候选信号</Button>
        <h2 className="page-title" style={{ margin: 0 }}>
          {cs.name} <span className="mono muted">{cs.security_code}</span>
        </h2>
        <ActionBadge action={cs.proposed_action} tLeg={cs.t_leg} strategyName={cs.strategy_name} size="lg" />
        <Tag color={SIGNAL_STATE[cs.state].color} data-testid="signal-state">{SIGNAL_STATE[cs.state].text}</Tag>
        <span>{cs.strategy_name}</span>
        <LifecycleBadge lifecycle={cs.lifecycle} />
        <span className="muted small">{HORIZON[cs.horizon]}</span>
        <span className="spacer" />
        <DataStatusTag status={cs.data_status} asOf={cs.data_as_of} gaps={cs.gaps} />
      </div>
      <GapNote status={cs.data_status} gaps={cs.gaps} asOf={cs.data_as_of} />
      <div className="sig-grid">
        <div className="sig-col">
          <Metrics cs={cs} />
          <Conflicts cs={cs} />
          <Reasons cs={cs} />
          <RuleRefs refs={cs.rule_refs} evidence={cs.evidence} />
          <TextBlocks cs={cs} />
        </div>
        <div className="sig-col">
          <Actions cs={cs} />
          <Tracking cs={cs} />
          <Events id={cs.id} />
          <section className="panel sig-panel">
            <h4>规则闸门</h4>
            {cs.gate_results.length ? (
              <Space wrap size={4}>{cs.gate_results.map((g) => <Tag key={g.gate} color={g.passed ? 'green' : 'red'}>{g.gate} {g.passed ? '通过' : '未通过'}</Tag>)}</Space>
            ) : <span className="muted small">无</span>}
            {cs.model_refs.length ? (
              <>
                <h4 style={{ marginTop: 8 }}>辅助模型</h4>
                {cs.model_refs.map((m) => <div key={m.model_key} className="small"><span className="mono">{m.model_key}@{m.version}</span> <EvidenceChips ids={m.evidence_ids} evidence={cs.evidence} /></div>)}
              </>
            ) : null}
          </section>
        </div>
      </div>
      <CardDisclaimer />
    </div>
  );
}

function Metrics({ cs }: { cs: CandidateSignal }) {
  return (
    <section className="panel sig-panel">
      <div className="sc-metrics">
        <div><label>规则满足度</label><b className="mono">{cs.score ?? '—'}</b></div>
        <div><label>置信度</label><ConfidenceTag c={cs.confidence} /></div>
        <div><label>有效至</label><b className="mono small">{cs.valid_until ? fmtTime(cs.valid_until) : '—'}</b></div>
        <div><label>止损</label><b className="mono down">{cs.stops.stop_loss ?? '—'}</b></div>
        <div><label>止盈</label><b className="mono up">{cs.stops.take_profit ?? '—'}</b></div>
        <div><label>时间止损</label><b className="mono">{cs.stops.time_stop_days != null ? `${cs.stops.time_stop_days} 日` : '—'}</b></div>
        <div><label>生成时间</label><b className="mono small">{fmtTime(cs.created_at)}</b></div>
        <div><label>快照</label><b className="mono small">{cs.feature_set_version}</b></div>
      </div>
    </section>
  );
}

/** 同一证券、未结束、方向相反的信号并列展示（不合成结论） */
function Conflicts({ cs }: { cs: CandidateSignal }) {
  const all = useCandidateSignals(cs.security_code);
  const others = conflictsOf(cs, all.data?.items ?? []);
  if (!others.length) return null;
  const pair = [cs, ...others];
  return (
    <section className="panel sig-panel conflict" data-testid="signal-conflicts">
      <h4>方向冲突 · 并列展示</h4>
      <div className="muted small" style={{ marginBottom: 6 }}>同一证券有方向相反的候选信号。各策略依据不同，系统不替你取舍，请结合各自的理由、反证与失效条件自行判断。</div>
      <div className="conflict-grid">
        {pair.map((s) => (
          <div key={s.id} className={`conflict-card${s.id === cs.id ? ' current' : ''}`} data-testid={`conflict-card-${s.id}`}>
            <Space size={4}>
              <ActionBadge action={s.proposed_action} tLeg={s.t_leg} strategyName={s.strategy_name} />
              <b>{s.strategy_name}</b>
              <LifecycleBadge lifecycle={s.lifecycle} />
            </Space>
            <div className="small">{HORIZON[s.horizon]} · 规则满足度 <span className="mono">{s.score ?? '—'}</span> · <Tag color={SIGNAL_STATE[s.state].color}>{SIGNAL_STATE[s.state].text}</Tag></div>
            <div className="small muted">失效条件：{s.invalidation[0]?.text ?? '—'}</div>
            {s.id === cs.id ? <span className="muted small">（当前）</span> : <Link to={`/candidate-signals/${s.id}`}>查看</Link>}
          </div>
        ))}
      </div>
    </section>
  );
}

function Reasons({ cs }: { cs: CandidateSignal }) {
  const q = useSignalReasonsAll(cs.id);
  const release = useReleaseReason();
  const [target, setTarget] = useState<NonExecutableReason | null>(null);
  const [note, setNote] = useState('');
  const items = q.data?.items ?? [];
  const order = { active: 0, released: 1, obsolete: 2 } as const;
  const sorted = [...items].sort((a, b) => order[a.status] - order[b.status] || b.detected_at.localeCompare(a.detected_at));
  const open = (r: NonExecutableReason) => {
    release.reset();
    setNote('');
    setTarget(r);
  };
  return (
    <section className={`panel sig-panel sc-sec${items.some((r) => r.status === 'active') ? ' blocked' : ''}`} data-testid="signal-reasons">
      <h4>不可执行原因 · 解除条件 · 自动重评状态</h4>
      {q.isPending ? <Loading /> : q.isError ? <ErrorBox error={q.error} /> : sorted.length ? sorted.map((r) => <ReasonCard key={r.id} r={r} onRelease={isTerminal(cs.state) ? undefined : open} />) : <span className="muted small">没有不可执行原因</span>}
      <Modal
        open={!!target}
        title={target ? `手动解除：${REASON_CODE[target.code]}` : ''}
        okText="确认解除"
        okButtonProps={{ loading: release.isPending, 'data-testid': 'release-ok' } as ButtonProps}
        onOk={() => target && release.mutate({ id: target.id, note: note.trim() || null }, { onSuccess: () => setTarget(null) })}
        onCancel={() => setTarget(null)}
        destroyOnHidden
      >
        {target ? (
          <>
            <Alert type="warning" showIcon style={{ marginBottom: 8 }} title={`解除后系统会重新检查该候选信号。解除条件：${target.release_condition.human_text}`} />
            <Input.TextArea rows={3} maxLength={200} showCount value={note} onChange={(e) => setNote(e.target.value)} placeholder="可选：备注（会写入审计）" data-testid="release-note" />
            {release.isError ? <div className="error-text" style={{ marginTop: 8 }} data-testid="release-error">{errorText(release.error)}</div> : null}
          </>
        ) : null}
      </Modal>
    </section>
  );
}

function RuleRefs({ refs, evidence }: { refs: RuleRef[]; evidence: Evidence[] }) {
  return (
    <section className="panel sig-panel">
      <h4>规则引用（{refs.length}）</h4>
      <Table<RuleRef>
        size="small"
        rowKey={(r) => `${r.rule_id}-${r.role}`}
        dataSource={refs}
        pagination={false}
        locale={{ emptyText: '无规则引用' }}
        columns={[
          { title: '规则', dataIndex: 'rule_id', render: (v: string) => <span className="mono">{v}</span> },
          { title: '作用', dataIndex: 'role', width: 80, render: (v: RuleRef['role']) => RULE_ROLE[v] },
          { title: '维度', dataIndex: 'dimension', width: 90, render: (v: RuleRef['dimension']) => DIMENSION[v] },
          { title: '结果', dataIndex: 'passed', width: 90, render: (v: boolean | null) => <PassedTag passed={v} /> },
          { title: '值 / 阈值', key: 'vt', width: 120, render: (_v, r) => <span className="mono small">{r.value ?? '—'} / {r.threshold ?? '—'}</span> },
          { title: '证据', key: 'ev', render: (_v, r) => <EvidenceChips ids={r.evidence_ids} evidence={evidence} /> },
        ]}
      />
    </section>
  );
}

function TextBlocks({ cs }: { cs: CandidateSignal }) {
  return (
    <section className="panel sig-panel">
      <div className="sc-sec counter"><h4>反证</h4>{cs.counter_evidence.length ? cs.counter_evidence.map((r, i) => <div key={i} className="tw"><span>· {r.text}</span><EvidenceChips ids={r.evidence_ids} evidence={cs.evidence} /></div>) : <span className="muted small">无</span>}</div>
      <div className="sc-sec"><h4>失效条件</h4>{cs.invalidation.length ? cs.invalidation.map((r, i) => <div key={i} className="tw"><span>· {r.text}</span>{r.expr ? <code>{r.expr}</code> : null}<EvidenceChips ids={r.evidence_ids} evidence={cs.evidence} /></div>) : <span className="muted small">无</span>}</div>
      <div className="sc-sec">
        <h4>风险提示</h4>
        {cs.risk_flags.length ? cs.risk_flags.map((f, i) => (
          <div key={i} className="tw"><Tag color={RISK_LEVEL[f.level].color}>{RISK_LEVEL[f.level].text}</Tag>{RISK_CONTROL[f.control]}：{f.message}</div>
        )) : <span className="muted small">无</span>}
      </div>
    </section>
  );
}

function Actions({ cs }: { cs: CandidateSignal }) {
  const dismiss = useDismissSignal();
  const create = useCreatePlanDraft();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');
  const terminal = isTerminal(cs.state);
  return (
    <section className="panel sig-panel" data-testid="signal-actions">
      <h4>操作</h4>
      <Space wrap>
        <Tooltip title={canDraft(cs.state) ? '按你的持仓与资金拟定计划草案；草案需你确认，交易由你在券商端自行完成' : '仅“可拟定草案”或“原因已解除”状态可拟定计划草案'}>
          <Button
            size="small"
            disabled={!canDraft(cs.state)}
            loading={create.isPending}
            onClick={() => create.mutate([cs.id], { onSuccess: (d) => nav(`/plan-drafts/${d.id}`) })}
            data-testid="draft-btn"
          >
            拟定计划草案
          </Button>
        </Tooltip>
        <Button size="small" danger disabled={terminal} onClick={() => { dismiss.reset(); setNote(''); setOpen(true); }} data-testid="dismiss-btn">忽略该信号</Button>
      </Space>
      {create.isError ? <div className="error-text small" style={{ marginTop: 6 }} data-testid="draft-error">{errorText(create.error)}</div> : null}
      {cs.plan_draft_ids.length ? (
        <div className="small" style={{ marginTop: 6 }}>
          关联计划草案：{cs.plan_draft_ids.map((d) => <Link key={d} to={`/plan-drafts/${d}`} className="mono" style={{ marginRight: 6 }}>{d.slice(-8)}</Link>)}
        </div>
      ) : null}
      <Modal
        open={open}
        title="忽略该候选信号"
        okText="确认忽略"
        okButtonProps={{ danger: true, loading: dismiss.isPending, 'data-testid': 'dismiss-ok' } as ButtonProps}
        onOk={() => dismiss.mutate({ id: cs.id, note: note.trim() || null }, { onSuccess: () => setOpen(false) })}
        onCancel={() => setOpen(false)}
        destroyOnHidden
      >
        <div className="muted small" style={{ marginBottom: 8 }}>忽略后该信号结束，生效中的不可执行原因随之作废，不能恢复。</div>
        <Input.TextArea rows={3} maxLength={200} showCount value={note} onChange={(e) => setNote(e.target.value)} placeholder="可选：备注" data-testid="dismiss-note" />
        {dismiss.isError ? <div className="error-text" style={{ marginTop: 8 }} data-testid="dismiss-error">{errorText(dismiss.error)}</div> : null}
      </Modal>
    </section>
  );
}

/** 策略版本的跟踪统计：每个数字旁显示 n，样本少时加标记（契约 Stat） */
function Tracking({ cs }: { cs: CandidateSignal }) {
  const tpls = useStrategyTemplates();
  const tpl = tpls.data?.items.find((t) => t.key === cs.strategy_key);
  const q = useStrategyTracking(tpl?.id, cs.strategy_version_id);
  return (
    <section className="panel sig-panel" data-testid="signal-tracking">
      <h4>该策略版本的历史跟踪（我的）</h4>
      {tpl ? <div className="muted small">策略健康度样本 n={tpl.health.n}{tpl.health.n < 30 ? '（样本少）' : ''}</div> : null}
      {tpls.isError ? <ErrorBox error={tpls.error} /> : q.isError ? <ErrorBox error={q.error} /> : !q.data ? (tpls.data && !tpl ? <span className="muted small">策略库里没有该策略</span> : <Loading />) : (
        <div className="stat-wrap"><table className="stat-table">
          <thead><tr><th>持有期</th><th>胜率</th><th>平均收益</th><th>平均超额</th><th>盈亏比</th><th>最长连亏</th></tr></thead>
          <tbody>
            {q.data.by_horizon.map((h) => (
              <tr key={h.horizon_days} data-testid={`track-${h.horizon_days}`}>
                <td>{h.horizon_days} 日</td>
                <td><StatValue s={h.win_rate} /></td>
                <td><StatValue s={h.avg_return_pct} /></td>
                <td><StatValue s={h.avg_excess_pct} /></td>
                <td><StatValue s={h.profit_loss_ratio} kind="ratio" /></td>
                <td className="mono">{h.max_loss_streak}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
      <div className="muted small">历史统计不代表未来表现。</div>
    </section>
  );
}

function Events({ id }: { id: string }) {
  const q = useSignalEvents(id);
  return (
    <section className="panel sig-panel" data-testid="signal-events">
      <h4>状态历史</h4>
      {q.isPending ? <Loading /> : q.isError ? <ErrorBox error={q.error} /> : q.data.length ? (
        <Timeline
          items={q.data.map((e) => ({
            key: `${e.at}-${e.to}`,
            color: SIGNAL_STATE[e.to]?.color === 'default' ? 'gray' : 'blue',
            content: (
              <div className="small">
                <span className="mono">{fmtTime(e.at)}</span>　{e.from ? `${SIGNAL_STATE[e.from]?.text ?? e.from} → ` : ''}<b>{SIGNAL_STATE[e.to]?.text ?? e.to}</b>
                <div className="muted">{causeText(e.cause)}</div>
              </div>
            ),
          }))}
        />
      ) : <span className="muted small">暂无状态记录</span>}
    </section>
  );
}
