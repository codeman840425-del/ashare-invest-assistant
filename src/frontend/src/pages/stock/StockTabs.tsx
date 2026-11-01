import { Alert, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useAnnouncements, useFactors, useFinancials, useFundFlows } from '../../api/marketQueries';
import type { Announcement, FactorGroup, FactorValue, FinancialPeriod, FundFlowDay } from '../../api/marketTypes';
import { DataStatusTag, ErrorBox, Loading } from '../../components/common';
import { ExternalLink } from '../../components/ExternalLink';
import { FundFlowChart } from '../../components/charts/FundFlowChart';
import { fmtAmount, fmtNum, fmtTime, pctClass, signed } from '../../lib/format';

/** plan §2.4 / 4：公告免责声明（原文） */
export const ANNOUNCEMENT_DISCLAIMER = '本产品不提供新闻资讯；公告信息为盘后更新，可能存在延迟与遗漏，请以交易所/巨潮原文为准。';

function TabHead({ children, status }: { children: React.ReactNode; status?: React.ReactNode }) {
  return (
    <div className="tab-head">
      <span className="muted small">{children}</span>
      <span className="spacer" />
      {status}
    </div>
  );
}

// ---------------- 财务 ---------------- // [待契约确认] 端点、指标集与口径
const periodLabel = (p: string) => {
  const m = p.slice(5, 7);
  return `${p.slice(0, 4)}${m === '03' ? 'Q1' : m === '06' ? 'H1' : m === '09' ? 'Q3' : m === '12' ? '年报' : p.slice(5)}`;
};
type FinRow = { key: string; label: string; kind: 'amount' | 'pct' | 'num'; get: (p: FinancialPeriod) => string | null; signedPct?: boolean };
const FIN_ROWS: FinRow[] = [
  { key: 'revenue', label: '营业收入', kind: 'amount', get: (p) => p.revenue },
  { key: 'revenue_yoy', label: '营收同比', kind: 'pct', get: (p) => p.revenue_yoy_pct, signedPct: true },
  { key: 'np', label: '归母净利润', kind: 'amount', get: (p) => p.net_profit },
  { key: 'np_yoy', label: '净利同比', kind: 'pct', get: (p) => p.net_profit_yoy_pct, signedPct: true },
  { key: 'eps', label: '基本每股收益（元）', kind: 'num', get: (p) => p.eps },
  { key: 'roe', label: 'ROE', kind: 'pct', get: (p) => p.roe_pct },
  { key: 'gm', label: '毛利率', kind: 'pct', get: (p) => p.gross_margin_pct },
  { key: 'debt', label: '资产负债率', kind: 'pct', get: (p) => p.debt_ratio_pct },
  { key: 'ocf', label: '经营活动现金流净额', kind: 'amount', get: (p) => p.operating_cash_flow },
];

export function FinancialsTab({ code }: { code: string }) {
  const q = useFinancials(code);
  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const d = q.data;
  const cols: ColumnsType<FinRow> = [
    { title: '指标', dataIndex: 'label', width: 150, fixed: 'left', render: (v: string) => <span className="fin-label">{v}</span> },
    ...d.items.map((p) => ({
      key: p.period_end,
      title: (
        <span className="fin-col">
          {periodLabel(p.period_end)}
          <span className="muted small mono">{p.announce_date ? `公告 ${p.announce_date.slice(5)}` : '公告日未知'}</span>
        </span>
      ),
      align: 'right' as const,
      render: (_: unknown, r: FinRow) => {
        const v = r.get(p);
        if (v === null) return <span className="muted">—</span>;
        if (r.kind === 'amount') return <span className={`mono ${Number(v) < 0 ? 'down' : ''}`}>{fmtAmount(v)}</span>;
        if (r.kind === 'pct') return <span className={`mono ${r.signedPct ? pctClass(v) : ''}`}>{r.signedPct ? signed(v) : fmtNum(v)}%</span>;
        return <span className="mono">{v}</span>;
      },
    })),
  ];
  return (
    <div data-testid="tab-financials">
      <TabHead status={<DataStatusTag status={d.data_status} asOf={d.data_as_of} gaps={d.gaps} />}>
        累计口径（年初至报告期末），金额单位元并简写为万/亿；数据在公告日之后才进入计算
      </TabHead>
      {d.items.length === 0 ? <div className="loading-box">暂无财务数据</div> : (
        <Table className="dense-table fin-table" size="small" rowKey="key" pagination={false} columns={cols} dataSource={FIN_ROWS} scroll={{ x: 'max-content' }} />
      )}
    </div>
  );
}

// ---------------- 资金流 ---------------- // [待契约确认] 端点与分档口径
const sum = (xs: FundFlowDay[]) => xs.reduce((a, x) => a + Number(x.main_net), 0);
const amtCell = (v: string | null) => <span className={`mono ${pctClass(v)}`}>{v === null ? '—' : (Number(v) > 0 ? '+' : '') + fmtAmount(v)}</span>;

export function FundFlowTab({ code }: { code: string }) {
  const q = useFundFlows(code, 60);
  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const d = q.data;
  const recent = [...d.items].reverse();
  const cols: ColumnsType<FundFlowDay> = [
    { title: '日期', dataIndex: 'trade_date', width: 96, render: (v: string) => <span className="mono">{v}</span> },
    { title: '主力净流入', dataIndex: 'main_net', align: 'right', render: amtCell },
    { title: '超大单', dataIndex: 'super_large_net', align: 'right', render: amtCell },
    { title: '大单', dataIndex: 'large_net', align: 'right', render: amtCell },
    { title: '中单', dataIndex: 'medium_net', align: 'right', render: amtCell },
    { title: '小单', dataIndex: 'small_net', align: 'right', render: amtCell },
    { title: '主力占比', dataIndex: 'main_net_pct', align: 'right', render: (v: string | null) => <span className={`mono ${pctClass(v)}`}>{v === null ? '—' : `${signed(v)}%`}</span> },
  ];
  return (
    <div data-testid="tab-fund-flow">
      <TabHead status={<DataStatusTag status={d.data_status} asOf={d.data_as_of} gaps={d.gaps} />}>
        主力 = 超大单 + 大单；分档阈值以数据源口径为准
      </TabHead>
      {d.gaps.length ? <div className="gap-note small">{d.gaps.map((g) => g.message).join('；')}</div> : null}
      <div className="flow-stats">
        {[['近 5 日主力净流入', 5], ['近 20 日', 20], ['近 60 日', 60]].map(([label, n]) => {
          const v = sum(d.items.slice(-Number(n)));
          return (
            <div key={label}>
              <label>{label}</label>
              <b className={`mono ${pctClass(v)}`}>{(v > 0 ? '+' : '') + fmtAmount(v)}</b>
            </div>
          );
        })}
      </div>
      <div className="flow-grid">
        <div className="chart-wrap" style={{ height: 260 }}>
          <FundFlowChart items={d.items} />
        </div>
        <Table className="dense-table static" size="small" rowKey="trade_date" pagination={false} columns={cols} dataSource={recent.slice(0, 10)} />
      </div>
    </div>
  );
}

// ---------------- 因子 ---------------- // [待契约确认] 端点、分组与分位口径
const GROUP: Record<FactorGroup, string> = { value: '估值', quality: '质量', growth: '成长', momentum: '动量', volatility: '波动', liquidity: '流动性' };
function PctBar({ v }: { v: string | null }) {
  if (v === null) return <span className="muted">—</span>;
  const n = Math.max(0, Math.min(100, Number(v)));
  return (
    <span className="pct-bar" title={`分位 ${fmtNum(v, 1)}`}>
      <span className="track"><span className="fill" style={{ width: `${n}%` }} /></span>
      <span className="mono">{fmtNum(v, 0)}</span>
    </span>
  );
}

export function FactorsTab({ code }: { code: string }) {
  const q = useFactors(code);
  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const d = q.data;
  const cols: ColumnsType<FactorValue> = [
    { title: '分组', dataIndex: 'group', width: 70, render: (g: FactorGroup) => <Tag variant="outlined">{GROUP[g]}</Tag> },
    { title: '因子', dataIndex: 'name', width: 170 },
    { title: '代码', dataIndex: 'factor_id', width: 140, render: (v: string) => <span className="mono muted small">{v}</span> },
    { title: '数值', dataIndex: 'value', align: 'right', width: 110, render: (v: string | null, r) => (v === null ? <span className="muted">缺失</span> : <span className="mono">{fmtNum(v)}{r.unit ? <span className="muted small"> {r.unit}</span> : null}</span>) },
    { title: '全市场分位', dataIndex: 'pct_rank_market', render: (v: string | null) => <PctBar v={v} /> },
    { title: '行业内分位', dataIndex: 'pct_rank_industry', render: (v: string | null) => <PctBar v={v} /> },
  ];
  return (
    <div data-testid="tab-factors">
      <TabHead status={<DataStatusTag status={d.data_status} asOf={d.data_as_of} gaps={d.gaps} />}>
        截面日 {d.trade_date} · 计算版本 {d.calc_version} · 分位 0–100 只表示在截面中的相对位置，不代表方向判断（如 PE 分位高 = 估值相对高）
      </TabHead>
      <Table className="dense-table static" size="small" rowKey="factor_id" pagination={false} columns={cols} dataSource={d.items} />
    </div>
  );
}

// ---------------- 公告（只给外链） ---------------- // [待契约确认] 端点与结构
export function AnnouncementsTab({ code }: { code: string }) {
  const q = useAnnouncements(code);
  const cols: ColumnsType<Announcement> = [
    { title: '发布时间', dataIndex: 'published_at', width: 140, render: (v: string) => <span className="mono">{fmtTime(v)}</span> },
    { title: '类别', dataIndex: 'category', width: 90, render: (v: string | null) => (v ? <Tag variant="outlined">{v}</Tag> : <span className="muted">—</span>) },
    { title: '标题', dataIndex: 'title', render: (v: string, r) => <ExternalLink href={r.url}>{v}</ExternalLink> },
    { title: '原文', dataIndex: 'url', width: 110, render: (v: string | null) => (v ? <ExternalLink href={v}>原文</ExternalLink> : <span className="muted small">无原文链接</span>) },
  ];
  return (
    <div data-testid="tab-announcements">
      <Alert type="info" showIcon className="ann-alert" title={ANNOUNCEMENT_DISCLAIMER} description="点击标题或“原文”在新窗口打开交易所/巨潮原文；本页不抓取、不转存公告内容。" />
      {q.isPending ? <Loading /> : q.isError ? <ErrorBox error={q.error} /> : (
        <>
          <TabHead status={<DataStatusTag status={q.data.data_status} asOf={q.data.data_as_of} gaps={q.data.gaps} />}>
            最近 {q.data.items.length} 条{q.data.next_cursor ? '（更早的请到交易所/巨潮查询）' : ''}
          </TabHead>
          <Table className="dense-table static" size="small" rowKey="id" pagination={false} columns={cols} dataSource={q.data.items} />
        </>
      )}
    </div>
  );
}
