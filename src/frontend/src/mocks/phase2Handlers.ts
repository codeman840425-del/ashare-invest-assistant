/** 示例数据；统一鉴权/CSRF由 accountHandlers 前置处理，设置按用户隔离且原子更新。 */
import { http, HttpResponse } from 'msw';
import { isUuid } from '../lib/uuid';
import type { RiskControlSetting } from '../api/phase2Types';
import { EXAMPLE_RISK_SETTINGS, exampleEvaluation } from './phase2Fixtures';
import { currentUser, state } from './session';
import { searchSecurities } from './marketFixtures';
import { errorBody, notFound, validation } from './handlerUtils';
const API = '/api/v1';
const settings = new Map<string, RiskControlSetting[]>();
const changes = new Map<string, Set<string>>();
export function resetPhase2() { settings.clear(); changes.clear(); }
function currentSettings() {
  const userId = currentUser()!.id;
  if (!settings.has(userId)) settings.set(userId, structuredClone(EXAMPLE_RISK_SETTINGS));
  return settings.get(userId)!;
}
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
function sameShape(value: unknown, example: unknown): boolean {
  if (Array.isArray(example)) return Array.isArray(value) && (example.every((x) => typeof x === 'string') ? value.every((x) => typeof x === 'string') : value.length === example.length && value.every((x, i) => sameShape(x, example[i])));
  if (record(example)) return record(value) && Object.keys(value).length === Object.keys(example).length && Object.keys(example).every((key) => sameShape(value[key], example[key]));
  if (typeof example === 'string') return typeof value === 'string' && /^-?\d+(?:\.\d+)?$/.test(value);
  if (typeof example === 'number') return typeof value === 'number' && Number.isSafeInteger(value);
  return typeof value === typeof example;
}
function validParams(control: string, params: unknown): boolean {
  const example = EXAMPLE_RISK_SETTINGS.find((s) => s.control === control);
  if (!example) return false;
  if (control === 'plan_violation') return record(params) && Object.keys(params).length === 1 && Array.isArray(params.checks) && params.checks.every((x) => typeof x === 'string' && EXAMPLE_CHECKS.includes(x));
  if (!sameShape(params, example.params)) return false;
  if (control === 'total_exposure') return record(params) && record(params.regime_ranges) && Object.values(params.regime_ranges).every((range) => Array.isArray(range) && range.length === 2);
  return true;
}
const EXAMPLE_CHECKS = ['opposite_side', 'qty_over_plan', 'held_after_invalidation', 'buy_without_stop', 'buy_during_wait'];
function invalidRange(setting: RiskControlSetting) {
  if (setting.control === 'position_cap') return Number(setting.params.single_position_max_pct) < 5 || Number(setting.params.single_position_max_pct) > 50;
  if (setting.control === 'total_exposure') return Object.values(setting.params.regime_ranges).some(([lo, hi]) => Number(lo) > Number(hi));
  return false; // 未明确的 min/max 不自造，报告列为契约待补。
}
export const phase2Handlers = [
  http.get(`${API}/risk-controls`, () => HttpResponse.json(currentSettings())),
  http.put(`${API}/risk-controls`, async ({ request }) => {
    const body: unknown = await request.json().catch(() => null);
    if (!Array.isArray(body)) return validation('body', '设置必须为数组（示例数据）');
    const seen = new Set<string>();
    const updates: RiskControlSetting[] = [];
    for (const item of body) {
      if (!record(item) || Object.keys(item).sort().join(',') !== 'control,enabled,params' || typeof item.control !== 'string' || typeof item.enabled !== 'boolean' || seen.has(item.control) || !validParams(item.control, item.params)) return validation('settings', '重复control、未知键或参数类型错误（示例数据）');
      seen.add(item.control);
      // 运行时按六项模板逐字段验证完毕；source仅由响应生成，不接收客户端写入。
      updates.push({ ...item, source: 'user' } as RiskControlSetting);
    }
    if (updates.some(invalidRange)) return HttpResponse.json(errorBody('RISK_CONTROL_INVALID_PARAMS', '参数超出已明确范围或区间倒置（示例数据）'), { status: 422 });
    const next = currentSettings().map((old) => updates.find((item) => item.control === old.control) ?? old);
    const userId = currentUser()!.id;
    settings.set(userId, next);
    changes.set(userId, new Set([...(changes.get(userId) ?? []), ...updates.map((s) => s.control)]));
    return HttpResponse.json(next);
  }),
  http.get(`${API}/risk-controls/evaluation`, ({ request }) => {
    const url = new URL(request.url); const code = url.searchParams.get('security_code');
    if (!code || !/^\d{6}\.(SH|SZ|BJ)$/.test(code)) return validation('security_code', 'security_code必填且格式正确（示例数据）');
    const security = searchSecurities(code, { limit: 1, types: ['stock', 'cdr', 'etf', 'index'] }).items[0];
    if (!security || security.security_code !== code) return notFound('证券');
    const userId = currentUser()!.id;
    // 合成种子账户明确归 demo_user；不把其他会话当成同一个账户。
    const accounts = currentUser()!.username === 'demo_user' ? [...state.accounts].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id)) : [];
    const accountId = url.searchParams.get('account_id');
    if (accountId !== null && !isUuid(accountId)) return validation('account_id', 'account_id必须是UUID（示例数据）');
    if (accountId && !accounts.some((a) => a.id === accountId)) return notFound('账户');
    return HttpResponse.json(exampleEvaluation(code, security.name, accountId ?? accounts[0]?.id ?? null, currentSettings(), changes.get(userId) ?? new Set()));
  }),
];
