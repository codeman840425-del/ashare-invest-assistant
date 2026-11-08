/** P2N-05b：DeepSeek边界骨架复核后参数化定稿；期望范围据8d4b507。 */
import { RISK_PARAM_RULES, assertRiskDefaults, validateRiskParams, riskParamValue, type RiskParamRule, type NumericRiskParamRule } from './riskControlParams';
import { EXAMPLE_RISK_SETTINGS } from '../mocks/phase2Fixtures';
import type { RiskControlSetting } from '../api/phase2Types';
const numeric = (RISK_PARAM_RULES as readonly RiskParamRule[]).filter((rule): rule is NumericRiskParamRule => rule.kind !== 'boolean');
function changed(rule: RiskParamRule, value: unknown): RiskControlSetting {
  const setting = structuredClone(EXAMPLE_RISK_SETTINGS.find((s) => s.control === rule.control)!);
  let target: unknown = setting.params; const parts = rule.path.split('.');
  for (const part of parts.slice(0, -1)) { if (!target || typeof target !== 'object' || Array.isArray(target)) throw new Error('错误测试路径'); target = Reflect.get(target, part); }
  if (!target || typeof target !== 'object') throw new Error('错误测试路径');
  Reflect.set(target, parts[parts.length - 1], value);
  return setting;
}
it.each(RISK_PARAM_RULES)('$control.$path：系统示例默认值与表相同且合法', (rule) => {
  const setting = EXAMPLE_RISK_SETTINGS.find((s) => s.control === rule.control)!;
  expect(riskParamValue(setting.params, rule.path)).toEqual(rule.defaultValue);
  expect(validateRiskParams(setting)).toEqual([]);
});
for (const rule of numeric) {
  for (const which of ['min', 'max', 'below', 'above'] as const) {
    it(`${rule.control}.${rule.path}：${which}闭区间边界`, () => {
      const n = which === 'min' ? rule.min : which === 'max' ? rule.max : which === 'below' ? rule.min - 1 : rule.max + 1;
      const value = rule.kind === 'integer' ? n : rule.kind === 'decimal_pair' ? which === 'below' ? [String(n), String(rule.max)] : which === 'above' ? [String(rule.min), String(n)] : [String(n), String(n)] : String(n);
      const issues = validateRiskParams(changed(rule, value));
      if (which === 'min' || which === 'max') expect(issues).toEqual([]);
      else expect(issues.some((i) => i.kind === 'range' && i.field.startsWith(`${rule.control}.params.${rule.path}`))).toBe(true);
    });
  }
}
it('默认启动校验：六项完整、坏默认值会阻断，不自动钳制或回填', () => {
  expect(() => assertRiskDefaults(EXAMPLE_RISK_SETTINGS)).not.toThrow();
  const rule = numeric.find((r) => r.control === 'stop_take')!;
  const bad = changed(rule, '0');
  expect(() => assertRiskDefaults(EXAMPLE_RISK_SETTINGS.map((s) => s.control === bad.control ? bad : s))).toThrow(/默认参数不合法/);
  expect(() => assertRiskDefaults(EXAMPLE_RISK_SETTINGS.slice(0, 5))).toThrow(/六项/);
});
it.each(numeric.filter((r) => r.kind === 'integer'))('$control.$path：整数不接受小数', (rule) => {
  expect(validateRiskParams(changed(rule, rule.min + 0.5)).some((i) => i.kind === 'type')).toBe(true);
});
it.each(numeric.filter((r) => r.kind !== 'integer'))('$control.$path：接受2位小数，拒绝3位及数字类型', (rule) => {
  const value = (rule.min + 0.25).toFixed(2);
  expect(validateRiskParams(changed(rule, rule.kind === 'decimal_pair' ? [value, String(rule.max)] : value))).toEqual([]);
  const more = (rule.min + 0.125).toFixed(3);
  expect(validateRiskParams(changed(rule, rule.kind === 'decimal_pair' ? [more, String(rule.max)] : more)).some((i) => i.kind === 'precision')).toBe(true);
  expect(validateRiskParams(changed(rule, rule.kind === 'decimal_pair' ? [rule.min, rule.max] : rule.min)).some((i) => i.kind === 'type')).toBe(true);
});
it.each(numeric.filter((r) => r.kind === 'decimal_pair'))('$control.$path：区间倒置拒绝', (rule) => {
  expect(validateRiskParams(changed(rule, [String(rule.max), String(rule.min)])).some((i) => i.kind === 'order')).toBe(true);
});
it('RC3三档之间不强制单调', () => {
  const item = structuredClone(EXAMPLE_RISK_SETTINGS.find((s) => s.control === 'total_exposure')!);
  if (item.control !== 'total_exposure') throw new Error('夹具错误');
  item.params.regime_ranges = { uptrend: ['0', '5'], range: ['90', '100'], downtrend: ['50', '60'] };
  expect(validateRiskParams(item)).toEqual([]);
});
