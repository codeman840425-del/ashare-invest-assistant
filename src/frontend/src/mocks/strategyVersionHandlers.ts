/**
 * F-05：策略版本详情模拟（契约 §7.4 `GET /strategies/{id}/versions/{vid}`，配置按 plan §2.5.14 C 节）。
 * 所有名称、规则、阈值均为合成示例，不代表任何推荐策略。
 * `internal_check` 按"方案 A"只给是否做过、方法类型与日期，**不含数值或通过与否**。
 */
import { http, HttpResponse } from 'msw';
import type { StrategyVersionDetail } from '../api/strategyTypes';
import { STRATEGY_TEMPLATES } from './strategyHandlers';

const API = '/api/v1';
const json = (body: unknown, status = 200) => HttpResponse.json(body as Record<string, unknown>, { status });

const SYNTHETIC: Record<string, Omit<StrategyVersionDetail, 'key' | 'version_no' | 'lifecycle' | 'card_version_id' | 'param_hash' | 'parent_version_id'>> = {
  demo_trend: {
    kind: 'rule_template',
    horizons: ['swing'],
    params_schema: {
      ma_fast: { type: 'int', default: 20, min: 5, max: 60, step: 1, desc: '快线周期（合成示例）' },
      ma_slow: { type: 'int', default: 60, min: 20, max: 200, step: 1, desc: '慢线周期（合成示例）' },
    },
    rules: [
      { id: 'R1', dimension: 'technical', role: 'entry', expr: 'close > ma(close, ma_fast)', weight: 1, required_features: ['close'] },
      { id: 'R2', dimension: 'capital', role: 'counter', expr: 'volume_ratio < 0.5', weight: 0, required_features: ['volume_ratio'] },
      { id: 'R3', dimension: 'technical', role: 'invalidation', expr: 'close < ma(close, ma_fast)', weight: 0, required_features: ['close'] },
    ],
    action_map: { entry_all_core_pass: 'buy', held_hold: 'hold', exit: 'sell', else: 'wait' },
    stops: { stop_loss: 'entry - 2 * atr(14)', take_profit: null, time_stop_days: 10 },
    dimension_view_thresholds: { bullish: 0.67, bearish: 0.33 },
    applicability: { market_regime: ['uptrend', 'range'] },
    valid_until: { trading_days: 5 },
    screen: null,
    risk_level: 'normal',
    internal_check: { done: true, method_types: ['factor_ic', 'param_robustness'], checked_on: '2026-10-28' },
  },
};

/** 兜底：模板没有专门配置时给一份最小合成结构，保证页面在任何模板上都能打开 */
const fallback = (key: string, horizons: string[]): (typeof SYNTHETIC)[string] => ({
  kind: 'rule_template',
  horizons: horizons as never,
  params_schema: { threshold: { type: 'float', default: 0.5, min: 0, max: 1, step: 0.01, desc: '合成示例阈值' } },
  rules: [
    { id: 'R1', dimension: 'technical', role: 'entry', expr: 'close > ma(close, 20)', weight: 1, required_features: ['close'] },
  ],
  action_map: { entry_all_core_pass: 'buy', else: 'wait' },
  stops: { stop_loss: 'entry - 2 * atr(14)', take_profit: null, time_stop_days: 5 },
  dimension_view_thresholds: null,
  applicability: null,
  valid_until: null,
  screen: null,
  risk_level: 'normal',
  internal_check: { done: false, method_types: [], checked_on: null },
});

export const strategyVersionHandlers = [
  http.get(`${API}/strategies/:id/versions/:vid`, ({ params }) => {
    const t = STRATEGY_TEMPLATES.find((x) => x.id === String(params.id));
    if (!t || t.current_version.id !== String(params.vid)) {
      return json({ error: { code: 'NOT_FOUND', message: '策略版本不存在（示例数据）', details: null, request_id: 'mock' } }, 404);
    }
    const base = SYNTHETIC[t.key] ?? fallback(t.key, t.horizons);
    return json({
      ...base,
      key: t.key,
      version_no: t.current_version.version_no,
      lifecycle: t.current_version.lifecycle,
      card_version_id: null,
      param_hash: `synth-${t.key}-${t.current_version.version_no}`,
      parent_version_id: null,
    } satisfies StrategyVersionDetail);
  }),
];
