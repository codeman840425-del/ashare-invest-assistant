import { useState } from 'react';
import { Segmented, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { Link } from 'react-router';
import { useMarketOverview, useSectorFlows } from '../../api/marketQueries';
import type { SectorFlow, SectorKind } from '../../api/marketTypes';
import type { MarketOverview } from '../../api/types';
import { DataStatusTag, ErrorBox, GapNote, Loading } from '../../components/common';
import { GAP_REASON, INDUSTRY_TAXONOMY, REGIME, SESSION } from '../../i18n/labels';
import { fmtAmount, fmtNum, fmtTime, pctClass, signed } from '../../lib/format';
import { PriceChartPanel } from '../stock/PriceChartPanel';

/** /market 市场概览（plan §2.3 能力 1 / §2.4）：指数、涨跌家数与涨跌停、regime 与参考仓位区间、两市成交额、板块资金 */
export function MarketPage() {
  const q = useMarketOverview();
  const [picked, setPicked] = useState<string | null>(null);
  if (q.isPending) return <div className="page-scroll" data-testid="market-page"><Loading /></div>;
  if (q.isError) return <div className="page-scroll" data-testid="market-page"><ErrorBox error={q.error} /></div>;
  const m = q.data;
  const sel = picked ?? m.indices[0]?.security_code ?? null;
  const selName = m.indices.find((i) => i.security_code === sel)?.name ?? sel;
  return (
    <div className="page-scroll market-page" data-testid="market-page">
      <div className="mk-head">
        <span className="page-title">市场概览</span>
        <span className="mono">{m.trade_date}</span>
        <Tag variant="outlined">{SESSION[m.session]}</Tag>
        <DataStatusTag status={m.data_status} asOf={m.data_as_of} gaps={m.gaps} />
        {/* F-07 + F-13 合并口径：data_as_of 为 null（契约 T-A53/A-12）时不渲染「更新于 」（空串会变成悬空标签），
            也不编造时间；时间行整条隐藏，缺口原因由下方 GapNote 披露 */}
        {m.data_as_of ? <span className="muted small mono">更新于 {fmtTime(m.data_as_of)}</span> : null}
      </div>
      <GapNote status={m.data_status} gaps={m.gaps} asOf={m.data_as_of} testId="market-gap-note" />
      <div className="index-strip" role="list" aria-label="主要指数">
        {m.indices.map((i) => (
          <button
            type="button"
            role="listitem"
            key={i.security_code}
            className={`index-card${i.security_code === sel ? ' active' : ''}`}
            onClick={() => setPicked(i.security_code)}
            aria-pressed={i.security_code === sel}
          >
            <span className="ic-name">{i.name}</span>
            <span className={`ic-price mono ${pctClass(i.change_pct)}`}>{fmtNum(i.price)}</span>
            <span className={`mono ${pctClass(i.change_pct)}`}>{i.change_pct === null ? '—' : `${signed(i.change_pct)}%`}</span>
            <span className="muted small mono">成交 {fmtAmount(i.amount)}</span>
          </button>
        ))}
      </div>
      <div className="mk-grid">
        <div>
          <div className="chart-caption"><b>{selName}</b> <span className="mono muted">{sel}</span></div>
          {sel ? <PriceChartPanel key={sel} code={sel} initial="1m" height={330} testId="index-chart" /> : null}
        </div>
        <div className="mk-side">
          <BreadthPanel m={m} />
          <RegimePanel m={m} />
        </div>
      </div>
      <SectorPanel />
    </div>
  );
}

function BreadthPanel({ m }: { m: MarketOverview }) {
  const b = m.breadth;
  const total = b ? b.up + b.down + b.flat : 0;
  return (
    <section className="panel side-panel" data-testid="breadth-panel">
      <div className="panel-head"><span className="panel-title">涨跌分布</span></div>
      {!b ? <div className="muted small hz-empty">涨跌家数暂不可用</div> : (
        <div className="breadth">
          <div className="breadth-bar" aria-label={`上涨 ${b.up} 家，平盘 ${b.flat} 家，下跌 ${b.down} 家`}>
            <span className="seg up-bg" style={{ width: `${(b.up / total) * 100}%` }} />
            <span className="seg flat-bg" style={{ width: `${(b.flat / total) * 100}%` }} />
            <span className="seg down-bg" style={{ width: `${(b.down / total) * 100}%` }} />
          </div>
          <div className="breadth-nums">
            <span className="up">上涨 <b className="mono">{b.up}</b></span>
            <span className="muted">平盘 <b className="mono">{b.flat}</b></span>
            <span className="down">下跌 <b className="mono">{b.down}</b></span>
          </div>
          <div className="stat-grid two">
            <div><label>涨停</label><b className="mono up">{b.limit_up}</b></div>
            <div><label>跌停</label><b className="mono down">{b.limit_down}</b></div>
            <div><label>两市成交额</label><b className="mono">{fmtAmount(m.turnover_total)}</b></div>
            <div><label>上涨占比</label><b className="mono">{fmtNum((b.up / total) * 100, 1)}%</b></div>
          </div>
        </div>
      )}
    </section>
  );
}

function RegimePanel({ m }: { m: MarketOverview }) {
  const r = m.regime_position_range;
  const lo = r ? Number(r.min_pct) : 0;
  const hi = r ? Number(r.max_pct) : 0;
  return (
    <section className="panel side-panel" data-testid="regime-panel">
      <div className="panel-head"><span className="panel-title">大盘状态</span></div>
      <div className="regime" style={{ paddingTop: 8 }}>
        <div>
          市场状态 <b>{m.regime ? REGIME[m.regime] : '—'}</b>
          <span className="muted small">　{r ? `参考仓位区间 ${fmtNum(lo, 0)}–${fmtNum(hi, 0)}%` : '参考仓位区间暂不可用'}</span>
        </div>
        {r ? (
          <div className="regime-bar" title="参考仓位区间（规则信号，非操作指令）">
            <div className="band" style={{ left: `${lo}%`, width: `${hi - lo}%` }} />
          </div>
        ) : null}
        <div className="muted small" style={{ marginTop: 6 }}>由大盘规则计算的状态与参考区间，仅供对照自身仓位；不构成操作指令。</div>
      </div>
    </section>
  );
}

/** 契约 v0.2.7 §7.3 /market/sector-flows：行业/概念涨跌与主力资金（盘后数据，上一交易日；不轮询） */
function SectorPanel() {
  const [kind, setKind] = useState<SectorKind>('industry');
  const q = useSectorFlows(kind);
  const maxAbs = Math.max(1, ...(q.data?.items ?? []).map((x) => Math.abs(Number(x.main_net ?? 0))));
  const cols: ColumnsType<SectorFlow> = [
    { title: '#', key: 'rank', width: 40, render: (_v, _r, i) => <span className="mono muted">{i + 1}</span> },
    { title: kind === 'industry' ? '行业' : '概念', dataIndex: 'name', width: 170 },
    { title: '涨跌幅', dataIndex: 'change_pct', width: 90, align: 'right', render: (v: string | null) => <span className={`mono ${pctClass(v)}`}>{v === null ? '—' : `${signed(v)}%`}</span> },
    {
      title: '主力净流入', dataIndex: 'main_net', render: (v: string | null) => {
        if (v === null) return <span className="muted">—</span>;
        const n = Number(v);
        return (
          <span className="flow-cell">
            <span className={`mono ${pctClass(n)}`}>{(n > 0 ? '+' : '') + fmtAmount(n)}</span>
            <span className="flow-track"><span className={`flow-fill ${n >= 0 ? 'up-bg' : 'down-bg'}`} style={{ width: `${(Math.abs(n) / maxAbs) * 100}%` }} /></span>
          </span>
        );
      },
    },
    { title: '成交额', dataIndex: 'amount', width: 100, align: 'right', render: (v: string | null) => <span className="mono">{v === null ? '—' : fmtAmount(v)}</span> },
    { title: '涨 / 跌家数', key: 'ud', width: 110, align: 'right', render: (_v, r) => <span className="mono"><span className="up">{r.up_count ?? '—'}</span> / <span className="down">{r.down_count ?? '—'}</span></span> },
    {
      title: '领涨股', dataIndex: 'leader', width: 200, render: (l: SectorFlow['leader']) => (l ? (
        <Link to={`/stocks/${l.security_code}`} onClick={(e) => e.stopPropagation()}>
          {l.name} <span className={`mono small ${pctClass(l.change_pct)}`}>{l.change_pct === null ? '' : `${signed(l.change_pct)}%`}</span>
        </Link>
      ) : <span className="muted">—</span>),
    },
  ];
  return (
    <section className="panel sector-panel" data-testid="sector-panel">
      <div className="panel-head">
        <span className="panel-title">板块资金</span>
        <Segmented size="small" value={kind} onChange={(v) => setKind(v as SectorKind)} options={[{ value: 'industry', label: '行业' }, { value: 'concept', label: '概念' }]} />
        <span className="muted small" data-testid="sector-meta">
          按主力净流入排序 · 盘后数据{q.data ? `（${q.data.trade_date}${q.data.taxonomy ? ` · ${INDUSTRY_TAXONOMY[q.data.taxonomy]}` : ''}）` : ''}
        </span>
        <span className="spacer" />
        {q.data ? <DataStatusTag status={q.data.data_status} asOf={q.data.data_as_of} gaps={q.data.gaps} /> : null}
      </div>
      {q.isPending ? <Loading /> : q.isError ? <ErrorBox error={q.error} /> : (
        <>
          <GapNote status={q.data.data_status} gaps={q.data.gaps} asOf={q.data.data_as_of} testId="sector-gap-note" />
          <Table className="dense-table static" size="small" rowKey="sector_code" pagination={false} columns={cols} dataSource={q.data.items}
            locale={{ emptyText: q.data.gaps.length ? `暂无板块资金：${q.data.gaps.map((g) => GAP_REASON[g.reason]).join('、')}` : '暂无板块资金' }} />
        </>
      )}
    </section>
  );
}
