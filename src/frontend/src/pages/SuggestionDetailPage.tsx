import { CAP_KIND_TEXT, HORIZON_DATA_MISSING, capExplanation, horizonDataMissing, noSuitableForLackOfData } from '../i18n/horizonCaps';
import { Alert, Button, Input, Modal, Select, Tag, Tooltip } from 'antd';
import { useState } from 'react';
import { ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons';
import { Link, useNavigate, useParams } from 'react-router';
import { useCandidateSignals, useSuggestionReasons, useHorizonAssessment, useSuggestion, useSuggestions } from '../api/queries';
import { ENUMS } from '../api/enums';
import type { DimensionMatrixRow, Evidence, StrategyConclusion, Suggestion } from '../api/types';
import { DataGrid, type DataColumn } from '../components/DataGrid';
import { ActionBadge, ConfidenceTag, ConsensusBadge, DataStatusTag, ErrorBox, Loading } from '../components/common';
import { EvidenceChips } from '../components/EvidenceChips';
import { CardDisclaimer } from '../components/RiskDisclosure';
import {
  ACTION_SHORT, CHECK_ON, DIMENSION, EPISTEMIC, EVAL_STATE, EXECUTABILITY, GAP_REASON, HORIZON, LIFECYCLE, ORIGIN, REASON_CODE,
  RELEASE_KIND, RISK_CONTROL, RISK_LEVEL, SIGNAL_STATE, SUGGESTION_STATUS, VIEW,
} from '../i18n/labels';
import { fmtTime, providerText, ruleCountText } from '../lib/format';
import { AddToResearch } from '../features/research/AddToResearch';
import { useCreatePlanDraft } from '../api/planQueries';
import { useMarkViewed, useRefreshSuggestion, useSuggestionAction, useSuggestionTracking } from '../api/suggestionQueries';
import { canDraft } from '../lib/signals';
import { stateErrorText } from '../lib/stateTransition';
import { errorText } from '../api/errorPolicy';
import { StatValue } from '../components/StatValue';
import { PendingContract } from '../components/PendingContract';
import { RuleRefs } from './signals/CandidateSignalDetailPage';

function matrixColumns(sg: Suggestion): DataColumn<DimensionMatrixRow>[] {
  return [
    { key: 'dimension', header: '维度', width: 96, pinned: 'left', sortable: false, render: (r) => <b>{DIMENSION[r.dimension]}{r.divergent ? <Tag color="orange" style={{ marginLeft: 4 }}>分歧</Tag> : null}</b> },
    ...sg.strategies.map<DataColumn<DimensionMatrixRow>>((s) => ({
      key: s.strategy_version_id,
      header: `${s.strategy_name} · ${ACTION_SHORT[s.action]}`,
      flex: 1,
      sortable: false,
      tooltip: (r) => {
        const dv = s.dimension_views.find((v) => v.dimension === r.dimension);
        return dv?.rules.map((x) => `${x.rule_id}: ${x.value ?? '—'} / ${x.threshold ?? '—'} ${x.passed === null ? '?（无法判断）' : x.passed ? '✓' : '✗'}`).join('\n') || undefined;
      },
      render: (r) => {
        const c = r.cells.find((x) => x.strategy_version_id === s.strategy_version_id);
        if (!c) return <span className="muted">—</span>;
        return (
          <div className={`mx-cell v-${c.view}`}>
            <span className="mx-view" style={{ color: VIEW[c.view].color }}>{VIEW[c.view].text}</span>
            <span className="mono mx-score">{c.score ?? '—'}</span>
            <span className="mono muted small">{ruleCountText(c)}</span>
            <EvidenceChips ids={c.key_evidence_ids} evidence={sg.evidence} />
          </div>
        );
      },
    })),
  ];
}

const evidenceColumns: DataColumn<Evidence>[] = [
  { key: 'id', header: 'ID', width: 56, value: (e) => e.id },
  { key: 'key', header: '指标 key', width: 220, value: (e) => e.key, render: (e) => <span className="mono">{e.key}</span> },
  { key: 'value', header: '值', width: 120, sortable: false, render: (e) => <span className="mono">{String(e.value)}{e.unit ? ` ${e.unit}` : ''}</span> },
  { key: 'type', header: '类型', width: 70, sortable: false, render: (e) => <Tag color={EPISTEMIC[e.epistemic_type].color}>{EPISTEMIC[e.epistemic_type].text}</Tag> },
  { key: 'src', header: '来源', flex: 1, sortable: false, render: (e) => <span className="mono small">{providerText(e)}</span> },
  { key: 'asof', header: '数据时间', width: 130, value: (e) => e.data_as_of, render: (e) => <span className="mono small">{fmtTime(e.data_as_of)}</span> },
  { key: 'fetched', header: '抓取时间', width: 130, value: (e) => e.fetched_at, render: (e) => <span className="mono small">{fmtTime(e.fetched_at)}</span> },
];

/**
 * 头部“适合周期”：suitable 为空时不显示为“都不适合”——周期分类有 data_missing 封顶则显示“数据不足”（T-B46/T-B47 R8/R9），
 * 否则显示“—”。周期分类与卡片共用同一个查询缓存。
 */
function SuitableHorizons({ sg }: { sg: Suggestion }) {
  const q = useHorizonAssessment(sg.security_code);
  const list = sg.horizon_assessment.suitable;
  return (
    <span className="small" data-testid="sg-suitable">适合周期：{list.length ? list.map((h) => <Tag key={h}>{HORIZON[h]}</Tag>)
      : q.data && noSuitableForLackOfData(q.data) ? <Tag data-testid="sg-hz-data-missing">{HORIZON_DATA_MISSING}</Tag> : <span className="muted">—</span>}
    </span>
  );
}

/** v0.2.2/v0.2.3 周期分类：按周期分组展示“支持 / 不支持”理由与缺失输入 */
function HorizonPanel({ sg }: { sg: Suggestion }) {
  const q = useHorizonAssessment(sg.security_code);
  const a = q.data;
  return (
    <div data-testid="horizon-panel">
      <div className="panel-head">
        <span className="panel-title">周期分类</span>
        {a ? <span className="muted small">{a.classifier_version}</span> : null}
        {a && a.snapshot_id !== sg.snapshot_id ? <span className="muted small" data-testid="hz-newer-snapshot">周期分类基于较新快照</span> : null}
      </div>
      {q.isLoading ? <div className="muted small">加载中…</div> : q.isError || !a ? <div className="muted small">周期分类暂不可用</div> : (
        <div className="hz-list small">
          {ENUMS.horizon.map((h) => {
            const rs = a.reasons.filter((x) => x.horizon === h);
            return (
              <div key={h} className="hz-row">
                <div><Tag color={a.suitable.includes(h) ? 'blue' : undefined}>{HORIZON[h]}</Tag><span className="mono">{a.scores[h]}</span>
                  {a.suitable.includes(h) ? <span className="muted">　适合</span>
                    : horizonDataMissing(a, h) ? <span className="muted" data-testid={`hz-dm-${h}`}>　{HORIZON_DATA_MISSING}</span> : null}</div>
                {(['for', 'against'] as const).map((pol) => rs.filter((x) => x.polarity === pol).map((x, i) => (
                  <div key={`${pol}-${i}`} className={`hz-reason ${pol}`}>
                    <span className="hz-pol">{pol === 'for' ? '支持' : '不支持'}</span>{x.text}
                    <EvidenceChips ids={x.evidence_ids} evidence={a.evidence} />
                  </div>
                )))}
              </div>
            );
          })}
          {a.caps.map((c, i) => (
            <div key={`cap-${i}`} className="hz-missing" data-testid={`cap-${c.horizon}-${c.rule_id ?? "missing"}`}>
              {HORIZON[c.horizon]} 封顶 {c.cap}（{CAP_KIND_TEXT[c.kind]}）：{capExplanation(c)}
              {c.rule_id ? <span className="mono muted">（{c.rule_id}）</span> : null}
            </div>
          ))}
          {/* v0.2.5 #2/#3：画像类规则只提示，不影响分数与 suitable */}
          {(a.hints ?? []).map((h, i) => (
            <div key={`hint-${i}`} className="hz-hint" data-testid={`hint-${h.horizon}-${h.rule_id}`}>
              {HORIZON[h.horizon]} 提示：{h.text}<span className="mono muted">（{h.rule_id}）</span>
            </div>
          ))}
          {a.inputs_missing.length ? (
            <div className="hz-missing">缺失输入（相关周期分数按封顶处理，不是真 0 分）：<span className="mono">{a.inputs_missing.join('、')}</span></div>
          ) : null}
        </div>
      )}
    </div>
  );
}

function StrategyCard({ s, sg }: { s: StrategyConclusion; sg: Suggestion }) {
  const signals = useCandidateSignals(sg.security_code);
  const reasons = useSuggestionReasons(sg.id);
  const sig = s.candidate_signal_id ? signals.data?.items.find((c) => c.id === s.candidate_signal_id) : undefined;
  const create = useCreatePlanDraft();
  const nav = useNavigate();
  const [showRules, setShowRules] = useState(false);
  // v0.2.9 #12：生效中的在前，其后是已解除的；已作废（所属信号已结束）不显示
  const rs = (reasons.data?.items ?? []).filter((r) => r.signal_id === s.candidate_signal_id && r.status !== 'obsolete')
    .sort((a, b) => (a.status === 'active' ? 0 : 1) - (b.status === 'active' ? 0 : 1));
  return (
    <section className="panel strat-card" data-testid="strategy-card">
      <div className="sc-head">
        <ActionBadge action={s.action} tLeg={s.t_leg} size="lg" />
        <div>
          <div className="sc-name">{s.strategy_name}</div>
          <div className="muted small">{HORIZON[s.horizon]} · v{s.version_no} · {LIFECYCLE[s.lifecycle]} · {EVAL_STATE[s.state]}{s.priority_downweighted ? ` · 优先级权重 ${s.priority_weight}` : ''}</div>
        </div>
        <span className="spacer" />
        {sig ? <Link to={`/candidate-signals/${sig.id}`} data-testid="to-signal"><Tag color={SIGNAL_STATE[sig.state].color}>{SIGNAL_STATE[sig.state].text}</Tag>候选信号详情</Link> : <Tag>不生成候选信号</Tag>}
      </div>
      <div className="sc-metrics">
        <div><label>规则满足度</label><b className="mono">{s.score ?? '—'}</b></div>
        <div><label>置信度</label><ConfidenceTag c={s.confidence} /></div>
        <div><label>止损</label><b className="mono down">{s.stops.stop_loss ?? '—'}</b></div>
        <div><label>止盈</label><b className="mono up">{s.stops.take_profit ?? '—'}</b></div>
        <div><label>时间止损</label><b className="mono">{s.stops.time_stop_days != null ? `${s.stops.time_stop_days} 日` : '—'}</b></div>
        <div><label>有效至</label><b className="mono small">{s.valid_until ? fmtTime(s.valid_until).slice(5) : '—'}</b></div>
      </div>
      <div className="sc-sec"><h4>理由</h4>{s.reasons.map((r, i) => <div key={i} className="tw"><span>· {r.text}</span><EvidenceChips ids={r.evidence_ids} evidence={sg.evidence} /></div>)}</div>
      <div className="sc-sec counter"><h4>反证</h4>{s.counter_evidence.length ? s.counter_evidence.map((r, i) => <div key={i} className="tw"><span>· {r.text}</span><EvidenceChips ids={r.evidence_ids} evidence={sg.evidence} /></div>) : <span className="muted small">无</span>}</div>
      <div className="sc-sec"><h4>失效条件</h4>{s.invalidation.map((r, i) => <div key={i} className="tw"><span>· {r.text}</span><EvidenceChips ids={r.evidence_ids} evidence={sg.evidence} /></div>)}</div>
      {rs.length ? (
        <div className="sc-sec blocked">
          <h4>不可执行原因 · 解除条件</h4>
          {rs.map((r) => (
            <div key={r.id} className={`reason reason-${r.status}`} data-testid={`sg-reason-${r.id}`}>
              <div>{r.status === 'released' ? <Tag color="green">已解除</Tag> : null}<Tag color={r.status === 'active' ? 'orange' : 'default'}>{r.code}</Tag><b>{REASON_CODE[r.code]}</b>：{r.description}</div>
              <div className="rc">
                解除条件（{RELEASE_KIND[r.release_condition.kind]}）：{r.release_condition.human_text}
                {r.release_condition.expr ? <code>{r.release_condition.expr}</code> : null}
              </div>
              <div className="muted small">检查时机：{r.release_condition.check_on.map((c) => CHECK_ON[c]).join('、')} · {r.release_condition.machine_checkable ? '系统自动检查' : '需您操作'} · 检出 {fmtTime(r.detected_at).slice(11)}{r.released_at ? ` · 解除 ${fmtTime(r.released_at).slice(11)}` : ''}</div>
            </div>
          ))}
        </div>
      ) : null}
      <div className="sc-foot">
        <Button size="small" type="link" onClick={() => setShowRules((v) => !v)} data-testid={`sg-rules-toggle-${s.strategy_key}`}>
          规则引用 {s.rule_refs.length} 条{s.model_refs.length ? ` · 模型 ${s.model_refs.length}` : ''}{showRules ? '（收起）' : '（展开）'}
        </Button>
        <span className="spacer" />
        {/* T-F12：只对本策略生成的候选信号拟定草案（POST /plan-drafts {signal_ids}，§7）；状态不允许时禁用并说明 */}
        <Tooltip title={!sig ? '本策略没有候选信号，不能拟定计划草案' : canDraft(sig.state) ? '按你的持仓与资金拟定计划草案；草案需你确认，交易由你在券商端自行完成' : `候选信号为“${SIGNAL_STATE[sig.state].text}”，仅“可拟定草案”或“原因已解除”状态可拟定`}>
          <Button
            size="small"
            disabled={!sig || !canDraft(sig.state) || sg.status !== 'active'}
            loading={create.isPending}
            onClick={() => sig && create.mutate([sig.id], { onSuccess: (d) => nav(`/plan-drafts/${d.id}`) })}
            data-testid={`sg-draft-${s.strategy_key}`}
          >
            拟定计划草案
          </Button>
        </Tooltip>
      </div>
      {create.isError ? <div className="error-text small" data-testid={`sg-draft-error-${s.strategy_key}`}>{stateErrorText(create.error, 'signal')}</div> : null}
      {showRules ? <RuleRefs refs={s.rule_refs} evidence={sg.evidence} /> : null}
    </section>
  );
}

export function SuggestionDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const q = useSuggestion(id);
  const list = useSuggestions();
  const refresh = useRefreshSuggestion();
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  useMarkViewed(q.data?.id);
  if (q.isLoading) return <Loading />;
  if (q.isError || !q.data) return <div className="page-scroll"><ErrorBox error={q.error ?? new Error('未找到候选信号卡')} /></div>;
  const sg = q.data;
  const exe = EXECUTABILITY[sg.executability.status];
  return (
    <div className="page-scroll detail" data-testid="suggestion-detail">
      <div className="detail-head">
        <Button size="small" icon={<ArrowLeftOutlined />} onClick={() => navigate('/terminal')}>终端</Button>
        <Select
          size="small" value={sg.id} style={{ width: 190 }} aria-label="切换证券"
          options={(list.data?.items ?? []).map((s) => ({ value: s.id, label: `${s.name} ${s.security_code}` }))}
          onChange={(v) => navigate(`/suggestions/${v}`)}
        />
        <span className="q-name">{sg.name}</span>
        <span className="mono muted">{sg.security_code}</span>
        <DataStatusTag status={sg.data_status} asOf={sg.data_as_of} gaps={sg.gaps} />
        <span className="muted small">候选信号卡 · {ORIGIN[sg.origin]} · 生成 {fmtTime(sg.created_at)} · 快照 {sg.snapshot_id} · {sg.feature_set_version}</span>
        <AddToResearch origin="suggestion" securityCode={sg.security_code} suggestionId={sg.id} />
        <Tag color={SUGGESTION_STATUS[sg.status].color} data-testid="sg-status">{SUGGESTION_STATUS[sg.status].text}</Tag>
        <Tooltip title="按已缓存的数据重算本证券的候选信号卡，不额外拉取行情">
          <Button
            size="small" icon={<ReloadOutlined />} loading={refresh.isPending} data-testid="sg-refresh"
            onClick={() => {
              setRefreshMsg(null);
              refresh.mutate(sg.security_code, {
                onSuccess: (newId) => {
                  if (newId && newId !== sg.id) navigate(`/suggestions/${newId}`);
                  else setRefreshMsg('已重算，当前卡没有变化');
                },
              });
            }}
          >
            刷新
          </Button>
        </Tooltip>
        <span className="spacer" />
        <SuitableHorizons sg={sg} />
        <ConsensusBadge status={sg.consensus.status} actions={sg.consensus.actions} />
        <Tag color={exe.color}>{exe.text}{sg.executability.reason_ids.length ? `（${sg.executability.reason_ids.length} 项原因）` : ''}</Tag>
      </div>

      {refresh.isError ? <Alert type="error" showIcon className="div-alert" data-testid="sg-refresh-error" title={errorText(refresh.error)} /> : null}
      {refreshMsg ? <Alert type="info" showIcon className="div-alert" data-testid="sg-refresh-msg" title={refreshMsg} /> : null}
      <SupersedeInfo sg={sg} />

      {sg.divergence.length ? (
        <Alert
          className="div-alert" type="warning" showIcon
          title={<span><b>存在分歧，不合并为单一结论</b>：各策略并列展示，请结合您的计划条件自行判断。</span>}
          description={
            <div className="div-list">
              {sg.divergence.map((d, i) => (
                <div key={i}>
                  <Tag color="orange">{d.dimensions.map((x) => DIMENSION[x]).join(' / ')}</Tag>{d.summary}
                  <span className="muted">　能化解分歧的信息：</span>{d.resolving_info.map((r) => r.description).join('；')}
                </div>
              ))}
            </div>
          }
        />
      ) : null}

      <div className="detail-grid">
        <section className="panel matrix-panel">
          <div className="panel-head"><span className="panel-title">六维度 × 策略矩阵</span><span className="muted small">单元格 = 维度观点 · 维度分 · 规则通过数 · 关键证据；悬停看规则阈值</span></div>
          {sg.strategies.length ? (
            <div style={{ height: 6 * 44 + 34 }}>
              <DataGrid<DimensionMatrixRow>
                testId="matrix"
                rows={sg.dimension_matrix}
                columns={matrixColumns(sg)}
                getRowId={(r) => r.dimension}
                rowClass={(r) => (r.divergent ? 'row-diverged' : undefined)}
                rowHeight={44}
              />
            </div>
          ) : <Alert type="info" title="暂无启用的策略实例，仅展示行情与数据状态" />}
        </section>
        <section className="panel side-panel">
          <div className="panel-head"><span className="panel-title">风控标记</span></div>
          {sg.risk_flags.length ? sg.risk_flags.map((f, i) => (
            <div key={i} className={`risk-row lv-${f.level}`}>
              <Tag color={RISK_LEVEL[f.level].color}>{RISK_LEVEL[f.level].text}</Tag><b>{RISK_CONTROL[f.control]}</b>　{f.message}
              {f.gated_actions.length ? <div className="muted small">受限动作：{f.gated_actions.map((a) => ACTION_SHORT[a]).join('、')}{f.quantity_cap != null ? ` · 数量上限 ${f.quantity_cap}` : ''}</div> : null}
            </div>
          )) : <div className="muted small">无</div>}
          <div className="panel-head"><span className="panel-title">数据缺口</span></div>
          {sg.gaps.length ? sg.gaps.map((g) => <div key={g.key} className="gap-row small"><Tag>{GAP_REASON[g.reason]}</Tag>{g.message}</div>) : <div className="muted small">无</div>}
          <HorizonPanel sg={sg} />
          <div className="panel-head"><span className="panel-title">说明（{sg.explanation.source === 'template' ? '模板生成' : 'LLM 生成'}）</span></div>
          <div className="small explain">{sg.explanation.text}</div>
          {sg.explanation.source === 'llm' && sg.explanation.llm_call_id ? (
            <div className="muted small" data-testid="sg-llm-call">LLM 调用记录 <span className="mono">{sg.explanation.llm_call_id}</span>（仅改写已有证据；引用格式待契约）</div>
          ) : null}
        </section>
      </div>

      <div className="panel-head section-gap"><span className="panel-title">各策略结论（并列，不合并）</span><span className="muted small">动作均为规则信号，需结合您的计划条件判断</span></div>
      <div className="strat-grid" style={{ gridTemplateColumns: `repeat(${Math.max(1, Math.min(4, sg.strategies.length))}, minmax(0, 1fr))` }}>
        {sg.strategies.map((s) => <StrategyCard key={s.strategy_version_id} s={s} sg={sg} />)}
      </div>

      <FollowUp sg={sg} />

      <div className="panel-head section-gap"><span className="panel-title">证据（时间 + 来源）</span><span className="muted small">事实 / 估计 / 假设 / 执行 四类分开标注</span></div>
      <section className="panel" style={{ height: Math.min(12, sg.evidence.length) * 28 + 34 }}>
        <DataGrid<Evidence> testId="evidence" rows={sg.evidence} columns={evidenceColumns} getRowId={(e) => e.id} />
      </section>
      <CardDisclaimer />
    </div>
  );
}

/** 取代链（§5.2 supersedes_id / superseded_by_id）：非当前卡给出提示与去当前卡的链接；完整链 /chain 的响应结构待契约 */
function SupersedeInfo({ sg }: { sg: Suggestion }) {
  return (
    <>
      {sg.status !== 'active' ? (
        <Alert
          className="div-alert" type={sg.status === 'invalidated' ? 'error' : 'warning'} showIcon data-testid="sg-inactive"
          title={<span>本卡{SUGGESTION_STATUS[sg.status].text}，内容仅供回看，不能据此拟定计划草案。</span>}
          description={sg.superseded_by_id ? <Link to={`/suggestions/${sg.superseded_by_id}`} data-testid="sg-superseded-by">查看取代它的候选信号卡</Link> : null}
        />
      ) : null}
      <div className="muted small sg-chain" data-testid="sg-chain">
        {sg.supersedes_id ? <span>取代了 <Link to={`/suggestions/${sg.supersedes_id}`} data-testid="sg-supersedes">上一张卡</Link></span> : <span>没有上一张卡</span>}
        <PendingContract testId="sg-chain-placeholder" what="完整取代链（/suggestions/{id}/chain 的响应结构）" />
      </div>
    </>
  );
}

/** 跟踪统计（GET /suggestions/{id}/tracking）与用户动作（POST /suggestions/{id}/actions） */
function FollowUp({ sg }: { sg: Suggestion }) {
  const tr = useSuggestionTracking(sg.id);
  const act = useSuggestionAction(sg.id);
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');
  const [done, setDone] = useState(false);
  return (
    <div className="sg-follow">
      <section className="panel" data-testid="sg-tracking">
        <div className="panel-head"><span className="panel-title">事后跟踪（本卡出现后的表现）</span><span className="muted small">每个数字旁是样本量 n；样本少时只作参考</span></div>
        {tr.isLoading ? <div className="muted small">加载中…</div> : tr.isError || !tr.data ? <div className="muted small">跟踪统计暂不可用</div> : (
          <div className="sg-track-grid">
            {(['t1', 't5', 't20'] as const).map((k) => (
              <div key={k}><label>{k === 't1' ? '1 日后' : k === 't5' ? '5 日后' : '20 日后'}</label><StatValue s={tr.data[k]} kind="ratio" testId={`sg-track-${k}`} /></div>
            ))}
          </div>
        )}
        <div className="muted small">数值按服务端原值显示（单位与口径待契约）；窗口：{tr.data?.t1.window ?? '—'}</div>
        <PendingContract testId="sg-track-basis" what="各期的价格依据" />
      </section>
      <section className="panel" data-testid="sg-actions">
        <div className="panel-head"><span className="panel-title">我的处理</span></div>
        {done ? <div className="small" data-testid="sg-dismissed">已记录：不再关注本卡</div> : (
          <Button size="small" onClick={() => setOpen(true)} data-testid="sg-dismiss">不再关注本卡</Button>
        )}
        <div className="muted small">只记录你的处理，不改变卡片内容；查看会自动记录一次。</div>
        <PendingContract testId="sg-trade-link-placeholder" what="关联我的成交（acted_trade_linked 的入口与 note 规则）" />
      </section>
      <Modal
        open={open} title="不再关注本卡" okText="记录" cancelText="取消" confirmLoading={act.isPending}
        onCancel={() => setOpen(false)}
        onOk={() => act.mutate({ kind: 'dismissed', note: note.trim() || null }, { onSuccess: () => { setOpen(false); setDone(true); } })}
      >
        <Input.TextArea rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="备注（可不填）" data-testid="sg-dismiss-note" />
        {act.isError ? <div className="error-text" style={{ marginTop: 8 }} data-testid="sg-dismiss-error">{errorText(act.error)}</div> : null}
      </Modal>
    </div>
  );
}
