/** 只提供完全合成的示例数据，不表示真实门禁/真实审批。 */
import { http, HttpResponse } from 'msw';
import { EXAMPLE_PROMOTION_REPORT } from './promotionFixtures';
import { currentUser } from './session';
import { errorBody } from './handlerUtils';
import { uid } from './fixtures';
const API = '/api/v1';
export const DEMO_REVIEW_ID = uid(940);
let decision = EXAMPLE_PROMOTION_REPORT.decision;
export function resetPromotions() { decision = 'pending'; }
const denied = () => HttpResponse.json(errorBody('FORBIDDEN', '无审批权限'), { status: 403 });
const missing = () => HttpResponse.json(errorBody('NOT_FOUND', '未找到审核记录'), { status: 404 });
export const promotionHandlers = [
  http.get(`${API}/promotion-requests/:id`, ({ params }) => params.id !== DEMO_REVIEW_ID ? missing() : HttpResponse.json({ ...EXAMPLE_PROMOTION_REPORT, decision })),
  http.post(`${API}/admin/promotions/:id/decision`, async ({ params, request }) => {
    if (currentUser()?.role !== 'admin') return denied();
    if (params.id !== DEMO_REVIEW_ID) return missing();
    const b = await request.json() as { decision: string; comment: string };
    if (b.decision !== 'approved' || !b.comment?.trim()) return HttpResponse.json(errorBody('VALIDATION_ERROR', '请填写审核意见'), { status: 400 });
    decision = 'approved';
    return HttpResponse.json({ decision });
  }),
  http.post(`${API}/admin/strategies/:id/versions/:vid/lifecycle`, async () => {
    if (currentUser()?.role !== 'admin') return denied();
    // 示例无真实门禁关联：不得伪造晋级成功。
    return HttpResponse.json(errorBody('PROMOTION_GATES_NOT_MET', '示例数据未绑定真实晋级门禁', { gates: ['G7'] }), { status: 422 });
  }),
];
