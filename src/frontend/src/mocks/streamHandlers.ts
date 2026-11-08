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

const sequences = new Map<string, number>();
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
  const seq = (sequences.get(ownerId) ?? 0) + 1; sequences.set(ownerId, seq);
  const e: LoggedEvent = { owner: ownerId, id: String(seq), type, data, at: Date.now() };
  log.push(e);
  prune();
  if (type === 'notification') addMockNotification(data as Notification, ownerId);
  for (const c of conns) if (c.owner === ownerId) c.send(frame(e));
  return e.id;
}

/** 示例控制帧：不写业务日志、不占事件序号。 */
export function pushStreamReset(reason: 'expired' | 'unknown' = 'unknown') {
  const owner = currentUser()?.id; if (!owner) return;
  const latest = sequences.get(owner) ?? 0;
  for (const conn of conns) if (conn.owner === owner) conn.send(frame({ type: 'reset', data: { reason, latest_event_id: latest ? String(latest) : null } }));
}

/** 模拟网络断开：服务端关闭全部连接（客户端应带 Last-Event-ID 重连） */
export function dropStreamConnections() {
  for (const c of [...conns]) c.close();
}

export const streamConnectionCount = () => conns.size;

export function resetStreamMock() {
  dropStreamConnections();
  sequences.clear();
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
        // T-A31：每用户十进制序号；首次无ID不发reset，未知/过窗先控制事件再实时流。
        const latest = sequences.get(owner) ?? 0;
        const after = last !== null && /^\d+$/.test(last) ? Number(last) : null;
        let prefix = 'retry: 3000\n\n';
        const anchor = log.find((e) => e.owner === owner && e.id === last);
        if (last !== null && (after === null || after < 1 || after > latest || !anchor)) {
          const reason = after !== null && after >= 1 && after <= latest ? 'expired' : 'unknown';
          prefix += frame({ type: 'reset', data: { reason, latest_event_id: latest ? String(latest) : null } });
        } else if (after !== null) {
          for (const e of log) if (e.owner === owner && Number(e.id) > after) prefix += frame(e);
        }
        c.send(prefix + ': connected\n\n');
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
