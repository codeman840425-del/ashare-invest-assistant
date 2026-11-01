/** T-F22：策略库最小查询（契约 §7.5）。 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';
import type { Paged } from './types';
import type { StrategyInstance, StrategyInstanceCreate, StrategyInstanceCreated, StrategyTemplate } from './strategyTypes';

export const sk = { templates: ['strategies'] as const, instances: ['strategy-instances'] as const };

export const useStrategyTemplates = () =>
  useQuery({ queryKey: sk.templates, queryFn: ({ signal }) => apiGet<Paged<StrategyTemplate>>('/strategies', { limit: 200 }, signal) });
export const useStrategyInstances = () =>
  useQuery({ queryKey: sk.instances, queryFn: ({ signal }) => apiGet<Paged<StrategyInstance>>('/strategy-instances', { limit: 200 }, signal) });

export function useCreateStrategyInstance() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: StrategyInstanceCreate) => apiPost<StrategyInstanceCreated>('/strategy-instances', b),
    onSuccess: () => qc.invalidateQueries({ queryKey: sk.instances }),
  });
}
/** 停用 = pause；再次启用已暂停的实例 = resume */
export function useInstanceTransition() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, to }: { id: string; to: 'pause' | 'resume' }) => apiPost<StrategyInstance>(`/strategy-instances/${encodeURIComponent(id)}/${to}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: sk.instances }),
  });
}
