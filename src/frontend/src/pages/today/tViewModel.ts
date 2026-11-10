/**
 * T-F36/T-F36b：t_view 的纯函数（契约 docs/contracts/intraday-bars.md §3.7，docs/T-A145=2ddefa5）。
 * 后端负责舍入与截断，前端原样显示（只加千分位）；时间一律换算到 Asia/Shanghai（Intl 显式 timeZone）。
 */
import type { Gap, TView } from '../../api/types';

export const T_VIEW_UNAVAILABLE = '分时数据暂不可用。';
export const T_VIEW_CHECKING = '数据核对中';

/** §3.7 ⑤ 不适用的三种 key 与文案 */
export const T_VIEW_NA_TEXT: Record<string, string> = {
  't_view.base_qty': '不适用：昨日无底仓。',
  't_view.security_type': '不适用：该品种暂不提供做 T 视图。',
  't_view.session': '开盘后显示。',
};
export const T_VIEW_NA_HOLIDAY = '今日休市。';
/** 未在 §3.7 ⑤ 表中的 not_applicable key：沿用全站既有文案（保守） */
export const T_VIEW_NA_FALLBACK = '不适用：该证券类型没有此类数据';

const DEC_RE = /^([+-])?(\d+)(?:\.(\d+))?$/;
export const isDec = (v: string | null | undefined): v is string => typeof v === 'string' && DEC_RE.test(v.trim());

/** 原样显示十进制字符串，只给整数部分加千分位，不改小数位数（§3.7 ⑧） */
export function withThousands(v: string): string {
  const m = v.trim().match(DEC_RE);
  if (!m) return v;
  const int = m[2].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${m[1] === '-' ? '-' : ''}${int}${m[3] !== undefined ? `.${m[3]}` : ''}`;
}

/** 十进制字符串 ROUND_HALF_UP 到 d 位（远离零），不经浮点 */
export function roundHalfUp(v: string, d: number): string {
  const m = v.trim().match(DEC_RE)!;
  const neg = m[1] === '-';
  const frac = (m[3] ?? '').padEnd(d + 1, '0');
  let n = BigInt(m[2] + frac.slice(0, d));
  if (Number(frac[d]) >= 5) n += 1n;
  const s = n.toString().padStart(d + 1, '0');
  const out = d ? `${s.slice(0, -d)}.${s.slice(-d)}` : s;
  return neg && n !== 0n ? `-${out}` : out;
}

/** dev_pct（百分数，4 位）展示 2 位带正负号，不再 ×100（§3.7 ②） */
export function fmtDevPct(v: string): string {
  const r = roundHalfUp(v, 2);
  const zero = /^-?0\.00$/.test(r);
  return `${!zero && !r.startsWith('-') ? '+' : ''}${zero ? '0.00' : withThousands(r)}%`;
}

/** 十进制精确比较 |a| ≥ |b|（等号算达到，§3.7 ③） */
export function absAtLeast(a: string, b: string): boolean {
  const x = a.trim().match(DEC_RE);
  const y = b.trim().match(DEC_RE);
  if (!x || !y) return false;
  const n = Math.max((x[3] ?? '').length, (y[3] ?? '').length);
  const big = (m: RegExpMatchArray) => BigInt(m[2] + (m[3] ?? '').padEnd(n, '0'));
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
export const fmtShanghaiHm = (iso: string | null) => fmtShanghai(iso)?.slice(11) ?? null;

/**
 * 今日可用底仓（§3.7 ④）：原样取后端 sellable_qty，不自行截断。
 * 违反契约（sellable_qty 大于 base_qty，或 base_qty / sellable_qty 为负）时返回 'violation'，界面显示「—」并附「数据核对中」。比较用有符号十进制，不用绝对值。
 */
export function availableBase(v: Pick<TView, 'base_qty' | 'sellable_qty'>): string | null | 'violation' {
  if (!isDec(v.sellable_qty)) return null;
  const s = v.sellable_qty.trim();
  if (s.startsWith('-') && !/^-0*(\.0*)?$/.test(s)) return 'violation';
  if (isDec(v.base_qty)) {
    const base = v.base_qty.trim().match(DEC_RE)!;
    const sellable = s.match(DEC_RE)!;
    const scale = Math.max((base[3] ?? '').length, (sellable[3] ?? '').length);
    const signed = (m: RegExpMatchArray) => BigInt(`${m[1] === '-' ? '-' : ''}${m[2]}${(m[3] ?? '').padEnd(scale, '0')}`);
    const baseQty = signed(base);
    if (baseQty < 0n || signed(sellable) > baseQty) return 'violation';
  }
  return s;
}

/** §3.7 ⑤：先看有没有 not_applicable；有则为不适用，返回文案 */
export function notApplicableText(gaps: readonly Gap[], nonTradingDay: boolean): string | null {
  const na = gaps.find((g) => g.reason === 'not_applicable');
  if (!na) return null;
  if (na.key === 't_view.session' && nonTradingDay) return T_VIEW_NA_HOLIDAY;
  return T_VIEW_NA_TEXT[na.key] ?? T_VIEW_NA_FALLBACK;
}

/**
 * 达阈值提示位（§3.7 ③）：只认后端阈值字段，缺省或 null 不提示；
 * 只在 fresh 时显示；partial 时只对值与阈值都齐全的那一项显示；stale、pending、unavailable 不显示。
 */
export function tViewHints(v: TView): string[] {
  if (v.data_status !== 'fresh' && v.data_status !== 'partial') return [];
  const out: string[] = [];
  if (isDec(v.dev_pct) && isDec(v.dev_pct_threshold) && absAtLeast(v.dev_pct, v.dev_pct_threshold)) {
    out.push(`偏离分时均价已达阈值（±${withThousands(roundHalfUp(v.dev_pct_threshold.replace(/^[+-]/, ''), 2))}%）`);
  }
  if (isDec(v.volume_ratio) && isDec(v.volume_ratio_threshold) && absAtLeast(v.volume_ratio, v.volume_ratio_threshold)) {
    out.push(`量比已达阈值（${withThousands(v.volume_ratio_threshold)} 倍）`);
  }
  return out;
}
