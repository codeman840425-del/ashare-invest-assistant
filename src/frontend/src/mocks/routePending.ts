/**
 * 示例场景（T-F20）：后端还没注册的路由。响应按后端实际行为复刻：
 * src/backend/app/common/errors.py 把未注册路由的 Starlette 404 转成 `404 NOT_FOUND` 信封（message “资源不存在”），
 * 与资源不存在的响应体相同；另提供 FastAPI 默认 {"detail":"Not Found"} 的变体。
 */
import { http, HttpResponse } from 'msw';
import { API_BASE } from '../api/client';
import { ROUTE_PENDING_PATHS } from '../api/errorPolicy';

export function routePendingHandlers(paths: readonly string[] = ROUTE_PENDING_PATHS, shape: 'envelope' | 'fastapi' = 'envelope') {
  return paths.map((p) =>
    http.all(`*${API_BASE}${p}`, () =>
      shape === 'fastapi'
        ? HttpResponse.json({ detail: 'Not Found' }, { status: 404 })
        : HttpResponse.json({ error: { code: 'NOT_FOUND', message: '资源不存在', details: null, request_id: 'req-示例-route' } }, { status: 404 })),
  );
}
