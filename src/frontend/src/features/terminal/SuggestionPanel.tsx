import { Button, Tag, Tooltip } from 'antd';
import { useNavigate } from 'react-router';
import { useActiveReasons, useCandidateSignals } from '../../api/queries';
import type { CandidateSignal, Suggestion, TerminalRow } from '../../api/types';
import { ActionBadge, ConfidenceTag, ErrorBox, Loading } from '../../components/common';
import { ACTION_FULL, ACTION_SHORT, HORIZON, REASON_CODE, RISK_CONTROL, RISK_LEVEL, SIGNAL_STATE } from '../../i18n/labels';

const shortAction = (a: keyof typeof ACTION_FULL) => ACTION_FULL[a].replace(/^规则信号：|（候选）$/g, '');

export function SuggestionPanel({ row, suggestion, loading, error }: { row: TerminalRow | undefined; suggestion: Suggestion | undefined; loading: boolean; error: unknown }) {
  const navigate = useNavigate();
  const cs = useCandidateSignals(row?.security_code);
  const reasons = useActiveReasons();
  const signalOf = (id: string | null): CandidateSignal | undefined => (id ? cs.data?.items.find((c) => c.id === id) : undefined);

  const head = (
    <div className="panel-head">
      <span className="panel-title">候选信号卡{row ? ` · ${row.name}` : ''}</span>
      {suggestion ? <a onClick={() => navigate(`/suggestions/${suggestion.id}`)}>完整详情 ›</a> : null}
    </div>
  );
  if (!row) return head;
  if (!row.suggestion) return <>{head}<div className="loading-box">暂无候选信号卡</div></>;
  if (error) return <>{head}<ErrorBox error={error} /></>;
  if (loading || !suggestion) return <>{head}<Loading /></>;
  const sg = suggestion;
  return (
    <>
      {head}
      <div className={`consensus-bar ${sg.consensus.status}`} data-testid="consensus-bar">
        {sg.consensus.status === 'divergent'
          ? `存在分歧（${sg.strategies.length} 个策略：${sg.strategies.map((s) => ACTION_SHORT[s.action]).join(' / ')}）· 并列展示，不合并`
          : sg.consensus.status === 'unanimous'
            ? `各策略一致：${shortAction(sg.strategies[0].action)}`
            : sg.consensus.status === 'single' ? '仅 1 个策略实例' : '暂无启用的策略实例'}
      </div>
      <div className="right-scroll">
        {sg.strategies.map((s) => {
          const sig = signalOf(s.candidate_signal_id);
          const rs = (reasons.data?.items ?? []).filter((r) => r.signal_id === s.candidate_signal_id);
          return (
            <div key={s.strategy_version_id} className="strat-mini">
              <div className="sm-head">
                <ActionBadge action={s.action} tLeg={s.t_leg} size="lg" />
                <span className="sm-name">{s.strategy_name}</span>
                <span className="muted small">{HORIZON[s.horizon]} · v{s.version_no}</span>
              </div>
              <div className="sm-row">
                <span>满足度 <b className="mono">{s.score ?? '—'}</b></span>
                <ConfidenceTag c={s.confidence} />
                {s.priority_downweighted ? <Tooltip title="因近期模拟跟踪表现降低排序优先级，不改变动作"><Tag>权重 {s.priority_weight}</Tag></Tooltip> : null}
              </div>
              <div className="sm-row mono small">
                止损 <b className="down">{s.stops.stop_loss ?? '—'}</b>　止盈 <b className="up">{s.stops.take_profit ?? '—'}</b>
                {sig ? <Tag color={SIGNAL_STATE[sig.state].color} style={{ marginLeft: 'auto' }}>{SIGNAL_STATE[sig.state].text}</Tag> : <span className="muted" style={{ marginLeft: 'auto' }}>不生成候选信号</span>}
              </div>
              <div className="sm-reason small">理由：{s.reasons[0]?.text ?? '—'}</div>
              <div className="sm-counter small">反证：{s.counter_evidence[0]?.text ?? '—'}</div>
              <div className="small muted">失效：{s.invalidation[0]?.text ?? '—'}</div>
              {rs.map((r) => (
                <div key={r.id} className="sm-block small">
                  不可执行：{REASON_CODE[r.code]}<span className="muted">（解除条件：{r.release_condition.human_text}）</span>
                </div>
              ))}
            </div>
          );
        })}
        {sg.risk_flags.length ? (
          <div className="risk-mini">
            {sg.risk_flags.map((f, i) => (
              <div key={i} className="small"><Tag color={RISK_LEVEL[f.level].color}>{RISK_CONTROL[f.control]}</Tag>{f.message}</div>
            ))}
          </div>
        ) : null}
        {sg.gaps.length ? <div className="gap-mini small">数据缺口：{sg.gaps.map((g) => g.message).join('；')}</div> : null}
      </div>
      <div className="right-actions">
        <Button size="small" onClick={() => navigate(`/suggestions/${sg.id}`)}>维度 × 策略矩阵</Button>
        <Tooltip title="计划草案接口（POST /plan-drafts）在后续任务接入">
          <Button size="small" type="primary" disabled>拟定计划草案</Button>
        </Tooltip>
      </div>
    </>
  );
}
