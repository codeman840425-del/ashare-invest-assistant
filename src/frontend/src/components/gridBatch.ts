/** T-F21 表格性能：虚拟化参数与批量事务的增量计算（纯函数，便于测试） */

/** 行虚拟化：只渲染可视区上下各 ROW_BUFFER 行（AG Grid Community 默认开启，不能用 domLayout=autoHeight，否则会关闭虚拟化） */
export const ROW_BUFFER = 10;
/** 批量事务的合并窗口：这段时间内到达的多次行情更新合并成一次渲染 */
export const ASYNC_TX_WAIT_MS = 50;

export type RowUpdatePlan<T> = { kind: 'none' } | { kind: 'update'; update: T[] } | { kind: 'reset' };

/**
 * T-F21 批量事务更新：行集合与顺序都没变时，只把引用变化的行（TanStack Query 结构共享保证未变的行引用不变）
 * 交给 applyTransactionAsync；增删或顺序变化时整体替换 rowData（AG Grid 按 getRowId 做增量，不丢滚动位置）。
 */
export function planRowUpdate<T>(prev: readonly T[], next: readonly T[], idOf: (row: T) => string): RowUpdatePlan<T> {
  if (prev === next) return { kind: 'none' };
  if (prev.length !== next.length) return { kind: 'reset' };
  const update: T[] = [];
  for (let i = 0; i < next.length; i++) {
    if (prev[i] === next[i]) continue;
    if (idOf(prev[i]) !== idOf(next[i])) return { kind: 'reset' };
    update.push(next[i]);
  }
  return update.length ? { kind: 'update', update } : { kind: 'none' };
}
