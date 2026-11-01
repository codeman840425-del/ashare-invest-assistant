import { useState } from 'react';
import { Alert, Table, Tag } from 'antd';
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
    create.mutate(
      {
        strategy_version_id: t.current_version.id, scope: 'account', account_id: accountId, security_code: null,
        horizon: t.horizons[0], param_overrides: null, budget_amount: null,
      },
      { ...done, onSuccess: (r) => setWarnings(r.warnings) },
    );
  };
  const mutErr = create.error ?? transition.error;

  return (
    <div className="page-scroll" data-testid="strategies-page">
      <div className="page">
        <h2 className="page-title">策略库</h2>
        <p className="muted">每个模板在主账户上启用后，每日按规则生成规则信号；名称与数据均为示例。</p>
        {warnings.length ? <Alert type="warning" showIcon title={warnings.join('；')} style={{ margin: '8px 0' }} data-testid="instance-warnings" /> : null}
        {mutErr ? <ErrorBox error={mutErr} prefix="操作失败" /> : null}
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
            { title: '周期', key: 'h', width: 120, render: (_, t) => t.horizons.map((h) => HORIZON[h]).join('、') },
            { title: '版本', key: 'v', width: 120, render: (_, t) => `v${t.current_version.version_no} · ${LIFECYCLE[t.current_version.lifecycle]}` },
            {
              title: '启用', key: 'on',
              render: (_, t) => (
                <StrategyEnableSwitch
                  name={t.name} riskLevel={t.risk_level} checked={instOf(t)?.status === 'active'}
                  loading={busy === t.id} disabled={!accountId || (busy !== null && busy !== t.id)}
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
