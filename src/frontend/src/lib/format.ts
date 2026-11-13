import type { DimensionCell, Evidence } from '../api/types';
import { PROVIDER } from '../i18n/labels';
/** 契约时间均为 +08:00；界面统一按北京时间显示。Z 或其他偏移换算到 Asia/Shanghai；+08:00 输出与旧实现逐字节不变。 */
/**
 * F-13：`t` 为 null/undefined 时返回空串，**不抛错**。
 * 空数据场景（契约 T-A53）`data_as_of` 为 null 是合法的；此前直接调 `.endsWith` 会让整页
 * 崩成 ErrorBoundary（市场页实测），这属于白屏级缺陷，不能等类型可空化才修。
 * 调用方仍应自行决定 null 时显示什么文案（本函数只保证不崩）。
 */
export const fmtTime = (t: string | null | undefined) => {
  if (t === null || t === undefined || t === '') return '';
  if (t.endsWith('+08:00') || !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(t)) {
    return t.replace('T', ' ').replace(/\+08:00$/, '').replace(/:00$/, '');
  }
  const date = new Date(t);
  if (Number.isNaN(date.getTime())) return t;
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date);
  const g = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  if (!g('year') || !g('month') || !g('day') || !g('hour') || !g('minute') || !g('second')) return t;
  const base = `${g('year')}-${g('month')}-${g('day')} ${g('hour')}:${g('minute')}`;
  return g('second') === '00' ? base : `${base}:${g('second')}`;
};
export const fmtNum = (v: string | number | null | undefined, digits = 2) =>
  v === null || v === undefined || v === '' || Number.isNaN(Number(v))
    ? '—'
    : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
export const pctClass = (v: string | number | null | undefined) =>
  v === null || v === undefined ? 'flat' : Number(v) > 0 ? 'up' : Number(v) < 0 ? 'down' : 'flat';
export const signed = (v: string | number | null | undefined, digits = 2) =>
  v === null || v === undefined ? '—' : (Number(v) > 0 ? '+' : '') + fmtNum(v, digits);
/** 金额简写：≥1 亿 → 亿，≥1 万 → 万 */
export const fmtAmount = (v: string | number | null | undefined) => {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`;
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(1)}万`;
  return n.toFixed(0);
};
/** 北京时间 → lightweight-charts 的 UTCTimestamp（把北京时间当作 UTC 显示，避免浏览器时区影响） */
export const bjToChartTime = (t: string) => {
  const m = t.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}(?::\d{2})?)/);
  return m ? Math.floor(Date.parse(`${m[1]}T${m[2].length === 5 ? m[2] + ':00' : m[2]}Z`) / 1000) : 0;
};

/** 证据来源：数据源 + 接口路径 */
export const providerText = (e: Evidence) =>
  `${(PROVIDER as Record<string, string | undefined>)[e.provider] ?? e.provider}${e.endpoint ? ' ' + e.endpoint : ''}`;

/** 维度单元格规则计数：入场类 “规则 x/y”；纯离场策略（rules_total = 0）显示 “离场 x/y”（v0.2.3 #20） */
export const ruleCountText = (c: Pick<DimensionCell, 'rules_passed' | 'rules_total' | 'exit_hits' | 'exit_total'>) =>
  c.rules_total ? `规则 ${c.rules_passed}/${c.rules_total}` : c.exit_total ? `离场 ${c.exit_hits}/${c.exit_total}` : '规则 —';
