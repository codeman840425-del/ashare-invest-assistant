/** T-F28：DeepSeek 草稿经契约 §7.4 逐字段复核；Stat 复用 §5。 */
import type { Lifecycle } from './enums';
import type { Stat } from './types';
export type GateId = "G1" | "G2" | "G3" | "G4" | "G5" | "G6" | "G7";

export type GateResult = "pass" | "fail" | "warn" | "skipped";

export type Decision = "pending" | "approved" | "rejected" | "changes_requested";

export type MaxJaccardNullReason = "no_history" | "no_comparable_set";

export interface GateResultEntry {
  gate: GateId;
  result: GateResult;
  detail: string;
}

export interface FixtureRun {
  fixture_id: string;
  passed: boolean;
  diff: unknown;
}

export interface G6Report {
  trigger_rate: Stat;
  coverage: Stat;
  max_jaccard: string | null;
  max_jaccard_null_reason: MaxJaccardNullReason | null;
  quota_delta_per_min: number;
}

/** T-F29：DeepSeek 机械草稿逐字段核对 §7.4；修正草稿未引用的 G1..G6 类型。 */
export type AutomaticGateId = Exclude<GateId, 'G7'>;
export interface PromotionBinding {
  review_id: string;
  card_id: string;
  version_id: string;
  version_no: number;
  content_sha256: string;
  stale: boolean;
  submitted_by: string;
  submitted_at: string;
  reviewer_id: string | null;
  decided_at: string | null;
}
export interface PromotionSummary extends PromotionBinding {
  card_key: string;
  lifecycle: Lifecycle;
  decision: Decision;
  g7: Decision;
  gates: { gate: AutomaticGateId; result: GateResult }[];
}
export interface PromotionFilters {
  decision?: string;
  card_id?: string;
  version_id?: string;
  stale: boolean;
}
export interface PromotionReport extends PromotionBinding {
  decision: Decision;
  gate_results: GateResultEntry[];
  fixture_runs: FixtureRun[];
  g6_report: G6Report;
}
