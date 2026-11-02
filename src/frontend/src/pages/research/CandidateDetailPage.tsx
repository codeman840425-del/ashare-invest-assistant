import { useState } from 'react';
import { Alert, Button, Drawer, Form, Input, Radio, Space, Tag } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { Link, useNavigate, useParams } from 'react-router';
import { ApiError } from '../../api/client';
import { useCandidate, useCandidateVersion, useCandidateVersions, useCreateCandidateVersion } from '../../api/candidateQueries';
import type { ResearchCandidate } from '../../api/candidateTypes';
import type { CandidateDecision } from '../../api/enums';
import { CursorPager } from '../../components/CursorPager';
import { ErrorBox, Loading } from '../../components/common';
import { CardDisclaimer } from '../../components/RiskDisclosure';
import { VersionView } from '../../features/research/VersionView';
import { CandidateWriteError, ConditionsEditor } from '../../features/research/candidateForm';
import { applyCandidateErrors, fromConditions, toConditionInputs, type ConditionValues } from '../../features/research/candidateFormUtils';
import { CANDIDATE_DECISION, RESEARCH_ORIGIN, RESEARCH_STATUS } from '../../i18n/candidateLabels';
import { fmtTime } from '../../lib/format';

const TERMINAL = ['dropped', 'planned'] as const;
const isTerminal = (s: ResearchCandidate['status']) => (TERMINAL as readonly string[]).includes(s);

/** T-F23 研究候选详情（契约 v0.2.9 §7.7A）：当前版本、版本历史、新建版本 / 做决定 */
export function CandidateDetailPage() {
  const { id = '' } = useParams();
  const q = useCandidate(id);
  const navigate = useNavigate();
  if (q.isPending) return <div className="page-scroll page" data-testid="candidate-detail"><Loading /></div>;
  if (q.isError || !q.data) {
    const nf = q.error instanceof ApiError && q.error.status === 404;
    return (
      <div className="page-scroll page" data-testid="candidate-detail">
        {nf ? <div data-testid="cand-not-found">研究候选不存在或不属于你。<Link to="/candidates">返回列表</Link></div> : <ErrorBox error={q.error} />}
      </div>
    );
  }
  const c = q.data;
  const terminal = isTerminal(c.status);
  return (
    <div className="page-scroll page" data-testid="candidate-detail">
      <div className="detail-head">
        <Button size="small" icon={<ArrowLeftOutlined />} onClick={() => navigate('/candidates')}>研究候选</Button>
        <Link to={`/stocks/${c.security_code}`} className="q-name">{c.name}</Link>
        <span className="mono muted">{c.security_code}</span>
        <Tag color={RESEARCH_STATUS[c.status].color} data-testid="cand-detail-status">{RESEARCH_STATUS[c.status].text}</Tag>
        <span className="muted small">
          来源 {RESEARCH_ORIGIN[c.origin]}
          {c.suggestion_id ? <> · <Link to={`/suggestions/${c.suggestion_id}`} data-testid="cand-source-suggestion">查看来源候选信号卡</Link></> : null}
          {' '}· 共 {c.version_count} 版 · 创建 {fmtTime(c.created_at)}（北京时间）
        </span>
      </div>
      {c.status === 'planned' ? (
        <Alert type="success" showIcon style={{ margin: '8px 0' }} data-testid="cand-planned"
          title={<>已据此创建操作计划，研究候选已结束。{c.plan_ids.length ? <>关联计划：{c.plan_ids.map((p) => <Link key={p} to={`/plans/${p}`} className="mono" style={{ marginRight: 6 }}>{p.slice(-8)}</Link>)}</> : null}</>} />
      ) : null}
      {c.status === 'dropped' ? (
        <Alert type="info" showIcon style={{ margin: '8px 0' }} data-testid="cand-dropped"
          title="已放弃：研究候选不能再修改或恢复，版本历史保留可回看；要重新研究这只证券请新建研究候选。" />
      ) : null}
      <div className="cand-grid">
        <section className="panel cand-panel" data-testid="cand-current">
          <div className="panel-head"><span className="panel-title">当前版本</span></div>
          <VersionView v={c.current_version} testId="cand-current-version" />
          <div className="muted small">以上内容是第 {c.current_version.version_no} 版创建时的快照，不随行情刷新；要看最新情况请新建版本。</div>
        </section>
        <div>
          {terminal ? null : <NewVersionPanel key={`${c.id}-${c.current_version.version_no}`} c={c} onReload={() => q.refetch()} />}
          <VersionHistory id={c.id} />
        </div>
      </div>
      <CardDisclaimer />
    </div>
  );
}

interface VersionValues { thesis?: string; conditions_to_hold?: ConditionValues[]; decision: CandidateDecision | 'none'; decision_reason?: string }

/** 新建版本：整体替换（未改的内容也要带上），base_version_no 取打开表单时的当前版本号 */
function NewVersionPanel({ c, onReload }: { c: ResearchCandidate; onReload: () => void }) {
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<VersionValues>();
  const save = useCreateCandidateVersion(c.id);
  const [topErrors, setTopErrors] = useState<string[]>([]);
  const decision = Form.useWatch('decision', form);
  const base = c.current_version;
  const submit = (v: VersionValues) => {
    setTopErrors([]);
    const d = v.decision === 'none' ? null : v.decision;
    save.mutate(
      {
        base_version_no: base.version_no,
        thesis: v.thesis?.trim() || null,
        conditions_to_hold: toConditionInputs(v.conditions_to_hold),
        decision: d,
        decision_reason: d ? (v.decision_reason ?? '').trim() : null,
      },
      {
        onSuccess: () => setOpen(false),
        onError: (e) => setTopErrors(applyCandidateErrors(form, e, ['thesis', 'decision', 'decision_reason'])),
      },
    );
  };
  if (!open) {
    return (
      <section className="panel cand-panel" data-testid="cand-actions">
        <div className="panel-head"><span className="panel-title">修改与决定</span></div>
        <Space wrap>
          <Button size="small" type="primary" onClick={() => setOpen(true)} data-testid="cand-new-version-btn">新建版本 / 做决定</Button>
        </Space>
        <div className="muted small" style={{ marginTop: 6 }}>每次修改或做决定都会新建一个版本，旧版本保留不变；系统内容按新建时的数据重新生成。</div>
      </section>
    );
  }
  return (
    <section className="panel cand-panel" data-testid="cand-version-form">
      <div className="panel-head"><span className="panel-title">新建第 {base.version_no + 1} 版（基于第 {base.version_no} 版）</span></div>
      <Form<VersionValues>
        form={form}
        layout="vertical"
        onFinish={submit}
        initialValues={{ thesis: base.thesis ?? '', conditions_to_hold: fromConditions(base.conditions_to_hold), decision: 'none', decision_reason: '' }}
      >
        <Form.Item name="thesis" label="研究要点" rules={[{ max: 2000, message: '至多 2000 字' }]}>
          <Input.TextArea rows={3} maxLength={2000} showCount data-testid="ver-thesis" />
        </Form.Item>
        <ConditionsEditor form={form} />
        <Form.Item name="decision" label="决定" style={{ marginTop: 12 }}>
          <Radio.Group data-testid="ver-decision">
            <Radio value="none">只修改内容，不做决定</Radio>
            {(['continue', 'watch', 'drop'] as const).map((d) => <Radio key={d} value={d} data-testid={`ver-decision-${d}`}>{CANDIDATE_DECISION[d]}</Radio>)}
          </Radio.Group>
        </Form.Item>
        {decision && decision !== 'none' ? (
          <Form.Item
            name="decision_reason"
            label="理由（必填，1–200 字）"
            rules={[
              { required: true, whitespace: true, message: '做决定时须填写理由' },
              { validator: async (_r, v: string | undefined) => { if ((v ?? '').trim().length > 200) throw new Error('至多 200 字'); } },
            ]}
          >
            <Input.TextArea rows={2} maxLength={220} showCount data-testid="ver-reason" />
          </Form.Item>
        ) : null}
        {decision === 'drop' ? <div className="warn small" data-testid="ver-drop-warn">放弃后研究候选结束，不能再修改或恢复（可以重新新建）。</div> : null}
        {topErrors.map((t) => <div key={t} className="error-text small" role="alert" data-testid="ver-top-error">{t}</div>)}
        {save.isError ? <CandidateWriteError error={save.error} onReload={onReload} /> : null}
        <Space style={{ marginTop: 8 }}>
          <Button type="primary" size="small" htmlType="submit" loading={save.isPending} data-testid="ver-submit">保存为新版本</Button>
          <Button size="small" onClick={() => { save.reset(); setOpen(false); }}>取消</Button>
        </Space>
      </Form>
    </section>
  );
}

function VersionHistory({ id }: { id: string }) {
  const list = useCandidateVersions(id);
  const [viewing, setViewing] = useState<number | null>(null);
  const one = useCandidateVersion(id, viewing);
  return (
    <section className="panel cand-panel" data-testid="cand-history">
      <div className="panel-head"><span className="panel-title">版本历史</span></div>
      {list.isError ? <ErrorBox error={list.error} /> : null}
      {list.items.map((v) => (
        <div key={v.id} className="tw small" data-testid={`cand-history-${v.version_no}`}>
          <span className="mono">第 {v.version_no} 版</span>
          <span className="muted"> · {fmtTime(v.created_at)}</span>
          {v.decision ? <Tag style={{ marginLeft: 6 }}>{CANDIDATE_DECISION[v.decision]}</Tag> : null}
          <Button size="small" type="link" onClick={() => setViewing(v.version_no)} data-testid={`cand-view-${v.version_no}`}>查看</Button>
        </div>
      ))}
      <CursorPager query={list} loaded={list.items.length} testId="cand-history-pager" unit="版" />
      <Drawer open={viewing !== null} onClose={() => setViewing(null)} size={620} title={viewing !== null ? `第 ${viewing} 版（创建时的快照）` : ''}>
        {one.isPending ? <Loading /> : one.isError ? <ErrorBox error={one.error} /> : one.data ? <VersionView v={one.data} testId="cand-view-version" /> : null}
      </Drawer>
    </section>
  );
}
