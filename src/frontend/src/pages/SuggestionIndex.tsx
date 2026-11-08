import { Link, useSearchParams } from 'react-router';
import { Alert, Input, Select, Table, Tag } from 'antd';
import { useSuggestionPages } from '../api/suggestionQueries';
import { ENUMS } from '../api/enums';
import type { SuggestionListItem } from '../api/types';
import { ActionBadge, ConsensusBadge, ErrorBox, Loading } from '../components/common';
import { CursorPager } from '../components/CursorPager';
import { EXECUTABILITY, SUGGESTION_STATUS } from '../i18n/labels';
import { fmtTime } from '../lib/format';

/** 当前卡与历史卡都读真实接口；不再跳首张或用占位页吞掉筛选参数。 */
export function SuggestionIndex() {
  const [params, setParams] = useSearchParams();
  const status = params.get('status') ?? 'active';
  const securityCode = params.get('security_code') ?? '';
  const valid = (ENUMS.suggestion_status as readonly string[]).includes(status) && (!securityCode || /^(?:\d{6}\.(?:SH|SZ|BJ))$/.test(securityCode));
  const q = useSuggestionPages(status, securityCode, valid);
  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];
  const change = (key: string, value: string) => { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); setParams(next); };
  return <div className="page-scroll"><div className="page" data-testid="suggestions-page">
    <h2 className="page-title">候选信号卡列表</h2>
    <p className="muted">各策略并列展示，证据链与风控提示见详情；动作需结合您的计划条件判断。</p>
    <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
      <Select aria-label="卡片状态" value={status} style={{ width: 160 }} onChange={(v) => change('status', v)} options={ENUMS.suggestion_status.map((value) => ({ value, label: SUGGESTION_STATUS[value].text }))} />
      <Input.Search key={securityCode} aria-label="证券代码筛选" defaultValue={securityCode} placeholder="证券代码，如 600000.SH" allowClear style={{ width: 300 }} onSearch={(value) => change('security_code', value.trim().toUpperCase())} />
    </div>
    {!valid ? <Alert type="warning" title="筛选参数格式不正确" /> : q.isPending ? <Loading /> : q.isError ? <ErrorBox error={q.error} /> : <>
      <Table<SuggestionListItem> size="small" rowKey="id" pagination={false} dataSource={rows} columns={[
        { title: '证券 / 详情', key: 'security', render: (_, s) => <Link to={`/suggestions/${s.id}`}>{s.name} <span className="mono">{s.security_code}</span></Link> },
        { title: '生成时间', key: 'at', render: (_, s) => fmtTime(s.created_at) },
        { title: '状态', key: 'status', render: (_, s) => <Tag color={SUGGESTION_STATUS[s.status].color}>{SUGGESTION_STATUS[s.status].text}</Tag> },
        { title: '各策略候选信号', key: 'actions', render: (_, s) => <div className="badges">{s.actions.map((a) => <ActionBadge key={a.strategy_key} action={a.action} strategyName={a.strategy_name} tLeg={a.t_leg} lifecycle={a.lifecycle} />)}</div> },
        { title: '共识', key: 'consensus', render: (_, s) => <ConsensusBadge status={s.consensus} /> },
        { title: '满足度', key: 'score', render: (_, s) => s.top_score ?? '—' },
        { title: '可执行性', key: 'executability', render: (_, s) => EXECUTABILITY[s.executability_status].text },
      ]} locale={{ emptyText: '当前筛选没有候选信号卡' }} />
      <CursorPager query={q} loaded={rows.length} />
    </>}
  </div></div>;
}
