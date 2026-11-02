import { Alert as AntAlert, Button, Space, Tag } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { Link, useNavigate, useParams } from 'react-router';
import { ApiError } from '../../api/client';
import { useAlert, usePatchAlert } from '../../api/planAlertQueries';
import { ALERT_NEXT } from '../../api/planAlertTypes';
import { ErrorBox, Loading } from '../../components/common';
import { ALERT_ORIGIN, ALERT_STATUS, SEVERITY, SEVERITY_TEXT } from '../../i18n/labels';
import { ALERT_ACTION_TEXT, ALERT_STATUS_COLOR } from '../../i18n/planAlertLabels';
import { fmtTime } from '../../lib/format';

/**
 * T-F23 裁定跟进：提醒详情（契约 v0.2.9 §7.7B）。GET 不改状态；状态按钮只给当前状态允许的目标（问题 82），
 * “标为已读”也是显式操作，不在打开时自动发送。
 */
export function AlertDetailPage() {
  const { id = '' } = useParams();
  const q = useAlert(id);
  const patch = usePatchAlert(id);
  const navigate = useNavigate();
  if (q.isPending) return <div className="page-scroll page" data-testid="alert-detail"><Loading /></div>;
  if (q.isError || !q.data) {
    const nf = q.error instanceof ApiError && q.error.status === 404;
    return (
      <div className="page-scroll page" data-testid="alert-detail">
        {nf ? <div data-testid="alert-not-found">提醒不存在或不属于你。<Link to="/alerts">返回提醒中心</Link></div> : <ErrorBox error={q.error} />}
      </div>
    );
  }
  const a = q.data;
  const next = ALERT_NEXT[a.status];
  return (
    <div className="page-scroll page" data-testid="alert-detail">
      <div className="detail-head">
        <Button size="small" icon={<ArrowLeftOutlined />} onClick={() => navigate('/alerts')}>提醒中心</Button>
        <Tag color={SEVERITY[a.severity]}>{SEVERITY_TEXT[a.severity]}</Tag>
        <span className="q-name">{a.title}</span>
        <Tag color={ALERT_STATUS_COLOR[a.status]} data-testid="alert-detail-status">{ALERT_STATUS[a.status]}</Tag>
      </div>
      <div className="muted small" style={{ margin: '6px 0' }}>
        来源 {ALERT_ORIGIN[a.origin]}
        {a.security_code ? <> · <Link to={`/stocks/${a.security_code}`}>{a.name} {a.security_code}</Link></> : ' · 账户级'}
        {' '}· 触发 {fmtTime(a.triggered_at)}{a.data_as_of ? ` · 数据截至 ${fmtTime(a.data_as_of)}` : ''}{a.handled_at ? ` · 最近状态变更 ${fmtTime(a.handled_at)}` : ''}（北京时间）
      </div>
      {patch.isError ? (
        <AntAlert type="error" showIcon data-testid="alert-patch-error" style={{ marginBottom: 8 }}
          title={patch.error instanceof ApiError && patch.error.code === 'INVALID_STATE_TRANSITION' ? '提醒状态已变化，不能这样标记；已重新载入。' : (patch.error as Error).message} />
      ) : null}
      <Space style={{ marginBottom: 8 }} data-testid="alert-actions">
        {next.length ? next.map((s) => (
          <Button key={s} size="small" loading={patch.isPending && patch.variables === s} onClick={() => patch.mutate(s, { onError: () => void q.refetch() })} data-testid={`alert-to-${s}`}>
            {ALERT_ACTION_TEXT[s]}
          </Button>
        )) : <span className="muted small" data-testid="alert-terminal">该提醒已{ALERT_STATUS[a.status]}，状态不能再变更。</span>}
      </Space>
      {a.affected_plans.length ? (
        <section className="panel" style={{ marginBottom: 8 }} data-testid="alert-plans">
          <div className="panel-head"><span className="panel-title">相关计划</span></div>
          {a.affected_plans.map((p) => (
            <div key={`${p.plan_id}-${p.plan_version_no}`} className="small"><Link to={`/plans/${p.plan_id}`}>计划 {p.plan_id.slice(-6)}（第 {p.plan_version_no} 版）</Link></div>
          ))}
        </section>
      ) : null}
      {a.checklist.length ? (
        <section className="panel" style={{ marginBottom: 8 }} data-testid="alert-checklist">
          <div className="panel-head"><span className="panel-title">核对清单</span></div>
          <ul>{a.checklist.map((c, i) => <li key={`${i}-${c}`} className="small">{c}</li>)}</ul>
        </section>
      ) : null}
      <section className="panel" data-testid="alert-evidence">
        <div className="panel-head"><span className="panel-title">事实与来源</span></div>
        {a.evidence.map((e) => (
          <div key={e.id} className="small">{e.key}：{String(e.value)}{e.unit ? ` ${e.unit}` : ''} · {e.provider} · 截至 {fmtTime(e.data_as_of ?? e.fetched_at)}</div>
        ))}
      </section>
      <div className="muted small" style={{ marginTop: 8 }}>示例数据。标为“已处理”只记录你的处理状态，不会下单或修改计划。</div>
    </div>
  );
}
