import { useMemo } from 'react';
import { Input, Segmented, Select, Space, Table, Tag, Tooltip } from 'antd';
import { Link, useSearchParams } from 'react-router';
import { ENUMS, type CandidateSignalState, type Horizon } from '../../api/enums';
import { useToday } from '../../api/queries';
import { releasedSince, useConflictSignalIds, useReleasedReasons, useSignalList, type SignalFilter } from '../../api/signalQueries';
import type { CandidateSignal, NonExecutableReason } from '../../api/types';
import { CursorPager } from '../../components/CursorPager';
import { ActionBadge, ConfidenceTag, ErrorBox } from '../../components/common';
import { HORIZON, REASON_CODE, SIGNAL_STATE } from '../../i18n/labels';
import { RELEASED_BY } from '../../i18n/signalLabels';
import { fmtTime } from '../../lib/format';
import { parseTab, type SignalsTab } from '../../lib/signals';
import { LifecycleBadge } from './LifecycleBadge';

const STATES = ENUMS.candidate_signal_state as readonly CandidateSignalState[];
const HORIZONS = ENUMS.horizon as readonly Horizon[];
const pick = <T extends string>(v: string | null, all: readonly T[]): T | '' => (v && (all as readonly string[]).includes(v) ? (v as T) : '');

/** 候选信号列表（契约 v0.2.7 §7.6）：URL 驱动筛选；“今日已解除”页签按 released_since 列出今天解除的原因 */
export function CandidateSignalsPage() {
  const [sp, setSp] = useSearchParams();
  const tab = parseTab(sp.get('tab'));
  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v);
    else next.delete(k);
    setSp(next, { replace: true });
  };
  return (
    <div className="page-scroll page" data-testid="candidate-signals-page">
      <h2 className="page-title">候选信号</h2>
      <div className="muted small" style={{ marginBottom: 8 }}>
        候选信号是策略规则信号经过可执行性检查后的结果，仅供你判断参考；各策略结论并列展示，系统不合成单一结论，交易由你在券商端自行完成。
      </div>
      <Segmented<SignalsTab>
        value={tab}
        onChange={(v) => setParam('tab', v === 'signals' ? '' : v)}
        options={[{ value: 'signals', label: '候选信号' }, { value: 'released', label: '今日已解除' }]}
        style={{ marginBottom: 12 }}
        data-testid="signals-tab"
      />
      {tab === 'released' ? <ReleasedTab /> : <SignalsList sp={sp} setParam={setParam} />}
    </div>
  );
}

function SignalsList({ sp, setParam }: { sp: URLSearchParams; setParam: (k: string, v: string) => void }) {
  const f: SignalFilter = {
    state: pick(sp.get('state'), STATES),
    security_code: (sp.get('security_code') ?? '').trim(),
    horizon: pick(sp.get('horizon'), HORIZONS),
    instance_id: (sp.get('instance_id') ?? '').trim(),
  };
  const list = useSignalList(f);
  const rows = list.items;
  // 方向冲突（v0.2.9 #7）：按服务端的 STRATEGY_CONFLICT 原因判断（服务端对全部信号计算，不受分页影响）
  const loadedIds = useMemo(() => rows.map((r) => r.id), [rows]);
  const conflictIds = useConflictSignalIds(loadedIds);
  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Select<CandidateSignalState | ''>
          style={{ width: 150 }}
          value={f.state}
          onChange={(v) => setParam('state', v)}
          options={[{ value: '', label: '全部状态' }, ...STATES.map((s) => ({ value: s, label: SIGNAL_STATE[s].text }))]}
          data-testid="filter-state"
        />
        <Select<Horizon | ''>
          style={{ width: 120 }}
          value={f.horizon}
          onChange={(v) => setParam('horizon', v)}
          options={[{ value: '', label: '全部周期' }, ...HORIZONS.map((h) => ({ value: h, label: HORIZON[h] }))]}
          data-testid="filter-horizon"
        />
        <Input.Search
          key={f.security_code}
          allowClear
          defaultValue={f.security_code}
          placeholder="证券代码，如 600000.SH"
          style={{ width: 220 }}
          onSearch={(v) => setParam('security_code', v.trim().toUpperCase())}
          data-testid="filter-code"
        />
        {f.instance_id ? <Tag closable onClose={() => setParam('instance_id', '')}>策略实例 {f.instance_id.slice(-6)}</Tag> : null}
      </Space>
      {list.isError ? <ErrorBox error={list.error} /> : null}
      <Table<CandidateSignal>
        size="small"
        rowKey="id"
        loading={list.isPending}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: '没有符合条件的候选信号' }}
        data-testid="signals-table"
        columns={[
          {
            title: '证券', key: 'sec', width: 150,
            render: (_v, r) => <Link to={`/candidate-signals/${r.id}`} data-testid={`sig-link-${r.id}`}>{r.name} <span className="mono muted">{r.security_code}</span></Link>,
          },
          {
            title: '策略', key: 'strategy',
            render: (_v, r) => <span>{r.strategy_name} <LifecycleBadge lifecycle={r.lifecycle} /></span>,
          },
          { title: '周期', dataIndex: 'horizon', width: 80, render: (h: Horizon) => HORIZON[h] },
          {
            title: '规则信号', key: 'action', width: 130,
            render: (_v, r) => (
              <Space size={4}>
                <ActionBadge action={r.proposed_action} tLeg={r.t_leg} strategyName={r.strategy_name} />
                {conflictIds.has(r.id) ? (
                  <Tooltip title="同一证券还有方向相反、尚未结束的候选信号，并列展示，请自行判断">
                    <Tag color="magenta" data-testid={`conflict-${r.id}`}>方向冲突</Tag>
                  </Tooltip>
                ) : null}
              </Space>
            ),
          },
          { title: '状态', dataIndex: 'state', width: 110, render: (s: CandidateSignalState) => <Tag color={SIGNAL_STATE[s].color}>{SIGNAL_STATE[s].text}</Tag> },
          { title: '规则满足度', dataIndex: 'score', width: 90, align: 'right', render: (v: number | null) => <span className="mono">{v ?? '—'}</span> },
          { title: '置信度', key: 'conf', width: 150, render: (_v, r) => <ConfidenceTag c={r.confidence} /> },
          { title: '原因', key: 'reasons', width: 60, align: 'right', render: (_v, r) => <span className="mono">{r.reason_ids.length}</span> },
          { title: '有效至', dataIndex: 'valid_until', width: 130, render: (v: string | null) => <span className="mono small">{v ? fmtTime(v).slice(5) : '—'}</span> },
          { title: '生成时间', dataIndex: 'created_at', width: 130, render: (v: string) => <span className="mono small">{fmtTime(v).slice(5)}</span> },
        ]}
      />
      <CursorPager query={list} loaded={rows.length} testId="signals-pager" />
    </>
  );
}

/** 今日已解除：GET /non-executable-reasons?status=released&released_since={trade_date}T00:00:00+08:00（released_at 倒序） */
function ReleasedTab() {
  const today = useToday();
  const tradeDate = today.data?.trade_date;
  const list = useReleasedReasons(tradeDate);
  const rows = list.items;
  // v0.2.9 #8：原因自带 security_code / name，不再按 signal_id 逐个取信号
  if (today.isError && !tradeDate) return <ErrorBox error={today.error} prefix="交易日加载失败" />;
  return (
    <>
      <div className="muted small" style={{ marginBottom: 8 }} data-testid="released-since">
        {tradeDate ? `${tradeDate} 起解除的不可执行原因（自 ${releasedSince(tradeDate)}）` : '正在读取交易日…'}
      </div>
      {list.isError ? <ErrorBox error={list.error} /> : null}
      <Table<NonExecutableReason>
        size="small"
        rowKey="id"
        loading={!tradeDate || list.isPending}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: '今天还没有解除的原因' }}
        data-testid="released-table"
        columns={[
          {
            title: '候选信号', key: 'sig',
            render: (_v, r) => (
              <Link to={`/candidate-signals/${r.signal_id}`} data-testid={`released-sig-${r.id}`}>
                {r.name} <span className="mono muted">{r.security_code}</span>
              </Link>
            ),
          },
          { title: '原因', key: 'code', render: (_v, r) => <span><Tag>{r.code}</Tag>{REASON_CODE[r.code]}</span> },
          { title: '解除条件', key: 'rc', render: (_v, r) => r.release_condition.human_text },
          { title: '解除方式', dataIndex: 'released_by', width: 140, render: (v: 'system' | 'user') => RELEASED_BY[v] },
          { title: '解除时间', dataIndex: 'released_at', width: 150, render: (v: string | null) => <span className="mono small">{v ? fmtTime(v) : '—'}</span> },
        ]}
      />
      <CursorPager query={list} loaded={rows.length} testId="released-pager" />
    </>
  );
}
