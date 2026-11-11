import { useState } from 'react';
import { Link, useParams } from 'react-router';
import { Alert, Descriptions, Select, Table, Tag } from 'antd';
import { useStrategyCard, useStrategyCardVersion, useStrategyCardVersions } from '../../api/cardQueries';
import type { CardRuleLine, StrategyCardDetail } from '../../api/cardTypes';
import { ErrorBox, Loading } from '../../components/common';
import { HORIZON } from '../../i18n/labels';
import { CARD_CATEGORY_TEXT, CARD_COMPLETENESS_TEXT, CARD_SOURCE_TEXT } from './StrategyCardsPage';

/**
 * 策略知识卡详情（F-04）：卡片当前版本的内容 + 历史版本切换。
 *
 * 只做展示：`gates_missing` 由后端给出（形如 `G1:stop_loss_to_quantify`），前端不判断门禁是否通过，
 * 也不把缺口翻译成“可以启用”。`validation_summary` 是研究员文档里的**外部**验证信息，产品不做回测。
 * 契约 §7.4 GET /strategy-cards/{id}、/{id}/versions、/{id}/versions/{no}。
 */
const RULE_SECTIONS: { key: keyof Pick<StrategyCardDetail, 'entry' | 'counter_evidence' | 'invalidation' | 'exit'>; title: string; hint: string }[] = [
  { key: 'entry', title: '入场条件', hint: '' },
  { key: 'counter_evidence', title: '反向证据', hint: '满足时降低该卡的权重' },
  { key: 'invalidation', title: '失效条件', hint: '满足即认为假设不成立' },
  { key: 'exit', title: '离场条件', hint: '含至少一条止损类规则' },
];

function RuleTable({ section, rows }: { section: string; rows: CardRuleLine[] }) {
  return (
    <Table<CardRuleLine>
      size="small" rowKey={(r) => `${section}-${r.text}`} pagination={false} dataSource={rows}
      locale={{ emptyText: '无' }}
      columns={[
        { title: '说明', key: 'text', render: (_, r) => r.text },
        {
          title: '规则表达式', key: 'expr', width: 300,
          render: (_, r) => (r.expr ? <span className="mono">{r.expr}</span> : <span className="muted">待量化</span>),
        },
        {
          title: '状态', key: 'st', width: 90,
          render: (_, r) => (r.status === 'quantified' ? <Tag color="green">已量化</Tag> : <Tag>待量化</Tag>),
        },
      ]}
    />
  );
}

export function StrategyCardDetailPage() {
  const { id = '' } = useParams();
  const [versionNo, setVersionNo] = useState<number | null>(null);
  const current = useStrategyCard(id);
  const versions = useStrategyCardVersions(id);
  const history = useStrategyCardVersion(id, versionNo ?? undefined);
  const q = versionNo === null ? current : history;

  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const d = q.data;

  return (
    <div className="page-scroll" data-testid="strategy-card-detail">
      <div className="page">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <h2 className="page-title" style={{ marginBottom: 0 }}>{d.name}</h2>
          <span className="mono muted">{d.key}</span>
          <Tag color={d.risk_level === 'high' ? 'red' : undefined}>{d.risk_level === 'high' ? '高风险' : '常规风险'}</Tag>
          <Link to="/strategy-cards" className="small">← 返回卡片列表</Link>
        </div>

        <div style={{ margin: '10px 0', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="muted small">版本：</span>
          <Select
            size="small" style={{ width: 180 }}
            value={versionNo ?? (current.data?.version_no ?? (versions.data?.[0]?.version_no ?? 1))}
            onChange={(v) => setVersionNo(v)}
            options={(versions.data ?? []).map((v) => ({ label: `v${v.version_no}`, value: v.version_no }))}
            data-testid="card-version-select" aria-label="选择卡片版本"
          />
          {versionNo !== null && versionNo !== current.data?.version_no ? (
            <span className="muted small" data-testid="viewing-history">正在查看历史版本</span>
          ) : null}
        </div>

        {/* 门禁缺口：后端给出，前端只展示 */}
        {d.gates_missing.length ? (
          <Alert
            type="info" showIcon style={{ margin: '8px 0' }} data-testid="gates-missing"
            title={<span>尚未通过的门禁：{d.gates_missing.join('、')}</span>}
            description="门禁由后端在申请晋级时跑；此处只显示缺口，不代表可用性判断。"
          />
        ) : null}

        <Descriptions size="small" column={2} bordered style={{ margin: '8px 0' }}>
          <Descriptions.Item label="类型">{CARD_CATEGORY_TEXT[d.category] ?? d.category}</Descriptions.Item>
          <Descriptions.Item label="周期">{d.horizons.map((h) => HORIZON[h] ?? h).join('、')}</Descriptions.Item>
          <Descriptions.Item label="完整度">{d.completeness ? CARD_COMPLETENESS_TEXT[d.completeness] : '—'}</Descriptions.Item>
          <Descriptions.Item label="来源">{d.source_kind ? CARD_SOURCE_TEXT[d.source_kind] ?? d.source_kind : '—'}</Descriptions.Item>
        </Descriptions>

        <h3>假设</h3>
        <div data-testid="hypothesis">
          <p><b>为什么可能有效：</b>{d.hypothesis.why_it_works}</p>
          <p><b>什么会证伪：</b>{d.hypothesis.falsified_by.length ? d.hypothesis.falsified_by.join('；') : '未填写'}</p>
        </div>

        <h3>维度</h3>
        <div data-testid="dimensions" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {d.dimensions.map((x) => (
            <Tag key={x.dimension}>{x.dimension} · {x.role === 'core' ? '核心' : x.role === 'auxiliary' ? '辅助' : '否决'}</Tag>
          ))}
        </div>

        {RULE_SECTIONS.map((s) => (
          <section key={s.key}>
            <h3>{s.title}{s.hint ? <span className="muted small">（{s.hint}）</span> : null}</h3>
            <RuleTable section={s.key} rows={d[s.key]} />
          </section>
        ))}

        <h3>数据需求</h3>
        <Table
          size="small" rowKey="feature_key" pagination={false} dataSource={d.data_needs}
          columns={[
            { title: '字段', key: 'k', render: (_, r: { feature_key: string }) => <span className="mono">{r.feature_key}</span> },
            { title: '频率', key: 'f', width: 100, render: (_, r: { frequency: string }) => r.frequency },
            { title: '复权', key: 'a', width: 90, render: (_, r: { adjust: string }) => r.adjust },
            { title: '可用时点', key: 't', render: (_, r: { available_at: string }) => r.available_at },
          ]}
        />

        {d.refs.length ? (
          <>
            <h3>出处</h3>
            <ul data-testid="refs">
              {d.refs.map((r) => (
                <li key={r.ref}>
                  <span className="mono">{r.ref}</span> {r.title}
                  {r.url ? <> · <a href={r.url} target="_blank" rel="noreferrer">{r.url}</a></> : null}
                </li>
              ))}
            </ul>
          </>
        ) : null}

        <h3>外部验证信息<span className="muted small">（来自研究员文档，产品不做回测）</span></h3>
        {d.validation_summary ? (
          <Descriptions size="small" column={2} bordered data-testid="validation-summary">
            <Descriptions.Item label="类型">{d.validation_summary.type}</Descriptions.Item>
            <Descriptions.Item label="窗口">{d.validation_summary.window ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="基准">{d.validation_summary.benchmark ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="成本模型">{d.validation_summary.cost_model ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="样本外结果">{d.validation_summary.oos_result ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="交易记录">{d.validation_summary.trade_log_ref ?? '—'}</Descriptions.Item>
          </Descriptions>
        ) : (
          <p className="muted" data-testid="no-validation-summary">研究员未提供外部验证信息。</p>
        )}
      </div>
    </div>
  );
}
