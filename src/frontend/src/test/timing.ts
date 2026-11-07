/**
 * T-F28：与时间顺序相关的用例统一用假时钟或明确状态，不用 sleep、不放宽超时。
 * - fakeClock(intervals)：只假定时器（不假 Date；intervals=false 时只假 setTimeout，页面上有高频 setInterval 时用）；shouldAdvanceTime 让 msw / react-query 的 0ms 调度照常推进，
 *   需要“到点”的地方用 advance(ms) 显式推进。setup.ts 的 afterEach 统一 useRealTimers。
 * - settled(qc)：等 react-query 没有进行中的查询和变更（“之后不再发请求”类断言的明确状态）。
 */
import { act, waitFor } from '@testing-library/react';
import type { QueryClient } from '@tanstack/react-query';
import { expect, vi } from 'vitest';

export const fakeClock = (intervals = true) =>
  vi.useFakeTimers({ shouldAdvanceTime: true, toFake: intervals ? ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] : ['setTimeout', 'clearTimeout'] });

export const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

export const settled = (qc: QueryClient) => waitFor(() => expect(qc.isFetching() + qc.isMutating()).toBe(0));
