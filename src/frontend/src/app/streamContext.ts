import { IS_MOCK } from '../lib/env';
import { createContext, useContext } from 'react';
import type { StreamState } from '../lib/eventStream';

/**
 * SSE 连接状态（T-F14）。`off` = 未启用（未登录区域、单元测试默认）。
 * 只有 `open` 时实时推送生效；轮询由独立上下文按T-A31三次建流失败门槛控制。
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

/** T-A31：前三次建流尝试不启用定时轮询；三次连续失败后由传输层开启，建流成功关闭。 */
export const StreamPollingContext = createContext(true);
export const useStreamPolling = () => useContext(StreamPollingContext);
