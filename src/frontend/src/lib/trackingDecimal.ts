/** 十进制字符串按HALF_UP显示两位；pct字段12即12%，仅胜率0–1另转百分数。 */
export function trackingDecimal(value: string | null, fraction = false): string {
  if (typeof value !== 'string') return '—（缺口：缺数据）';
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match) return '—（缺口：数值格式未知）';
  const decimals = match[3] ?? '';
  const scale = 10n ** BigInt(decimals.length);
  const magnitude = BigInt(match[2] + decimals) * (fraction ? 10000n : 100n);
  const rounded = (magnitude * 2n + scale) / (scale * 2n);
  return `${match[1] && rounded !== 0n ? '-' : ''}${rounded / 100n}.${(rounded % 100n).toString().padStart(2, '0')}`;
}
