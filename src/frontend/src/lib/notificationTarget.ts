/**
 * Notification.target 跳转（契约 §5.1 v0.2.3，T-F14）：`route` 由服务端生成、前端直接跳转。
 * 前端只做两件事：
 * 1. 安全检查：只接受站内相对路径（safeInternalRoute：以单个 “/” 开头、不以 “//” 或 “/\\” 开头），防止通知把用户带到站外；
 * 2. 形状检查：路径须与 §5.1 为该 `type` 规定的路由一致；不一致（或 route 缺失）时按 §5.1 用 type + id 拼出路由，
 *    拼不出来（`strategy_version` 需要 strategy_id，target 里没有）就不跳转。
 * `type=none` 时 id、route 都为 null，不跳转。
 */
import type { NotificationTarget } from '../api/types';
import { safeInternalRoute } from '../pages/today/todayRoutes';

type T = NotificationTarget['type'];

/** §5.1 已定的路由形状 */
const SHAPES: Record<Exclude<T, 'none'>, RegExp> = {
  suggestion: /^\/suggestions\/[^/?#]+$/,
  candidate_signal: /^\/candidate-signals\/[^/?#]+$/,
  plan_draft: /^\/plan-drafts\/[^/?#]+$/,
  plan: /^\/plans\/[^/?#]+$/,
  daily_report: /^\/daily-reports\/\d{4}-\d{2}-\d{2}$/,
  import_batch: /^\/portfolio\/import\?batch=[^&#]+$/,
  reconciliation: /^\/portfolio\?tab=reconciliation&account_id=[^&#]+$/,
  strategy_version: /^\/strategies\/[^/?#]+\?version=[^&#]+$/,
};

const enc = encodeURIComponent;
/** 只靠 type + id 就能拼出的路由（strategy_version 还需要 strategy_id，拼不出） */
function build(type: Exclude<T, 'none'>, id: string): string | null {
  switch (type) {
    case 'suggestion': return `/suggestions/${enc(id)}`;
    case 'candidate_signal': return `/candidate-signals/${enc(id)}`;
    case 'plan_draft': return `/plan-drafts/${enc(id)}`;
    case 'plan': return `/plans/${enc(id)}`;
    case 'daily_report': return /^\d{4}-\d{2}-\d{2}$/.test(id) ? `/daily-reports/${id}` : null;
    case 'import_batch': return `/portfolio/import?batch=${enc(id)}`;
    case 'reconciliation': return `/portfolio?tab=reconciliation&account_id=${enc(id)}`;
    case 'strategy_version': return null;
  }
}

export function notificationRoute(t: NotificationTarget): string | null {
  if (t.type === 'none') return null;
  const shape = SHAPES[t.type];
  if (!shape) return null;
  const r = safeInternalRoute(t.route);
  if (r && shape.test(r)) return r;
  return t.id ? build(t.type, t.id) : null;
}
