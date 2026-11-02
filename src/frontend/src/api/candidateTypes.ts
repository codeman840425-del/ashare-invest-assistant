/** T-F23：研究候选（契约 v0.2.9 §7.7A，T-A11） */
import type {
  CandidateDecision, ConfidenceLevel, ResearchCandidateOrigin, ResearchCandidateStatus, SecurityType, SourceKind,
} from './enums';
import type { DataStatusBlock, Evidence, HorizonHint, TextWithEvidence } from './types';

/** 用户填写的成立条件：verify_by 与 verify_method 至少填一个 */
export interface CandidateConditionInput {
  text: string;
  verify_by: string | null;
  verify_method: string | null;
  confidence: ConfidenceLevel | null;
}
/** 固定为 hypothesis，用户不能选 */
export type CandidateCondition = CandidateConditionInput & { epistemic_type: 'hypothesis' };
export type CandidateFact = TextWithEvidence & { epistemic_type: 'fact' | 'estimate'; source_kind: SourceKind };
export interface FitAssessment {
  profile_filled: boolean;
  holdings_available: boolean;
  hints: HorizonHint[];
  warnings: TextWithEvidence[];
}
export interface CandidateVersion extends DataStatusBlock {
  id: string;
  candidate_id: string;
  version_no: number;
  security_code: string;
  /** 生成时的简称 */
  name: string;
  thesis: string | null;
  reasons: CandidateFact[];
  conditions_to_hold: CandidateCondition[];
  counter_evidence: CandidateFact[];
  fit_assessment: FitAssessment;
  decision: CandidateDecision | null;
  decision_reason: string | null;
  snapshot_id: string;
  evidence: Evidence[];
  created_at: string;
}
export interface ResearchCandidate {
  id: string;
  security_code: string;
  name: string;
  security_type: SecurityType;
  origin: ResearchCandidateOrigin;
  /** 本版恒为 null */
  strategy_run_id: string | null;
  suggestion_id: string | null;
  status: ResearchCandidateStatus;
  /** 本版恒为 [] */
  plan_ids: string[];
  version_count: number;
  current_version: CandidateVersion;
  created_at: string;
}
export interface ResearchCandidateSummary {
  id: string;
  security_code: string;
  name: string;
  origin: ResearchCandidateOrigin;
  status: ResearchCandidateStatus;
  suggestion_id: string | null;
  current_version_no: number;
  decision: CandidateDecision | null;
  last_version_at: string;
  created_at: string;
}
/** 本版 POST /candidates 不接受 strategy_screen */
export type CandidateCreateOrigin = Exclude<ResearchCandidateOrigin, 'strategy_screen'>;
export interface CandidateCreate {
  origin: CandidateCreateOrigin;
  security_code: string | null;
  suggestion_id: string | null;
  thesis: string | null;
  conditions_to_hold: CandidateConditionInput[];
}
/** 整体替换：未改的内容也要带上 */
export interface CandidateVersionCreate {
  base_version_no: number;
  thesis: string | null;
  conditions_to_hold: CandidateConditionInput[];
  decision: CandidateDecision | null;
  decision_reason: string | null;
}
