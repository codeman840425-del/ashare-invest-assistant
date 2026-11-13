import { useQuery } from '@tanstack/react-query';
import { apiGet } from './client';
import type { CardRiskLevel, Horizon } from './enums';
import type { Stat } from './types';
import { useCursorPages } from '../lib/cursorPaging';

/** api-contract §7.4：只读取知识卡，不推断晋级或运行状态。 */
export interface StrategyCardSummary {
  id: string;
  key: string;
  name: string;
  category: string;
  horizons: Horizon[];
  completeness: 'draft' | 'documented' | 'runnable_candidate' | 'promoted' | 'retired';
  current_version_no: number;
  source_kind: 'builtin' | 'admin' | 'user' | 'llm_draft' | 'reference';
  performance: { win_rate_5d: Stat; avg_excess_5d: Stat } | null;
}

/** 详情只声明本页消费的契约字段；其余结构化规则不在前端重算。 */
export interface StrategyCardReading {
  narrative: string;
  risk_level: CardRiskLevel;
  gates_missing: string[];
  refs: { ref: string; title: string; url: string | null }[];
}

const cardId = (card: StrategyCardSummary) => card.id;
export const useStrategyCards = () => useCursorPages<StrategyCardSummary>({
  queryKey: ['strategy-cards'], path: '/strategy-cards', idOf: cardId,
});

export const useStrategyCardReading = (id: string) => useQuery({
  queryKey: ['strategy-card-reading', id],
  queryFn: ({ signal }) => apiGet<StrategyCardReading>(`/strategy-cards/${encodeURIComponent(id)}`, undefined, signal),
});
