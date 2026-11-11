import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { Select, Table, Tag } from 'antd';
import type { CardCompleteness, Horizon } from '../../api/enums';
import { useStrategyCards } from '../../api/cardQueries';
import type { StrategyCardListItem } from '../../api/cardTypes';
import { ErrorBox, Loading } from '../../components/common';
import { HORIZON } from '../../i18n/labels';

/**
 * 策略知识卡（F-04）：卡片列表 + 筛选，点进详情看规则与门禁缺口。
 *
 * 卡片是**知识**而非可直接启用的策略：本页只展示研究员写的卡片内容与系统算出的 completeness /
 * gates_missing，不在前端重新判定门禁，也不把 completeness 翻译成“可用/不可用”的判断。
 * 契约 §7.4 GET /strategy-cards（completeness / horizon / category 可筛选，§1.2 游标分页）。
 */
export const CARD_COMPLETENESS_TEXT: Record<CardCompleteness, string> = {
  draft: '草稿',
  documented: '已成文',
  runnable_candidate: '可运行候选',
  promoted: '已晋级',
  retired: '已退役',
};
const COMPLETENESS_COLOR: Record<CardCompleteness, string | undefined> = {
  draft: 'default',
  documented: 'blue',
  runnable_candidate: 'gold',
  promoted: 'green',
  retired: 'default',
};
export const CARD_SOURCE_TEXT: Record<string, string> = {
  builtin: '内置',
  admin: '管理员',
  user: '本人',
  llm_draft: '草稿（LLM）',
  reference: '参考',
};

/** plan §2.5.14 B 节 category 的中文展示（取值以后端枚举为准，未知值原样显示） */
export const CARD_CATEGORY_TEXT: Record<string, string> = {
  trend: '趋势', momentum: '动量', reversal: '反转', breakout: '突破', value: '价值', quality: '质量',
  dividend: '红利', low_vol: '低波', event: '事件', intraday_t: '日内做T', risk: '风险',
};

const COMPLETENESS_OPTIONS: { label: string; value: CardCompleteness | 'all' }[] = [
  { label: '全部完整度', value: 'all' },
  ...(Object.keys(CARD_COMPLETENESS_TEXT) as CardCompleteness[]).map((k) => ({ label: CARD_COMPLETENESS_TEXT[k], value: k })),
];
const HORIZON_OPTIONS: { label: string; value: Horizon | 'all' }[] = [
  { label: '全部周期', value: 'all' },
  ...(Object.keys(HORIZON) as Horizon[]).map((k) => ({ label: HORIZON[k], value: k })),
];

export function StrategyCardsPage() {
  const [completeness, setCompleteness] = useState<CardCompleteness | 'all'>('all');
  const [horizon, setHorizon] = useState<Horizon | 'all'>('all');
  const filters = useMemo(
    () => ({ ...(completeness === 'all' ? {} : { completeness }), ...(horizon === 'all' ? {} : { horizon }) }),
    [completeness, horizon],
  );
  const q = useStrategyCards(filters);

  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;

  return (
    <div className="page-scroll" data-testid="strategy-cards-page">
      <div className="page">
        <h2 className="page-title">策略知识卡</h2>
        <p className="muted">每张卡描述一个交易假设：为什么可能有效、怎么证伪、什么条件下失效。卡片是知识，不等于可直接启用的策略。</p>
        <div style={{ display: 'flex', gap: 8, margin: '8px 0', flexWrap: 'wrap' }}>
          <Select size="small" style={{ width: 160 }} value={completeness} options={COMPLETENESS_OPTIONS}
            onChange={(v) => setCompleteness(v)} data-testid="filter-completeness" aria-label="按完整度筛选" />
          <Select size="small" style={{ width: 160 }} value={horizon} options={HORIZON_OPTIONS}
            onChange={(v) => setHorizon(v)} data-testid="filter-horizon" aria-label="按周期筛选" />
        </div>
        {q.data.truncated ? (
          <div className="muted small" data-testid="cards-truncated" style={{ margin: '8px 0' }}>
            卡片较多，只显示了前一部分；请用筛选缩小范围。
          </div>
        ) : null}
        <Table<StrategyCardListItem>
          size="small" rowKey="id" pagination={false} dataSource={q.data.items}
          locale={{ emptyText: '没有符合筛选条件的策略卡。' }}
          columns={[
            {
              title: '卡片', key: 'name',
              render: (_, c) => (
                <span>
                  <Link to={`/strategy-cards/${c.id}`} data-testid={`card-link-${c.key}`}>{c.name}</Link>{' '}
                  <span className="mono muted">{c.key}</span>
                </span>
              ),
            },
            { title: '类型', key: 'cat', width: 100, render: (_, c) => CARD_CATEGORY_TEXT[c.category] ?? c.category },
            { title: '周期', key: 'h', width: 140, render: (_, c) => c.horizons.map((h) => HORIZON[h] ?? h).join('、') },
            {
              title: '完整度', key: 'c', width: 120,
              render: (_, c) => <Tag color={COMPLETENESS_COLOR[c.completeness]} data-testid={`card-completeness-${c.key}`}>{CARD_COMPLETENESS_TEXT[c.completeness] ?? c.completeness}</Tag>,
            },
            { title: '版本', key: 'v', width: 80, render: (_, c) => `v${c.current_version_no}` },
            { title: '来源', key: 's', width: 110, render: (_, c) => CARD_SOURCE_TEXT[c.source_kind] ?? c.source_kind },
          ]}
        />
      </div>
    </div>
  );
}
