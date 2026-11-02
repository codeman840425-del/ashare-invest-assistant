import { useMemo } from 'react';
import { Segmented, Tooltip } from 'antd';
import { StarFilled } from '@ant-design/icons';
import type { TerminalAccount, TerminalRow, TerminalScope } from '../../api/types';
import { DataGrid, type DataColumn } from '../../components/DataGrid';
import { ActionBadge, ConsensusBadge, DataStatusTag } from '../../components/common';
import { EXECUTABILITY, REGIME, RISK_LEVEL } from '../../i18n/labels';
import { fmtAmount, fmtNum, pctClass, signed } from '../../lib/format';

const SCOPES: { label: string; value: TerminalScope }[] = [
  { label: '全部', value: 'all' },
  { label: '持仓', value: 'holdings' },
  { label: '自选', value: 'watchlist' },
];

export function AccountStrip({ account }: { account: TerminalAccount | null | undefined }) {
  if (!account) return <div className="acct-strip muted small">未选择账户</div>;
  const r = account.regime_position_range;
  return (
    <div className="acct-strip" data-testid="account-strip">
      <div><label>总资产</label><b className="mono">{fmtNum(account.total_assets, 0)}</b></div>
      <div><label>可用资金</label><b className="mono">{fmtNum(account.cash_available, 0)}</b></div>
      <div><label>总仓位</label><b className="mono">{fmtNum(account.position_pct, 1)}%</b></div>
      <div><label>当日盈亏</label><b className={`mono ${pctClass(account.pnl_day)}`}>{signed(account.pnl_day, 0)}</b></div>
      <div>
        <label>大盘环境</label>
        <b>{account.regime ? REGIME[account.regime] : '—'}</b>
        {r ? <span className="muted small"> 参考区间 {fmtNum(r.min_pct, 0)}–{fmtNum(r.max_pct, 0)}%</span> : null}
      </div>
      <div><label>数据</label><DataStatusTag status={account.data_status} /></div>
    </div>
  );
}

/** 行 id 用稳定引用（批量事务按 id 对齐） */
const rowIdOf = (r: TerminalRow) => r.security_code;

export function WatchTable({ rows, loading, scope, onScope, selected, onSelect, onOpen }: {
  rows: TerminalRow[];
  loading: boolean;
  scope: TerminalScope;
  onScope: (s: TerminalScope) => void;
  selected: string | null;
  onSelect: (r: TerminalRow) => void;
  onOpen: (r: TerminalRow) => void;
}) {
  const columns = useMemo<DataColumn<TerminalRow>[]>(() => [
    {
      key: 'name', header: '简称 / 代码', width: 150, pinned: 'left', value: (r) => r.security_code,
      render: (r) => (
        <div className="cell-name">
          {r.focus ? <StarFilled className="star" /> : null}{r.name}
          {r.holding ? <span className="hold-mark">持</span> : null}
          <span className="mono muted small" style={{ marginLeft: 4 }}>{r.security_code}</span>
        </div>
      ),
    },
    {
      key: 'price', header: '现价', width: 64, numeric: true, value: (r) => (r.quote ? Number(r.quote.price) : null),
      render: (r) => (r.quote ? <span className={pctClass(r.quote.change_pct)}>{r.quote.price}</span> : <span className="muted">—</span>),
    },
    {
      key: 'chg', header: '涨跌%', width: 66, numeric: true, value: (r) => (r.quote ? Number(r.quote.change_pct) : null),
      render: (r) => (r.quote ? <span className={pctClass(r.quote.change_pct)}>{signed(r.quote.change_pct)}%</span> : <span className="muted">—</span>),
    },
    { key: 'amount', header: '成交额', width: 66, numeric: true, value: (r) => (r.quote ? Number(r.quote.amount) : null), render: (r) => fmtAmount(r.quote?.amount) },
    {
      key: 'weight', header: '持仓占比', width: 70, numeric: true, value: (r) => (r.holding ? Number(r.holding.weight_pct) : null),
      tooltip: (r) => (r.holding ? `持仓 ${r.holding.qty} 股 · 可卖 ${r.holding.sellable_qty} · 成本 ${r.holding.cost_price}` : undefined),
      render: (r) => (r.holding ? <span className={Number(r.holding.weight_pct) > 20 ? 'warn' : ''}>{r.holding.weight_pct}%</span> : <span className="muted">—</span>),
    },
    {
      key: 'pnl', header: '浮盈%', width: 64, numeric: true, value: (r) => (r.holding?.pnl_pct != null ? Number(r.holding.pnl_pct) : null),
      // v0.2.9 #3：无行情的持仓 pnl_pct 为 null，显示“—”并标“估算”
      render: (r) => (r.holding?.pnl_pct == null
        ? <span className="muted">—{r.holding?.estimated ? <span className="small"> 估算</span> : null}</span>
        : <span className={pctClass(r.holding.pnl_pct)}>{signed(r.holding.pnl_pct)}%</span>),
    },
    {
      key: 'actions', header: '各策略候选信号', width: 170, sortable: false,
      render: (r) => r.suggestion && r.suggestion.actions.length ? (
        <div className="badges">{r.suggestion.actions.map((a) => <ActionBadge key={a.strategy_key} action={a.action} strategyName={a.strategy_name} tLeg={a.t_leg} />)}</div>
      ) : <span className="muted small">无启用实例</span>,
    },
    { key: 'consensus', header: '共识', width: 56, sortable: false, render: (r) => (r.suggestion ? <ConsensusBadge status={r.suggestion.consensus} /> : <ConsensusBadge status="none" />) },
    { key: 'score', header: '满足度', width: 60, numeric: true, value: (r) => r.suggestion?.top_score ?? null, render: (r) => r.suggestion?.top_score ?? '—' },
    {
      key: 'exec', header: '可执行性', width: 86, sortable: false,
      render: (r) => {
        if (!r.suggestion) return <span className="muted">—</span>;
        const e = EXECUTABILITY[r.suggestion.executability_status];
        return (
          <Tooltip title={r.active_reason_count ? `${r.active_reason_count} 项不可执行原因（见右侧卡片的解除条件）` : undefined}>
            <span style={{ color: e.color === 'orange' ? '#f0883e' : e.color === 'green' ? '#3fb950' : '#7d8794' }}>
              {e.text}{r.active_reason_count ? ` ·${r.active_reason_count}` : ''}
            </span>
          </Tooltip>
        );
      },
    },
    {
      key: 'risk', header: '风控', width: 50, sortable: false,
      render: (r) => (r.max_risk_level ? <span style={{ color: RISK_LEVEL[r.max_risk_level].color === 'red' ? '#ff7b72' : RISK_LEVEL[r.max_risk_level].color === 'orange' ? '#f0b429' : '#58a6ff' }}>{RISK_LEVEL[r.max_risk_level].text}</span> : <span className="muted">—</span>),
    },
    { key: 'ds', header: '数据', width: 72, sortable: false, render: (r) => <DataStatusTag status={r.data_status} asOf={r.quote?.t} /> },
  ], []);

  return (
    <>
      <div className="panel-head">
        <span className="panel-title">自选 / 持仓</span>
        <Segmented size="small" options={SCOPES} value={scope} onChange={(v) => onScope(v as TerminalScope)} />
        <span className="muted small" style={{ marginLeft: 'auto' }}>{rows.length} 只</span>
      </div>
      <DataGrid<TerminalRow>
        testId="watch-table"
        rows={rows}
        columns={columns}
        loading={loading}
        getRowId={rowIdOf}
        batchUpdates
        selectedId={selected}
        onRowClick={onSelect}
        onRowDoubleClick={onOpen}
        rowClass={(r) => (r.data_status === 'stale' || r.data_status === 'unavailable' ? 'row-stale' : undefined)}
        emptyText="暂无自选或持仓"
      />
      <div className="table-foot muted small">单击切换图表与右侧卡片 · 双击进入候选信号卡详情 · 灰显行 = 数据已过期/不可用</div>
    </>
  );
}
