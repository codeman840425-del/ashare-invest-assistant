/** T-F28：DeepSeek 草稿经契约 §7.4 逐字段复核；Stat 复用 §5。 */
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

export interface PromotionReport {
  decision: Decision;
  gate_results: GateResultEntry[];
  fixture_runs: FixtureRun[];
  g6_report: G6Report;
}
