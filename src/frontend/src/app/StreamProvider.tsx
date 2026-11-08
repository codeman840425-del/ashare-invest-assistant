import { useEffect, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { startEventStream } from '../lib/eventStream';
import { createStreamConsumer, resyncAfterReconnect } from './streamEvents';
import { StreamPollingContext, NotificationSyncContext, StreamStatusContext, streamConfig, type NotificationSyncState, type StreamStatus } from './streamContext';

/** 登录后的外壳里挂一条 SSE 连接（契约 §8 GET /stream），事件写入查询缓存，连接状态下发给轮询开关 */
export function StreamProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<StreamStatus>(streamConfig.enabled ? 'connecting' : 'off');
  const [polling, setPolling] = useState(!streamConfig.enabled);
  const [sync, setSync] = useState<NotificationSyncState>('idle');
  useEffect(() => {
    if (!streamConfig.enabled) return undefined;
    let active = true; let generation = 0;
    const resync = (full = false) => {
      const current = ++generation; setSync('loading');
      void resyncAfterReconnect(qc, full).then(() => { if (active && current === generation) setSync('ready'); }, () => { if (active && current === generation) setSync('error'); });
    };
    const consume = createStreamConsumer(qc, () => resync(true));
    const h = startEventStream({
      retryMs: streamConfig.retryMs,
      maxRetryMs: streamConfig.maxRetryMs,
      idleTimeoutMs: streamConfig.idleTimeoutMs,
      onState: setStatus,
      onOpen: () => resync(),
      onPolling: setPolling,
      onMessage: consume,
    });
    return () => { active = false; h.stop(); };
  }, [qc]);
  return <StreamStatusContext.Provider value={status}><NotificationSyncContext.Provider value={sync}><StreamPollingContext.Provider value={polling}>{children}</StreamPollingContext.Provider></NotificationSyncContext.Provider></StreamStatusContext.Provider>;
}
