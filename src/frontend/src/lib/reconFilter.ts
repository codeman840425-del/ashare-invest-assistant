/** T-F25：对账页地址栏筛选解析（契约 v0.2.9 内 T-A04 #33 ④） */
import type { ReconFilter } from '../api/adminQueries';
import { ENUMS, type SecurityReconciliationKind, type SecurityReconciliationSource } from '../api/enums';

const STATUSES = ['open', 'resolved', 'all'] as const;
const KINDS = ENUMS.security_reconciliation_kind;
const SOURCES = ENUMS.security_reconciliation_source;

/**
 * 地址栏 ?status=&kind=&source= → 筛选。前端不认识的值不发给服务端（服务端对非法值返回 400），
 * 而是丢弃并在页面上说明，避免整页报错。
 */
export function parseReconFilter(sp: URLSearchParams): { filter: ReconFilter; ignored: string[] } {
  const ignored: string[] = [];
  const st = sp.get('status');
  let status: ReconFilter['status'] = 'open';
  if (st !== null && st !== '') {
    if ((STATUSES as readonly string[]).includes(st)) status = st as ReconFilter['status'];
    else ignored.push(`status=${st}`);
  }
  const kinds: SecurityReconciliationKind[] = [];
  for (const k of (sp.get('kind') ?? '').split(',').map((x) => x.trim()).filter(Boolean)) {
    if ((KINDS as readonly string[]).includes(k)) {
      if (!kinds.includes(k as SecurityReconciliationKind)) kinds.push(k as SecurityReconciliationKind);
    } else ignored.push(`kind=${k}`);
  }
  const src = sp.get('source');
  let source: SecurityReconciliationSource | null = null;
  if (src !== null && src !== '') {
    if ((SOURCES as readonly string[]).includes(src)) source = src as SecurityReconciliationSource;
    else ignored.push(`source=${src}`);
  }
  return { filter: { status, kinds, source }, ignored };
}

