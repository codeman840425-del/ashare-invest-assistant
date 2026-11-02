import { useState } from 'react';
import { Button, Checkbox, Input, Select, Space, Table, Tag } from 'antd';
import { Link, useSearchParams } from 'react-router';
import { ENUMS, type ResearchCandidateOrigin, type ResearchCandidateStatus } from '../../api/enums';
import { CANDIDATE_STATUSES as STATUSES, parseCandidateStatus, useCandidates, type CandidateFilter } from '../../api/candidateQueries';
import type { ResearchCandidateSummary } from '../../api/candidateTypes';
import { CursorPager } from '../../components/CursorPager';
import { ErrorBox } from '../../components/common';
import { CardDisclaimer } from '../../components/RiskDisclosure';
import { CreateCandidateModal } from '../../features/research/CreateCandidateModal';
import { CANDIDATE_DECISION, RESEARCH_ORIGIN, RESEARCH_STATUS } from '../../i18n/candidateLabels';
import { fmtTime } from '../../lib/format';

const ORIGINS = ENUMS.research_candidate_origin as readonly ResearchCandidateOrigin[];


/** T-F23 研究候选列表（契约 v0.2.9 §7.7A GET /candidates）：URL 驱动筛选，默认不含已放弃 */
export function CandidatesPage() {
  const [sp, setSp] = useSearchParams();
  const [creating, setCreating] = useState(false);
  const status = parseCandidateStatus(sp.get('status'));
  const originRaw = sp.get('origin') ?? '';
  const f: CandidateFilter = {
    status,
    origin: (ORIGINS as readonly string[]).includes(originRaw) ? (originRaw as ResearchCandidateOrigin) : '',
    security_code: (sp.get('security_code') ?? '').trim(),
    suggestion_id: (sp.get('suggestion_id') ?? '').trim(),
  };
  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v);
    else next.delete(k);
    setSp(next, { replace: true });
  };
  const list = useCandidates(f);
  const rows = list.items;
  return (
    <div className="page-scroll page" data-testid="candidates-page">
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <h2 className="page-title">研究候选</h2>
        <Button type="primary" size="small" onClick={() => setCreating(true)} data-testid="cand-new-btn">新建研究候选</Button>
      </Space>
      <div className="muted small" style={{ marginBottom: 8 }}>
        研究候选是你自己的研究记录：研究要点与成立条件由你填写；满足的规则、反证与适配提示由系统在每次新建版本时按当时数据生成，之后不刷新。
        研究候选不能直接生成计划草案；每只证券同时只保留一个研究中或观察中的候选，已放弃后可以重新新建。
      </div>
      <Space wrap style={{ marginBottom: 12 }}>
        <Checkbox checked={status === 'all'} onChange={(e) => setParam('status', e.target.checked ? 'all' : '')} data-testid="filter-all">全部状态（含已放弃）</Checkbox>
        <Select<ResearchCandidateStatus[]>
          mode="multiple"
          allowClear
          disabled={status === 'all'}
          style={{ minWidth: 260 }}
          placeholder="默认：研究中、观察中、已计划"
          value={status === 'all' ? [] : status}
          onChange={(v) => setParam('status', v.join(','))}
          options={STATUSES.map((s) => ({ value: s, label: RESEARCH_STATUS[s].text }))}
          data-testid="filter-status"
        />
        <Select<ResearchCandidateOrigin | ''>
          style={{ width: 150 }}
          value={f.origin ?? ''}
          onChange={(v) => setParam('origin', v)}
          options={[{ value: '', label: '全部来源' }, ...ORIGINS.map((o) => ({ value: o, label: RESEARCH_ORIGIN[o] }))]}
          data-testid="filter-origin"
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
        {f.suggestion_id ? <Tag closable onClose={() => setParam('suggestion_id', '')} data-testid="filter-suggestion">来源候选信号卡 {f.suggestion_id.slice(-6)}</Tag> : null}
      </Space>
      {list.isError ? <ErrorBox error={list.error} /> : null}
      <Table<ResearchCandidateSummary>
        size="small"
        rowKey="id"
        loading={list.isPending}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: '没有符合条件的研究候选' }}
        data-testid="candidates-table"
        columns={[
          {
            title: '证券', key: 'sec', width: 180,
            render: (_v, r) => <Link to={`/candidates/${r.id}`} data-testid={`cand-link-${r.id}`}>{r.name} <span className="mono muted">{r.security_code}</span></Link>,
          },
          {
            title: '状态', dataIndex: 'status', width: 90,
            render: (s: ResearchCandidateStatus) => <Tag color={RESEARCH_STATUS[s].color} data-testid="cand-status">{RESEARCH_STATUS[s].text}</Tag>,
          },
          { title: '来源', dataIndex: 'origin', width: 110, render: (o: ResearchCandidateOrigin) => RESEARCH_ORIGIN[o] },
          { title: '当前版本', dataIndex: 'current_version_no', width: 90, align: 'right', render: (n: number) => <span className="mono">第 {n} 版</span> },
          { title: '当前版本决定', dataIndex: 'decision', width: 120, render: (d: ResearchCandidateSummary['decision']) => (d ? CANDIDATE_DECISION[d] : <span className="muted">—</span>) },
          { title: '最近版本时间', dataIndex: 'last_version_at', width: 140, render: (v: string) => <span className="mono small">{fmtTime(v).slice(5)}</span> },
          { title: '创建时间', dataIndex: 'created_at', width: 140, render: (v: string) => <span className="mono small">{fmtTime(v).slice(5)}</span> },
        ]}
      />
      <CursorPager query={list} loaded={rows.length} testId="candidates-pager" />
      <div className="muted small">时间均为北京时间。</div>
      <CardDisclaimer />
      {creating ? <CreateCandidateModal open={creating} onClose={() => setCreating(false)} origin="manual" /> : null}
    </div>
  );
}
