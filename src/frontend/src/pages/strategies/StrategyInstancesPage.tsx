import { useState } from 'react';
import { Segmented, Table, Tag } from 'antd';
import type { InstanceStatus } from '../../api/enums';
import { useInstanceTransition, useStrategyInstances } from '../../api/strategyQueries';
import type { StrategyInstance } from '../../api/strategyTypes';
import { ErrorBox, Loading } from '../../components/common';
import { StrategyEnableSwitch } from '../../components/StrategyEnableSwitch';
import { isHighRisk } from '../../lib/strategyRisk';
import { HORIZON, INSTANCE_ORIGIN, LIFECYCLE } from '../../i18n/labels';

/**
 * 我的策略实例（F-03，编排者 2026-11-11 裁定独立成页）。
 *
 * 与「策略库」（/strategies，按模板 × 启用开关的视角）互补而非重复：本页按**实例**视角列出
 * 每个实例的运行状态、作用范围、周期与生命周期，并提供暂停/恢复/确认三种操作。
 * 契约 §7.5 GET /strategy-instances（status 可多值，默认 proposed,active,paused）、§6.0A 状态机。
 * 不重算任何规则：可用操作与状态一律照后端返回，前端只做展示与转发。
 */
const STATUS_TEXT: Record<InstanceStatus, string> = {
  proposed: '待确认',
  active: '运行中',
  paused: '已暂停',
  archived: '已归档',
};
const STATUS_COLOR: Record<InstanceStatus, string | undefined> = {
  proposed: 'gold',
  active: 'green',
  paused: 'default',
  archived: 'default',
};
const SCOPE_TEXT: Record<StrategyInstance['scope'], string> = {
  account: '账户',
  security: '单只证券',
  watch_group: '自选分组',
};

export function StrategyInstancesPage() {
  const iq = useStrategyInstances();
  const transition = useInstanceTransition();
  const [busy, setBusy] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);

  if (iq.isPending) return <Loading />;
  if (iq.isError) return <ErrorBox error={iq.error} />;

  const all = iq.data.items;
  const shown = includeArchived ? all : all.filter((x) => x.status !== 'archived');
  const archivedCount = all.filter((x) => x.status === 'archived').length;

  const act = (inst: StrategyInstance, to: 'pause' | 'resume' | 'confirm') => {
    setBusy(inst.id);
    transition.mutate({ id: inst.id, to }, { onSettled: () => setBusy(null) });
  };

  const scopeText = (x: StrategyInstance) =>
    x.scope === 'security' ? `${SCOPE_TEXT.security}${x.security_code ? ` · ${x.security_code}` : ''}` : SCOPE_TEXT[x.scope];

  return (
    <div className="page-scroll" data-testid="strategy-instances-page">
      <div className="page">
        <h2 className="page-title">我的策略实例</h2>
        <p className="muted">每个实例按所属模板与周期每日生成候选信号；暂停后不再产出，恢复即继续。</p>
        {transition.error ? <ErrorBox error={transition.error} prefix="操作失败" /> : null}
        {iq.data.truncated ? (
          <div className="muted small" data-testid="instances-truncated" style={{ margin: '8px 0' }}>
            实例较多，只显示了前一部分；请到「策略库」按模板缩小范围。
          </div>
        ) : null}
        {archivedCount > 0 ? (
          <div style={{ margin: '8px 0' }} data-testid="instances-status-filter">
            <Segmented
              size="small"
              value={includeArchived ? 'all' : 'live'}
              onChange={(v) => setIncludeArchived(v === 'all')}
              options={[
                { label: `进行中（${all.length - archivedCount}）`, value: 'live' },
                { label: `含已归档（${all.length}）`, value: 'all' },
              ]}
            />
          </div>
        ) : null}
        <Table<StrategyInstance>
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={shown}
          locale={{ emptyText: '还没有策略实例。到「策略库」启用一个模板即可创建。' }}
          expandable={{
            expandedRowRender: (x) => (
              <div className="muted small" data-testid={`inst-detail-${x.id}`}>
                {x.derived_strategy_version_id ? <div>运行派生版本（参数已改动）</div> : null}
                <div>来源：{INSTANCE_ORIGIN[x.origin]}</div>
                <div>预算：{x.budget_amount ?? '未设置'}　自动降权：{x.auto_downweight ? '开' : '关'}</div>
                {x.paused_by ? <div>暂停方：{x.paused_by === 'user' ? '本人' : '系统'}{x.pause_reason_code ? `（${x.pause_reason_code}）` : ''}</div> : null}
                {x.paused_until ? <div>暂停至：{x.paused_until}</div> : null}
              </div>
            ),
          }}
          columns={[
            {
              title: '策略',
              key: 'name',
              render: (_, x) => (
                <span>
                  {x.strategy_name} <span className="mono muted">{x.strategy_key}</span>
                  {isHighRisk(x.risk_level) ? <Tag color="red" style={{ marginLeft: 6 }}>高风险</Tag> : null}
                </span>
              ),
            },
            { title: '版本', key: 'v', width: 130, render: (_, x) => <span>v{x.version_no} · {LIFECYCLE[x.lifecycle]}</span> },
            { title: '周期', key: 'h', width: 90, render: (_, x) => HORIZON[x.horizon] },
            { title: '范围', key: 'scope', width: 150, render: (_, x) => scopeText(x) },
            {
              title: '状态',
              key: 'status',
              width: 110,
              render: (_, x) => (
                <Tag color={STATUS_COLOR[x.status]} data-testid={`inst-status-${x.id}`}>{STATUS_TEXT[x.status]}</Tag>
              ),
            },
            {
              title: '启用',
              key: 'on',
              width: 260,
              render: (_, x) => (
                <StrategyEnableSwitch
                  name={x.name ?? x.strategy_name}
                  riskLevel={x.risk_level}
                  checked={x.status === 'active'}
                  loading={busy === x.id}
                  disabled={x.status === 'archived' || (busy !== null && busy !== x.id)}
                  onChange={(v) => {
                    if (v) act(x, x.status === 'proposed' ? 'confirm' : 'resume');
                    else act(x, 'pause');
                  }}
                  testId={`inst-enable-${x.id}`}
                />
              ),
            },
          ]}
        />
      </div>
    </div>
  );
}
