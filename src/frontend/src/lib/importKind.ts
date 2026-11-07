import type { ImportBatch, ImportKind } from '../api/accountTypes';
import { PARSERS } from '../i18n/importLabels';

/** T-F20（T-B66）：解析器 id 前缀 tdx_{kind}（后端 options 以此判 kind_mismatch） */
export const parserKind = (id: string): ImportKind | null => (id.startsWith('tdx_trades') ? 'trades' : id.startsWith('tdx_positions') ? 'positions' : null);
export const parsersFor = (kind: ImportKind) => PARSERS.filter((p) => parserKind(p.id) === kind);
/**
 * IMPORT_UNRECOGNIZED_FORMAT 的候选解析器（后端 preview.py：params.candidate_ids 数组；契约模板 params.candidates 为“、”拼接文本）。
 * 候选里只有另一种类型的解析器时返回那个类型，用于提示按正确类型重新上传（不能在本批次里跨类型改解析器）。
 */
export function otherKindHint(b: Pick<ImportBatch, 'kind' | 'file_findings'>): ImportKind | null {
  const f = b.file_findings.find((x) => x.code === 'IMPORT_UNRECOGNIZED_FORMAT');
  if (!f) return null;
  const p = (f.params ?? {}) as { candidate_ids?: unknown; candidates?: unknown };
  const ids = Array.isArray(p.candidate_ids) ? p.candidate_ids.map(String)
    : typeof p.candidates === 'string' ? p.candidates.split(/[、,，\s]+/).filter(Boolean) : [];
  const kinds = [...new Set(ids.map(parserKind).filter((k): k is ImportKind => k !== null))];
  return kinds.length === 1 && kinds[0] !== b.kind ? kinds[0] : null;
}
