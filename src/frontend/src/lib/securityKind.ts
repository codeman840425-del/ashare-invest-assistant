/**
 * 可转债识别（编排者 2026-11-02 裁定 Q63；契约 v0.2.8 持仓结构没有 security_type 字段，见 T-A09-frontend 遗留问题）。
 * 临时按代码前缀判断：沪市 110/111/113/118，深市 123/127/128。契约补上类型字段后改为直接读字段。
 */
const CB_PREFIX: Record<string, string[]> = { SH: ['110', '111', '113', '118'], SZ: ['123', '127', '128'] };

export function isConvertibleBondCode(code: string): boolean {
  const m = /^(\d{6})\.(SH|SZ)$/.exec(code);
  if (!m) return false;
  return (CB_PREFIX[m[2]] ?? []).some((p) => m[1].startsWith(p));
}
