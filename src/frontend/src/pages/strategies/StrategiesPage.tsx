import { useState } from 'react';
import { Link } from 'react-router';
import { Alert, Table, Tag } from 'antd';
import type { Lifecycle } from '../../api/enums';
import { useAccounts } from '../../api/accountQueries';
import { useCreateStrategyInstance, useInstanceTransition, useStrategyInstances, useStrategyTemplates } from '../../api/strategyQueries';
import type { StrategyInstance, StrategyTemplate } from '../../api/strategyTypes';
import { ErrorBox, Loading } from '../../components/common';
import { StrategyEnableSwitch } from '../../components/StrategyEnableSwitch';
import { isHighRisk } from '../../lib/strategyRisk';
import { HORIZON, LIFECYCLE } from '../../i18n/labels';

/**
 * 策略库（T-F22 最小版）：模板列表 + 启用开关。完整策略库（版本、跟踪统计、派生）在后续任务实现。
 * 启用 = 用模板当前版本在主账户上创建实例（POST /strategy-instances）；停用 = 暂停实例；再启用已暂停的实例 = 恢复。
 * 高风险模板（risk_level: high）开关旁固定展示风险说明，启用不弹窗、不发任何确认字段（契约 v0.2.6 T006e）。
 */
/** 契约 STRATEGY_VERSION_NOT_RUNNABLE：只有 published / observing 可以启用 */
const RUNNABLE: readonly Lifecycle[] = ['published', 'observing'];

export function StrategiesPage() {
  const tq = useStrategyTemplates();
  const iq = useStrategyInstances();
  const accounts = useAccounts();
  const create = useCreateStrategyInstance();
  const transition = useInstanceTransition();
  const [busy, setBusy] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  if (tq.isPending || iq.isPending) return <Loading />;
  if (tq.isError) return <ErrorBox error={tq.error} />;
  if (iq.isError) return <ErrorBox error={iq.error} />;
  const accountId = accounts.data?.items[0]?.id ?? null;
  const runnable = (t: StrategyTemplate) => RUNNABLE.includes(t.current_version.lifecycle) && t.horizons.length > 0;
  const instOf = (t: StrategyTemplate): StrategyInstance | undefined =>
    iq.data.items.find((x) => x.strategy_id === t.id && x.scope === 'account' && x.account_id === accountId && x.status !== 'archived');

  const toggle = (t: StrategyTemplate, next: boolean) => {
    setWarnings([]);
    setBusy(t.id);
    const done = { onSettled: () => setBusy(null) };
    const inst = instOf(t);
    if (!next) {
      if (inst) transition.mutate({ id: inst.id, to: 'pause' }, done);
      else setBusy(null);
      return;
    }
    if (inst?.status === 'paused') { transition.mutate({ id: inst.id, to: 'resume' }, done); return; }
    // 评审 m6：已有待确认（proposed）实例时走 confirm，不重复创建
    if (inst?.status === 'proposed') { transition.mutate({ id: inst.id, to: 'confirm' }, done); return; }
    const horizon = t.horizons[0];
    if (!horizon || !accountId) { setBusy(null); return; }
    create.mutate(
      {
        strategy_version_id: t.current_version.id, scope: 'account', account_id: accountId, security_code: null,
        horizon, param_overrides: null, budget_amount: null,
      },
      { ...done, onSuccess: (r) => setWarnings(r.warnings) },
    );
  };
  const mutErr = create.error ?? transition.error;

  return (
    <div className="page-scroll" data-testid="strategies-page">
      <div className="page">
        <h2 className="page-title">策略库</h2>
        <p className="muted">每个模板在主账户上启用后，每日按规则生成候选信号；模拟中的版本仅作模拟跟踪。</p>
        {warnings.length ? <Alert type="warning" showIcon title={warnings.join('；')} style={{ margin: '8px 0' }} data-testid="instance-warnings" /> : null}
        {mutErr ? <ErrorBox error={mutErr} prefix="操作失败" /> : null}
        {/* 评审 m7：账户加载失败或还没有账户时说明开关为何不可用 */}
        {accounts.isError ? <ErrorBox error={accounts.error} prefix="账户加载失败，暂时无法启用策略" /> : null}
        {accounts.isSuccess && !accountId ? (
          <Alert type="info" showIcon data-testid="no-account" style={{ margin: '8px 0' }}
            title={<>请先创建券商账户，再启用策略。<Link to="/portfolio">去持仓页创建账户 ›</Link></>} />
        ) : null}
        {tq.data.truncated || iq.data.truncated ? (
          <Alert type="warning" showIcon data-testid="list-truncated" style={{ margin: '8px 0' }} title="列表较长，只显示了前一部分；请用筛选缩小范围。" />
        ) : null}
        <Table<StrategyTemplate>
          size="small" rowKey="id" pagination={false} dataSource={tq.data.items}
          columns={[
            {
              title: '模板', key: 'name',
              render: (_, t) => (
                <span>
                  {t.name} <span className="mono muted">{t.key}</span>
                  {isHighRisk(t.risk_level) ? <Tag color="red" style={{ marginLeft: 6 }}>高风险</Tag> : null}
                </span>
              ),
            },
            { title: '健康度', key: 'health', render: (_, t) => t.health ? `${t.health.state} · n=${t.health.n} · 权重 ${t.health.weight}` : '暂无健康度' },
            { title: '周期', key: 'h', width: 120, render: (_, t) => t.horizons.map((h) => HORIZON[h]).join('、') },
            {
              title: '版本', key: 'v', width: 160,
              render: (_, t) => (
                <span>
                  v{t.current_version.version_no} · {t.current_version.lifecycle === 'simulating' ? '模拟中' : LIFECYCLE[t.current_version.lifecycle]}
                  {!runnable(t) ? <span className="muted small" data-testid={`not-runnable-${t.key}`}>（{t.horizons.length ? '该版本暂不可启用' : '未声明适用周期'}）</span> : null}
                </span>
              ),
            },
            {
              title: '启用', key: 'on',
              render: (_, t) => (
                <StrategyEnableSwitch
                  name={t.name} riskLevel={t.risk_level} checked={instOf(t)?.status === 'active'}
                  loading={busy === t.id} disabled={!accountId || (!runnable(t) && !instOf(t)) || (busy !== null && busy !== t.id)}
                  onChange={(v) => toggle(t, v)} testId={`enable-${t.key}`}
                />
              ),
            },
          ]}
        />
      </div>
    </div>
  );
}
