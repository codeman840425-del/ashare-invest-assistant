/**
 * 契约 §8 GET /stream 的事件（T-F14）。每条事件 `id`（单调递增字符串）、`event`（下列类型之一）、`data`（JSON）。
 * 标 ⚖ 的事件（signal / candidate_signal / plan_draft_ready / suggestion）展示时旁边须有固定免责提示（§1.3）。
 * 研究候选（/candidates）没有 SSE 事件。
 */
import type { Action, CandidateSignalState, DataLicenceState, DataStatus } from './enums';
import type { DateStr, DateTime, Decimal, Notification, SignalEvent, SuggestionSummary, Uuid } from './types';

export interface StreamQuoteItem { security_code: string; name: string; price: Decimal; change_pct: Decimal; amount: Decimal; t: DateTime }

export interface StreamEventMap {
  heartbeat: { at: DateTime };
  quote: { items: StreamQuoteItem[]; data_as_of: DateTime };
  signal: SignalEvent;
  candidate_signal: { id: Uuid; security_code: string; name: string; state: CandidateSignalState; proposed_action: Action; strategy_key: string; strategy_name: string };
  reason_released: { reason_id: Uuid; signal_id: Uuid; code: string; released_at: DateTime };
  plan_draft_ready: { plan_draft_id: Uuid; signal_ids: Uuid[]; security_code: string; name: string; valid_until: DateTime | null };
  plan_triggered: { plan_id: Uuid; condition: string; at: DateTime };
  suggestion: { id: Uuid; security_code: string; name: string; supersedes_id: Uuid | null; summary: SuggestionSummary };
  notification: Notification;
  report: { date: DateStr };
  data_status: { dataset: string; data_status: DataStatus; data_as_of: DateTime | null };
  data_licence: { status: DataLicenceState; verification_id: Uuid | null; last_error_code: string | null; at: DateTime };
}

export type StreamEventType = keyof StreamEventMap;
export const STREAM_EVENT_TYPES: readonly StreamEventType[] = [
  'heartbeat', 'quote', 'signal', 'candidate_signal', 'reason_released', 'plan_draft_ready', 'plan_triggered', 'suggestion',
  'notification', 'report', 'data_status', 'data_licence',
];
export const isStreamEventType = (x: string): x is StreamEventType => (STREAM_EVENT_TYPES as readonly string[]).includes(x);
