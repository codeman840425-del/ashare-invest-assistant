/** P2N-05b：8d4b507 §7.11.2。DeepSeek仅作14行保真转换，字段映射/规则判定本地复核。 */
import { ENUMS, type RiskControl } from '../api/enums';
import type { RiskControlSetting } from '../api/phase2Types';
type BaseRule = { control: RiskControl; path: string };
export type NumericRiskParamRule = BaseRule & { min: number; max: number } & (
  { kind: 'decimal'; defaultValue: string } |
  { kind: 'integer'; defaultValue: number } |
  { kind: 'decimal_pair'; defaultValue: readonly [string, string] }
);
export type RiskParamRule = NumericRiskParamRule | (BaseRule & { kind: 'boolean'; defaultValue: boolean });
export interface RiskParamIssue { field: string; kind: 'type' | 'precision' | 'range' | 'order'; message: string }
export const RISK_PARAM_RULES = [
  {
    "control": "stop_take",
    "path": "long_horizon_default_stop_pct",
    "kind": "decimal",
    "defaultValue": "-20",
    "min": -50,
    "max": -5
  },
  {
    "control": "stop_take",
    "path": "clamp_to_price_limit",
    "kind": "boolean",
    "defaultValue": true
  },
  {
    "control": "position_cap",
    "path": "single_position_max_pct",
    "kind": "decimal",
    "defaultValue": "20",
    "min": 5,
    "max": 50
  },
  {
    "control": "total_exposure",
    "path": "regime_ranges.uptrend",
    "kind": "decimal_pair",
    "defaultValue": [
      "60",
      "90"
    ],
    "min": 0,
    "max": 100
  },
  {
    "control": "total_exposure",
    "path": "regime_ranges.range",
    "kind": "decimal_pair",
    "defaultValue": [
      "40",
      "60"
    ],
    "min": 0,
    "max": 100
  },
  {
    "control": "total_exposure",
    "path": "regime_ranges.downtrend",
    "kind": "decimal_pair",
    "defaultValue": [
      "0",
      "30"
    ],
    "min": 0,
    "max": 100
  },
  {
    "control": "total_exposure",
    "path": "regime_confirm_days",
    "kind": "integer",
    "defaultValue": 2,
    "min": 1,
    "max": 5
  },
  {
    "control": "sector_concentration",
    "path": "sw_l1_max_pct",
    "kind": "decimal",
    "defaultValue": "40",
    "min": 10,
    "max": 100
  },
  {
    "control": "sector_concentration",
    "path": "concept_max_pct",
    "kind": "decimal",
    "defaultValue": "50",
    "min": 10,
    "max": 100
  },
  {
    "control": "loss_streak_drawdown",
    "path": "closed_loss_streak",
    "kind": "integer",
    "defaultValue": 3,
    "min": 2,
    "max": 10
  },
  {
    "control": "loss_streak_drawdown",
    "path": "drawdown_from_peak_pct",
    "kind": "decimal",
    "defaultValue": "10",
    "min": 3,
    "max": 50
  },
  {
    "control": "loss_streak_drawdown",
    "path": "strategy_sim_fail_streak",
    "kind": "integer",
    "defaultValue": 5,
    "min": 3,
    "max": 20
  },
  {
    "control": "loss_streak_drawdown",
    "path": "pause_on_trigger",
    "kind": "boolean",
    "defaultValue": true
  },
  {
    "control": "loss_streak_drawdown",
    "path": "pause_days",
    "kind": "integer",
    "defaultValue": 5,
    "min": 1,
    "max": 20
  }
] as const satisfies readonly RiskParamRule[];

const isRecord = (x: unknown): x is Record<string, unknown> => !!x && typeof x === 'object' && !Array.isArray(x);
export function riskParamValue(params: unknown, path: string): unknown {
  let value = params;
  for (const part of path.split('.')) { if (!isRecord(value)) return undefined; value = value[part]; }
  return value;
}
export function numericRiskRule(control: RiskControl, path: string): NumericRiskParamRule {
  const found = (RISK_PARAM_RULES as readonly RiskParamRule[]).find((r): r is NumericRiskParamRule => r.control === control && r.path === path && r.kind !== 'boolean');
  if (!found) throw new Error(`缺少契约参数规则：${control}.${path}`);
  return found;
}
export function validateRiskParams(setting: RiskControlSetting): RiskParamIssue[] {
  const issues: RiskParamIssue[] = [];
  for (const rule of RISK_PARAM_RULES) {
    if (rule.control !== setting.control) continue;
    const value = riskParamValue(setting.params, rule.path);
    const field = `${setting.control}.params.${rule.path}`;
    const add = (kind: RiskParamIssue['kind'], message: string, key = field) => { issues.push({ field: key, kind, message }); };
    if (rule.kind === 'boolean') { if (typeof value !== 'boolean') add('type', '必须为boolean'); continue; }
    if (rule.kind === 'decimal_pair' && (!Array.isArray(value) || value.length !== 2)) { add('type', '区间必须是两个decimal字符串'); continue; }
    const values: unknown[] = rule.kind === 'decimal_pair' && Array.isArray(value) ? value : [value];
    const before = issues.length;
    values.forEach((v, i) => {
      const key = rule.kind === 'decimal_pair' ? `${field}.${i}` : field;
      if (rule.kind === 'integer') {
        if (typeof v !== 'number' || !Number.isSafeInteger(v)) { add('type', '必须为整数', key); return; }
      } else {
        if (typeof v !== 'string' || !/^-?\d+(?:\.\d+)?$/.test(v)) { add('type', '必须为decimal字符串', key); return; }
        if ((v.split('.')[1]?.length ?? 0) > 2) { add('precision', '百分比最多2位小数', key); return; }
      }
      const number = Number(v);
      if (!Number.isFinite(number) || number < rule.min || number > rule.max) add('range', `必须在闭区间[${rule.min}, ${rule.max}]内`, key);
    });
    if (rule.kind === 'decimal_pair' && issues.length === before && Number(values[0]) > Number(values[1])) add('order', '区间下限不能大于上限');
  }
  return issues;
}
/** mock启动即校验默认值；不把默认表作为用户可编辑/可提交的字段。 */
export function assertRiskDefaults(settings: readonly RiskControlSetting[]) {
  if (settings.length !== 6 || new Set(settings.map((s) => s.control)).size !== 6 || ENUMS.risk_control.some((control) => !settings.some((s) => s.control === control))) throw new Error('风控默认设置必须包含六项');
  const issues = settings.flatMap(validateRiskParams);
  if (issues.length) throw new Error(`风控默认参数不合法：${issues.map((i) => `${i.field} ${i.message}`).join('；')}`);
}

function sameParamShape(value: unknown, reference: unknown): boolean {
  if (Array.isArray(reference)) return Array.isArray(value) && value.every((entry, i) => reference.length === 0 ? typeof entry === 'string' : sameParamShape(entry, reference[i] ?? reference[0]));
  if (isRecord(reference)) return isRecord(value) && Object.keys(value).length === Object.keys(reference).length && Object.keys(reference).every((key) => sameParamShape(value[key], reference[key]));
  return typeof value === typeof reference && value !== null;
}
/** 只信任响应default；缺失、错型、越界不回退到params/文档参考值。 */
export function restoredRiskDefault(item: RiskControlSetting): RiskControlSetting | null {
  if (!item.default || !sameParamShape(item.default, item.params)) return null;
  // control对应params与default同形已由上方运行时校验及契约映射类型保证。
  const next = { ...item, enabled: true, params: structuredClone(item.default) } as RiskControlSetting;
  if (validateRiskParams(next).length) return null;
  if (next.control === 'plan_violation' && !next.params.checks.every((key) => ['opposite_side', 'qty_over_plan', 'held_after_invalidation', 'buy_without_stop', 'buy_during_wait'].includes(key))) return null;
  return next;
}
