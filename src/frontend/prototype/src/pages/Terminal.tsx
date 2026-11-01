import { useMemo, useState } from 'react';
import { Badge, Button, Empty, Segmented, Table, Tag, Tooltip, message } from 'antd';
import { StarFilled } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  CANDIDATE_SIGNALS, DAILY_REPORT, NOTIFICATIONS, PORTFOLIO, QUOTES, SIGNAL_EVENTS, STRATEGIES, WATCHLIST, nameOf, positionOf,
  reasonsOf, specOf, suggestionOf,
} from '../mock/data';
import type { WatchlistItem } from '../types/contract';
import { ACTION_FULL, HORIZON, NOTIFY_KIND, REASON_CODE, SEVERITY, REGIME, RISK_CONTROL, RISK_LEVEL, SIGNAL_STATE } from '../labels';
import { ActionBadge, ConfidenceTag, ConsensusBadge, DataStatusTag, fmtNum, fmtTime, pctClass, signed } from '../components/common';
import { IntradayChart, KlineChart } from '../components/Charts';
import { go } from '../router';

type Row = WatchlistItem & { key: string };

export function Terminal() {
  const [selected, setSelected] = useState('600000.SH');
  const [filter, setFilter] = useState<string>('全部');
  const rows: Row[] = useMemo(
    () =>
      WATCHLIST.filter((w) => (filter === '持仓' ? w.in_portfolio : filter === '自选' ? !w.in_portfolio : filter === '重点' ? w.focus : true)).map((w) => ({ ...w, key: w.security_code })),
    [filter],
  );
  const sg = suggestionOf(selected);
  const q = QUOTES[selected];
  const spec = specOf(selected);
  const firstStops = sg.strategies.find((s) => s.stop_loss);

  const columns: ColumnsType<Row> = [
    {
      title: '代码 / 简称', dataIndex: 'security_code', width: 100,
      render: (_, r) => (
        <div className="cell-name">
          <div>{r.focus ? <StarFilled className="star" /> : null}{r.name}{r.in_portfolio ? <span className="hold-mark">持</span> : null}</div>
          <div className="mono muted small">{r.security_code}</div>
        </div>
      ),
    },
    {
      title: '现价', width: 56, align: 'right',
      render: (_, r) => <span className={`mono ${pctClass(QUOTES[r.security_code].change_pct)}`}>{QUOTES[r.security_code].price}</span>,
    },
    {
      title: '涨跌%', width: 60, align: 'right',
      render: (_, r) => <span className={`mono ${pctClass(QUOTES[r.security_code].change_pct)}`}>{signed(QUOTES[r.security_code].change_pct)}%</span>,
    },
    {
      title: '持仓 / 占比', width: 70, align: 'right',
      render: (_, r) => {
        const p = positionOf(r.security_code);
        return p ? (
          <div className="mono small">
            <div>{fmtNum(p.qty, 0)}</div>
            <div className={Number(p.weight_pct) > 20 ? 'warn' : 'muted'}>{p.weight_pct}%</div>
          </div>
        ) : <span className="muted">—</span>;
      },
    },
    {
      title: '各策略动作（候选）', width: 150,
      render: (_, r) => {
        const s = suggestionOf(r.security_code);
        return s.strategies.length ? (
          <div className="badges">{s.strategies.map((x) => <ActionBadge key={x.strategy_key} action={x.action} strategyKey={x.strategy_key} tLeg={x.t_leg} />)}</div>
        ) : <span className="muted small">无启用实例</span>;
      },
    },
    { title: '共识', width: 46, align: 'center', render: (_, r) => <ConsensusBadge consensus={suggestionOf(r.security_code).consensus} /> },
    { title: '数据', width: 58, render: (_, r) => <DataStatusTag status={QUOTES[r.security_code].data_status} asOf={QUOTES[r.security_code].data_as_of} /> },
    {
      title: '', width: 36, align: 'center',
      render: (_, r) => <a onClick={(e) => { e.stopPropagation(); go(`/suggestions/${suggestionOf(r.security_code).id}`); }}>详情</a>,
    },
  ];

  const totalAssets = Number(PORTFOLIO.total_assets);
  const cash = Number(PORTFOLIO.cash);
  const posPct = ((totalAssets - cash) / totalAssets) * 100;

  return (
    <div className="terminal">
      {/* 左：账户条 + 自选/持仓表 */}
      <section className="panel left">
        <div className="acct-strip">
          <div><label>总资产</label><b className="mono">{fmtNum(PORTFOLIO.total_assets, 0)}</b></div>
          <div><label>可用资金</label><b className="mono">{fmtNum(PORTFOLIO.cash, 0)}</b></div>
          <div><label>总仓位</label><b className="mono">{posPct.toFixed(1)}%</b></div>
          <div><label>当日盈亏</label><b className="mono up">+1,864</b></div>
          <div><label>大盘环境</label><b>{REGIME[DAILY_REPORT.account.market_regime]}</b><span className="muted small"> 区间 40–60%</span></div>
        </div>
        <div className="panel-head">
          <span className="panel-title">自选 / 持仓</span>
          <Segmented size="small" options={['全部', '持仓', '自选', '重点']} value={filter} onChange={(v) => setFilter(v as string)} />
        </div>
        <Table<Row>
          className="dense-table"
          size="small"
          columns={columns}
          dataSource={rows}
          pagination={false}
          rowClassName={(r) => {
            const st = QUOTES[r.security_code].data_status;
            return [st === 'stale' || st === 'unavailable' ? 'row-stale' : '', r.security_code === selected ? 'row-selected' : ''].join(' ');
          }}
          onRow={(r) => ({
            onClick: () => setSelected(r.security_code),
            onDoubleClick: () => go(`/suggestions/${suggestionOf(r.security_code).id}`),
          })}
        />
        <div className="table-foot muted small">单击切换图表 · 双击或“详情”进入候选信号卡 · 灰显行 = 数据已过期/不可用</div>
        <div className="panel-head"><span className="panel-title">通知</span><Badge count={NOTIFICATIONS.filter((n) => !n.read).length} size="small" /><a onClick={() => go('/notifications')}>通知中心 ›</a></div>
        <div className="notif-list">
          {NOTIFICATIONS.map((n) => (
            <div key={n.id} className={`event-row ${n.read ? 'read' : ''}`} onClick={() => n.link && (window.location.hash = n.link.slice(1))}>
              <span className="mono muted">{fmtTime(n.created_at).slice(5, 16)}</span>
              <Tag color={SEVERITY[n.severity]} className="ev-kind">{NOTIFY_KIND[n.kind]}</Tag>
              <span className="ev-text">{n.title}</span>
            </div>
          ))}
        </div>
      </section>

      {/* 中：图表 + 信号流 */}
      <section className="panel center">
        <div className="quote-head">
          <span className="q-name">{nameOf(selected)}</span>
          <span className="mono muted">{selected}</span>
          <span className={`q-price mono ${pctClass(q.change_pct)}`}>{q.price}</span>
          <span className={`mono ${pctClass(q.change_pct)}`}>{signed(Number(q.price) - spec.prev_close)} ({signed(q.change_pct)}%)</span>
          <span className="muted small mono">成交额 {fmtNum(Number(q.amount) / 1e8, 2)} 亿</span>
          <DataStatusTag status={q.data_status} asOf={q.data_as_of} />
          <span className="muted small mono">{fmtTime(q.data_as_of).slice(11)}</span>
        </div>
        <div className="chart-title">日 K（前复权 · 示例）<span className="muted small">　▲/▼ = 候选信号标记（策略简称 + 动作），虚线 = 首个策略的止损/止盈</span><span className="legend"><i style={{ background: '#e3b341' }} />MA5<i style={{ background: '#58a6ff' }} />MA20<i style={{ background: '#bc8cff' }} />MA60</span></div>
        <div className="chart-wrap kline"><KlineChart code={selected} stopLoss={firstStops?.stop_loss} takeProfit={firstStops?.take_profit} /></div>
        <div className="chart-title">分时（黄线 = 均价）</div>
        <div className="chart-wrap intraday">
          {q.data_status === 'unavailable' ? <Empty description="停牌，无分时数据（示例）" /> : <IntradayChart code={selected} />}
        </div>
        <div className="panel-head"><span className="panel-title">盘中规则事件流</span><span className="muted small">来自 /signals 与 SSE（示例）</span></div>
        <div className="event-stream">
          {SIGNAL_EVENTS.map((e) => (
            <div key={e.signal_event_id} className={`event-row ${e.security_code === selected ? 'hl' : ''}`} onClick={() => setSelected(e.security_code)}>
              <span className="mono muted">{fmtTime(e.at).slice(11)}</span>
              <span className="ev-name">{nameOf(e.security_code)}</span>
              <Tag className="ev-kind">{e.kind}</Tag>
              <span className="ev-text">{e.text}</span>
            </div>
          ))}
        </div>
      </section>

      {/* 右：当前候选信号卡（摘要） */}
      <section className="panel right">
        <div className="panel-head">
          <span className="panel-title">候选信号卡 · {nameOf(selected)}</span>
          <a onClick={() => go(`/suggestions/${sg.id}`)}>完整详情 ›</a>
        </div>
        <div className={`consensus-bar ${sg.consensus.status}`}>
          {sg.consensus.status === 'divergent'
            ? `存在分歧（${sg.strategies.length} 个策略：${sg.strategies.map((s) => ACTION_FULL[s.action].replace(/^规则信号：|（候选）$/g, '').slice(0, 2)).join(' / ')}）`
            : sg.consensus.status === 'unanimous'
              ? `各策略一致：${ACTION_FULL[sg.strategies[0].action].slice(5)}`
              : sg.consensus.status === 'single' ? '仅 1 个策略实例' : '暂无启用的策略实例'}
        </div>
        <div className="right-scroll">
          {sg.strategies.map((s) => {
            const cs = CANDIDATE_SIGNALS.find((c) => c.id === s.candidate_signal_id);
            const rs = cs ? reasonsOf(cs.id) : [];
            return (
              <div key={s.strategy_key} className="strat-mini">
                <div className="sm-head">
                  <ActionBadge action={s.action} tLeg={s.t_leg} size="lg" />
                  <span className="sm-name">{STRATEGIES[s.strategy_key].name}</span>
                  <span className="muted small">{HORIZON[s.horizon]} · v{s.version_no}</span>
                </div>
                <div className="sm-row">
                  <span>满足度 <b className="mono">{s.score}</b></span>
                  <ConfidenceTag c={s.confidence} />
                  {s.priority_downweighted ? <Tooltip title="因近期模拟跟踪表现降低排序优先级，不改变动作"><Tag color="default">降权 {s.priority_weight}</Tag></Tooltip> : null}
                </div>
                <div className="sm-row mono small">
                  止损 <b className="down">{s.stop_loss ?? '—'}</b>　止盈 <b className="up">{s.take_profit ?? '—'}</b>
                  {cs ? <Tag color={SIGNAL_STATE[cs.state].color} style={{ marginLeft: 'auto' }}>{SIGNAL_STATE[cs.state].text}</Tag> : <span className="muted" style={{ marginLeft: 'auto' }}>不进入可执行性检查</span>}
                </div>
                <div className="sm-reason small">理由：{s.reasons[0]?.text}</div>
                <div className="sm-counter small">反证：{s.counter_evidence[0]?.text}</div>
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
          <Button size="small" onClick={() => go(`/suggestions/${sg.id}`)}>查看维度×策略矩阵</Button>
          <Button size="small" type="primary" disabled={!sg.candidate_signal_ids.length} onClick={() => message.info('示例：此处将按您的持仓和资金拟定计划草案（原型不调用接口）')}>生成计划草案</Button>
        </div>
      </section>
    </div>
  );
}
