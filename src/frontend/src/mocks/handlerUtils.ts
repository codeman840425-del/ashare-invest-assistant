import { HttpResponse } from 'msw';
import type { ApiErrorBody, Paged } from '../api/types';

let reqSeq = 0;
/** 契约 §2 错误信封 */
export function errorBody(code: string, message: string, details: Record<string, unknown> | null = null): ApiErrorBody {
  reqSeq += 1;
  return { error: { code, message, details, request_id: `mock-${String(reqSeq).padStart(6, '0')}` } };
}

export const notFound = (what: string) => HttpResponse.json(errorBody('NOT_FOUND', `${what} 不存在（示例数据）`), { status: 404 });
/** 契约 §4：400 VALIDATION_ERROR，details = {fields:[{field, issue}]} */
export const validation = (field: string, issue: string) =>
  HttpResponse.json(errorBody('VALIDATION_ERROR', issue, { fields: [{ field, issue }] }), { status: 400 });

/** 契约 §1.2 游标分页（示例实现：cursor 即偏移量） */
export function page<T>(items: T[], url: URL): Paged<T> {
  const limit = Math.min(Math.max(Number(url.searchParams.get('limit') ?? 50) || 50, 1), 200);
  const start = Number(url.searchParams.get('cursor') ?? 0) || 0;
  const slice = items.slice(start, start + limit);
  return { items: slice, next_cursor: start + limit < items.length ? String(start + limit) : null };
}

/** 弱 ETag（契约 §7.3 `/terminal`、`/today`）：内容哈希；If-None-Match 命中返回 304 空体 */
export function weakEtag(body: unknown): string {
  const text = JSON.stringify(body);
  let h = 5381;
  for (let i = 0; i < text.length; i++) h = ((h << 5) + h + text.charCodeAt(i)) | 0;
  return `W/"${(h >>> 0).toString(16)}"`;
}
export function jsonWithEtag(request: Request, body: unknown) {
  const etag = weakEtag(body);
  const inm = request.headers.get('If-None-Match');
  if (inm && inm.split(',').map((x) => x.trim()).includes(etag)) return new HttpResponse(null, { status: 304, headers: { ETag: etag } });
  return HttpResponse.json(body as Record<string, unknown>, { headers: { ETag: etag } });
}
