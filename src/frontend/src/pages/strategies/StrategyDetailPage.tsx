import { Link, useParams, useSearchParams } from 'react-router';
import { Alert, Descriptions, Table, Tag } from 'antd';
import type { StrategyRule } from '../../api/strategyTypes';
import { useSiteStrategyTracking, useStrategyVersionDetail } from '../../api/strategyQueries';
import { ErrorBox, Loading } from '../../components/common';
import { HORIZON, LIFECYCLE } from '../../i18n/labels';

/**
 * 策略详情（F-05）：`/strategies/:id?version=:vid`（契约 §7.4，通知里 `strategy_version` 的跳转格式）。
 *
 * 只展示该**不可变版本**的配置与统计：参数定义、规则、作用周期、止损与时间止损、
 * 内部检验（方案 A：只有是否做过/方法类型/日期，**不含数值或通过与否**）、全站跟踪统计。
 * 前端不重算任何规则，也不把 `internal_check.done` 翻译成“可用”。
 */
export function StrategyDetailPage() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const versionId = sp.get('version') ?? undefined;
  const q = useStrategyVersionDetail(id, versionId);
  const track = useSiteStrategyTracking(id, versionId);

  if (!versionId) {
    return (
      <div className="page-scroll" data-testid="strategy-detail-page">
        <div className="page">
          <Alert
            type="info" showIcon data-testid="need-version"
            title="请从策略库选择具体版本"
            description={<>策略内容按版本不可变，详情需要版本 id。<Link to="/strategies">去策略库 ›</Link></>}
          />
        </div>
      </div>
    );
  }
  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const d = q.data;

  return (
    <div className="page-scroll" data-testid="strategy-detail-page">
      <div className="page">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <h2 className="page-title" style={{ marginBottom: 0 }}>{d.key}</h2>
          <span className="muted">v{d.version_no}</span>
          <Tag>{LIFECYCLE[d.lifecycle] ?? d.lifecycle}</Tag>
          <Tag color={d.risk_level === 'high' ? 'red' : undefined}>{d.risk_level === 'high' ? '高风险' : '常规风险'}</Tag>
          <Link to="/strategies" className="small">← 返回策略库</Link>
        </div>

        <Descriptions size="small" column={2} bordered style={{ margin: '10px 0' }} data-testid="version-meta">
          <Descriptions.Item label="作用周期">{d.horizons.map((h) => HORIZON[h] ?? h).join('、')}</Descriptions.Item>
          <Descriptions.Item label="类型">{d.kind}</Descriptions.Item>
          <Descriptions.Item label="参数指纹"><span className="mono small">{d.param_hash}</span></Descriptions.Item>
          <Descriptions.Item label="父版本">{d.parent_version_id ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="关联知识卡">{d.card_version_id ? <span className="mono small">{d.card_version_id}</span> : '未关联'}</Descriptions.Item>
          <Descriptions.Item label="内部检验">
            <span data-testid="internal-check">
              {d.internal_check.done
                ? `做过（${d.internal_check.method_types.join('、') || '未注明方法'}，${d.internal_check.checked_on ?? '未注明日期'}）`
                : '未做过'}
            </span>
          </Descriptions.Item>
        </Descriptions>

        <h3>参数定义</h3>
        <Table
          size="small" rowKey="name" pagination={false} data-testid="params-schema"
          dataSource={Object.entries(d.params_schema).map(([name, f]) => ({ name, ...f }))}
          locale={{ emptyText: '该版本没有可调参数' }}
          columns={[
            { title: '参数', key: 'n', render: (_, r: { name: string }) => <span className="mono">{r.name}</span> },
            { title: '说明', key: 'd', render: (_, r: { desc?: string | null }) => r.desc ?? '—' },
            { title: '类型', key: 't', width: 90, render: (_, r: { type: string }) => r.type },
            { title: '默认', key: 'v', width: 80, render: (_, r: { default?: unknown }) => String(r.default ?? '—') },
            {
              title: '取值范围', key: 'r', width: 160,
              render: (_, r: { min?: number | null; max?: number | null }) =>
                r.min == null && r.max == null ? '—' : `${r.min ?? '−∞'} ~ ${r.max ?? '+∞'}`,
            },
          ]}
        />

        <h3>规则</h3>
        <Table<StrategyRule>
          size="small" rowKey="id" pagination={false} dataSource={d.rules}
          columns={[
            { title: '编号', key: 'id', width: 80, render: (_, r) => <span className="mono">{r.id}</span> },
            { title: '维度', key: 'dim', width: 110, render: (_, r) => r.dimension },
            { title: '角色', key: 'role', width: 100, render: (_, r) => <Tag>{r.role}</Tag> },
            { title: '表达式', key: 'expr', render: (_, r) => <span className="mono">{r.expr}</span> },
          ]}
        />

        {d.stops ? (
          <>
            <h3>止损与退出</h3>
            <Descriptions size="small" column={3} bordered data-testid="stops">
              <Descriptions.Item label="止损">{d.stops.stop_loss ?? '未设置'}</Descriptions.Item>
              <Descriptions.Item label="止盈">{d.stops.take_profit ?? '未设置'}</Descriptions.Item>
              <Descriptions.Item label="时间止损">{d.stops.time_stop_days != null ? `${d.stops.time_stop_days} 个交易日` : '未设置'}</Descriptions.Item>
            </Descriptions>
          </>
        ) : null}

        <h3>跟踪统计<span className="muted small">（全站汇总，不含任何他人持仓或个股信息）</span></h3>
        {track.isPending ? <Loading text="统计加载中…" /> : null}
        {track.isError ? <ErrorBox error={track.error} prefix="统计加载失败" /> : null}
        {track.data ? (
          <Table
            size="small" rowKey="horizon_days" pagination={false} data-testid="tracking"
            dataSource={track.data.by_horizon}
            columns={[
              { title: '周期', key: 'h', width: 80, render: (_, r) => `${r.horizon_days} 日` },
              {
                title: '胜率', key: 'w',
                render: (_, r) => (r.win_rate.value === null ? <span className="muted">样本不足</span> : `${(Number(r.win_rate.value) * 100).toFixed(1)}%（n=${r.win_rate.n}）`),
              },
              {
                title: '平均超额', key: 'e',
                render: (_, r) => (r.avg_excess_pct.value === null ? <span className="muted">样本不足</span> : `${r.avg_excess_pct.value}%（n=${r.avg_excess_pct.n}）`),
              },
              { title: '最大连亏', key: 'l', width: 100, render: (_, r) => r.max_loss_streak },
            ]}
          />
        ) : null}
        {track.data?.gaps?.length ? (
          <p className="muted small" data-testid="tracking-gaps">{track.data.gaps.map((g) => g.message).join('；')}</p>
        ) : null}
      </div>
    </div>
  );
}
