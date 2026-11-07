/**
 * T-F25：GET /admin/securities/reconciliation 的示例数据与处理（契约 v0.2.9 内 T-A04 #33 ④，§7.9）。
 * 全部为虚构示例：609999.SH 是虚构代码（vendor_unknown 隔离区示例，T-F26 搜索不到它）；
 * 830001.BJ 的 quote_missing 属于 demo_user 的证书（T-F26 用它演示 quote_missing=true）。
 * 不含证书值、行情数值或快照内容；quote_conflict 只有代码与天数。管理员校验由 accountHandlers 的前置处理统一做（非管理员 404）。
 */
import { http, HttpResponse } from 'msw';
import type { SecurityReconciliationDiff } from '../api/adminTypes';
import { ENUMS } from '../api/enums';
import { uid } from './fixtures';
import { page, validation } from './handlerUtils';

const API = '/api/v1';
const DEMO = { user_id: uid(2), username: 'demo_user' };
const ADMIN = { user_id: uid(3), username: 'admin' };

const row = (n: number, r: Omit<SecurityReconciliationDiff, 'id' | 'field' | 'master_value' | 'source_value' | 'resolved_on' | 'status'> & Partial<SecurityReconciliationDiff>): SecurityReconciliationDiff => ({
  id: uid(31000 + n), field: null, master_value: null, source_value: null, status: 'open', resolved_on: null, ...r,
});

/** 隔离区示例代码（vendor_unknown，open） */
export const VENDOR_UNKNOWN_CODE = '609999.SH';

export const RECON_FIXTURES: SecurityReconciliationDiff[] = [
  row(1, { kind: 'vendor_unknown', source: 'mairui_lists', security_code: VENDOR_UNKNOWN_CODE, name: null, source_name: '示例未知', licence_owner: DEMO, first_seen_on: '2026-10-28', last_seen_on: '2026-10-30', seen_days: 3 }),
  row(2, { kind: 'quote_missing', source: 'mairui_lists', security_code: '830001.BJ', name: '演示精工', source_name: null, licence_owner: DEMO, first_seen_on: '2026-10-29', last_seen_on: '2026-10-30', seen_days: 2 }),
  row(3, { kind: 'vendor_stale_listed', source: 'mairui_lists', security_code: '600003.SH', name: '示例终止', source_name: '示例终止', licence_owner: ADMIN, first_seen_on: '2026-10-22', last_seen_on: '2026-10-30', seen_days: 7 }),
  row(4, { kind: 'quote_conflict', source: 'mairui_real_all', security_code: '600000.SH', name: '示例银行', source_name: null, licence_owner: ADMIN, first_seen_on: '2026-10-29', last_seen_on: '2026-10-30', seen_days: 2 }),
  row(5, { kind: 'field_mismatch', source: 'cninfo', security_code: '300001.SZ', name: '演示电子', source_name: '演示电子', licence_owner: null, field: 'list_date', master_value: '2010-01-08', source_value: '2010-01-18', first_seen_on: '2026-10-24', last_seen_on: '2026-10-24', seen_days: 1 }),
  row(6, { kind: 'field_mismatch', source: 'akshare', security_code: '600000.SH', name: '示例银行', source_name: '示例发展', licence_owner: null, field: 'name', master_value: '示例银行', source_value: '示例发展', first_seen_on: '2026-10-24', last_seen_on: '2026-10-24', seen_days: 1 }),
  row(7, { kind: 'quote_missing', source: 'mairui_lists', security_code: '688001.SH', name: '演示芯片', source_name: null, licence_owner: DEMO, first_seen_on: '2026-10-26', last_seen_on: '2026-10-27', seen_days: 2, status: 'resolved', resolved_on: '2026-10-28' }),
];

/** §7.9：last_seen_on desc, id desc */
const sorted = () => [...RECON_FIXTURES].sort((a, b) => b.last_seen_on.localeCompare(a.last_seen_on) || b.id.localeCompare(a.id));

/** 本人证书（user_id）有未关闭的 quote_missing 的代码（T-F26 的 SecurityHit.quote_missing 用） */
export const openQuoteMissingFor = (userId: string) =>
  new Set(RECON_FIXTURES.filter((r) => r.kind === 'quote_missing' && r.status === 'open' && r.licence_owner?.user_id === userId).map((r) => r.security_code));
/** 隔离区：未关闭的 vendor_unknown 代码（搜索与 /securities/{code} 都看不到） */
export const quarantinedCodes = () => new Set(RECON_FIXTURES.filter((r) => r.kind === 'vendor_unknown' && r.status === 'open').map((r) => r.security_code));

export const reconHandlers = [
  http.get(`${API}/admin/securities/reconciliation`, ({ request }) => {
    const url = new URL(request.url);
    const status = url.searchParams.get('status') ?? 'open';
    if (!['open', 'resolved', 'all'].includes(status)) return validation('status', 'status 取值 open|resolved|all');
    const kinds = (url.searchParams.get('kind') ?? '').split(',').filter(Boolean);
    if (kinds.some((k) => !(ENUMS.security_reconciliation_kind as readonly string[]).includes(k))) return validation('kind', 'kind 取值见 security_reconciliation_kind');
    const source = url.searchParams.get('source');
    if (source !== null && !(ENUMS.security_reconciliation_source as readonly string[]).includes(source)) return validation('source', 'source 取值见 security_reconciliation_source');
    const items = sorted().filter((r) => (status === 'all' || r.status === status) && (!kinds.length || kinds.includes(r.kind)) && (!source || r.source === source));
    return HttpResponse.json(page(items, url));
  }),
];
