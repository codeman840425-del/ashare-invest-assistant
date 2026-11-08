import type { ExplanationFallbackReason, Role } from '../api/enums';
export const EXPLANATION_FALLBACK_TEXT: Record<ExplanationFallbackReason, string> = {
  not_enabled: '未启用或未配置路由（未调用）',
  budget_exceeded: '预算超限',
  timeout: '模型调用超时',
  provider_error: '上游服务失败',
  validation_failed: '解释守卫验证拒绝',
};
export function explanationFallbackText(reason: string): string {
  return Object.hasOwn(EXPLANATION_FALLBACK_TEXT, reason) ? EXPLANATION_FALLBACK_TEXT[reason as ExplanationFallbackReason] : reason;
}
/** T-A36：目前尚无此前端页面；页面落地并注册路由后才可改为true。 */
export function hasAdminLlmUsagePage(): boolean { return false; }
export function adminLlmUsageHref(role: Role | undefined, callId: string | null, pageAvailable: boolean): string | null {
  return role === 'admin' && callId && pageAvailable ? `/admin/llm/usage?call_id=${encodeURIComponent(callId)}` : null;
}
