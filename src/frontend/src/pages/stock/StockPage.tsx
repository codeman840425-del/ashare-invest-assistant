import { Button, Result, Tabs, Tag, Tooltip } from 'antd';
import { Navigate, useLocation, useNavigate, useParams, useSearchParams } from 'react-router';
import { ApiError } from '../../api/client';
import { ENUMS } from '../../api/enums';
import { CODE_RE, useBarsOf, useBarsWindow, useQuote, useSecurityProfile } from '../../api/marketQueries';
import type { SecurityProfile } from '../../api/marketTypes';
import { useHorizonAssessment } from '../../api/queries';
import type { Bar, BarsResponse, QuoteItem } from '../../api/types';
import { DataStatusTag, ErrorBox, GapNote, KeyTip, Loading } from '../../components/common';
import { CAP_KIND_TEXT, capExplanation } from '../../i18n/horizonCaps';
import { BOARD, HORIZON, INDUSTRY_TAXONOMY, LISTING_STATUS, PROVIDER, SECURITY_RISK_FLAG, SECURITY_TYPE } from '../../i18n/labels';
import { fmtAmount, fmtNum, fmtTime, pctClass, signed } from '../../lib/format';
import { PriceChartPanel } from './PriceChartPanel';
import { AnnouncementsTab, FactorsTab, FinancialsTab, FundFlowTab } from './StockTabs';
import { AddToResearch } from '../../features/research/AddToResearch';

const TABS = ['financials', 'fund-flow', 'factors', 'announcements'] as const;
type TabKey = (typeof TABS)[number];

/** /stocks/:code 个股档案（plan §2.4）：行情头 + 深色分时/日K/周K + 周期分类 + 财务/资金/因子/公告外链 */
export function StockPage() {
  const { code: raw = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  // 评审 T-F22a m13：先去空格、转大写再校验；合法但写法不规范时改写为规范 URL
  const code = raw.trim().toUpperCase();
  const valid = CODE_RE.test(code);
  const profile = useSecurityProfile(valid && code === raw ? code : undefined);

  if (valid && code !== raw) return <Navigate to={`/stocks/${encodeURIComponent(code)}${location.search}`} replace />;

  if (!valid) {
    return (
      <div className="page-scroll" data-testid="stock-page">
        <Result status="warning" title="证券代码格式不正确" subTitle={<span>应为 6 位代码加交易所后缀，例如 <span className="mono">600000.SH</span>；收到 <span className="mono">{code}</span></span>}
          extra={<Button size="small" onClick={() => navigate('/terminal')}>回到交易终端</Button>} />
      </div>
    );
  }
  if (profile.isPending) return <div className="page-scroll" data-testid="stock-page"><Loading /></div>;
  if (profile.isError) {
    const nf = profile.error instanceof ApiError && profile.error.status === 404;
    return (
      <div className="page-scroll" data-testid="stock-page">
        {nf ? (
          <Result status="404" title="未找到该证券" subTitle={<span className="mono">{code}</span>} extra={<Button size="small" onClick={() => navigate('/market')}>去市场概览</Button>} />
        ) : <ErrorBox error={profile.error} />}
      </div>
    );
  }
  return <StockBody key={code} profile={profile.data} />;
}

function StockBody({ profile }: { profile: SecurityProfile }) {
  const code = profile.security_code;
  const [sp, setSp] = useSearchParams();
  const tab: TabKey = (TABS as readonly string[]).includes(sp.get('tab') ?? '') ? (sp.get('tab') as TabKey) : 'financials';
  return (
    <div className="page-scroll stock-page" data-testid="stock-page">
      <StockHeader profile={profile} />
      <div className="stock-top">
        <PriceChartPanel code={code} initial={profile.suspended ? 'd' : '1m'} height={392} />
        <div className="stock-side">
          <ProfilePanel profile={profile} />
          <HorizonPanel code={code} />
        </div>
      </div>
      <section className="panel stock-tabs">
        <Tabs
          size="small"
          activeKey={tab}
          onChange={(k) => setSp((p) => { const n = new URLSearchParams(p); n.set('tab', k); return n; }, { replace: true })}
          items={[
            { key: 'financials', label: '财务', children: <FinancialsTab code={code} /> },
            { key: 'fund-flow', label: '资金流', children: <FundFlowTab code={code} /> },
            { key: 'factors', label: '因子', children: <FactorsTab code={code} /> },
            { key: 'announcements', label: '公告', children: <AnnouncementsTab code={code} /> },
          ]}
        />
      </section>
    </div>
  );
}

function todayBar(bars: Bar[] | undefined, q: QuoteItem | null | undefined) {
  const last = bars?.[bars.length - 1];
  return last && q && last.t.slice(0, 10) === q.t.slice(0, 10) ? last : null;
}

/** 1m 响应顶层 pre_close（契约 v0.2.6 Bar 响应）；只在与行情同一交易日时使用 */
function intradayPreClose(res: BarsResponse | undefined, q: QuoteItem | null | undefined) {
  if (!res?.pre_close || !q) return null;
  const day = (res.items[0]?.t ?? res.data_as_of).slice(0, 10);
  return day === q.t.slice(0, 10) ? res.pre_close : null;
}

/**
 * 市值 = 价格 × 股本。评审 T-F22a m19：A 股价格 < 1e5、股本 < 1e12，乘积 < 1e17，
 * 双精度相对误差约 1e-16，展示只保留到 0.01 亿（1e6 元），浮点误差远小于展示精度，因此保留 Number 乘法。
 */
const capOf = (price: string, shares: number) => Number(price) * shares;

function StockHeader({ profile }: { profile: SecurityProfile }) {
  const code = profile.security_code;
  const quote = useQuote(code);
  // T-F21：与图表的日 K 窗口共用缓存（同一窗口大小）
  const daily = useBarsWindow(code, 'd', 250);
  // 评审 T-F22a m12：日 K 还没有当日 bar 时，用 1m 响应的 pre_close 作昨收（与分时图共用缓存）
  const intraday = useBarsOf(code, '1m', 240);
  const q = quote.data;
  const tb = todayBar(daily.first ? daily.bars : undefined, q);
  // v0.2.7：停牌不是上市状态，用 suspended 表示
  const suspended = profile.suspended === true;
  const preClose = tb?.pre_close ?? intradayPreClose(intraday.data, q) ?? (suspended && q ? q.price : null);
  const float = profile.float_shares ? Number(profile.float_shares) : null;
  // v0.2.8：ETF 价格保留 3 位小数（价格字段是字符串，原样显示即保留；涨跌额也按 3 位）
  const pd = profile.type === 'etf' ? 3 : 2;
  const stats: [string, React.ReactNode][] = [
    ['今开', tb ? <span className={pctClass(preClose ? Number(tb.open) - Number(preClose) : 0)}>{tb.open}</span> : '—'],
    ['最高', tb ? <span className={pctClass(preClose ? Number(tb.high) - Number(preClose) : 0)}>{tb.high}</span> : '—'],
    ['最低', tb ? <span className={pctClass(preClose ? Number(tb.low) - Number(preClose) : 0)}>{tb.low}</span> : '—'],
    ['昨收', preClose ?? '—'],
    ['成交量', q ? `${fmtAmount(Number(q.volume) / 100)}手` : '—'],
    ['成交额', q ? fmtAmount(q.amount) : '—'],
    ['换手率', q && float ? `${fmtNum((Number(q.volume) / float) * 100)}%` : '—'],
    ['总市值', q && profile.total_shares ? fmtAmount(capOf(q.price, Number(profile.total_shares))) : '—'],
    ['流通市值', q && float ? fmtAmount(capOf(q.price, float)) : '—'],
  ];
  return (
    <header className="stock-head" data-testid="stock-head">
      <div className="sh-id">
        <span className="q-name">{profile.name}</span>
        <span className="mono muted">{code}</span>
        {profile.type !== 'stock' ? <Tag color="blue" data-testid="security-type-tag">{SECURITY_TYPE[profile.type]}</Tag> : null}
        {profile.board ? <Tag variant="outlined">{BOARD[profile.board]}</Tag> : null}
        {profile.risk_flag ? <Tag color="orange" data-testid="risk-flag-tag">{SECURITY_RISK_FLAG[profile.risk_flag]}</Tag> : null}
        {suspended ? <Tag color="default" data-testid="suspended-tag">停牌</Tag> : null}
        {profile.listing_status !== 'listed' ? <Tag color="default" data-testid="listing-status-tag">{LISTING_STATUS[profile.listing_status]}</Tag> : null}
        <AddToResearch origin="from_stock" securityCode={code} securityType={profile.type} />
      </div>
      {quote.isPending ? <span className="muted">行情加载中…</span> : q ? (
        <div className="sh-quote">
          <span className={`q-price mono ${pctClass(q.change_pct)}`}>{q.price}</span>
          <span className={`mono ${pctClass(q.change_pct)}`}>
            {preClose && !suspended ? `${signed(Number(q.price) - Number(preClose), pd)} ` : ''}({signed(q.change_pct)}%)
          </span>
          <Tooltip title="行情时间（北京时间）"><span className="muted small mono">{fmtTime(q.t)}</span></Tooltip>
          <DataStatusTag status={q.data_status} asOf={q.data_as_of} gaps={q.gaps} />
        </div>
      ) : <span className="muted">无行情缓存</span>}
      {q ? <GapNote status={q.data_status} gaps={q.gaps} asOf={q.data_as_of} testId="quote-gap-note" /> : null}
      <div className="sh-stats">
        {stats.map(([k, v]) => (
          <div key={k}>
            <label>{k}</label>
            <b className="mono">{v}</b>
          </div>
        ))}
      </div>
    </header>
  );
}

function ProfilePanel({ profile }: { profile: SecurityProfile }) {
  // v0.2.8：ETF 的板块、风险标记、股本、行业为 null、概念为 []，不算数据缺口，显示“不适用”
  const etf = profile.type === 'etf';
  const none = etf ? '不适用' : '—';
  const rows: [string, React.ReactNode][] = [
    ['类型', SECURITY_TYPE[profile.type]],
    ['所属行业', profile.industry ? `${profile.industry.name}（${INDUSTRY_TAXONOMY[profile.industry.taxonomy]}）` : none],
    ['概念', profile.concepts.length ? profile.concepts.map((c) => c.name).join('、') : none],
    ['上市日期', profile.list_date ? `${profile.list_date}${profile.list_date_basis === 'neeq_select' ? '（精选层挂牌日）' : ''}` : '—'],
    ...(profile.delist_date ? [['退市日期', profile.delist_date] as [string, React.ReactNode]] : []),
    ...(profile.former_names.length ? [['曾用名', profile.former_names.map((f) => f.name).join('、')] as [string, React.ReactNode]] : []),
    ...(profile.code_history.length
      ? [['原代码', <span className="mono">{profile.code_history.map((c) => c.security_code).join('、')}</span>] as [string, React.ReactNode]]
      : []),
    ['总股本', profile.total_shares ? `${fmtAmount(profile.total_shares)}股` : none],
    ['流通股本', profile.float_shares ? `${fmtAmount(profile.float_shares)}股` : none],
    ...(etf ? [['交易单位', '每手 100 份，价格保留 3 位小数'] as [string, React.ReactNode]] : []),
    ['交易所', profile.exchange === 'SH' ? '上交所' : profile.exchange === 'SZ' ? '深交所' : '北交所'],
  ];
  return (
    <section className="panel side-panel" data-testid="profile-panel">
      <div className="panel-head">
        <span className="panel-title">基本信息</span>
        <span className="spacer" />
        <DataStatusTag status={profile.data_status} asOf={profile.data_as_of} gaps={profile.gaps} />
      </div>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
      {/* v0.2.7：attribution 原样展示；sources 说明各字段来源 */}
      <div className="muted small profile-attr" data-testid="profile-attribution">
        {profile.attribution}（主数据截至 {profile.master_as_of}）
        {profile.sources.length ? ` · 来源：${[...new Set(profile.sources.map((x) => PROVIDER[x.provider]))].join('、')}` : ''}
      </div>
    </section>
  );
}

/** 契约 §7.3 /horizon-assessments：周期分类（只描述适合的持有周期，不含动作） */
function HorizonPanel({ code }: { code: string }) {
  const q = useHorizonAssessment(code);
  const notFound = q.error instanceof ApiError && q.error.status === 404;
  return (
    <section className="panel side-panel" data-testid="horizon-panel">
      <div className="panel-head">
        <span className="panel-title">周期分类</span>
        {q.data ? <span className="muted small mono">v{q.data.classifier_version}</span> : null}
        <span className="spacer" />
        <span className="muted small">只描述适合的持有周期</span>
      </div>
      {q.isPending ? <Loading /> : notFound ? (
        <div className="muted small hz-empty">暂无周期分类结果（该证券当前未进入策略池）</div>
      ) : q.isError ? <ErrorBox error={q.error} /> : (
        <div className="hz-list stock-hz">
          {ENUMS.horizon.map((h) => {
            const score = q.data.scores[h];
            const caps = q.data.caps.filter((c) => c.horizon === h);
            const hints = q.data.hints.filter((x) => x.horizon === h);
            const ok = q.data.suitable.includes(h);
            return (
              <div key={h} className={`hz-line${ok ? ' ok' : ''}`} data-testid={`hz-${h}`}>
                <span className="hz-name">{HORIZON[h]}</span>
                <span className="track"><span className="fill" style={{ width: `${score}%` }} /></span>
                <span className="mono hz-score">{score}</span>
                {ok ? <Tag color="blue" variant="outlined">适合</Tag> : <span className="hz-tag-gap" />}
                {/* 评审 T-F22a m10：封顶/提示可 Tab 聚焦、Enter/Space 打开，读屏读到全文 */}
                {caps.length ? (
                  <KeyTip lines={caps.map((c) => `封顶 ${c.cap}（${CAP_KIND_TEXT[c.kind]}）：${capExplanation(c)}`)} className="warn small" testId={`cap-${h}`}>封顶</KeyTip>
                ) : null}
                {hints.length ? (
                  <KeyTip lines={hints.map((x) => x.text)} className="muted small" testId={`hint-${h}`}>提示</KeyTip>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
