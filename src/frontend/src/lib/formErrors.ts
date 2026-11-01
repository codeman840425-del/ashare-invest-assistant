import type { FormInstance } from 'antd';
import { ApiError } from '../api/client';

/** 契约 §4：400 VALIDATION_ERROR 的 details.fields 映射到表单项；返回未能映射的问题（显示在表单顶部） */
export function applyFieldErrors(form: FormInstance, e: unknown, known: readonly string[]): string[] {
  if (!(e instanceof ApiError) || e.code !== 'VALIDATION_ERROR') return [];
  const fields = ((e.details as { fields?: { field: string; issue: string }[] } | null)?.fields ?? []);
  const rest: string[] = [];
  const mapped = fields.filter((f) => known.includes(f.field) || (rest.push(`${f.field}：${f.issue}`), false));
  form.setFields(mapped.map((f) => ({ name: f.field, errors: [f.issue] })));
  return rest;
}
