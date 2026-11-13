import { useState } from 'react';
import { Button, Empty, Tag } from 'antd';
import { useStrategyCardReading, useStrategyCards, type StrategyCardSummary } from '../../api/strategyCardQueries';
import { CursorPager } from '../../components/CursorPager';
import { ErrorBox, Loading } from '../../components/common';
import { HORIZON } from '../../i18n/labels';

const COMPLETENESS: Record<StrategyCardSummary['completeness'], string> = {
  draft: '草稿', documented: '已文档化', runnable_candidate: '待晋级候选', promoted: '已晋级', retired: '已退役',
};

function CardReading({ id }: { id: string }) {
  const q = useStrategyCardReading(id);
  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} prefix="知识卡正文加载失败" />;
  return (
    <div>
      {q.data.risk_level === 'high' ? <Tag color="red">高风险</Tag> : null}
      <h4>研究正文</h4>
      {q.data.narrative.trim() ? <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{q.data.narrative}</div> : <p className="muted">暂无研究正文</p>}
      <h4>晋级待完成项</h4>
      {q.data.gates_missing.length ? <ul>{q.data.gates_missing.map((gate) => <li key={gate}>{gate}</li>)}</ul> : <p className="muted">接口未列出待完成项</p>}
      <h4>参考出处</h4>
      {q.data.refs.length ? <ul>{q.data.refs.map((ref, index) => <li key={`${ref.ref}-${index}`}>{ref.ref} · {ref.title}{ref.url ? <span className="muted"> · {ref.url}</span> : null}</li>)}</ul> : <p className="muted">暂无参考出处</p>}
    </div>
  );
}

function KnowledgeCard({ card }: { card: StrategyCardSummary }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <article className="panel" data-testid="strategy-knowledge-card" aria-label={card.name}>
      <h3>{card.name} <span className="muted small">{card.key} · v{card.current_version_no}</span></h3>
      <p>分类：{card.category} · 周期：{card.horizons.length ? card.horizons.map((h) => HORIZON[h]).join('、') : '未声明适用周期'}</p>
      <p>完整度：{COMPLETENESS[card.completeness]}</p>
      {card.performance === null ? <p className="muted">暂无表现记录</p> : (
        <p>5日胜率：{card.performance.win_rate_5d.value ?? '—'}（样本 {card.performance.win_rate_5d.n}）；5日平均超额：{card.performance.avg_excess_5d.value ?? '—'}（样本 {card.performance.avg_excess_5d.n}）</p>
      )}
      <Button aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>{expanded ? '收起正文' : '阅读正文'}</Button>
      {expanded ? <CardReading id={card.id} /> : null}
    </article>
  );
}

export function StrategyCardsPage() {
  const q = useStrategyCards();
  if (q.isPending) return <Loading />;
  if (q.isError && !q.items.length) return <ErrorBox error={q.error} prefix="策略知识卡加载失败" />;
  return (
    <div className="page-scroll" data-testid="strategy-cards-page">
      <div className="page">
        <h2 className="page-title">策略知识卡</h2>
        <p className="muted">阅读策略研究与参考出处；卡片完整度不代表策略已启用。</p>
        {q.items.length ? q.items.map((card) => <KnowledgeCard key={card.id} card={card} />) : <Empty description="暂无可见的策略知识卡" />}
        <CursorPager query={q} loaded={q.items.length} unit="张" />
      </div>
    </div>
  );
}
