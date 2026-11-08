import { useEffect, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { startEventStream } from '../lib/eventStream';
import { createStreamConsumer, resyncAfterReconnect } from './streamEvents';
import { NotificationSyncContext, StreamStatusContext, streamConfig, type NotificationSyncState, type StreamStatus } from './streamContext';

/** 登录后的外壳里挂一条 SSE 连接（契约 §8 GET /stream），事件写入查询缓存，连接状态下发给轮询开关 */
export function StreamProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<StreamStatus>(streamConfig.enabled ? 'connecting' : 'off');
  const [sync, setSync] = useState<NotificationSyncState>('idle');
  useEffect(() => {
    if (!streamConfig.enabled) return undefined;
    let active = true; const consume = createStreamConsumer(qc);
    const h = startEventStream({
      retryMs: streamConfig.retryMs,
      maxRetryMs: streamConfig.maxRetryMs,
      idleTimeoutMs: streamConfig.idleTimeoutMs,
      onState: setStatus,
      onOpen: () => {
        // 无ID/超窗的显式服务端信号未定，所有初连/重连一律补读本人列表与计数。
        setSync('loading');
        void resyncAfterReconnect(qc).then(() => { if (active) setSync('ready'); }, () => { if (active) setSync('error'); });
      },
      onMessage: consume,
    });
    return () => { active = false; h.stop(); };
  }, [qc]);
  return <StreamStatusContext.Provider value={status}><NotificationSyncContext.Provider value={sync}>{children}</NotificationSyncContext.Provider></StreamStatusContext.Provider>;
}
