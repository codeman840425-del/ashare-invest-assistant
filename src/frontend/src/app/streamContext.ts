import { IS_MOCK } from '../lib/env';
import { createContext, useContext } from 'react';
import type { StreamState } from '../lib/eventStream';

/**
 * SSE 连接状态（T-F14）。`off` = 未启用（未登录区域、单元测试默认）。
 * 只有 `open` 时实时推送生效；其余状态下各轮询照常（契约 §8：断线时退回轮询）。
 */
export type StreamStatus = StreamState | 'off';
export const StreamStatusContext = createContext<StreamStatus>('off');
export const useStreamStatus = () => useContext(StreamStatusContext);
/** SSE 已连上：未读数、终端、首页不再定时轮询 */
export const useStreamLive = () => useContext(StreamStatusContext) === 'open';

/**
 * 运行开关与时间参数。单元测试环境默认关闭（避免每个页面测试都挂一条长连接），
 * T-F14 的测试里显式打开并把重连间隔调小。
 */
export const streamConfig = {
  enabled: IS_MOCK && import.meta.env.MODE !== 'test',
  retryMs: undefined as number | undefined,
  maxRetryMs: undefined as number | undefined,
  idleTimeoutMs: undefined as number | undefined,
};

/** 补读独立于TCP连通：失败不能宣称离线数据已经补齐。 */
export type NotificationSyncState = 'idle' | 'loading' | 'ready' | 'error';
export const NotificationSyncContext = createContext<NotificationSyncState>('idle');
export const useNotificationSync = () => useContext(NotificationSyncContext);
