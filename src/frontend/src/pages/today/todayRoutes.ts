/** T-F08 今日关注：路由相关的常量与校验（单独成文件，供页面与测试共用） */

/** 契约 v0.2.7 §7.3“查看全部”去向表（逐字照抄前端路由列） */
export const MORE_ROUTE = {
  focus: '/terminal',
  pending_plan_drafts: '/plan-drafts?status=pending,stale',
  released_reasons: '/candidate-signals?tab=released',
  risk_flags: '/risk-controls?tab=events',
  invalidations_today: '/suggestions?status=invalidated',
  alerts: '/alerts',
  plan_triggers: '/plans?status=triggered',
  data_gaps: null,
} as const;

export type TodayListKey = keyof typeof MORE_ROUTE;

/**
 * data_gaps[].route 白名单：只接受以单个 `/` 开头的站内路径；拒绝 `//host`、`/\host`、`http:`、`javascript:`、空白与控制字符。
 * 不合规的 route 不渲染链接（当作 null）。
 */
export function safeInternalRoute(route: string | null | undefined): string | null {
  if (typeof route !== 'string') return null;
  return /^\/(?![/\\])[A-Za-z0-9\-._~!$&'()*+,;=:@%/?#]*$/.test(route) ? route : null;
}
