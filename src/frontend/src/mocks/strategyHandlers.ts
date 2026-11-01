/**
 * T-F22：策略库最小模拟（契约 v0.2.6 §7.5 /strategies、/strategy-instances）。名称均为示例。
 * 高风险模板（risk_level: high，如 S-03 st_strong_momo）默认不启用；启用不需要任何确认字段（T006e）。
 */
import { http, HttpResponse } from 'msw';
import { ENUMS, type Horizon } from '../api/enums';
import type { StrategyInstance, StrategyInstanceCreate, StrategyTemplate } from '../api/strategyTypes';
import { errorBody, page } from './handlerUtils';
import { ACCOUNT_ID, STRATEGIES, uid } from './fixtures';
import { HORIZON } from '../i18n/labels';
import { currentUser, state } from './session';

const API = '/api/v1';
const json = (body: unknown, status = 200) => HttpResponse.json(body as Record<string, unknown>, { status });

export const STRATEGY_TEMPLATES: StrategyTemplate[] = [
  ...Object.values(STRATEGIES).map((s, i): StrategyTemplate => ({
    id: uid(500 + i), key: s.key, name: s.name, horizons: [s.horizon],
    current_version: { id: s.version_id, version_no: s.version_no, lifecycle: s.lifecycle },
    health: { state: 'ok', weight: s.priority_weight, n: 40 + i * 7 }, risk_level: 'normal',
  })),
  {
    id: uid(510), key: 'st_pullback_ma', name: '强势股短线回踩（示例）', horizons: ['short'],
    current_version: { id: uid(320), version_no: 1, lifecycle: 'published' }, health: { state: 'ok', weight: '1.00', n: 18 }, risk_level: 'normal',
  },
  {
    id: uid(511), key: 'st_strong_momo', name: '涨停强势情绪接力（示例）', horizons: ['short'],
    current_version: { id: uid(321), version_no: 1, lifecycle: 'observing' }, health: { state: 'ok', weight: '0.50', n: 6 }, risk_level: 'high',
  },
];

let instances: StrategyInstance[] = [];
let seq = 0;
export function resetStrategies() {
  seq = 0;
  // 4 个示例模板已有实例（与 fixtures 的 instance_id 一致）；S-01、S-03 默认未启用
  instances = Object.values(STRATEGIES).map((s, i) => ({
    id: s.instance_id, strategy_id: uid(500 + i), strategy_version_id: s.version_id, status: s.key === 'demo_reversal' ? 'paused' : 'active',
    scope: 'account', account_id: ACCOUNT_ID, security_code: null, horizon: s.horizon,
  }));
}
resetStrategies();

const fail = (status: number, code: string, message: string, details: Record<string, unknown> | null = null) => json(errorBody(code, message, details), status);

export const strategyHandlers = [
  http.get(`${API}/strategies`, ({ request }) => {
    const url = new URL(request.url);
    const h = url.searchParams.get('horizon');
    return json(page(STRATEGY_TEMPLATES.filter((t) => !h || t.horizons.includes(h as Horizon)), url));
  }),
  http.get(`${API}/strategy-instances`, ({ request }) => json(page(instances.filter((x) => x.status !== 'archived'), new URL(request.url)))),
  http.post(`${API}/strategy-instances`, async ({ request }) => {
    const b = (await request.json()) as Partial<StrategyInstanceCreate>;
    const t = STRATEGY_TEMPLATES.find((x) => x.current_version.id === b.strategy_version_id);
    if (!t) return fail(404, 'NOT_FOUND', '策略版本不存在（示例数据）');
    if (!b.horizon || !(ENUMS.horizon as readonly string[]).includes(b.horizon)) {
      return fail(400, 'VALIDATION_ERROR', '参数校验失败', { fields: [{ field: 'horizon', issue: '取值不合法' }] });
    }
    if (!t.horizons.includes(b.horizon)) return fail(422, 'STRATEGY_HORIZON_MISMATCH', '模板不适用于该周期', { horizons: t.horizons });
    if (t.current_version.lifecycle === 'retired') return fail(422, 'STRATEGY_VERSION_NOT_RUNNABLE', '该版本已退役');
    // 请求里即便带了旧的确认字段（如 fit_ack）也忽略；高风险模板同样直接 201
    const warnings: string[] = [];
    const pref = state.profiles.get(currentUser()!.id)?.horizon_pref ?? [];
    if (pref.length && !pref.includes(b.horizon)) warnings.push(`你的画像偏好周期不含${HORIZON[b.horizon]}，周期分类可能判定不适合（示例）`);
    const inst: StrategyInstance = {
      id: uid(4500 + seq++), strategy_id: t.id, strategy_version_id: t.current_version.id, status: 'active',
      scope: b.scope ?? 'account', account_id: b.account_id ?? null, security_code: b.security_code ?? null, horizon: b.horizon,
    };
    instances.push(inst);
    return json({ id: inst.id, status: 'active', derived_strategy_version_id: null, warnings }, 201);
  }),
  http.post(`${API}/strategy-instances/:id/:op`, ({ params }) => {
    const x = instances.find((i) => i.id === params.id);
    if (!x) return fail(404, 'NOT_FOUND', '策略实例不存在（示例数据）');
    const to = { pause: 'paused', resume: 'active', archive: 'archived', confirm: 'active' }[String(params.op)] as StrategyInstance['status'] | undefined;
    if (!to) return fail(404, 'NOT_FOUND', '端点不存在');
    const ok = (params.op === 'pause' && x.status === 'active') || (params.op === 'resume' && x.status === 'paused')
      || (params.op === 'confirm' && x.status === 'proposed') || (params.op === 'archive' && x.status !== 'archived');
    if (!ok) return fail(409, 'INVALID_STATE_TRANSITION', `不能从 ${x.status} 变为 ${to}`, { from: x.status, to });
    x.status = to;
    return json(x);
  }),
];
