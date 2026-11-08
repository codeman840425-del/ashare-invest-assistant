/**
 * 策略库模拟（契约 v0.2.7 §5.1 StrategyInstance、§6.0A 状态机、§7.4 /strategies、§7.5 /strategy-instances）。名称均为示例。
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
  { id: uid(512), key: 'demo_gate_draft', name: '门禁草稿（示例数据）', horizons: ['swing'], current_version: { id: uid(322), version_no: 1, lifecycle: 'draft' }, health: null, risk_level: 'normal' },
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
const T0 = '2026-10-20T09:00:00+08:00';

/** 按模板补齐 v0.2.7 StrategyInstance 的完整字段（示例） */
function fullInstance(x: Pick<StrategyInstance, 'id' | 'strategy_version_id' | 'status' | 'horizon'> & Partial<StrategyInstance>): StrategyInstance {
  const t = STRATEGY_TEMPLATES.find((v) => v.current_version.id === x.strategy_version_id || v.id === x.strategy_id) ?? STRATEGY_TEMPLATES[0];
  const at = x.created_at ?? T0;
  return {
    strategy_id: t.id, strategy_key: t.key, strategy_name: t.name, version_no: t.current_version.version_no, lifecycle: t.current_version.lifecycle,
    derived_strategy_version_id: null, risk_level: t.risk_level, origin: 'user', scope: 'account', account_id: ACCOUNT_ID, security_code: null, name: null,
    param_overrides: null, budget_amount: null, auto_downweight: true, paused_by: x.status === 'paused' ? 'user' : null, pause_reason_code: null, paused_until: null,
    created_at: at, confirmed_at: x.status === 'proposed' ? null : at, updated_at: at, archived_at: null,
    ...x,
  };
}

export function resetStrategies() {
  seq = 0;
  // 4 个示例模板已有实例（与 fixtures 的 instance_id 一致）；S-01、S-03 默认未启用
  instances = Object.values(STRATEGIES).map((s, i) => fullInstance({
    id: s.instance_id, strategy_id: uid(500 + i), strategy_version_id: s.version_id, status: s.key === 'demo_reversal' ? 'paused' : 'active',
    horizon: s.horizon, created_at: `2026-10-${String(20 + i).padStart(2, '0')}T09:00:00+08:00`,
  }));
}
resetStrategies();

/** 测试辅助：插入一个示例实例（如 proposed、origin=system），缺省字段按模板补齐；resetMockState 时清除 */
export function mockAddInstance(x: Parameters<typeof fullInstance>[0]) {
  instances.push(fullInstance(x));
}

const fail = (status: number, code: string, message: string, details: Record<string, unknown> | null = null) => json(errorBody(code, message, details), status);

/** §6.0A 状态机：允许的目标状态 */
const ALLOWED: Record<StrategyInstance['status'], StrategyInstance['status'][]> = {
  proposed: ['active', 'archived'], active: ['paused', 'archived'], paused: ['active', 'archived'], archived: [],
};
const OP_TO: Record<string, StrategyInstance['status']> = { confirm: 'active', pause: 'paused', resume: 'active', archive: 'archived' };
/** 操作的合法起点（confirm 只能从 proposed，resume 只能从 paused） */
const OP_FROM: Record<string, StrategyInstance['status'][]> = {
  confirm: ['proposed'], pause: ['active'], resume: ['paused'], archive: ['proposed', 'active', 'paused'],
};
const RUNNABLE = ['published', 'observing'];
const SORTS: Record<string, (a: StrategyInstance, b: StrategyInstance) => number> = {
  created_at_desc: (a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id),
  updated_at_desc: (a, b) => b.updated_at.localeCompare(a.updated_at) || b.id.localeCompare(a.id),
  strategy_name_asc: (a, b) => a.strategy_name.localeCompare(b.strategy_name, 'zh') || a.id.localeCompare(b.id),
};
const multi = (url: URL, k: string) => (url.searchParams.get(k) ?? '').split(',').filter(Boolean);

/** 跟踪统计（示例）：按模板给不同样本量，覆盖 n ≥ 30、5 ≤ n < 30（样本少）、n < 5（value=null）三档 */
const TRACK_N: Record<string, number> = { demo_trend: 64, demo_value: 26, demo_t: 4, demo_reversal: 12 };
function stat(v: number, n: number, window: string) {
  return { value: n < 5 ? null : v.toFixed(4), n, window, small_sample: n < 30 };
}
export function trackingOf(t: StrategyTemplate, scope: 'mine' | 'site') {
  const base = (TRACK_N[t.key] ?? (t.health?.n ?? 0)) * (scope === 'site' ? 3 : 1);
  return {
    scope,
    by_horizon: ([1, 5, 20] as const).map((d, i) => {
      const n = Math.max(0, Math.round(base / (1 + i * 0.6)));
      const w = `${d}d`;
      return {
        horizon_days: d, win_rate: stat(0.52 + i * 0.02, n, w), avg_return_pct: stat(0.004 * (i + 1), n, w),
        avg_excess_pct: stat(0.001 * (i + 1), n, w), profit_loss_ratio: stat(1.2 + i * 0.1, n, w), max_loss_streak: 2 + i,
      };
    }),
  };
}

export const strategyHandlers = [
  http.get(`${API}/strategies/:id/versions/:vid/tracking`, ({ params, request }) => {
    const t = STRATEGY_TEMPLATES.find((x) => x.id === params.id);
    if (!t) return json(errorBody('NOT_FOUND', '策略模板不存在（示例数据）'), 404);
    // v0.2.9 #10：scope 默认 mine，只收 mine|site，其他 → 400
    const raw = new URL(request.url).searchParams.get('scope');
    if (raw !== null && raw !== 'mine' && raw !== 'site') return json(errorBody('VALIDATION_ERROR', 'scope 取值 mine|site', { fields: [{ field: 'scope', issue: 'scope 取值 mine|site' }] }), 400);
    const scope = raw === 'site' ? 'site' : 'mine';
    return json(trackingOf(t, scope));
  }),
  http.get(`${API}/strategies`, ({ request }) => {
    const url = new URL(request.url);
    const h = url.searchParams.get('horizon');
    const risk = url.searchParams.get('risk_level');
    return json(page(STRATEGY_TEMPLATES.filter((t) => (!h || t.horizons.includes(h as Horizon)) && (!risk || t.risk_level === risk)), url));
  }),
  // v0.2.7 §7.5：多值 status（默认不含 archived）、筛选、排序、游标分页；游标与筛选/排序不一致 → 400 INVALID_CURSOR
  http.get(`${API}/strategy-instances`, ({ request }) => {
    const url = new URL(request.url);
    const status = multi(url, 'status');
    const st = status.length ? status : ['proposed', 'active', 'paused'];
    if (st.some((v) => !(ENUMS.instance_status as readonly string[]).includes(v))) return fail(400, 'VALIDATION_ERROR', '参数校验失败', { fields: [{ field: 'status', issue: '取值不合法' }] });
    const order = url.searchParams.get('order') ?? 'created_at_desc';
    if (!SORTS[order]) return fail(400, 'VALIDATION_ERROR', '参数校验失败', { fields: [{ field: 'order', issue: '取值见 instance_sort' }] });
    const eq = (k: 'strategy_id' | 'strategy_version_id' | 'horizon' | 'scope' | 'account_id' | 'security_code' | 'origin' | 'risk_level') => {
      const v = url.searchParams.get(k);
      return (x: StrategyInstance) => !v || x[k] === v;
    };
    const filters = (['strategy_id', 'strategy_version_id', 'horizon', 'scope', 'account_id', 'security_code', 'origin', 'risk_level'] as const).map(eq);
    // 示例游标：`{签名}:{偏移}`，签名 = 筛选与排序参数
    const sig = [...url.searchParams.entries()].filter(([k]) => k !== 'cursor' && k !== 'limit').sort().map(([k, v]) => `${k}=${v}`).join('&');
    const cursor = url.searchParams.get('cursor');
    let offset = 0;
    if (cursor) {
      const i = cursor.lastIndexOf(':');
      if (i < 0 || cursor.slice(0, i) !== sig) return fail(400, 'INVALID_CURSOR', '游标与本次的筛选或排序不一致');
      offset = Number(cursor.slice(i + 1)) || 0;
    }
    const items = instances.filter((x) => st.includes(x.status) && filters.every((f) => f(x))).sort(SORTS[order]);
    const pu = new URL(url);
    pu.searchParams.set('cursor', String(offset));
    const pg = page(items, pu);
    return json({ ...pg, next_cursor: pg.next_cursor === null ? null : `${sig}:${pg.next_cursor}` });
  }),
  http.post(`${API}/strategy-instances`, async ({ request }) => {
    const b = (await request.json()) as Partial<StrategyInstanceCreate>;
    const t = STRATEGY_TEMPLATES.find((x) => x.current_version.id === b.strategy_version_id);
    if (!t) return fail(404, 'NOT_FOUND', '策略版本不存在（示例数据）');
    if (!b.horizon || !(ENUMS.horizon as readonly string[]).includes(b.horizon)) {
      return fail(400, 'VALIDATION_ERROR', '参数校验失败', { fields: [{ field: 'horizon', issue: '取值不合法' }] });
    }
    // 契约 §4：409 {lifecycle}，只有 published / observing 可运行（评审 T-F22a m8）
    if (!RUNNABLE.includes(t.current_version.lifecycle)) {
      return fail(409, 'STRATEGY_VERSION_NOT_RUNNABLE', '该版本暂不可运行（示例）', { lifecycle: t.current_version.lifecycle });
    }
    if (!t.horizons.includes(b.horizon)) return fail(422, 'STRATEGY_HORIZON_MISMATCH', '模板不适用于该周期', { strategy_key: t.key, horizons: t.horizons });
    // 请求里即便带了旧的确认字段（如 fit_ack）也忽略；高风险模板同样直接 201
    const warnings: string[] = [];
    const pref = state.profiles.get(currentUser()!.id)?.horizon_pref ?? [];
    if (pref.length && !pref.includes(b.horizon)) warnings.push(`你的画像偏好周期不含${HORIZON[b.horizon]}，周期分类可能判定不适合（示例）`);
    const now = new Date().toISOString();
    // v0.2.7：用户创建的实例 origin=user，直接 active
    const inst = fullInstance({
      id: uid(4500 + seq++), strategy_id: t.id, strategy_version_id: t.current_version.id, status: 'active', origin: 'user',
      scope: b.scope ?? 'account', account_id: b.account_id ?? null, security_code: b.security_code ?? null, horizon: b.horizon,
      param_overrides: b.param_overrides ?? null, budget_amount: b.budget_amount ?? null, created_at: now, updated_at: now,
    });
    instances.push(inst);
    return json({ id: inst.id, status: 'active', derived_strategy_version_id: null, warnings }, 201);
  }),
  // v0.2.7 §6.0A：已在目标状态 → 200 幂等；非法转换 → 409 {from, to, allowed}；system 实例不可归档；
  // confirm/resume 到不可运行的版本 → 409 STRATEGY_VERSION_NOT_RUNNABLE{lifecycle}；成功 200 返回完整对象
  http.post(`${API}/strategy-instances/:id/:op`, ({ params }) => {
    const x = instances.find((i) => i.id === params.id);
    if (!x) return fail(404, 'NOT_FOUND', '策略实例不存在（示例数据）');
    const op = String(params.op);
    const to = OP_TO[op];
    if (!to) return fail(404, 'NOT_FOUND', '端点不存在');
    if (x.status === to) return json(x);
    if (!OP_FROM[op].includes(x.status) || !ALLOWED[x.status].includes(to)) {
      return fail(409, 'INVALID_STATE_TRANSITION', `不能从 ${x.status} 变为 ${to}`, { from: x.status, to, allowed: ALLOWED[x.status] });
    }
    if (op === 'archive' && x.origin === 'system') {
      return fail(409, 'INVALID_STATE_TRANSITION', '系统内置实例不能归档', { from: x.status, to, allowed: ALLOWED[x.status].filter((s) => s !== 'archived') });
    }
    if ((op === 'confirm' || op === 'resume') && !RUNNABLE.includes(x.lifecycle)) {
      return fail(409, 'STRATEGY_VERSION_NOT_RUNNABLE', '该版本暂不可运行（示例）', { lifecycle: x.lifecycle });
    }
    const now = new Date().toISOString();
    Object.assign(x, {
      status: to, updated_at: now,
      ...(op === 'confirm' ? { confirmed_at: now } : {}),
      ...(op === 'pause' ? { paused_by: 'user' } : {}),
      ...(op === 'resume' ? { paused_by: null, pause_reason_code: null, paused_until: null } : {}),
      ...(op === 'archive' ? { archived_at: now } : {}),
    });
    return json(x);
  }),
];
