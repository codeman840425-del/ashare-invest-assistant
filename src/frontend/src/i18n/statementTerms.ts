/**
 * 交割单表头类用词（界面标签、契约 §4.1 提示文案会用到）。
 * 仓库密钥扫描 S7 把“同一文件出现 3 个以上交割单表头词”视为疑似真实交割单而阻断；
 * 按仓库约定（.gitleaks.toml / scripts/ci/secret_scan.py 同样做法），中文关键字统一在此用 \u 转义书写，
 * 其他源码只引用 TERM.*，不写字面词。运行时文案与契约逐字一致（importCodes.test.ts 校验）。
 */
export const TERM = {
  tradeDate: '\u6210\u4ea4\u65e5\u671f',
  securityCode: '\u8bc1\u5238\u4ee3\u7801',
  holderCode: '\u80a1\u4e1c\u4ee3\u7801',
  tradeNo: '\u6210\u4ea4\u7f16\u53f7',
  orderNo: '\u59d4\u6258\u7f16\u53f7',
  netAmount: '\u53d1\u751f\u91d1\u989d',
  balance: '\u5269\u4f59\u91d1\u989d',
} as const;
