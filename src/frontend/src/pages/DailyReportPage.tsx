import { Alert, Select, Tag } from 'antd';
import { Navigate, useNavigate, useParams } from 'react-router';
import { useDailyReport, useDailyReports } from '../api/queries';
import type { DailyReport, TextWithEvidence } from '../api/types';
import { ActionBadge, ConsensusBadge, DataStatusTag, ErrorBox, Loading } from '../components/common';
import { EvidenceChips } from '../components/EvidenceChips';
import { DIMENSION, EXECUTABILITY, GAP_REASON, RECONCILIATION, REGIME } from '../i18n/labels';
import { fmtNum, fmtTime, pctClass, signed } from '../lib/format';

const CHANGE = { new: { t: '新增', c: 'blue' }, changed: { t: '有变化', c: 'orange' }, unchanged: { t: '无变化', c: 'default' }, removed: { t: '已移出', c: 'default' } } as const;
const VS_REGIME = { below: '低于参考区间', within: '在参考区间内', above: '高于参考区间' } as const;

function Lines({ items, r }: { items: TextWithEvidence[]; r: DailyReport }) {
  if (!items.length) return <span className="muted small">无</span>;
  return <>{items.map((x, i) => <div key={i} className="tw small"><span>· {x.text}</span><EvidenceChips ids={x.evidence_ids} evidence={r.evidence} /></div>)}</>;
}

/** /daily-reports：跳到最新一期 */
export function DailyReportIndex() {
  const list = useDailyReports();
  if (list.isLoading) return <Loading />;
  if (list.isError) return <ErrorBox error={list.error} />;
  const latest = list.data?.items[0];
  return latest ? <Navigate to={`/daily-reports/${latest.date}`} replace /> : <div className="loading-box">暂无日报</div>;
}

export function DailyReportPage() {
  const { date } = useParams();
  const navigate = useNavigate();
  const list = useDailyReports();
  const q = useDailyReport(date);
  if (q.isLoading) return <Loading />;
  if (q.isError || !q.data) return <div className="page-scroll"><ErrorBox error={q.error ?? new Error('未找到日报')} /></div>;
  const r = q.data;
  const a = r.account;
  const range = r.market.regime_position_range;
  const lo = range ? Number(range.min_pct) : 0;
  const hi = range ? Number(range.max_pct) : 0;
  const rec = RECONCILIATION[r.reconciliation.status];
  return (
    <div className="page-scroll report" data-testid="daily-report">
      <div className="detail-head">
        <span className="q-name">盘后日报</span>
        <Select
          size="small" value={r.date} style={{ width: 130 }} aria-label="选择日期"
          options={(list.data?.items ?? []).map((x) => ({ value: x.date, label: x.date }))}
          onChange={(d) => navigate(`/daily-reports/${d}`)}
        />
        <Tag>不可变快照</Tag>
        <DataStatusTag status={r.data_status} asOf={r.data_as_of} gaps={r.gaps} />
        <span className="muted small">生成于 {fmtTime(r.generated_at)} · 数据截至 {fmtTime(r.data_as_of)} · 说明来源：{r.explanation.source === 'template' ? '模板' : 'LLM'}</span>
      </div>
      <div className="report-summary">{r.explanation.text}</div>
      {r.gaps.length ? (
        <Alert
          className="gap-alert" type="warning" showIcon
          title={`数据缺口 ${r.gaps.length} 项（缺失不臆测；相关维度标为“未知”）`}
          description={<div className="gap-grid">{r.gaps.map((g) => <div key={g.key}><Tag>{GAP_REASON[g.reason]}</Tag><span className="mono muted small">{g.key}</span>　{g.message}</div>)}</div>}
        />
      ) : null}

      <div className="report-top">
        <section className="panel acct">
          <div className="panel-head"><span className="panel-title">账户概览</span><Tag color={rec.color}>{rec.text}{r.reconciliation.diff_count ? ` · ${r.reconciliation.diff_count} 处差异` : ''}</Tag></div>
          {a ? (
            <>
              <div className="stat-grid">
                <div><label>总资产</label><b className="mono">{fmtNum(a.total_assets)}</b></div>
                <div><label>现金</label><b className="mono">{fmtNum(a.cash)}</b></div>
                <div><label>总仓位</label><b className="mono">{fmtNum(a.position_pct, 1)}%</b></div>
                <div><label>当日盈亏</label><b className={`mono ${pctClass(a.pnl_day)}`}>{signed(a.pnl_day)}</b></div>
              </div>
              <div className="regime">
                <div className="small">
                  大盘环境 <Tag color="blue">{r.market.regime ? REGIME[r.market.regime] : '未知'}</Tag>
                  {range ? `参考仓位区间 ${lo}–${hi}%` : ''}{a.position_vs_regime ? ` · 当前${VS_REGIME[a.position_vs_regime]}` : ''}
                </div>
                {range ? (
                  <div className="regime-bar">
                    <div className="band" style={{ left: `${lo}%`, width: `${hi - lo}%` }} />
                    <div className="mark" style={{ left: `${Number(a.position_pct)}%` }} />
                  </div>
                ) : null}
              </div>
            </>
          ) : <div className="muted small">未选择账户</div>}
        </section>
        <section className="panel expo">
          <div className="panel-head"><span className="panel-title">市场</span></div>
          {r.market.breadth ? (
            <div className="small mono">上涨 <b className="up">{r.market.breadth.up}</b> · 下跌 <b className="down">{r.market.breadth.down}</b> · 涨停 {r.market.breadth.limit_up} · 跌停 {r.market.breadth.limit_down}</div>
          ) : <div className="muted small">市场宽度：缺失</div>}
          <Lines items={r.market.summary} r={r} />
        </section>
        <section className="panel acct-risk">
          <div className="panel-head"><span className="panel-title">待处理</span></div>
          <div className="small">计划草案 <b className="mono">{r.pending.plan_drafts}</b> 份 · 未解除的不可执行原因 <b className="mono">{r.pending.active_reasons}</b> 项</div>
        </section>
      </div>

      <div className="panel-head section-gap"><span className="panel-title">逐股卡片（持仓 + 自选，共 {r.stocks.length} 只）</span><span className="muted small">各策略结论并列；点击卡片进入候选信号卡</span></div>
      <div className="stock-grid">
        {r.stocks.map((s) => (
          <section
            key={s.security_code}
            className={`panel stock-card ${s.change_from_previous === 'removed' ? 'dim' : ''}`}
            onClick={() => s.suggestion_id && navigate(`/suggestions/${s.suggestion_id}`)}
          >
            <div className="stc-head">
              <b>{s.name}</b><span className="mono muted small">{s.security_code}</span>
              <Tag color={CHANGE[s.change_from_previous].c}>{CHANGE[s.change_from_previous].t}</Tag>
              <span className="spacer" />
              {s.suggestion ? <ConsensusBadge status={s.suggestion.consensus} /> : null}
            </div>
            {s.suggestion?.actions.length ? (
              <div className="badges">{s.suggestion.actions.map((x) => <ActionBadge key={x.strategy_key} action={x.action} strategyName={x.strategy_name} tLeg={x.t_leg} />)}</div>
            ) : <div className="small muted">暂无启用的策略实例</div>}
            {s.suggestion ? (
              <div className="small muted">
                {EXECUTABILITY[s.suggestion.executability_status].text}
                {s.suggestion.top_score != null ? ` · 最高满足度 ${s.suggestion.top_score}` : ''}
                {s.suggestion.divergent_dimensions.length ? ` · 分歧维度：${s.suggestion.divergent_dimensions.map((d) => DIMENSION[d]).join('、')}` : ''}
              </div>
            ) : null}
            <div className="stc-sec"><b className="small">要点</b><Lines items={s.highlights} r={r} /></div>
            <div className="stc-sec stc-inv"><b className="small">失效条件</b><Lines items={s.invalidation} r={r} /></div>
            <div className="stc-sec"><b className="small">次日关注</b><Lines items={s.next_watch} r={r} /></div>
          </section>
        ))}
      </div>
    </div>
  );
}
