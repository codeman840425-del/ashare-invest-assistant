/**
 * SSE GET /stream 的本地模拟（契约 §8，T-F14）。
 * - 全部在 MSW 内存里生成，不发任何外网请求；未登录 → 401 信封。
 * - 每条业务事件带单调递增的字符串 id；heartbeat 每 15 秒一次、不带 id（不影响续传位置）。
 * - 事件日志保留 10 分钟；请求头带 Last-Event-ID 时补发其后的事件。
 * - 测试用 pushStreamEvent / dropStreamConnections 驱动；浏览器演示模式在首次连接后推一条“示例”通知。
 */
import { http, HttpResponse } from 'msw';
import type { StreamEventMap, StreamEventType } from '../api/streamTypes';
import type { Notification } from '../api/types';
import { errorBody } from './handlerUtils';
import { exampleNotificationVersion } from './notificationStreamFixtures';
import { addMockNotification } from './notificationStore';
import { currentUser } from './session';

const API = '/api/v1';
export const STREAM_RETENTION_MS = 10 * 60_000;
export const HEARTBEAT_MS = 15_000;

interface LoggedEvent { owner: string; id: string; type: StreamEventType; data: unknown; at: number }
interface Conn { owner: string; send: (chunk: string) => void; close: () => void }

let seq = 0;
let log: LoggedEvent[] = [];
const conns = new Set<Conn>();
/** 收到的每次连接的 Last-Event-ID（测试断言续传用） */
export const streamRequests: (string | null)[] = [];
let demoPushed = false;
const demoTimers = new Set<ReturnType<typeof setTimeout>>();

const enc = new TextEncoder();
const frame = (e: { id?: string; type: string; data: unknown }) =>
  `${e.id ? `id: ${e.id}\n` : ''}event: ${e.type}\ndata: ${JSON.stringify(e.data)}\n\n`;

function prune(now = Date.now()) {
  log = log.filter((e) => now - e.at <= STREAM_RETENTION_MS);
}

/** 推一条业务事件给所有连接（并写入日志供续传）；notification 事件同时写入通知列表 */
export function pushStreamEvent<K extends StreamEventType>(type: K, data: StreamEventMap[K], ownerId = currentUser()?.id): string {
  if (!ownerId) throw new Error('示例事件必须属于已登录用户');
  seq += 1;
  const e: LoggedEvent = { owner: ownerId, id: String(seq), type, data, at: Date.now() };
  log.push(e);
  prune();
  if (type === 'notification') addMockNotification(data as Notification, ownerId);
  for (const c of conns) if (c.owner === ownerId) c.send(frame(e));
  return e.id;
}

/** 模拟网络断开：服务端关闭全部连接（客户端应带 Last-Event-ID 重连） */
export function dropStreamConnections() {
  for (const c of [...conns]) c.close();
}

export const streamConnectionCount = () => conns.size;

export function resetStreamMock() {
  dropStreamConnections();
  seq = 0;
  log = [];
  streamRequests.length = 0;
  demoPushed = false;
  for (const timer of demoTimers) clearTimeout(timer); demoTimers.clear();
}

const isDemo = () => typeof window !== 'undefined' && import.meta.env.MODE !== 'test';


export const streamHandlers = [
  http.get(`${API}/stream`, ({ request }) => {
    const owner = currentUser()?.id;
    if (!owner) return HttpResponse.json(errorBody('AUTH_REQUIRED', '请先登录'), { status: 401 });
    const last = request.headers.get('Last-Event-ID');
    streamRequests.push(last);
    prune();
    let conn: Conn | null = null;
    let hb: ReturnType<typeof setInterval> | null = null;
    const cleanup = () => {
      if (hb) clearInterval(hb);
      hb = null;
      if (conn) conns.delete(conn);
    };
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        let open = true;
        conn = {
          owner,
          send: (chunk) => {
            if (!open) return;
            try {
              controller.enqueue(enc.encode(chunk));
            } catch {
              open = false;
              cleanup();
            }
          },
          close: () => {
            if (!open) return;
            open = false;
            cleanup();
            try {
              controller.close();
            } catch {
              /* 已被读端取消 */
            }
          },
        };
        conns.add(conn);
        const c = conn;
        // 续传：只补发保留期内 id 大于 Last-Event-ID 的事件
        const after = last !== null && /^\d+$/.test(last) ? Number(last) : null;
        if (after !== null) for (const e of log) if (e.owner === owner && Number(e.id) > after) c.send(frame(e));
        c.send(': connected\n\n');
        hb = setInterval(() => c.send(frame({ type: 'heartbeat', data: { at: new Date().toISOString() } })), HEARTBEAT_MS);
        request.signal.addEventListener('abort', () => c.close(), { once: true });
        if (isDemo() && !demoPushed) {
          demoPushed = true;
          for (const [index, version] of ([1, 2] as const).entries()) {
            const timer = setTimeout(() => { demoTimers.delete(timer); pushStreamEvent('notification', exampleNotificationVersion(version), owner); }, 6_000 + index * 3_000);
            demoTimers.add(timer);
          }
        }
      },
      cancel() {
        cleanup();
      },
    });
    return new HttpResponse(body, { headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' } });
  }),
];
