import { Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { useToday } from '../../api/queries';
import type { TerminalRow, TodayResponse } from '../../api/types';
import { ActionBadge, ConsensusBadge, DataStatusTag, ErrorBox, Loading } from '../../components/common';
import { CardDisclaimer } from '../../components/RiskDisclosure';
import {
  ACTION_SHORT, EXECUTABILITY, PLAN_DRAFT_STATUS, REASON_CODE, RECONCILIATION, REGIME, RISK_CONTROL, RISK_LEVEL, SESSION,
} from '../../i18n/labels';
import { fmtNum, fmtTime, pctClass, signed } from '../../lib/format';

/**
 * T-F08 今日关注（GET /today，契约 v0.2.6 §7.3 ⚖）。
 * 只展示契约里给出的字段；列表顺序按服务端返回（plan 2.4：按与用户的相关度排序，不按“股票好坏”）。
 * 每个列表最多 50 条，more=true 时给出对应列表页的入口。
 */

/** more=true 时去哪个列表页查看（契约只说“到对应列表接口查看”，页面对应关系见 T-F08.md 遗留问题） */
const MORE_ROUTE = {
  focus: '/terminal',
  pending_plan_drafts: '/plan-drafts',
  released_reasons: '/candidate-signals',
  risk_flags: '/risk-controls',
  invalidations_today: '/suggestions',
} as const;

type ListKey = keyof typeof MORE_ROUTE;

function Section({ title, k, data, testId, children }: { title: string; k: ListKey; data: TodayResponse; testId: string; children: ReactNode }) {
  const list = data[k];
  return (
    <section className="today-card" data-testid={testId} aria-label={title}>
      <div className="today-card-head">
        <span className="today-card-title">{title}</span>
        <span className="muted small">{list.items.length} 条</span>
        {list.more ? <Link className="small" to={MORE_ROUTE[k]} data-testid={`${testId}-more`}>仅显示前 50 条，查看全部 ›</Link> : null}
      </div>
      {list.items.length ? children : <div className="muted small today-empty">无</div>}
    </section>
  );
}

const stockLink = (code: string | null, name: string | null) =>
  code ? <Link to={`/stocks/${encodeURIComponent(code)}`}><span className="mono">{code}</span> {name}</Link> : <span className="muted">账户级</span>;

const focusColumns: ColumnsType<TerminalRow> = [
  { title: '证券', key: 'sec', width: 150, render: (_, r) => stockLink(r.security_code, r.name) },
  { title: '现价', key: 'price', width: 80, align: 'right', render: (_, r) => <span className={`num ${pctClass(r.quote?.change_pct)}`}>{fmtNum(r.quote?.price)}</span> },
  { title: '涨跌幅', key: 'chg', width: 80, align: 'right', render: (_, r) => <span className={`num ${pctClass(r.quote?.change_pct)}`}>{r.quote ? `${signed(r.quote.change_pct)}%` : '—'}</span> },
  { title: '持仓占比', key: 'w', width: 80, align: 'right', render: (_, r) => (r.holding ? <span className="num">{fmtNum(r.holding.weight_pct)}%</span> : <span className="muted">未持有</span>) },
  {
    title: '候选信号', key: 'sg', render: (_, r) => (r.suggestion ? (
      <Link to={`/suggestions/${r.suggestion.id}`} className="today-sg">
        <ConsensusBadge status={r.suggestion.consensus} />
        {r.suggestion.actions.map((a) => <ActionBadge key={a.strategy_key} action={a.action} strategyName={a.strategy_name} tLeg={a.t_leg} />)}
        <Tag color={EXECUTABILITY[r.suggestion.executability_status].color}>{EXECUTABILITY[r.suggestion.executability_status].text}</Tag>
      </Link>
    ) : <span className="muted">无</span>),
  },
  { title: '不可执行原因', key: 'rs', width: 96, align: 'right', render: (_, r) => (r.active_reason_count ? <span className="num">{r.active_reason_count}</span> : <span className="muted">0</span>) },
  { title: '风险', key: 'risk', width: 70, render: (_, r) => (r.max_risk_level ? <Tag color={RISK_LEVEL[r.max_risk_level].color}>{RISK_LEVEL[r.max_risk_level].text}</Tag> : <span className="muted">—</span>) },
  { title: '数据', key: 'ds', width: 120, render: (_, r) => <DataStatusTag status={r.data_status} asOf={r.data_as_of} /> },
];

export function TodayPage() {
  const q = useToday();
  if (q.isLoading) return <Loading />;
  if (q.isError || !q.data) return <div className="page-scroll"><ErrorBox error={q.error ?? new Error('加载失败')} /></div>;
  const t = q.data;
  const range = t.market.regime_position_range;
  const rec = RECONCILIATION[t.reconciliation.status];
  const dr = t.daily_report;
  return (
    <div className="page-scroll today" data-testid="today-page">
      <div className="detail-head">
        <span className="q-name">今日关注</span>
        <span className="small">交易日 <span className="mono">{t.trade_date}</span></span>
        <Tag data-testid="today-session">{SESSION[t.session]}</Tag>
        <span className="small" data-testid="today-regime">
          大盘环境：{t.market.regime ? REGIME[t.market.regime] : '未知'}
          {range ? <span className="muted">（参考仓位区间 {fmtNum(range.min_pct, 0)}–{fmtNum(range.max_pct, 0)}%，模板参数，不是指令）</span> : null}
        </span>
        <DataStatusTag status={t.market.data_status} />
        <span className="muted small">更新于 {fmtTime(t.server_time)}</span>
        <Link to="/notifications" className="small" data-testid="today-unread">未读通知 <span className="num">{t.unread_notifications}</span></Link>
      </div>
      <CardDisclaimer />

      <div className="today-status">
        <section className="today-card" data-testid="today-daily-report" aria-label="盘后日报">
          <div className="today-card-head"><span className="today-card-title">盘后日报</span></div>
          {dr.status === 'ready' ? (
            <Link to={`/daily-reports/${dr.date}`}>{dr.date} 日报已生成，查看 ›</Link>
          ) : dr.status === 'generating' ? (
            <span><Tag color="processing">生成中</Tag>{dr.date} 日报正在生成</span>
          ) : (
            <span className="muted">{dr.date} 日报尚未生成（收盘后生成）</span>
          )}
        </section>
        <section className="today-card" data-testid="today-reconciliation" aria-label="对账">
          <div className="today-card-head"><span className="today-card-title">对账</span></div>
          <span>
            <Tag color={rec.color}>{rec.text}</Tag>
            {t.reconciliation.status === 'not_imported' ? (
              <Link to="/portfolio/import">导入交割单 ›</Link>
            ) : (
              <>
                差异 <span className="num">{t.reconciliation.diff_count}</span> 项，其中重要 <span className="num">{t.reconciliation.important_count}</span> 项
                {t.reconciliation.as_of ? <span className="muted small">（截至 {fmtTime(t.reconciliation.as_of)}）</span> : null}
                {' '}<Link to="/portfolio?tab=reconciliation">查看 ›</Link>
              </>
            )}
          </span>
        </section>
      </div>

      <Section title="重点关注" k="focus" data={t} testId="today-focus">
        <Table<TerminalRow>
          size="small" pagination={false} rowKey="security_code" dataSource={t.focus.items} columns={focusColumns}
          aria-label="重点关注列表"
        />
      </Section>

      <div className="today-grid">
        <Section title="待确认的计划草案" k="pending_plan_drafts" data={t} testId="today-drafts">
          <ul className="today-list">
            {t.pending_plan_drafts.items.map((d) => (
              <li key={d.id}>
                <Link to={`/plan-drafts/${d.id}`}>{d.name} <span className="mono muted">{d.security_code}</span></Link>
                <ActionBadge action={d.action} />
                <Tag color={PLAN_DRAFT_STATUS[d.status].color}>{PLAN_DRAFT_STATUS[d.status].text}</Tag>
                <span className="muted small">{d.valid_until ? `有效至 ${fmtTime(d.valid_until)}` : '未设有效期'}</span>
              </li>
            ))}
          </ul>
        </Section>

        <Section title="风险提示" k="risk_flags" data={t} testId="today-risks">
          <ul className="today-list">
            {t.risk_flags.items.map((f, i) => (
              <li key={`${f.security_code ?? 'acct'}-${f.control}-${i}`}>
                <Tag color={RISK_LEVEL[f.level].color}>{RISK_LEVEL[f.level].text}</Tag>
                <span className="small">{RISK_CONTROL[f.control]}</span>
                {stockLink(f.security_code, f.name)}
                <span>{f.message}</span>
                {f.gated_actions.length ? <span className="muted small">受限动作：{f.gated_actions.map((a) => ACTION_SHORT[a]).join('、')}</span> : null}
                {f.quantity_cap !== null ? <span className="muted small">数量上限 <span className="num">{fmtNum(f.quantity_cap, 0)}</span></span> : null}
              </li>
            ))}
          </ul>
        </Section>

        <Section title="今日解除的不可执行原因" k="released_reasons" data={t} testId="today-released">
          <ul className="today-list">
            {t.released_reasons.items.map((r) => (
              <li key={r.reason_id}>
                <Tag>{REASON_CODE[r.code] ?? r.code}</Tag>
                <Link to={`/candidate-signals/${r.signal_id}`}>{r.name} <span className="mono muted">{r.security_code}</span></Link>
                <span className="muted small">解除于 {fmtTime(r.released_at)}</span>
              </li>
            ))}
          </ul>
        </Section>

        <Section title="今日失效" k="invalidations_today" data={t} testId="today-invalidations">
          <ul className="today-list">
            {t.invalidations_today.items.map((x, i) => (
              <li key={`${x.suggestion_id}-${x.strategy_key}-${i}`}>
                <Link to={`/suggestions/${x.suggestion_id}`}>{x.name} <span className="mono muted">{x.security_code}</span></Link>
                <span className="mono small muted">{x.strategy_key}</span>
                <span>{x.text}</span>
                <span className="muted small">{fmtTime(x.at)}</span>
              </li>
            ))}
          </ul>
        </Section>
      </div>
    </div>
  );
}
