import { assertRiskDefaults } from '../lib/riskControlParams';
/** P2N-05a 示例数据：由 DeepSeek 状态草稿逐项复核生成；不调用行情、不执行真实求值。 */
import type { DailyReport, Evidence, Gap, Stat, Suggestion } from '../api/types';
import type { RiskControlSetting, RiskEvaluation, SuggestionTracking, TrackingResult } from '../api/phase2Types';
import { PHASE2_STATES } from './phase2States';

const id = (n: number) => `eeeeeeee-eeee-4eee-8eee-${n.toString(16).padStart(12, 'e')}`;
const missing = (key: string, message: string): Gap => ({ key, reason: 'no_source', message });
const dimensionStates = PHASE2_STATES.filter((s) => s.kind === 'dimension');
export function withDailyDimensions(input: DailyReport): DailyReport {
  const report = structuredClone(input);
  for (const [index, stock] of report.stocks.entries()) {
    if (stock.change_from_previous === 'removed') { stock.analysis_snapshot_id = null; stock.dimensions = null; continue; }
    stock.data_status = 'partial';
    if (stock.close === null) stock.highlights = [{ text: '示例数据：收盘价缺失，不补造价格事实', expr: null, evidence_ids: [] }];
    stock.analysis_snapshot_id = id(200 + index);
    stock.dimensions = dimensionStates.map((sample, j) => {
      const evidenceId = `${stock.security_code}:D${j + 1}`;
      const evidence: Evidence = { id: evidenceId, key: sample.feature, value: sample.value, unit: sample.unit,
        provider: 'system', endpoint: null, data_as_of: report.data_as_of, fetched_at: report.generated_at, epistemic_type: 'fact' };
      report.evidence.push(evidence);
      const gaps = [missing(`${stock.security_code}.${sample.feature}`, sample.value === null ? sample.text : '示例数据：技术维度仅提供一项合成事实，其余输入缺失')];
      report.gaps.push(...gaps);
      return { dimension: sample.dimension, facts: sample.value === null ? [] : [{ text: sample.text, expr: null, evidence_ids: [evidenceId] }],
        feature_refs: [{ feature_key: sample.feature, status: sample.status, evidence_ids: [evidenceId] }],
        data_status: sample.data_status, data_as_of: sample.value === null ? null : report.data_as_of, gaps };
    });
  }
  // F25缺口必须与日报市场/账户说明一致，不能沿用旧夹具的range冒充已知。
  report.evidence = report.evidence.filter((e) => e.key !== 'market.regime_score');
  report.market.regime = null;
  report.market.regime_position_range = null;
  if (report.account) report.account.position_vs_regime = null;
  report.market.summary = [...report.market.summary.slice(0, 1), { text: '示例数据：大盘环境未知，参考仓位区间缺失', expr: null, evidence_ids: [] }];
  report.explanation = { source: 'template', llm_call_id: null, text: '示例数据：大盘环境未知；六维是事实覆盖，不是六个新策略。各策略结论并列，不合并动作；未知指标不填0。' };
  report.data_status = 'partial';
  return report;
}

export const EXAMPLE_RISK_SETTINGS: RiskControlSetting[] = [
  { control: 'stop_take', enabled: true, source: 'system', params: { long_horizon_default_stop_pct: '-20', clamp_to_price_limit: true }, default: { long_horizon_default_stop_pct: '-20', clamp_to_price_limit: true } },
  { control: 'position_cap', enabled: true, source: 'system', params: { single_position_max_pct: '20' }, default: { single_position_max_pct: '20' } },
  { control: 'total_exposure', enabled: true, source: 'system', params: { regime_ranges: { uptrend: ['60', '90'], range: ['40', '60'], downtrend: ['0', '30'] }, regime_confirm_days: 2 }, default: { regime_ranges: { uptrend: ['60', '90'], range: ['40', '60'], downtrend: ['0', '30'] }, regime_confirm_days: 2 } },
  { control: 'sector_concentration', enabled: true, source: 'system', params: { sw_l1_max_pct: '40', concept_max_pct: '50' }, default: { sw_l1_max_pct: '40', concept_max_pct: '50' } },
  { control: 'loss_streak_drawdown', enabled: true, source: 'system', params: { closed_loss_streak: 3, drawdown_from_peak_pct: '10', strategy_sim_fail_streak: 5, pause_on_trigger: true, pause_days: 5 }, default: { closed_loss_streak: 3, drawdown_from_peak_pct: '10', strategy_sim_fail_streak: 5, pause_on_trigger: true, pause_days: 5 } },
  { control: 'plan_violation', enabled: false, source: 'user', params: { checks: ['opposite_side', 'qty_over_plan', 'held_after_invalidation', 'buy_without_stop', 'buy_during_wait'] }, default: { checks: ['opposite_side', 'qty_over_plan', 'held_after_invalidation', 'buy_without_stop', 'buy_during_wait'] } },
];
assertRiskDefaults(EXAMPLE_RISK_SETTINGS);

export function exampleEvaluation(code: string, name: string, accountId: string | null, settings: RiskControlSetting[], changed: ReadonlySet<string>): RiskEvaluation {
  const at = '2026-10-30T17:30:00+08:00';
  const controls = PHASE2_STATES.filter((s) => s.kind === 'evaluation').map((sample): RiskEvaluation['controls'][number] => {
    const enabled = settings.find((s) => s.control === sample.control)?.enabled ?? sample.enabled;
    const state = !enabled ? 'disabled' : accountId === null ? 'unknown' : changed.has(sample.control) ? 'unknown' : sample.state === 'disabled' ? 'unknown' : sample.state;
    const gaps = state === 'unknown' ? [missing(sample.control === 'total_exposure' ? 'f.market_regime' : sample.control,
      accountId === null ? '示例数据：本人尚无账户输入与来源快照' : changed.has(sample.control) ? '示例数据：设置已变更，尚无重算后的评价' : sample.text + '；输入缺失，不能判定')] : [];
    return { control: sample.control, enabled, state, flags: state === 'triggered' ? [{ control: sample.control, level: 'warning' as const,
      message: '示例数据：已知单股仓位超限；可新增数量的输入不全，额度未知', gated_actions: ['buy', 'add'], quantity_cap: null, evidence_ids: ['R1'] }] : [], gaps };
  });
  return { account_id: accountId, security_code: code, name, snapshot_id: accountId === null ? null : id(700), evaluated_at: at, controls,
    evidence: accountId === null ? [] : [{ id: 'R1', key: 'position_pct', value: '25', unit: 'pct', provider: 'system', endpoint: null, data_as_of: at, fetched_at: at, epistemic_type: 'fact' }],
    data_status: 'partial', data_as_of: at, gaps: controls.flatMap((c) => c.gaps) };
}

const smallStat = (n: number): Stat => ({ value: null, n, small_sample: true, window: '本卡合成示例窗口' });
export function exampleTracking(suggestion: Suggestion): SuggestionTracking {
  const version = suggestion.strategies.find((v) => v.action !== 'wait');
  const samples = PHASE2_STATES.filter((s) => s.kind === 'tracking');
  const results: TrackingResult[] = samples.flatMap((sample, index): TrackingResult[] => {
    const bound = sample.state === 'excluded' ? suggestion.strategies.find((v) => v.action === 'wait') : index < 3 ? version : suggestion.strategies.find((v) => v.strategy_version_id !== version?.strategy_version_id && v.action !== 'wait');
    if (!bound) return [];
    const complete = sample.state === 'complete';
    const priceId = `P${index + 1}`;
    const at = '2026-11-04T09:30:00+08:00';
    const priceEvidence: Evidence[] = complete ? [
      { id: priceId, key: 'entry_exit.qfq_as_of', value: '10.00 / 10.125', unit: 'CNY_per_share', provider: 'system', endpoint: null, data_as_of: at, fetched_at: at, epistemic_type: 'fact' },
      { id: priceId + '-raw', key: 'entry_tradability.raw', value: '10.00', unit: 'CNY_per_share', provider: 'system', endpoint: null, data_as_of: '2026-11-03T09:30:00+08:00', fetched_at: at, epistemic_type: 'fact' },
    ] : sample.state === 'untradable' || sample.state === 'excluded' ? [
      { id: priceId, key: sample.state === 'untradable' ? 'tradability.suspended' : 'action.excluded', value: sample.state === 'untradable' ? true : 'wait', unit: null, provider: 'system', endpoint: null, data_as_of: at, fetched_at: at, epistemic_type: 'fact' },
    ] : [];
    return [{ strategy_version_id: bound.strategy_version_id, instance_id: bound.instance_id, action: bound.action,
      horizon_days: sample.state === 'unavailable' ? 1 : sample.horizon_days, state: sample.state, entry_at: complete ? '2026-11-03T09:30:00+08:00' : null, entry_price: complete ? '10.00' : null,
      exit_at: complete ? at : null, exit_price: complete ? '10.125' : null,
      benchmark_code: '000300.SH', benchmark_entry_price: null, benchmark_exit_price: null,
      return_pct: sample.return_pct, benchmark_return_pct: sample.benchmark_return_pct, excess_pct: sample.excess_pct,
      max_drawdown_pct: complete ? '-0.25' : null, max_runup_pct: complete ? '1.50' : null,
      direction_correct: null, invalidation_triggered_at: null, exclusion_reason: sample.exclusion_reason, price_basis: 'qfq', cost_applied: false,
      evidence: priceEvidence, evidence_ids: priceEvidence.map((e) => e.id), gaps: [missing(complete ? 'benchmark' : sample.state, complete ? '示例数据：基准行情缺失，基准收益及超额收益未知' : `示例数据：${sample.exclusion_reason ?? (sample.state === 'pending' ? '尚未到期' : '计算输入缺失')}`)] }];
  });
  // 单条观测绝不把 n 补到5；保留旧Stat，不用 results.length 替代有效样本。
  return { t1: smallStat(results.some((r) => r.state === 'complete') ? 1 : 0), t5: smallStat(0), t20: smallStat(0), results,
    data_status: 'partial', data_as_of: '2026-11-06T15:00:00+08:00', gaps: [missing('tracking', '示例数据：只有少量逐条观测，不能推断聚合表现')] };
}
