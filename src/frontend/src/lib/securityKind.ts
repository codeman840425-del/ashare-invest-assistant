/**
 * 可转债文案识别（契约 v0.2.9 #2）：是否无行情、能否进个股页一律读持仓行的 `estimated` / `security_type`；
 * 代码前缀（沪市 110/111/113/118，深市 123/127/128）只用于在 security_type=null 的行上显示“可转债”字样。
 */
const CB_PREFIX: Record<string, string[]> = { SH: ['110', '111', '113', '118'], SZ: ['123', '127', '128'] };

export function isConvertibleBondCode(code: string): boolean {
  const m = /^(\d{6})\.(SH|SZ)$/.exec(code);
  if (!m) return false;
  return (CB_PREFIX[m[2]] ?? []).some((p) => m[1].startsWith(p));
}
