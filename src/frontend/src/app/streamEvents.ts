/**
 * 把 §8 SSE 事件落到 TanStack Query 缓存（T-F14）。原则：
 * - 能直接就地更新的（quote 的行情、suggestion 的摘要）先就地改，避免整页重拉；
 * - 其余一律按查询键前缀失效，由各页面按需重拉（失效不会请求没有挂载的查询）；
 * - 未知事件类型忽略（契约后续加事件时前端不报错）；data 不是合法 JSON 的事件丢弃。
 */
import type { QueryClient, QueryKey } from '@tanstack/react-query';
import type { TerminalResponse } from '../api/types';
import { isStreamEventType, type StreamEventMap, type StreamEventType } from '../api/streamTypes';
import type { SseMessage } from '../lib/sseParser';

export interface ParsedStreamEvent<K extends StreamEventType = StreamEventType> { id: string | null; type: K; data: StreamEventMap[K] }

export function parseStreamMessage(m: SseMessage): ParsedStreamEvent | null {
  if (!isStreamEventType(m.event)) return null;
  try {
    return { id: m.id, type: m.event, data: JSON.parse(m.data) as StreamEventMap[StreamEventType] };
  } catch {
    return null;
  }
}

const inv = (qc: QueryClient, ...keys: QueryKey[]) => {
  for (const queryKey of keys) void qc.invalidateQueries({ queryKey });
};

/** 首页与终端都是聚合视图：多数业务事件都会让它们变化（ETag 未变时服务端回 304，代价很小） */
const AGGREGATES: QueryKey[] = [['terminal'], ['today']];

export function applyStreamEvent(qc: QueryClient, e: ParsedStreamEvent) {
  switch (e.type) {
    case 'heartbeat':
      return;
    case 'quote': {
      const d = e.data as StreamEventMap['quote'];
      const byCode = new Map(d.items.map((q) => [q.security_code, q]));
      qc.setQueriesData<TerminalResponse>({ queryKey: ['terminal'] }, (old) => {
        if (!old) return old;
        let changed = false;
        const rows = old.rows.map((r) => {
          const q = byCode.get(r.security_code);
          if (!q) return r;
          changed = true;
          return { ...r, quote: { price: q.price, change_pct: q.change_pct, amount: q.amount, t: q.t } };
        });
        return changed ? { ...old, rows } : old;
      });
      return;
    }
    case 'suggestion': {
      const d = e.data as StreamEventMap['suggestion'];
      qc.setQueriesData<TerminalResponse>({ queryKey: ['terminal'] }, (old) => {
        if (!old) return old;
        if (!old.rows.some((r) => r.security_code === d.security_code)) return old;
        return { ...old, rows: old.rows.map((r) => (r.security_code === d.security_code ? { ...r, suggestion: d.summary } : r)) };
      });
      // 被取代的旧卡状态变了（status / superseded_by_id）
      inv(qc, ['suggestions'], ['today'], ...(d.supersedes_id ? [['suggestion', d.supersedes_id]] : []));
      return;
    }
    case 'signal':
      inv(qc, ['signals']);
      return;
    case 'candidate_signal': {
      const d = e.data as StreamEventMap['candidate_signal'];
      inv(qc, ['candidate-signals'], ['candidate-signal', d.id], ...AGGREGATES);
      return;
    }
    case 'reason_released':
      inv(qc, ['non-executable-reasons'], ['candidate-signals'], ['candidate-signal', (e.data as StreamEventMap['reason_released']).signal_id], ...AGGREGATES);
      return;
    case 'plan_draft_ready':
      inv(qc, ['plan-drafts'], ['candidate-signals'], ['today']);
      return;
    case 'plan_triggered':
      inv(qc, ['plans'], ['today']);
      return;
    case 'notification':
      // 列表与未读数共用 ['notifications'] 前缀
      inv(qc, ['notifications']);
      return;
    case 'report':
      inv(qc, ['daily-reports'], ['daily-report', (e.data as StreamEventMap['report']).date], ['today']);
      return;
    case 'data_status':
      inv(qc, ...AGGREGATES);
      return;
    case 'data_licence':
      // Me.data_licence_status 驱动全站证书横幅；['me'] 前缀同时覆盖 /me/data-licence
      inv(qc, ['me']);
      return;
    default:
      return;
  }
}

/** 断线重连成功后：可能错过了超出服务端 10 分钟保留期的事件，未读数与聚合视图各补拉一次 */
export function resyncAfterReconnect(qc: QueryClient) {
  inv(qc, ['notifications'], ...AGGREGATES);
}
