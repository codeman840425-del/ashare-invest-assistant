/** T-A31 / §8：同源fetch SSE；3秒起指数退避、抖动、稳定60秒归零，45秒无字节中断。 */
import { buildUrl, fetchUrl } from '../api/client';
import { SseParser, type SseMessage } from './sseParser';
export type StreamState = 'connecting' | 'open' | 'retrying' | 'closed';
export interface EventStreamOptions {
  path?: string;
  onMessage: (m: SseMessage) => void;
  onState?: (s: StreamState) => void;
  onOpen?: (info: { reconnect: boolean; lastEventId: string | null }) => void;
  onPolling?: (enabled: boolean) => void;
  onRetry?: (info: { delayMs: number; failures: number; attempt: number }) => void;
  /** 测试显式注入时覆盖服务端retry，生产采用retry:3000。 */
  retryMs?: number;
  maxRetryMs?: number;
  idleTimeoutMs?: number;
  random?: () => number;
  fetchImpl?: typeof fetch;
}
export const STREAM_DEFAULTS = { retryMs: 3_000, maxRetryMs: 60_000, idleTimeoutMs: 45_000, stableMs: 60_000, failureThreshold: 3 } as const;
/** 先指数退避，再±20%抖动；按契约字面上限，实际等待也不超过60秒。 */
export function streamRetryDelay(base: number, attempt: number, cap: number, random = Math.random): number {
  const nominal = Math.min(base * 2 ** Math.min(attempt, 30), cap);
  return Math.min(cap, Math.round(nominal * (0.8 + 0.4 * random())));
}
export interface EventStreamHandle { stop: () => void; lastEventId: () => string | null; state: () => StreamState }
export function startEventStream(opts: EventStreamOptions): EventStreamHandle {
  const retryBase = opts.retryMs ?? STREAM_DEFAULTS.retryMs; const retryMax = opts.maxRetryMs ?? STREAM_DEFAULTS.maxRetryMs;
  const idleMs = opts.idleTimeoutMs ?? STREAM_DEFAULTS.idleTimeoutMs; const url = fetchUrl(buildUrl(opts.path ?? '/stream'));
  let stopped = false; let state: StreamState = 'closed'; let lastId: string | null = null; let serverRetry: number | null = null;
  let attempt = 0; let failures = 0; let everOpened = false; let ctrl: AbortController | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null; let idleTimer: ReturnType<typeof setTimeout> | null = null; let stableTimer: ReturnType<typeof setTimeout> | null = null;
  const setState = (s: StreamState) => { if (state !== s) { state = s; opts.onState?.(s); } };
  const clearIdle = () => { if (idleTimer) clearTimeout(idleTimer); idleTimer = null; };
  const clearStable = () => { if (stableTimer) clearTimeout(stableTimer); stableTimer = null; };
  const armIdle = () => { clearIdle(); idleTimer = setTimeout(() => ctrl?.abort(new DOMException('heartbeat timeout', 'TimeoutError')), idleMs); };
  const scheduleRetry = () => {
    if (stopped) return; setState('retrying');
    const delayMs = streamRetryDelay(opts.retryMs ?? serverRetry ?? retryBase, attempt, retryMax, opts.random); attempt++;
    opts.onRetry?.({ delayMs, failures, attempt });
    retryTimer = setTimeout(() => { retryTimer = null; void connect(); }, delayMs);
  };
  async function connect() {
    if (stopped) return; setState(everOpened ? 'retrying' : 'connecting'); ctrl = new AbortController(); let stable = false;
    const headers: Record<string, string> = { Accept: 'text/event-stream', 'Cache-Control': 'no-cache' }; if (lastId) headers['Last-Event-ID'] = lastId;
    const parser = new SseParser((m) => {
      if (m.event === 'reset') {
        try {
          const data: unknown = JSON.parse(m.data);
          if (data && typeof data === 'object') {
            const reset = data as Record<string, unknown>;
            if ((reset.reason === 'expired' || reset.reason === 'unknown') && (reset.latest_event_id === null || typeof reset.latest_event_id === 'string' && /^\d+$/.test(reset.latest_event_id))) {
              // 按reset清空续传缓存；不把尚未收到的latest当作已消费事件，下一条业务帧正常推进。
              lastId = null; parser.lastEventId = null;
            }
          }
        } catch { /* 畸形reset不改变续传点，交消息边界校验丢弃。 */ }
      } else if (m.id !== null) lastId = m.id || null;
      opts.onMessage(m);
    }); parser.lastEventId = lastId;
    try {
      armIdle();
      const res = await (opts.fetchImpl ?? fetch)(url, { headers, credentials: 'same-origin', cache: 'no-store', signal: ctrl.signal });
      if (stopped) return;
      if ([401, 403, 404].includes(res.status)) { stopped = true; opts.onPolling?.(true); setState('closed'); return; }
      if (!res.ok || !res.body || !(res.headers.get('Content-Type') ?? '').includes('text/event-stream')) throw new Error(`stream http ${res.status}`);
      const reconnect = everOpened; everOpened = true; setState('open'); opts.onPolling?.(false);
      // 短连接成功不归零退避；只有保持连接完整60秒才归零。
      stableTimer = setTimeout(() => { stable = true; attempt = 0; failures = 0; stableTimer = null; }, STREAM_DEFAULTS.stableMs);
      opts.onOpen?.({ reconnect, lastEventId: lastId });
      const reader = res.body.getReader(); const dec = new TextDecoder();
      for (;;) {
        const { done, value } = await reader.read(); if (done) break;
        armIdle(); parser.push(dec.decode(value, { stream: true })); if (parser.retry !== null) serverRetry = parser.retry;
      }
    } catch { /* 建流/传输失败交由统一退避；不记录消息或凭据。 */ }
    finally { clearIdle(); clearStable(); parser.reset(); }
    if (!stopped) {
      // T-A32：未满60秒结束都计一次失败，200后EOF/读超时也累计；建流成功本身不清计数。
      if (!stable) { failures++; if (failures >= STREAM_DEFAULTS.failureThreshold) opts.onPolling?.(true); }
      scheduleRetry();
    }
  }
  opts.onPolling?.(false); void connect();
  return {
    stop() { stopped = true; if (retryTimer) clearTimeout(retryTimer); clearIdle(); clearStable(); ctrl?.abort(); setState('closed'); },
    lastEventId: () => lastId, state: () => state,
  };
}
