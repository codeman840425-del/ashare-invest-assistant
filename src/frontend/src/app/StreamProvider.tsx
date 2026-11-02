import { useEffect, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { startEventStream } from '../lib/eventStream';
import { applyStreamEvent, parseStreamMessage, resyncAfterReconnect } from './streamEvents';
import { StreamStatusContext, streamConfig, type StreamStatus } from './streamContext';

/** 登录后的外壳里挂一条 SSE 连接（契约 §8 GET /stream），事件写入查询缓存，连接状态下发给轮询开关 */
export function StreamProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<StreamStatus>(streamConfig.enabled ? 'connecting' : 'off');
  useEffect(() => {
    if (!streamConfig.enabled) return undefined;
    const h = startEventStream({
      retryMs: streamConfig.retryMs,
      maxRetryMs: streamConfig.maxRetryMs,
      idleTimeoutMs: streamConfig.idleTimeoutMs,
      onState: setStatus,
      onOpen: ({ reconnect }) => {
        if (reconnect) resyncAfterReconnect(qc);
      },
      onMessage: (m) => {
        const e = parseStreamMessage(m);
        if (e) applyStreamEvent(qc, e);
      },
    });
    return () => h.stop();
  }, [qc]);
  return <StreamStatusContext.Provider value={status}>{children}</StreamStatusContext.Provider>;
}
