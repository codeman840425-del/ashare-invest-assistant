/**
 * T-F36：t_view 的纯函数（契约 docs/contracts/intraday-bars.md §3.2、§3.3、§3.5，docs/T-A143=362ad41）。
 * 时间一律换算到 Asia/Shanghai（Intl 显式 timeZone），与浏览器/机器时区无关。
 */
import type { TView } from '../../api/types';
import { fmtNum } from '../../lib/format';

export const T_VIEW_UNAVAILABLE = '分时数据暂不可用。';

type Num = string | number | null | undefined;
export const isNum = (v: Num): v is string | number => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v));

/** 十进制精确比较 |a| 与 b（都按十进制字符串比较，避免浮点边界误判）；返回 a 的绝对值是否 ≥ b */
export function absAtLeast(a: string | number, b: string | number): boolean {
  const norm = (v: string | number) => {
    const s = typeof v === 'number' ? v.toString() : v.trim();
    const m = s.match(/^([+-])?(\d*)(?:\.(\d*))?$/);
    return m && (m[2] || m[3]) ? { int: m[2] || '0', frac: m[3] ?? '' } : null;
  };
  const x = norm(a);
  const y = norm(b);
  if (!x || !y) return Math.abs(Number(a)) >= Number(b);
  const n = Math.max(x.frac.length, y.frac.length);
  const big = (v: { int: string; frac: string }) => BigInt(v.int + v.frac.padEnd(n, '0'));
  return big(x) >= big(y);
}

/** 北京时间 YYYY-MM-DD HH:mm；无法解析返回 null */
export function fmtShanghai(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(d);
  const g = (t: string) => parts.find((p) => p.type === t)?.value ?? '';
  return `${g('year')}-${g('month')}-${g('day')} ${g('hour')}:${g('minute')}`;
}

/** 今日可用底仓：取 sellable_qty，且不超过昨日底仓 base_qty、不小于 0（契约 §3.2）；缺数为 null */
export function availableBase(v: Pick<TView, 'base_qty' | 'sellable_qty'>): number | null {
  if (!isNum(v.sellable_qty)) return null;
  const s = Math.max(0, Number(v.sellable_qty));
  return isNum(v.base_qty) ? Math.min(s, Math.max(0, Number(v.base_qty))) : s;
}

/** 提示位：只有后端返回阈值字段（前端暂定名）时才判定；只描述指标状态 */
export function tViewHints(v: TView): string[] {
  const out: string[] = [];
  if (isNum(v.dev_pct) && isNum(v.dev_pct_threshold) && absAtLeast(v.dev_pct, v.dev_pct_threshold)) {
    out.push(`偏离分时均价已达阈值（±${fmtNum(Number(v.dev_pct_threshold) * 100)}%）`);
  }
  if (isNum(v.volume_ratio) && isNum(v.volume_ratio_threshold) && absAtLeast(v.volume_ratio, v.volume_ratio_threshold)) {
    out.push(`量比已达阈值（${fmtNum(v.volume_ratio_threshold)} 倍）`);
  }
  return out;
}

export const signedPct = (ratio: string | number) => {
  const p = Number(ratio) * 100;
  return `${p > 0 ? '+' : ''}${fmtNum(p)}%`;
};
