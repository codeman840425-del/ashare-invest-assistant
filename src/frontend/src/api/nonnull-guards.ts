/**
 * F-18：Evidence / StreamEventMap.quote 的 data_as_of 非空静态类型守卫（直接赋值断言，不依赖 @ts-expect-error）。
 *
 * 与 F-14 `pool-f14-nullability.test.tsx` 的差别：那里靠「@ts-expect-error 是否被消耗」做间接证明，类型一放宽
 * 报的是 TS2578（未使用指令），失败点落在注解上；本文件让**失败点落在字段的真实位置**：
 *
 *   把 null 赋给 `Pick<T, '字段'>` 形状的对象。若字段是非空 string，该赋值直接 TS2322（正确，说明守卫拦得住）；
 *   若字段被人放宽成 `string | null`，赋值就合法、不再报错 —— 所以这里必须配合「期望报错」的写法才成立。
 *
 * 因此本文件对**应当拒绝 null** 的字段用 `// @ts-expect-error`（失败即 TS2578，等于放宽被发现），
 * 对**应当接受 null** 的字段用无条件赋值（失败即 TS2322，等于被错误收紧）。
 * 两边任一处被改错都会让 `tsc` 在本文件报错 —— 而 F-14 只覆盖了前一类。
 */
import type { DataStatusBlock, Evidence } from './types';
import type { StreamEventMap, StreamQuoteItem } from './streamTypes';

/** ① 应拒绝 null 的字段：放宽成 | null 后，本 block 的指令变成未使用 → TS2578（红） */
export function assertEvidenceTimestampsRejectNull(): void {
  // @ts-expect-error Evidence.data_as_of 必须是非空 string（A-12 不放宽）
  const a: Pick<Evidence, 'data_as_of'> = { data_as_of: null };
  // @ts-expect-error Evidence.fetched_at 必须是非空 string
  const b: Pick<Evidence, 'fetched_at'> = { fetched_at: null };
  void a; void b;
}

export function assertQuoteTimestampsRejectNull(): void {
  // @ts-expect-error SSE quote.data_as_of 必须是非空 string（契约 §8 发布前提）
  const q: Pick<StreamEventMap['quote'], 'data_as_of'> = { data_as_of: null };
  // @ts-expect-error quote.items[].t 必须是非空 string
  const it: Pick<StreamQuoteItem, 't'> = { t: null };
  void q; void it;
}

/** ② 应接受 null 的字段：被人改回非空时，下面的赋值立刻 TS2322（红） */
export function assertDataStatusBlockAcceptsNull(): void {
  const ok: Pick<DataStatusBlock, 'data_as_of'> = { data_as_of: null };
  void ok;
}

/** ③ 反向：应缺键即红 —— 缺 data_as_of 时赋值失败（键必须出现） */
export function assertDataStatusBlockRequiresKey(): void {
  // @ts-expect-error DataStatusBlock 的 data_as_of 键必须出现（值可 null，键不可缺）
  const missing: DataStatusBlock = { data_status: 'unavailable', gaps: [] };
  void missing;
}
