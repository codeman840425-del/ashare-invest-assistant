/**
 * SSE 客户端（契约 §8 GET /stream，T-F14）。
 *
 * 不用浏览器原生 EventSource，改用 fetch + 流式读取，原因：
 * 1. 契约的断点续传靠请求头 `Last-Event-ID`；原生 EventSource 只在它自己的自动重连里带这个头，
 *    页面主动重连（心跳超时、恢复联网）时无法带上，也不能自定义退避；
 * 2. 需要区分 401（会话失效，停止重连）与其他失败（按退避重连）；EventSource 拿不到状态码；
 * 3. 同一套代码在浏览器与测试（MSW 拦截 fetch）里都能跑，不出网。
 *
 * 行为：
 * - 只连同源相对路径 `/api/v1/stream`（buildUrl 拒绝绝对地址），credentials=same-origin；
 * - 收到的每个事件记住 id，重连时以 `Last-Event-ID` 头带上（服务端保留最近 10 分钟，§8）；
 * - 心跳 15 秒一次（§8），超过 idleTimeoutMs（默认 45 秒，即 3 个心跳周期）没有任何字节视为断线，主动断开重连；
 * - 断线后按退避重连：首次 retryMs（服务端 `retry:` 字段优先），之后每次乘 2，封顶 maxRetryMs；连上后退避归零；
 * - 401/403 视为会话失效，停止重连（状态 closed）；404 视为后端还没注册 /stream（T-F20，该端点没有资源 404），同样停止；其余失败都重连；
 * - 断线期间（connecting / retrying / closed）由调用方退回到轮询（§8：未读数、终端、首页 ≥ 15 秒）。
 */
import { buildUrl, fetchUrl } from '../api/client';
import { SseParser, type SseMessage } from './sseParser';

export type StreamState = 'connecting' | 'open' | 'retrying' | 'closed';

export interface EventStreamOptions {
  /** 契约相对路径，默认 `/stream` */
  path?: string;
  onMessage: (m: SseMessage) => void;
  onState?: (s: StreamState) => void;
  /** 每次（重新）连上时回调；reconnect=true 表示断线后重连成功 */
  onOpen?: (info: { reconnect: boolean; lastEventId: string | null }) => void;
  retryMs?: number;
  maxRetryMs?: number;
  idleTimeoutMs?: number;
  /** 测试注入用；默认全局 fetch（只请求后端相对路径） */
  fetchImpl?: typeof fetch;
}

/** 待架构冻结：复用既有客户端退避/心跳超时策略，集中可注入，非新增服务端契约。 */
export const STREAM_DEFAULTS = { retryMs: 3_000, maxRetryMs: 60_000, idleTimeoutMs: 45_000 } as const;

export interface EventStreamHandle {
  stop: () => void;
  lastEventId: () => string | null;
  state: () => StreamState;
}

export function startEventStream(opts: EventStreamOptions): EventStreamHandle {
  const retryBase = opts.retryMs ?? STREAM_DEFAULTS.retryMs;
  const retryMax = opts.maxRetryMs ?? STREAM_DEFAULTS.maxRetryMs;
  const idleMs = opts.idleTimeoutMs ?? STREAM_DEFAULTS.idleTimeoutMs;
  const url = fetchUrl(buildUrl(opts.path ?? '/stream'));
  let stopped = false;
  // 初值 closed：首次 connect() 时切到 connecting 会回调 onState（StrictMode 下先停后起也能把状态拉回来）
  let state: StreamState = 'closed';
  let lastId: string | null = null;
  let serverRetry: number | null = null;
  let attempt = 0;
  let everOpened = false;
  let ctrl: AbortController | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let idleTimer: ReturnType<typeof setTimeout> | null = null;

  const setState = (s: StreamState) => {
    if (state === s) return;
    state = s;
    opts.onState?.(s);
  };
  const clearIdle = () => {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = null;
  };
  const armIdle = () => {
    clearIdle();
    idleTimer = setTimeout(() => ctrl?.abort(new DOMException('heartbeat timeout', 'TimeoutError')), idleMs);
  };

  const scheduleRetry = () => {
    if (stopped) return;
    setState('retrying');
    const base = serverRetry ?? retryBase;
    const wait = Math.min(base * 2 ** attempt, Math.max(retryMax, base));
    attempt += 1;
    retryTimer = setTimeout(() => {
      retryTimer = null;
      void connect();
    }, wait);
  };

  async function connect() {
    if (stopped) return;
    setState(everOpened ? 'retrying' : 'connecting');
    ctrl = new AbortController();
    const headers: Record<string, string> = { Accept: 'text/event-stream', 'Cache-Control': 'no-cache' };
    if (lastId) headers['Last-Event-ID'] = lastId;
    const parser = new SseParser((m) => {
      if (m.id) lastId = m.id;
      opts.onMessage(m);
    });
    parser.lastEventId = lastId;
    try {
      armIdle();
      const res = await (opts.fetchImpl ?? fetch)(url, { headers, credentials: 'same-origin', cache: 'no-store', signal: ctrl.signal });
      if (res.status === 401 || res.status === 403 || res.status === 404) {
        clearIdle();
        stopped = true;
        setState('closed');
        return;
      }
      const ct = res.headers.get('Content-Type') ?? '';
      if (!res.ok || !res.body || !ct.includes('text/event-stream')) throw new Error(`stream http ${res.status}`);
      const reconnect = everOpened;
      everOpened = true;
      attempt = 0;
      setState('open');
      opts.onOpen?.({ reconnect, lastEventId: lastId });
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        armIdle();
        parser.push(dec.decode(value, { stream: true }));
        if (parser.retry !== null) serverRetry = parser.retry;
      }
    } catch {
      // 断线、心跳超时、非 2xx：统一走重连
    } finally {
      clearIdle();
      parser.reset();
    }
    if (!stopped) scheduleRetry();
  }

  void connect();

  return {
    stop() {
      stopped = true;
      if (retryTimer) clearTimeout(retryTimer);
      clearIdle();
      ctrl?.abort();
      setState('closed');
    },
    lastEventId: () => lastId,
    state: () => state,
  };
}
