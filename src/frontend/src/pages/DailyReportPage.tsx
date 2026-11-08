import { Alert, Button, Segmented, Select, Tag } from 'antd';
import { useEffect, useId, useRef } from 'react';
import { Link, Navigate, useLocation, useNavigate, useParams, useSearchParams } from 'react-router';
import { useDailyReport, useDailyReportPages, useDailyReports } from '../api/queries';
import type { DailyReport, DailyReportStock, TextWithEvidence } from '../api/types';
import { ActionBadge, ConsensusBadge, DataStatusTag, ErrorBox, Loading } from '../components/common';
import { EvidenceChips } from '../components/EvidenceChips';
import { CardDisclaimer } from '../components/RiskDisclosure';
import { DIMENSION, EXECUTABILITY, GAP_REASON, RECONCILIATION, REGIME, RISK_LEVEL } from '../i18n/labels';
import { fmtNum, fmtTime, pctClass, signed } from '../lib/format';
import { PENDING_ROUTE, STOCK_FILTERS, type StockFilter } from './dailyReportRoutes';

const CHANGE = { new: { t: '新增', c: 'blue' }, changed: { t: '有变化', c: 'orange' }, unchanged: { t: '无变化', c: 'default' }, removed: { t: '已移出', c: 'default' } } as const;
const VS_REGIME = { below: '低于参考区间', within: '在参考区间内', above: '高于参考区间' } as const;

const FILTER_LABEL: Record<StockFilter, string> = { all: '全部', changed: '新增 / 有变化', unchanged: '无变化', removed: '已移出' };
const matchFilter = (s: DailyReportStock, f: StockFilter) =>
  f === 'all' || (f === 'changed' ? s.change_from_previous === 'new' || s.change_from_previous === 'changed' : s.change_from_previous === f);


const clampPct = (v: number) => Math.min(100, Math.max(0, Number.isFinite(v) ? v : 0));

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

const LOAD_MORE = '__more__';

/** 日期切换：游标分页的日期下拉 + 上一期 / 下一期（列表按日期倒序） */
function DateSwitcher({ date }: { date: string }) {
  const navigate = useNavigate();
  // 评审 7afbc06 m2：切换日期时保留 ?filter= 等查询参数
  const { search, pathname } = useLocation();
  const go = (d: string) => navigate({ pathname: `/daily-reports/${d}`, search });
  const pages = useDailyReportPages();
  const dates = (pages.data?.pages ?? []).flatMap((p) => p.items.map((x) => x.date));
  const idx = dates.indexOf(date);
  // 评审 7afbc06 m1：当前是已加载的最后一项且还有下一页时，加载完直接跳到新一页的第一项
  // 评审 b23401a N6：等待期间用户换了日期（看地址，不看仍在显示的旧数据）或离开了页面，就不再跳转
  const pathRef = useRef(pathname);
  useEffect(() => { pathRef.current = pathname; }, [pathname]);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const loadOlder = async () => {
    const from = pathname;
    const res = await pages.fetchNextPage();
    if (!alive.current || pathRef.current !== from) return;
    const all = (res.data?.pages ?? []).flatMap((p) => p.items.map((x) => x.date));
    const i = all.indexOf(date);
    const next = i >= 0 ? all[i + 1] : undefined;
    if (next) go(next);
  };
  const older = idx >= 0 ? dates[idx + 1] : undefined;
  const newer = idx > 0 ? dates[idx - 1] : undefined;
  const options = [
    ...(idx < 0 ? [{ value: date, label: date }] : []),
    ...dates.map((d) => ({ value: d, label: d })),
    ...(pages.hasNextPage ? [{ value: LOAD_MORE, label: pages.isFetchingNextPage ? '加载中…' : '加载更早…' }] : []),
  ];
  return (
    <span className="report-dates">
      <Button size="small" disabled={!older && !pages.hasNextPage} aria-label="上一期"
        onClick={() => (older ? go(older) : void loadOlder())}>‹ 上一期</Button>
      <Select
        size="small" value={date} style={{ width: 130 }} aria-label="选择日期" options={options} loading={pages.isLoading}
        onChange={(d) => (d === LOAD_MORE ? void pages.fetchNextPage() : go(d))}
      />
      <Button size="small" disabled={!newer} aria-label="下一期" onClick={() => newer && go(newer)}>下一期 ›</Button>
    </span>
  );
}

function StockCard({ s, r }: { s: DailyReportStock; r: DailyReport }) {
  const navigate = useNavigate();
  const to = s.suggestion_id ? `/suggestions/${s.suggestion_id}` : null;
  const open = () => to && navigate(to);
  const titleId = useId();
  return (
    // 评审 b23401a N4/N5：卡片本身不再是 role="link"（避免证据标签这类可聚焦元素嵌套在链接里）；
    // 键盘和读屏用标题上的真实链接，链接名带“查看候选信号卡”的去向说明；鼠标点卡片空白处仍可进入
    <section
      className={`panel stock-card ${s.change_from_previous === 'removed' ? 'dim' : ''} ${to ? 'clickable' : 'static'}`}
      data-testid={`stc-${s.security_code}`}
      aria-labelledby={titleId}
      {...(to ? { onClick: open } : {})}
    >
      <div className="stc-head">
        {to ? (
          <Link id={titleId} to={to} className="stc-title" onClick={(e) => e.stopPropagation()} data-testid={`stc-link-${s.security_code}`}>
            <b>{s.name}</b> <span className="mono muted small">{s.security_code}</span><span className="sr-only">：查看候选信号卡</span>
          </Link>
        ) : (
          <span id={titleId} className="stc-title"><b>{s.name}</b> <span className="mono muted small">{s.security_code}</span></span>
        )}
        {s.change_from_previous === null ? <Tag>无比较基准 · 见数据缺口</Tag> : <Tag color={CHANGE[s.change_from_previous].c}>{CHANGE[s.change_from_previous].t}</Tag>}
        {s.change_fields?.length ? <span className="muted small">变化：{s.change_fields.join("、")}</span> : null}
        <span className="spacer" />
        {/* v0.2.3 #3：收盘价、涨跌幅、数据状态、最高风险级别 */}
        <span className={`mono small ${pctClass(s.change_pct)}`} data-testid="stc-close">
          {s.close ?? '—'} {s.change_pct != null ? `${signed(s.change_pct)}%` : ''}
        </span>
        <DataStatusTag status={s.data_status} />
        {s.max_risk_level ? <Tag color={RISK_LEVEL[s.max_risk_level].color}>风险 {RISK_LEVEL[s.max_risk_level].text}</Tag> : null}
        {s.suggestion ? <ConsensusBadge status={s.suggestion.consensus} /> : null}
      </div>
      {s.suggestion?.actions.length ? (
        <div className="badges">{s.suggestion.actions.map((x) => <ActionBadge key={x.strategy_key} action={x.action} strategyName={x.strategy_name} tLeg={x.t_leg} lifecycle={x.lifecycle} />)}</div>
      ) : <div className="small muted">{s.change_from_previous === 'removed' ? '已移出持仓与自选，本期不再生成策略结论' : '暂无启用的策略实例'}</div>}
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
  );
}

function AccountPanel({ r }: { r: DailyReport }) {
  const a = r.account;
  const range = r.market.regime_position_range;
  const lo = range ? clampPct(Number(range.min_pct)) : 0;
  const hi = range ? clampPct(Number(range.max_pct)) : 0;
  const rec = RECONCILIATION[r.reconciliation.status];
  const recTo = r.account_id ? `/portfolio?tab=reconciliation&account_id=${encodeURIComponent(r.account_id)}` : null;
  return (
    <section className="panel acct" data-testid="report-account">
      <div className="panel-head">
        <span className="panel-title">账户概览</span>
        <Tag color={rec.color} data-testid="report-rec">
          {rec.text}{r.reconciliation.diff_count ? ` · ${r.reconciliation.diff_count} 处差异` : ''}{r.reconciliation.important_count ? `（重要 ${r.reconciliation.important_count}）` : ''}
        </Tag>
        {r.reconciliation.as_of ? <span className="muted small">对账于 {fmtTime(r.reconciliation.as_of)}</span> : null}
        {recTo && r.reconciliation.status === 'diff' ? <Link className="small" to={recTo}>查看对账 ›</Link> : null}
      </div>
      {a ? (
        <>
          <div className="stat-grid">
            <div><label>总资产</label><b className="mono">{fmtNum(a.total_assets)}</b></div>
            <div><label>现金余额</label><b className="mono">{fmtNum(a.cash)}</b></div>
            <div><label>总仓位</label><b className="mono">{a.position_pct === null ? '—（缺少资产分母）' : `${fmtNum(a.position_pct, 1)}%`}</b></div>
            <div><label>当日盈亏</label><b className={`mono ${pctClass(a.pnl_day)}`}>{a.pnl_day === null ? '—（缺少计算基准）' : signed(a.pnl_day)}</b></div>
          </div>
          <div className="regime">
            <div className="small">
              大盘环境 <Tag color="blue">{r.market.regime ? REGIME[r.market.regime] : '未知'}</Tag>
              {range ? `参考仓位区间 ${lo}–${hi}%（模板参数，不是指令）` : '参考仓位区间：缺失'}{a.position_vs_regime ? ` · 当前${VS_REGIME[a.position_vs_regime]}` : ''}
            </div>
            {range && a.position_pct !== null ? (
              <div className="regime-bar" role="img" aria-label={`当前仓位 ${a.position_pct === null ? '—（缺少资产分母）' : `${fmtNum(a.position_pct, 1)}%`}，参考区间 ${lo}–${hi}%`}>
                <div className="band" style={{ left: `${lo}%`, width: `${Math.max(0, hi - lo)}%` }} />
                <div className="mark" style={{ left: `${clampPct(Number(a.position_pct))}%` }} />
              </div>
            ) : null}
          </div>
        </>
      ) : (
        <div className="muted small" data-testid="report-no-account">
          {r.reconciliation.status === 'not_imported' ? '尚未导入交割单，账户概览为空。' : '本期日报未关联账户。'}
          <Link to="/portfolio/import">去导入交割单 ›</Link>
        </div>
      )}
    </section>
  );
}

export function DailyReportPage() {
  const { date } = useParams();
  const [sp, setSp] = useSearchParams();
  const q = useDailyReport(date);
  if (q.isLoading) return <Loading />;
  if (q.isError || !q.data) {
    return (
      <div className="page-scroll report">
        <ErrorBox error={q.error ?? new Error('未找到日报')} />
        <div className="small" style={{ marginTop: 6 }}><Link to="/daily-reports">查看最新一期日报 ›</Link></div>
      </div>
    );
  }
  const r = q.data;
  const raw = sp.get('filter');
  const filter: StockFilter = (STOCK_FILTERS as readonly string[]).includes(raw ?? '') ? (raw as StockFilter) : 'all';
  const count = (f: StockFilter) => r.stocks.filter((s) => matchFilter(s, f)).length;
  const shown = r.stocks.filter((s) => matchFilter(s, filter));
  const setFilter = (f: StockFilter) => {
    const next = new URLSearchParams(sp);
    if (f === 'all') next.delete('filter'); else next.set('filter', f);
    setSp(next, { replace: true });
  };
  return (
    <div className="page-scroll report" data-testid="daily-report">
      <div className="detail-head">
        <span className="q-name">盘后日报</span>
        <DateSwitcher date={r.date} />
        <Tag>不可变快照</Tag>
        <DataStatusTag status={r.data_status} asOf={r.data_as_of} gaps={r.gaps} />
        <span className="muted small">生成于 {fmtTime(r.generated_at)} · 数据截至 {fmtTime(r.data_as_of)} · 说明来源：{r.explanation.source === 'template' ? '模板' : 'LLM'}</span>
      </div>
      <div className="report-summary">{r.explanation.text}</div>
      <CardDisclaimer />
      {r.gaps.length ? (
        <Alert
          className="gap-alert" type="warning" showIcon data-testid="report-gaps"
          title={`数据缺口 ${r.gaps.length} 项（缺失不臆测；相关维度标为“未知”）`}
          description={<div className="gap-grid">{r.gaps.map((g) => <div key={g.key}><Tag>{GAP_REASON[g.reason]}</Tag><span className="mono muted small">{g.key}</span>　{g.message}</div>)}</div>}
        />
      ) : null}

      <div className="report-top">
        <AccountPanel r={r} />
        <section className="panel expo">
          <div className="panel-head"><span className="panel-title">市场</span></div>
          {r.market.breadth ? (
            <div className="small mono">上涨 <b className="up">{r.market.breadth.up}</b> · 下跌 <b className="down">{r.market.breadth.down}</b> · 涨停 {r.market.breadth.limit_up} · 跌停 {r.market.breadth.limit_down}</div>
          ) : <div className="muted small" data-testid="report-no-breadth">市场宽度：缺失</div>}
          <Lines items={r.market.summary} r={r} />
        </section>
        <section className="panel acct-risk" data-testid="report-pending">
          <div className="panel-head"><span className="panel-title">待处理</span></div>
          <div className="small">
            计划草案 <b className="mono">{r.pending.plan_drafts}</b> 份
            {r.pending.plan_drafts ? <> <Link to={PENDING_ROUTE.plan_drafts}>查看 ›</Link></> : null}
          </div>
          <div className="small">
            未解除的不可执行原因 <b className="mono">{r.pending.active_reasons}</b> 项
            {r.pending.active_reasons ? <> <Link to={PENDING_ROUTE.active_reasons}>查看 ›</Link></> : null}
          </div>
        </section>
      </div>

      <div className="panel-head section-gap">
        <span className="panel-title">逐股卡片（持仓 + 自选，共 {r.stocks.length} 只）</span>
        <Segmented
          size="small" value={filter} onChange={(v) => setFilter(v as StockFilter)} aria-label="按变化筛选"
          options={STOCK_FILTERS.map((f) => ({ value: f, label: `${FILTER_LABEL[f]} ${count(f)}` }))}
        />
        <span className="muted small">各策略结论并列；点击卡片进入候选信号卡</span>
      </div>
      {shown.length ? (
        <div className="stock-grid">{shown.map((s) => <StockCard key={s.security_code} s={s} r={r} />)}</div>
      ) : <div className="loading-box" data-testid="report-empty">{r.stocks.length ? '没有符合筛选条件的证券' : '本期没有持仓或自选证券'}</div>}
    </div>
  );
}
