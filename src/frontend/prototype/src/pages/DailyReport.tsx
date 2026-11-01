import { Alert, Progress, Select, Tag } from 'antd';
import { DAILY_REPORT, STRATEGIES } from '../mock/data';
import { GAP_REASON, HORIZON, REASON_CODE, REGIME, RISK_CONTROL, RISK_LEVEL } from '../labels';
import { ActionBadge, ConfidenceTag, ConsensusBadge, DataStatusTag, fmtNum, fmtTime, pctClass, signed } from '../components/common';
import { go } from '../router';

const RECON = { matched: { t: '已对账一致', c: 'green' }, diff: { t: '对账存在差异', c: 'orange' }, not_imported: { t: '未导入交割单', c: 'default' } } as const;

export function DailyReport({ date }: { date?: string }) {
  const r = DAILY_REPORT;
  const a = r.account;
  const [lo, hi] = a.regime_exposure_range_pct.map(Number);
  return (
    <div className="report">
      <div className="detail-head">
        <span className="q-name">盘后日报</span>
        <Select size="small" value={date && date === r.date ? date : r.date} style={{ width: 130 }} options={[{ value: r.date, label: r.date }]} />
        <Tag>不可变快照</Tag>
        <DataStatusTag status={r.data_status} asOf={r.data_as_of} />
        <span className="muted small">生成于 {fmtTime(r.generated_at)} · 数据截至 {fmtTime(r.data_as_of)} · 说明来源：{r.summary.source === 'template' ? '模板' : 'LLM'}</span>
      </div>
      <div className="report-summary">{r.summary.text}</div>
      <Alert
        className="gap-alert" type="warning" showIcon
        message={`数据缺口 ${r.gaps.length} 项（缺失不臆测；相关维度标为“未知”）`}
        description={<div className="gap-grid">{r.gaps.map((g) => <div key={g.key}><Tag>{GAP_REASON[g.reason]}</Tag><span className="mono muted small">{g.key}</span>　{g.message}</div>)}</div>}
      />

      <div className="report-top">
        <section className="panel acct">
          <div className="panel-head"><span className="panel-title">账户概览</span><Tag color={RECON[a.reconciliation].c}>{RECON[a.reconciliation].t}</Tag></div>
          <div className="stat-grid">
            <div><label>总资产</label><b className="mono">{fmtNum(a.total_assets)}</b></div>
            <div><label>现金</label><b className="mono">{fmtNum(a.cash)}</b></div>
            <div><label>持仓市值</label><b className="mono">{fmtNum(a.market_value)}</b></div>
            <div><label>当日盈亏</label><b className={`mono ${pctClass(a.day_pnl)}`}>{signed(a.day_pnl)}（{signed(a.day_pnl_pct)}%）</b></div>
          </div>
          <div className="regime">
            <div className="small">总仓位 <b className="mono">{a.position_pct}%</b>　大盘环境 <Tag color="blue">{REGIME[a.market_regime]}</Tag>建议区间 {lo}–{hi}%</div>
            <div className="regime-bar">
              <div className="band" style={{ left: `${lo}%`, width: `${hi - lo}%` }} />
              <div className="mark" style={{ left: `${a.position_pct}%` }} />
            </div>
          </div>
        </section>
        <section className="panel expo">
          <div className="panel-head"><span className="panel-title">行业暴露</span><span className="muted small">单行业上限 40%</span></div>
          {a.exposure.sector.map((s) => (
            <div key={s.name} className="expo-row">
              <span>{s.name}</span>
              <Progress percent={Number(s.pct)} size="small" showInfo={false} strokeColor={Number(s.pct) > 40 ? '#f5384a' : '#58a6ff'} />
              <span className="mono">{s.pct}%</span>
            </div>
          ))}
        </section>
        <section className="panel acct-risk">
          <div className="panel-head"><span className="panel-title">账户级风控标记</span></div>
          {a.risk_flags.map((f, i) => (
            <div key={i} className={`risk-row lv-${f.level}`}><Tag color={RISK_LEVEL[f.level].color}>{RISK_LEVEL[f.level].text}</Tag><b>{RISK_CONTROL[f.control]}</b>　{f.message}</div>
          ))}
        </section>
      </div>

      <div className="panel-head section-gap"><span className="panel-title">逐股卡片（持仓 + 自选，共 {r.stocks.length} 只）</span><span className="muted small">各策略结论并列；点击卡片进入候选信号卡</span></div>
      <div className="stock-grid">
        {r.stocks.map((s) => (
          <section key={s.security_code} className={`panel stock-card ${s.data_status !== 'fresh' ? 'dim' : ''}`} onClick={() => go(`/suggestions/${s.suggestion_id}`)}>
            <div className="stc-head">
              <b>{s.name}</b><span className="mono muted small">{s.security_code}</span>
              <span className={`mono ${pctClass(s.change_pct)}`}>{s.close}　{signed(s.change_pct)}%</span>
              <span className="spacer" />
              <ConsensusBadge consensus={s.consensus} />
              <DataStatusTag status={s.data_status} />
            </div>
            <div className="small muted">{s.position ? `持仓 ${fmtNum(s.position.qty, 0)} 股 · 成本 ${s.position.cost} · 浮盈 ${signed(s.position.pnl, 0)} · 占比 ${s.position.weight_pct}%` : '自选（未持仓）'}</div>
            <div className="stc-facts small">{s.facts.map((f, i) => <span key={i}>{f.text}<i className="muted">［{f.evidence_ids.join(',')}］</i></span>)}</div>
            {s.strategies.length ? s.strategies.map((x) => (
              <div key={x.strategy_key} className="stc-strat small">
                <ActionBadge action={x.action} />
                <span className="stc-sname">{STRATEGIES[x.strategy_key].name}</span>
                <span className="muted">{HORIZON[x.horizon]}</span>
                <span className="mono">满足度 {x.score}</span>
                <ConfidenceTag c={x.confidence} />
                <span className="mono">损 <b className="down">{x.stop_loss ?? '—'}</b> 盈 <b className="up">{x.take_profit ?? '—'}</b></span>
              </div>
            )) : <div className="small muted">暂无启用的策略实例</div>}
            {s.strategies[0]?.invalidation[0] ? <div className="small stc-inv">失效条件：{s.strategies[0].invalidation[0].text}</div> : null}
            <div className="stc-tags">
              {s.blocked_reason_codes.map((c) => <Tag key={c} color="orange">不可执行：{REASON_CODE[c]}</Tag>)}
              {s.risk_flags.map((f, i) => <Tag key={i} color={RISK_LEVEL[f.level].color}>{RISK_CONTROL[f.control]}</Tag>)}
              {s.gaps.map((g) => <Tag key={g.key}>缺口：{g.message}</Tag>)}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
