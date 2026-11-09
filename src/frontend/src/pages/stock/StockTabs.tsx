import { Alert, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { CursorPager } from '../../components/CursorPager';
import { useAnnouncements, useFactors, useFinancials, useFundFlows } from '../../api/marketQueries';
import type { Announcement, FactorValue, FinancialPeriod, FundFlowDay } from '../../api/marketTypes';
import { ANNOUNCEMENT_CATEGORY, factorCategoryLabel, PROVIDER, REPORT_PERIOD } from '../../i18n/labels';
import { DataStatusTag, ErrorBox, GapNote, Loading } from '../../components/common';
import { NOT_APPLICABLE_TEXT, isNotApplicable } from '../../lib/dataGaps';
import { ExternalLink } from '../../components/ExternalLink';
import { FundFlowChart } from '../../components/charts/FundFlowChart';
import { fmtAmount, fmtNum, fmtTime, pctClass, signed } from '../../lib/format';

/** 契约 v0.2.7 §7.3 公告 disclaimer 原文；以响应里的 disclaimer 为准，这里只在响应到达前占位 */
export const ANNOUNCEMENT_DISCLAIMER = '公告内容以交易所及上市公司披露原文为准，本系统仅提供标题与原文链接。';

/** v0.2.7 sources：数据来源说明（提供方去重） */
export function SourcesNote({ sources }: { sources: { provider: keyof typeof PROVIDER }[] }) {
  if (!sources.length) return null;
  return <span className="muted small" data-testid="sources-note">来源：{[...new Set(sources.map((x) => PROVIDER[x.provider]))].join('、')}</span>;
}

function TabHead({ children, status }: { children: React.ReactNode; status?: React.ReactNode }) {
  return (
    <div className="tab-head">
      <span className="muted small">{children}</span>
      <span className="spacer" />
      {status}
    </div>
  );
}

// ---------------- 财务 ---------------- // 契约 v0.2.7 §5.1 FinancialPeriod
const periodLabel = (p: FinancialPeriod) => `${p.period_end.slice(0, 4)} ${REPORT_PERIOD[p.report_period]}`;
type FinRow = { key: string; label: string; kind: 'amount' | 'pct' | 'num'; get: (p: FinancialPeriod) => string | null; signedPct?: boolean };
const FIN_ROWS: FinRow[] = [
  { key: 'revenue', label: '营业收入', kind: 'amount', get: (p) => p.revenue },
  { key: 'revenue_yoy', label: '营收同比', kind: 'pct', get: (p) => p.revenue_yoy_pct, signedPct: true },
  { key: 'np', label: '归母净利润', kind: 'amount', get: (p) => p.net_profit },
  { key: 'np_yoy', label: '净利同比', kind: 'pct', get: (p) => p.net_profit_yoy_pct, signedPct: true },
  { key: 'dnp', label: '扣非净利润', kind: 'amount', get: (p) => p.deducted_net_profit },
  { key: 'eps', label: '基本每股收益（元）', kind: 'num', get: (p) => p.eps },
  { key: 'bvps', label: '每股净资产（元）', kind: 'num', get: (p) => p.bvps },
  { key: 'roe', label: 'ROE', kind: 'pct', get: (p) => p.roe_pct },
  { key: 'gm', label: '毛利率', kind: 'pct', get: (p) => p.gross_margin_pct },
  { key: 'debt', label: '资产负债率', kind: 'pct', get: (p) => p.debt_ratio_pct },
  { key: 'ocf', label: '经营活动现金流净额', kind: 'amount', get: (p) => p.operating_cash_flow },
];

export function FinancialsTab({ code }: { code: string }) {
  const q = useFinancials(code);
  if (q.isPending) return <Loading />;
  // T-F34b：错误分支保留页签容器，路由未实现的 404 由 ErrorBox 显示「功能开发中」，不白屏
  if (q.isError) return <div data-testid="tab-financials"><ErrorBox error={q.error} /></div>;
  const d = q.data;
  const cols: ColumnsType<FinRow> = [
    { title: '指标', dataIndex: 'label', width: 150, fixed: 'left', render: (v: string) => <span className="fin-label">{v}</span> },
    ...d.items.map((p) => ({
      key: p.period_end,
      title: (
        <span className="fin-col" data-testid={`fin-col-${p.period_end}`}>
          {periodLabel(p)}{p.is_restated ? <Tag className="fin-restated" color="default">已追溯调整</Tag> : null}
          <span className="muted small mono">{p.announce_date ? `公告 ${p.announce_date}` : '公告日未知'}</span>
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
        累计口径（年初至报告期末），金额单位元并简写为万/亿；数据在公告日之后才进入计算 <SourcesNote sources={d.sources} />
      </TabHead>
      <GapNote status={d.data_status} gaps={d.gaps} asOf={d.data_as_of} />
      {d.items.length === 0 ? <div className="loading-box" data-testid="fin-empty">{isNotApplicable(d.gaps) ? NOT_APPLICABLE_TEXT : '暂无财务数据'}</div> : (
        <Table className="dense-table fin-table" size="small" rowKey="key" pagination={false} columns={cols} dataSource={FIN_ROWS} scroll={{ x: 'max-content' }} />
      )}
    </div>
  );
}

// ---------------- 资金流 ---------------- // 契约 v0.2.7 §5.1 FundFlowDay（分档可为 null；is_final=false 为盘中未定稿）
const sum = (xs: FundFlowDay[]) => xs.reduce((a, x) => a + (x.main_net === null ? 0 : Number(x.main_net)), 0);
const amtCell = (v: string | null) => <span className={`mono ${pctClass(v)}`}>{v === null ? '—' : (Number(v) > 0 ? '+' : '') + fmtAmount(v)}</span>;

export function FundFlowTab({ code }: { code: string }) {
  const q = useFundFlows(code, 60);
  if (q.isPending) return <Loading />;
  if (q.isError) return <div data-testid="tab-fund-flow"><ErrorBox error={q.error} /></div>;
  const d = q.data;
  const recent = [...d.items].reverse();
  const cols: ColumnsType<FundFlowDay> = [
    {
      title: '日期', dataIndex: 'trade_date', width: 120,
      render: (v: string, r) => <span className="mono">{v}{r.is_final ? null : <span className="muted small" data-testid="flow-not-final">（盘中）</span>}</span>,
    },
    { title: '成交额', dataIndex: 'amount', align: 'right', render: (v: string | null) => <span className="mono">{v === null ? '—' : fmtAmount(v)}</span> },
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
        主力 = 超大单 + 大单；分档阈值以数据源口径为准；“—”为该档无数据 <SourcesNote sources={d.sources} />
      </TabHead>
      <GapNote status={d.data_status} gaps={d.gaps} asOf={d.data_as_of} />
      {/* v0.2.8：ETF 等没有资金流时显示“不适用”，不画 0 值统计与空图 */}
      {isNotApplicable(d.gaps) && d.items.length === 0 ? <div className="loading-box" data-testid="flow-empty">{NOT_APPLICABLE_TEXT}</div> : (<>
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
      </>)}
    </div>
  );
}

// ---------------- 因子 ---------------- // 契约 v0.2.7 §5.1 FactorValue：只有全市场排名，没有行业内分位
function PctBar({ v, rank }: { v: string | null; rank: number | null }) {
  if (v === null) return <span className="muted">—</span>;
  const n = Math.max(0, Math.min(100, Number(v)));
  return (
    <span className="pct-bar" title={`全市场分位 ${fmtNum(v, 1)}${rank !== null ? `，第 ${rank} 名` : ''}`}>
      <span className="track"><span className="fill" style={{ width: `${n}%` }} /></span>
      <span className="mono">{fmtNum(v, 0)}</span>
    </span>
  );
}

export function FactorsTab({ code }: { code: string }) {
  const q = useFactors(code);
  if (q.isPending) return <Loading />;
  if (q.isError) return <div data-testid="tab-factors"><ErrorBox error={q.error} /></div>;
  const d = q.data;
  const cols: ColumnsType<FactorValue> = [
    { title: '分类', dataIndex: 'category', width: 80, render: (g: string) => <Tag variant="outlined">{factorCategoryLabel(g)}</Tag> },
    { title: '因子', dataIndex: 'name', width: 170 },
    { title: '代码', dataIndex: 'factor_id', width: 140, render: (v: string) => <span className="mono muted small">{v}</span> },
    { title: '数值', dataIndex: 'value', align: 'right', width: 110, render: (v: string | null, r) => (v === null ? <span className="muted">缺失</span> : <span className="mono">{fmtNum(v)}{r.unit ? <span className="muted small"> {r.unit}</span> : null}</span>) },
    { title: '全市场排名', dataIndex: 'market_rank', align: 'right', width: 100, render: (v: number | null) => <span className="mono">{v === null ? '—' : v}</span> },
    { title: '全市场分位', dataIndex: 'market_rank_pct', render: (v: string | null, r) => <PctBar v={v} rank={r.market_rank} /> },
  ];
  return (
    <div data-testid="tab-factors">
      <TabHead status={<DataStatusTag status={d.data_status} asOf={d.data_as_of} gaps={d.gaps} />}>
        截面日 {d.trade_date} · 因子集 {d.factor_set_version} · 共 {d.counts.total} 个 · 分位 0–100 只表示在全市场截面中的相对位置，不代表方向判断（如 PE 分位高 = 估值相对高）
        <SourcesNote sources={d.sources} />
      </TabHead>
      <GapNote status={d.data_status} gaps={d.gaps} asOf={d.data_as_of} />
      {Object.keys(d.counts.by_category).length ? (
        <div className="factor-counts muted small" data-testid="factor-counts">
          {Object.entries(d.counts.by_category).map(([k, n]) => <span key={k}>{factorCategoryLabel(k)} {n}</span>)}
        </div>
      ) : null}
      {d.items.length === 0 ? <div className="loading-box" data-testid="factor-empty">{isNotApplicable(d.gaps) ? NOT_APPLICABLE_TEXT : '暂无因子数据'}</div> : <Table className="dense-table static" size="small" rowKey="factor_id" pagination={false} columns={cols} dataSource={d.items} />}
    </div>
  );
}

// ---------------- 公告（只给外链） ---------------- // 契约 v0.2.7 §5.1 Announcement
export function AnnouncementsTab({ code }: { code: string }) {
  const q = useAnnouncements(code);
  const cols: ColumnsType<Announcement> = [
    { title: '发布时间', dataIndex: 'published_at', width: 140, render: (v: string) => <span className="mono">{fmtTime(v)}</span> },
    {
      title: '类别', dataIndex: 'category', width: 110,
      render: (v: Announcement['category'], r) => <Tag variant="outlined" title={r.category_raw ?? undefined}>{v === 'other' && r.category_raw ? r.category_raw : ANNOUNCEMENT_CATEGORY[v]}</Tag>,
    },
    { title: '标题', dataIndex: 'title', render: (v: string, r) => <ExternalLink href={r.url}>{v}</ExternalLink> },
    {
      title: '原文', dataIndex: 'url', width: 150,
      render: (v: string | null, r) => (v ? <ExternalLink href={v}>原文{r.file_format === 'pdf' ? '（PDF）' : ''}</ExternalLink>
        : <span className="muted small">{r.url_host ? `链接不在白名单（${r.url_host}）` : '无原文链接'}</span>),
    },
  ];
  return (
    <div data-testid="tab-announcements">
      <Alert type="info" showIcon className="ann-alert" data-testid="ann-disclaimer" title={q.first?.disclaimer ?? ANNOUNCEMENT_DISCLAIMER} description="点击标题或“原文”在新窗口打开交易所/巨潮原文；本页不抓取、不转存公告内容。" />
      {q.isPending ? <Loading /> : !q.first ? <ErrorBox error={q.error} /> : (
        <>
          <TabHead status={<DataStatusTag status={q.first.data_status} asOf={q.first.data_as_of} gaps={q.first.gaps} />}>
            最近 {q.items.length} 条
          </TabHead>
          <GapNote status={q.first.data_status} gaps={q.first.gaps} asOf={q.first.data_as_of} />
          {isNotApplicable(q.first.gaps) && q.items.length === 0 ? <div className="loading-box" data-testid="ann-empty">{NOT_APPLICABLE_TEXT}</div> : (
            <Table className="dense-table static" size="small" rowKey="id" pagination={false} columns={cols} dataSource={q.items} />
          )}
          {/* T-F21：§1.2 游标“加载更多”取更早的公告 */}
          <CursorPager query={q} loaded={q.items.length} testId="ann-pager" />
        </>
      )}
    </div>
  );
}
