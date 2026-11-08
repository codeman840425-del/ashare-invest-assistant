/** P2N-05a：DeepSeek 类型草稿按契约 §7.11 逐字段复核；draft 不是响应字段。 */
import type { DataStatusBlock, Evidence, Gap, Stat, TextWithEvidence, RiskFlag } from './types';
import type { Dimension, RiskControl, Action } from './enums';

export interface DailyDimensionAnalysis extends Omit<DataStatusBlock, 'data_as_of'> {
  dimension: Dimension;
  facts: TextWithEvidence[];
  feature_refs: {
    feature_key: string;
    status: 'declared' | 'verified_doc' | 'verified_live' | 'gap' | 'deprecated' | null;
    evidence_ids: string[];
  }[];
  data_status: DataStatusBlock['data_status'];
  data_as_of: string | null;
  gaps: Gap[];
}

export type RiskControlParamsMap = {
  stop_take: {
    long_horizon_default_stop_pct: string;
    clamp_to_price_limit: boolean;
  };
  position_cap: {
    single_position_max_pct: string;
  };
  total_exposure: {
    regime_ranges: {
      uptrend: [string, string];
      range: [string, string];
      downtrend: [string, string];
    };
    regime_confirm_days: number;
  };
  sector_concentration: {
    sw_l1_max_pct: string;
    concept_max_pct: string;
  };
  loss_streak_drawdown: {
    closed_loss_streak: number;
    drawdown_from_peak_pct: string;
    strategy_sim_fail_streak: number;
    pause_on_trigger: boolean;
    pause_days: number;
  };
  plan_violation: {
    checks: string[];
  };
};

/** GET/PUT响应：default只读，和对应params严格同形。 */
export type RiskControlSetting = {
  [K in RiskControl]: {
    control: K;
    enabled: boolean;
    source: 'system' | 'user';
    params: RiskControlParamsMap[K];
    readonly default: RiskControlParamsMap[K];
  };
}[RiskControl];
/** PUT请求不能包含source/default。 */
export type RiskControlSettingPut = {
  [K in RiskControl]: { control: K; enabled: boolean; params: RiskControlParamsMap[K] };
}[RiskControl];

export interface RiskEvaluation extends DataStatusBlock {
  account_id: string | null;
  security_code: string;
  name: string;
  snapshot_id: string | null;
  evaluated_at: string;
  controls: {
    control: RiskControl;
    enabled: boolean;
    state: 'ok' | 'triggered' | 'unknown' | 'disabled';
    flags: RiskFlag[];
    gaps: Gap[];
  }[];
  evidence: Evidence[];
}

export interface RiskEvent extends RiskFlag {
  id: string;
  security_code: string | null;
  name: string | null;
  status: 'active' | 'cleared';
  triggered_at: string;
  cleared_at: string | null;
  suggestion_id: string | null;
  evidence: Evidence[];
}

export interface TrackingResult {
  strategy_version_id: string;
  instance_id: string | null;
  action: Action;
  horizon_days: 1 | 5 | 20;
  state: 'pending' | 'complete' | 'untradable' | 'excluded' | 'unavailable';
  entry_at: string | null;
  entry_price: string | null;
  exit_at: string | null;
  exit_price: string | null;
  benchmark_code: string;
  benchmark_entry_price: string | null;
  benchmark_exit_price: string | null;
  return_pct: string | null;
  benchmark_return_pct: string | null;
  excess_pct: string | null;
  max_drawdown_pct: string | null;
  max_runup_pct: string | null;
  direction_correct: boolean | null;
  invalidation_triggered_at: string | null;
  exclusion_reason: string | null;
  price_basis: 'qfq';
  cost_applied: boolean;
  evidence: Evidence[];
  evidence_ids: string[];
  gaps: Gap[];
}

export interface SuggestionTracking extends DataStatusBlock {
  t1: Stat;
  t5: Stat;
  t20: Stat;
  results: TrackingResult[];
}
