import { Button, Result, Tabs, Tag, Tooltip } from 'antd';
import { useNavigate, useParams, useSearchParams } from 'react-router';
import { ApiError } from '../../api/client';
import { ENUMS } from '../../api/enums';
import { CODE_RE, useBarsOf, useQuote, useSecurityProfile } from '../../api/marketQueries';
import type { Board, SecurityProfile } from '../../api/marketTypes';
import { useHorizonAssessment } from '../../api/queries';
import type { Bar, QuoteItem } from '../../api/types';
import { DataStatusTag, ErrorBox, Loading } from '../../components/common';
import { CAP_KIND_TEXT, capExplanation } from '../../i18n/horizonCaps';
import { HORIZON } from '../../i18n/labels';
import { fmtAmount, fmtNum, fmtTime, pctClass, signed } from '../../lib/format';
import { PriceChartPanel } from './PriceChartPanel';
import { AnnouncementsTab, FactorsTab, FinancialsTab, FundFlowTab } from './StockTabs';

const BOARD: Record<Board, string> = { main: '主板', chinext: '创业板', star: '科创板', bse: '北交所' };
const TABS = ['financials', 'fund-flow', 'factors', 'announcements'] as const;
type TabKey = (typeof TABS)[number];

/** /stocks/:code 个股档案（plan §2.4）：行情头 + 深色分时/日K/周K + 周期分类 + 财务/资金/因子/公告外链 */
export function StockPage() {
  const { code = '' } = useParams();
  const navigate = useNavigate();
  const valid = CODE_RE.test(code);
  const profile = useSecurityProfile(code);

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
        <PriceChartPanel code={code} initial={profile.status === 'suspended' ? 'd' : '1m'} height={392} />
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

function StockHeader({ profile }: { profile: SecurityProfile }) {
  const code = profile.security_code;
  const quote = useQuote(code);
  const daily = useBarsOf(code, 'd', 250);
  const q = quote.data;
  const tb = todayBar(daily.data?.items, q);
  const suspended = profile.status === 'suspended';
  const preClose = tb?.pre_close ?? (suspended && q ? q.price : null);
  const float = profile.float_shares ? Number(profile.float_shares) : null;
  const stats: [string, React.ReactNode][] = [
    ['今开', tb ? <span className={pctClass(preClose ? Number(tb.open) - Number(preClose) : 0)}>{tb.open}</span> : '—'],
    ['最高', tb ? <span className={pctClass(preClose ? Number(tb.high) - Number(preClose) : 0)}>{tb.high}</span> : '—'],
    ['最低', tb ? <span className={pctClass(preClose ? Number(tb.low) - Number(preClose) : 0)}>{tb.low}</span> : '—'],
    ['昨收', preClose ?? '—'],
    ['成交量', q ? `${fmtAmount(Number(q.volume) / 100)}手` : '—'],
    ['成交额', q ? fmtAmount(q.amount) : '—'],
    ['换手率', q && float ? `${fmtNum((Number(q.volume) / float) * 100)}%` : '—'],
    ['总市值', q && profile.total_shares ? fmtAmount(Number(q.price) * Number(profile.total_shares)) : '—'],
    ['流通市值', q && float ? fmtAmount(Number(q.price) * float) : '—'],
  ];
  return (
    <header className="stock-head" data-testid="stock-head">
      <div className="sh-id">
        <span className="q-name">{profile.name}</span>
        <span className="mono muted">{code}</span>
        <Tag variant="outlined">{BOARD[profile.board]}</Tag>
        {profile.risk_warning ? <Tag color="orange">风险警示</Tag> : null}
        {suspended ? <Tag color="default" data-testid="suspended-tag">停牌</Tag> : null}
        {profile.status === 'delisted' ? <Tag color="default">已退市</Tag> : null}
      </div>
      {quote.isPending ? <span className="muted">行情加载中…</span> : q ? (
        <div className="sh-quote">
          <span className={`q-price mono ${pctClass(q.change_pct)}`}>{q.price}</span>
          <span className={`mono ${pctClass(q.change_pct)}`}>
            {preClose && !suspended ? `${signed(Number(q.price) - Number(preClose))} ` : ''}({signed(q.change_pct)}%)
          </span>
          <Tooltip title="行情时间（北京时间）"><span className="muted small mono">{fmtTime(q.t)}</span></Tooltip>
          <DataStatusTag status={q.data_status} asOf={q.data_as_of} gaps={q.gaps} />
        </div>
      ) : <span className="muted">无行情缓存</span>}
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
  const rows: [string, React.ReactNode][] = [
    ['所属行业', profile.industry ?? '—'],
    ['概念', profile.concepts.length ? profile.concepts.join('、') : '—'],
    ['上市日期', profile.list_date ?? '—'],
    ['总股本', profile.total_shares ? `${fmtAmount(profile.total_shares)}股` : '—'],
    ['流通股本', profile.float_shares ? `${fmtAmount(profile.float_shares)}股` : '—'],
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
                {caps.length ? (
                  <Tooltip title={caps.map((c) => `封顶 ${c.cap}（${CAP_KIND_TEXT[c.kind]}）：${capExplanation(c)}`).join('；')}>
                    <span className="warn small" data-testid={`cap-${h}`}>封顶</span>
                  </Tooltip>
                ) : null}
                {hints.length ? (
                  <Tooltip title={hints.map((x) => x.text).join('；')}>
                    <span className="muted small" data-testid={`hint-${h}`}>提示</span>
                  </Tooltip>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
