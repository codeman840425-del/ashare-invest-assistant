/**
 * 契约 v0.2.7 §7.3 `/today` 补充的示例数据：提醒、计划触发、数据缺口、顶层 evidence[]，以及风控事件（§7.5 /risk-controls/events）。
 * 全部为示例：标题与条件文字只陈述“发生了什么”，不含动作建议；只读，不下单。
 */
import type { DataGapScope, GapReason, Severity } from '../api/enums';
import type { Evidence, RiskFlag, TodayAlert, TodayDataGap, TodayPlanTrigger } from '../api/types';
import { NOW, SUGGESTIONS, TERMINAL_ROWS, TRADE_DATE, uid } from './fixtures';

const nameOf = (code: string) => TERMINAL_ROWS.find((r) => r.security_code === code)?.name ?? code;
const ev = (id: string, key: string, value: Evidence['value'], unit: string | null, at: string, provider: Evidence['provider'] = 'mairui'): Evidence => ({
  id, key, value, unit, provider, endpoint: null, data_as_of: at, fetched_at: at.replace(/:00\+/, ':20+'), epistemic_type: 'fact',
});

/** /today 顶层 evidence[]（id 在同一响应内唯一） */
export const TODAY_EVIDENCE: Evidence[] = [
  ev('TE1', 'price', '10.24', 'CNY', '2026-11-02T10:30:00+08:00'),
  ev('TE2', 'announcement_title', '示例银行业绩预告（示例）', null, '2026-11-01T19:30:00+08:00', 'exchange'),
  ev('TE3', 'position_pct', '21.5', '%', '2026-11-02T10:30:00+08:00', 'system'),
  ev('TE4', 'price', '23.18', 'CNY', '2026-11-02T10:29:00+08:00'),
  ev('TE5', 'price', '13.04', 'CNY', '2026-11-02T10:28:00+08:00'),
];

const SEV: Record<Severity, number> = { important: 3, attention: 2, info: 1 };
/** 提醒：status ∈ {new, read}，不含 origin=plan_condition；severity → triggered_at desc → id */
export function todayAlerts(): TodayAlert[] {
  const a = (n: number, x: Omit<TodayAlert, 'id' | 'rule_id'>): TodayAlert => ({ id: uid(7100 + n), rule_id: uid(7150 + n), ...x });
  return [
    a(1, {
      origin: 'holding_event', severity: 'attention', status: 'new', security_code: '600000.SH', name: nameOf('600000.SH'),
      title: '示例银行发布业绩预告（示例）', triggered_at: '2026-11-01T19:35:00+08:00', data_as_of: '2026-11-01T19:30:00+08:00',
      affected_plans: [{ plan_id: uid(7301), plan_version_no: 2, condition_id: null }], evidence_ids: ['TE2'],
    }),
    a(2, {
      origin: 'user_custom', severity: 'important', status: 'read', security_code: null, name: null,
      title: '账户仓位比例超过自定义上限 20%（示例）', triggered_at: '2026-11-02T10:30:00+08:00', data_as_of: '2026-11-02T10:30:00+08:00',
      affected_plans: [], evidence_ids: ['TE3'],
    }),
    a(3, {
      origin: 'user_custom', severity: 'info', status: 'new', security_code: '600000.SH', name: nameOf('600000.SH'),
      title: '示例银行价格到达自定义提醒价 10.20（示例）', triggered_at: '2026-11-02T10:30:00+08:00', data_as_of: '2026-11-02T10:30:00+08:00',
      affected_plans: [], evidence_ids: ['TE1'],
    }),
  ].sort((x, y) => SEV[y.severity] - SEV[x.severity] || y.triggered_at.localeCompare(x.triggered_at) || x.id.localeCompare(y.id));
}

/** 计划触发：invalidation 优先 → triggered_at desc → plan_id */
export function todayPlanTriggers(): TodayPlanTrigger[] {
  return ([
    {
      plan_id: uid(7301), plan_version_no: 2, security_code: '000001.SZ', name: nameOf('000001.SZ'), condition_id: uid(7311), condition_kind: 'trigger',
      condition_text: '价格回落到 23.20 以下（计划条件已满足）', triggered_at: '2026-11-02T10:29:00+08:00', alert_id: null, evidence_ids: ['TE4'],
    },
    {
      plan_id: uid(7302), plan_version_no: 1, security_code: '002001.SZ', name: nameOf('002001.SZ'), condition_id: uid(7312), condition_kind: 'invalidation',
      condition_text: '收盘价跌破 12.50 时该计划失效（失效条件已满足）', triggered_at: '2026-11-02T10:05:00+08:00', alert_id: uid(7199), evidence_ids: ['TE5'],
    },
  ] satisfies TodayPlanTrigger[]).sort((x, y) => (x.condition_kind === y.condition_kind ? 0 : x.condition_kind === 'invalidation' ? -1 : 1)
    || y.triggered_at.localeCompare(x.triggered_at) || x.plan_id.localeCompare(y.plan_id));
}

const GAP_ORDER: GapReason[] = ['data_licence_unavailable', 'user_input_missing', 'upstream_error', 'quota_deferred'];
/** 数据缺口：licenceOut=本人证书未设置或不可用时多一条 data_licence_unavailable；reason 顺序 → key */
export function todayDataGaps(licenceOut: boolean): TodayDataGap[] {
  const g = (key: string, reason: GapReason, scope: DataGapScope, x: Partial<TodayDataGap> & { message: string }): TodayDataGap => ({
    key, reason, scope, dataset: null, security_count: 0, securities: [], since: null, route: null, ...x,
  });
  const out: TodayDataGap[] = [
    g('user_input_missing:cash', 'user_input_missing', 'account', {
      message: '近 5 个交易日没有导入交割单，持仓与现金可能不是最新（示例）', since: '2026-10-27T15:00:00+08:00', route: '/portfolio/import',
    }),
    g('upstream_error:fund_flows', 'upstream_error', 'security', {
      dataset: 'fund_flows', message: '资金流数据源暂时出错，以下证券的资金流停在上一交易日（示例）', security_count: 2,
      securities: [{ security_code: '600000.SH', name: nameOf('600000.SH') }, { security_code: '000001.SZ', name: nameOf('000001.SZ') }],
      since: '2026-11-02T09:35:00+08:00',
    }),
    g('quota_deferred:factors', 'quota_deferred', 'market', {
      dataset: 'factors', message: '本时段数据配额已用完，因子截面顺延到下一时段更新（示例）', since: '2026-11-02T10:00:00+08:00',
    }),
  ];
  if (licenceOut) {
    out.push(g('data_licence_unavailable', 'data_licence_unavailable', 'user', {
      message: '你的数据证书不可用：行情与候选信号停在旧数据（示例）', since: NOW, route: '/settings/data-licence',
    }));
  }
  return out.sort((x, y) => GAP_ORDER.indexOf(x.reason) - GAP_ORDER.indexOf(y.reason) || x.key.localeCompare(y.key));
}

/** 风控事件（§7.5）：/today.risk_flags 的每一条都对应一条 active 事件，risk_event_id = 事件 id */
export interface MockRiskEvent extends RiskFlag {
  id: string; security_code: string | null; name: string | null; status: 'active' | 'cleared';
  triggered_at: string; cleared_at: string | null; suggestion_id: string | null; evidence: Evidence[];
}
export function riskEvents(): MockRiskEvent[] {
  const active = SUGGESTIONS.flatMap((sg) => sg.risk_flags.map((f) => ({ sg, f }))).map(({ sg, f }, i): MockRiskEvent => ({
    ...f, id: uid(7400 + i), security_code: sg.security_code, name: nameOf(sg.security_code), status: 'active',
    triggered_at: sg.created_at, cleared_at: null, suggestion_id: sg.id, evidence: sg.evidence.filter((e) => f.evidence_ids.includes(e.id)),
  }));
  const cleared: MockRiskEvent = {
    control: 'total_exposure', level: 'warning', message: '总仓位曾超过参考区间上限（示例，已解除）', gated_actions: ['add'], quantity_cap: null, evidence_ids: [],
    id: uid(7450), security_code: null, name: null, status: 'cleared', triggered_at: '2026-10-30T14:10:00+08:00', cleared_at: '2026-10-30T14:55:00+08:00',
    suggestion_id: null, evidence: [],
  };
  return [...active, cleared].sort((a, b) => b.triggered_at.localeCompare(a.triggered_at) || b.id.localeCompare(a.id));
}

/** m7：一条示例“今日失效”（“限制已解除”见 fixtures 的 released 原因），让首页这两块在示例数据下也有内容 */
export function todaySamples() {
  const sg = SUGGESTIONS.find((s) => s.security_code === '000001.SZ') ?? SUGGESTIONS[0];
  return {
    // T-F17：“限制已解除”改由 fixtures 中真实的 released 原因（002001.SZ 日内做T）提供，不再放悬空 signal_id 的样本
    released: [] as { reason_id: string; signal_id: string; code: 'DATA_STALE'; security_code: string; name: string; released_at: string }[],
    invalidations: sg ? [{
      suggestion_id: sg.id, security_code: sg.security_code, name: nameOf(sg.security_code), strategy_key: sg.strategies[0]?.strategy_key ?? 'demo_trend',
      text: '价格跌破 20 日均线，该条规则信号失效（示例）', at: `${TRADE_DATE}T10:20:00+08:00`,
    }] : [],
  };
}
