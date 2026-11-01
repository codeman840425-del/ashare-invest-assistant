/**
 * 契约 v0.2.3 §4.1 导入提示码（IMPORT_*，共 46 个：21 error + 25 warning）。
 * code / severity / scope / template / handling 取自契约表（去掉 markdown 标记），由 importCodes.test.ts 逐行对照契约校验；
 * title 为前端维护的中文短名；tone 决定着色：error=红、action=橙（needs_action：需逐项处理，或确认时统一接受默认处理）、
 * info=金（仅提示）、skip=灰（该行被跳过：不写入，也不算错误）。
 * needs_action 按契约“处理”列含“需确认/需选择”推出（7 个），与后端 app/schemas/enums.py IMPORT_CODE_TABLE 一致。
 * 运行时以服务端 ImportFinding.needs_action / resolution_choices 为准；这张表只负责文案、图例与着色。
 */
import type { ImportScope, ImportSeverity } from './enums';
import { TERM } from '../i18n/statementTerms';

export type ImportTone = 'error' | 'action' | 'info' | 'skip';
export interface ImportCodeSpec {
  no: number;
  code: string;
  severity: ImportSeverity;
  scope: ImportScope;
  needs_action: boolean;
  tone: ImportTone;
  title: string;
  template: string;
  handling: string;
}

export const IMPORT_CODES: readonly ImportCodeSpec[] = [
  { no: 1, code: 'IMPORT_EMPTY_FILE', severity: 'error', scope: 'file', needs_action: false, tone: 'error', title: '空文件', template: '文件为空（0 字节或只有空白字符）', handling: '不可覆盖；上传时即拒绝（422 IMPORT_FILE_ERRORS，不创建批次）' },
  { no: 2, code: 'IMPORT_FILE_TOO_LARGE', severity: 'error', scope: 'file', needs_action: false, tone: 'error', title: '文件过大', template: '文件超过 {limit_mb} MB', handling: '不可覆盖；上传时拒绝，不创建批次' },
  { no: 3, code: 'IMPORT_UNSUPPORTED_FILE_TYPE', severity: 'error', scope: 'file', needs_action: false, tone: 'error', title: '文件类型不支持', template: '只支持 .txt / .csv 文本文件', handling: '不可覆盖；上传时拒绝（扩展名不符，或 NUL 字节占比 > 1% 视为二进制）' },
  { no: 4, code: 'IMPORT_TOO_MANY_ROWS', severity: 'error', scope: 'file', needs_action: false, tone: 'error', title: '行数超限', template: '数据行超过 {limit} 行（默认 50,000）', handling: '不可覆盖；请拆分文件' },
  { no: 5, code: 'IMPORT_ENCODING_UNDETECTED', severity: 'error', scope: 'file', needs_action: false, tone: 'error', title: '编码无法识别', template: '无法识别文件编码', handling: '可处理：用户在预览页手选编码后重新解析（encoding_override）' },
  { no: 6, code: 'IMPORT_UNRECOGNIZED_FORMAT', severity: 'error', scope: 'file', needs_action: false, tone: 'error', title: '格式无法识别', template: '无法识别文件格式，候选解析器：{candidates}', handling: '可处理：用户手选解析器或手工列映射后重新解析' },
  { no: 7, code: 'IMPORT_REQUIRED_COLUMN_MISSING', severity: 'error', scope: 'file', needs_action: false, tone: 'error', title: '缺少必填列', template: '缺少必填列：{columns}', handling: '可处理：只能把文件中已存在的列映射到缺失字段；不得推算（例如用金额 / 数量推价格）' },
  { no: 8, code: 'IMPORT_ACCOUNT_MISMATCH', severity: 'error', scope: 'file', needs_action: false, tone: 'error', title: '账户不一致', template: `文件中的${TERM.holderCode}与所选账户已登记的不一致（按 HMAC 比较）`, handling: `可处理：改选账户，或确认“属于本账户的新${TERM.holderCode}”（写审计）` },
  { no: 9, code: 'IMPORT_ROW_DECODE_ERROR', severity: 'error', scope: 'row', needs_action: false, tone: 'error', title: '行解码失败', template: '第 {row_no} 行无法按 {encoding} 解码', handling: '不可覆盖；最先判定。文件末尾不完整的多字节字符也归此码，不得因此整文件拒绝' },
  { no: 10, code: 'IMPORT_ROW_TRUNCATED', severity: 'error', scope: 'row', needs_action: false, tone: 'error', title: '行不完整', template: '第 {row_no} 行不完整（文件末行没有换行且列数不足）', handling: '不可覆盖；优先于 ROW_COLUMN_MISMATCH；残缺字段一律不入库' },
  { no: 11, code: 'IMPORT_ROW_COLUMN_MISMATCH', severity: 'error', scope: 'row', needs_action: false, tone: 'error', title: '列数/列位置不一致', template: '第 {row_no} 行的列数或列位置与表头不一致', handling: '不可覆盖（改文件或手动录入）；两种切分策略结果不一致也归此码' },
  { no: 12, code: 'IMPORT_REQUIRED_FIELD_EMPTY', severity: 'error', scope: 'field', needs_action: false, tone: 'error', title: '必填字段为空', template: '必填字段 {field} 为空', handling: '不可覆盖' },
  { no: 13, code: 'IMPORT_INVALID_DATE', severity: 'error', scope: 'field', needs_action: false, tone: 'error', title: '日期无效', template: '日期 {value} 无效', handling: '不可覆盖' },
  { no: 14, code: 'IMPORT_FUTURE_DATE', severity: 'error', scope: 'field', needs_action: false, tone: 'error', title: '日期在未来', template: '日期 {value} 晚于导入当天', handling: '不可覆盖' },
  { no: 15, code: 'IMPORT_INVALID_TIME', severity: 'error', scope: 'field', needs_action: false, tone: 'error', title: '时间无效', template: '时间 {value} 无效', handling: '不可覆盖；5 位左补零（93005→09:30:05）；4 位及更短的非零值报错，不猜测；0 或空视为缺失、不报错' },
  { no: 16, code: 'IMPORT_INVALID_NUMBER', severity: 'error', scope: 'field', needs_action: false, tone: 'error', title: '数字无效', template: '{field} 的值 {value} 不是有效数字', handling: '不可覆盖；先做全角转半角、去千分位' },
  { no: 17, code: 'IMPORT_INVALID_SECURITY_CODE', severity: 'error', scope: 'field', needs_action: false, tone: 'error', title: `${TERM.securityCode}格式无效`, template: `${TERM.securityCode} {value} 格式无效（应为 6 位数字）`, handling: '不可覆盖；格式有效但主数据中没有的见 UNKNOWN_SECURITY' },
  { no: 18, code: 'IMPORT_INVALID_QUANTITY', severity: 'error', scope: 'field', needs_action: false, tone: 'error', title: '数量无效', template: '买卖类数量为 0（且不是撤单或废单）', handling: '不可覆盖' },
  { no: 19, code: 'IMPORT_INVALID_PRICE', severity: 'error', scope: 'field', needs_action: false, tone: 'error', title: '价格/金额无效', template: '价格或成交金额 ≤ 0', handling: '不可覆盖' },
  { no: 20, code: 'IMPORT_SIDE_QTY_SIGN_MISMATCH', severity: 'error', scope: 'row', needs_action: false, tone: 'error', title: '数量符号与方向不符', template: '数量符号与买卖方向不一致', handling: '不可覆盖' },
  { no: 21, code: 'IMPORT_AMOUNT_MISMATCH', severity: 'error', scope: 'row', needs_action: false, tone: 'error', title: '成交金额不符', template: '数量绝对值 × 价格 与成交金额相差 {diff} 元（容差 0.05 元）', handling: '不可覆盖' },
  { no: 22, code: 'IMPORT_DUPLICATE_FILE', severity: 'warning', scope: 'file', needs_action: false, tone: 'info', title: '重复文件', template: '同一文件已于 {imported_at} 导入（批次 {batch_id}）', handling: '仅提示；仍可预览，重复行由去重挡住' },
  { no: 23, code: 'IMPORT_NO_DATA_ROWS', severity: 'warning', scope: 'file', needs_action: false, tone: 'info', title: '没有数据行', template: '只有表头，没有数据行', handling: '仅提示；批次照常创建，确认时返回 422 IMPORT_NOTHING_TO_COMMIT' },
  { no: 24, code: 'IMPORT_UNKNOWN_COLUMN', severity: 'warning', scope: 'file', needs_action: false, tone: 'info', title: '未识别的列', template: '已忽略未识别的列：{columns}', handling: '仅提示；按表头名取列，不按固定列序' },
  { no: 25, code: 'IMPORT_FILE_POSSIBLY_TRUNCATED', severity: 'warning', scope: 'file', needs_action: false, tone: 'info', title: '文件可能不完整', template: '文件末尾不完整，可能没有导出完整', handling: '仅提示；与 ROW_TRUNCATED / 末行 ROW_DECODE_ERROR 同时出现' },
  { no: 26, code: 'IMPORT_ENCODING_LOW_CONFIDENCE', severity: 'warning', scope: 'file', needs_action: true, tone: 'action', title: '编码置信度低', template: '编码判定为 {encoding}，置信度 {confidence} 较低', handling: '需确认：请核对预览中的中文；可改选编码' },
  { no: 27, code: 'IMPORT_FORMAT_LOW_CONFIDENCE', severity: 'warning', scope: 'file', needs_action: true, tone: 'action', title: '格式识别得分低', template: '解析器 {parser} 的识别得分 {score} 低于 0.95', handling: '需确认：请核对列映射' },
  { no: 28, code: 'IMPORT_SNAPSHOT_AS_OF_ASSUMED', severity: 'warning', scope: 'file', needs_action: true, tone: 'action', title: '快照时间为推定', template: '快照没有日期，导出时间按 {as_of} 处理', handling: '需确认：确认或修改导出时间（问题 20）' },
  { no: 29, code: 'IMPORT_SNAPSHOT_TOTALS_MISMATCH', severity: 'warning', scope: 'file', needs_action: false, tone: 'info', title: '快照合计不一致', template: '资金摘要与明细合计不一致（券商口径未知）', handling: '仅展示，不判定、不阻止' },
  { no: 30, code: 'IMPORT_SNAPSHOT_SUPERSEDES', severity: 'warning', scope: 'file', needs_action: false, tone: 'info', title: '快照将覆盖旧版本', template: '该账户在 {as_of} 已有快照，确认后新版本覆盖旧版本（旧版本保留）', handling: '仅提示' },
  { no: 31, code: 'IMPORT_UNSUPPORTED_CURRENCY', severity: 'warning', scope: 'file', needs_action: false, tone: 'info', title: '非人民币资金行已忽略', template: '已忽略 {currency} 资金摘要行（只支持人民币）', handling: '仅提示' },
  { no: 32, code: 'IMPORT_NET_AMOUNT_MISMATCH', severity: 'warning', scope: 'row', needs_action: false, tone: 'info', title: `${TERM.netAmount}不符`, template: `${TERM.netAmount}与 ±成交金额 − 费用 相差 {diff} 元（容差 0.02 元）`, handling: '仅提示；照常导入，对账时参考' },
  { no: 33, code: 'IMPORT_UNKNOWN_SECURITY', severity: 'warning', scope: 'row', needs_action: true, tone: 'action', title: '证券不在主数据中', template: `${TERM.securityCode} {code} 不在证券主数据中（可能已退市或刚上市）`, handling: '需确认：确认后按原代码导入' },
  { no: 34, code: 'IMPORT_MARKET_INFERRED_CONFLICT', severity: 'warning', scope: 'row', needs_action: true, tone: 'action', title: '市场推断冲突', template: `由代码段推断的市场与${TERM.holderCode}类型不一致`, handling: '需确认；以证券主数据为准' },
  { no: 35, code: 'IMPORT_NAME_MISMATCH', severity: 'warning', scope: 'field', needs_action: false, tone: 'info', title: '证券名称不同', template: '证券名称 {name_raw} 与主数据 {name} 不同', handling: '仅提示；比较前去掉全部空白，名称内部有空格本身不报错' },
  { no: 36, code: 'IMPORT_UNKNOWN_BIZ_TYPE', severity: 'warning', scope: 'row', needs_action: true, tone: 'action', title: '业务类型未识别', template: '业务类型 {biz} 未识别，本行未导入', handling: '行状态 skipped；需确认（可改为手动录入），不猜测' },
  { no: 37, code: 'IMPORT_ROW_CANCELLED', severity: 'warning', scope: 'row', needs_action: false, tone: 'skip', title: '撤单行', template: '撤单行，已忽略', handling: `行状态 skipped，无需处理；${TERM.tradeNo} 0 不参与去重` },
  { no: 38, code: 'IMPORT_ROW_REJECTED', severity: 'warning', scope: 'row', needs_action: false, tone: 'skip', title: '废单行', template: '废单行，已忽略', handling: '行状态 skipped，无需处理' },
  { no: 39, code: 'IMPORT_DUPLICATE_IN_DB', severity: 'warning', scope: 'row', needs_action: false, tone: 'skip', title: '与已导入成交重复', template: '与已导入的成交重复（批次 {batch_id}）', handling: '默认 skipped；可覆盖：强制作为新成交，须填理由并写审计' },
  { no: 40, code: 'IMPORT_DUPLICATE_IN_FILE', severity: 'warning', scope: 'row', needs_action: false, tone: 'skip', title: '文件内重复', template: '与本文件第 {other_row_no} 行重复', handling: '默认 skipped；可覆盖（同上）。去重规则 3（无编号）下完全相同的行不报此码，按 #n 保留为真实的多笔成交' },
  { no: 41, code: 'IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL', severity: 'warning', scope: 'row', needs_action: true, tone: 'action', title: '疑似与手动录入重复', template: '可能与手动录入的成交 {trade_id} 是同一笔', handling: '需选择：跳过导入行（默认）/ 保留导入并作废手动记录' },
  { no: 42, code: 'IMPORT_MISSING_OPENING_POSITION', severity: 'warning', scope: 'row', needs_action: false, tone: 'info', title: '可能缺期初持仓', template: '卖出数量超过重建后的持仓，可能缺期初持仓', handling: '仅提示；建议补录期初持仓' },
  { no: 43, code: 'IMPORT_CASH_CHAIN_BREAK', severity: 'warning', scope: 'row', needs_action: false, tone: 'info', title: '资金余额链断开', template: `${TERM.balance}链在本行断开，差额 {diff} 元`, handling: '仅提示（日间可能有非成交资金流水）' },
  { no: 44, code: 'IMPORT_NON_TRADING_DAY', severity: 'warning', scope: 'row', needs_action: false, tone: 'info', title: '非交易日', template: `${TERM.tradeDate} {date} 不是交易日`, handling: '仅提示' },
  { no: 45, code: 'IMPORT_TIME_OUTSIDE_SESSION', severity: 'warning', scope: 'row', needs_action: false, tone: 'info', title: '非交易时段', template: '成交时间不在交易时段内', handling: '仅提示' },
  { no: 46, code: 'IMPORT_LOT_SIZE_IRREGULAR', severity: 'warning', scope: 'row', needs_action: false, tone: 'info', title: '不符合整手规则', template: '买入数量不符合整手规则', handling: '仅提示（科创板 200 股起、按 1 股递增等规则按板块处理）' },
];

export const IMPORT_CODE_MAP: ReadonlyMap<string, ImportCodeSpec> = new Map(IMPORT_CODES.map((c) => [c.code, c]));

/** 着色：antd Tag 颜色 + 预览行背景类名（styles.css 的 .imp-*） */
export const IMPORT_TONE: Record<ImportTone, { tag: string; label: string; rowClass: string }> = {
  error: { tag: 'red', label: '错误（不写入）', rowClass: 'imp-error' },
  action: { tag: 'orange', label: '需处理的警告', rowClass: 'imp-action' },
  info: { tag: 'gold', label: '仅提示的警告', rowClass: 'imp-info' },
  skip: { tag: 'default', label: '已跳过（不写入，不算错误）', rowClass: 'imp-skip' },
};

/** 用 params 渲染模板中的 {param} 占位；缺参数时保留占位符原样，便于发现问题 */
export function renderTemplate(template: string, params: Record<string, unknown> | null | undefined): string {
  return template.replace(/\{([a-z_]+)\}/g, (m, k: string) => (params && params[k] !== undefined && params[k] !== null ? String(params[k]) : m));
}

/** 契约外的未知码兜底：按 severity 着色，标题显示原码 */
export function importCodeSpec(code: string, severity: ImportSeverity = 'warning'): ImportCodeSpec {
  return (
    IMPORT_CODE_MAP.get(code) ?? {
      no: 0, code, severity, scope: 'row', needs_action: false, tone: severity === 'error' ? 'error' : 'info', title: `未知提示码 ${code}`, template: '', handling: '',
    }
  );
}

/** 运行时着色：以服务端 needs_action 为准（未处理 → 橙；已处理按表内 tone，action 退为 info） */
export function findingTone(f: { code: string; severity: ImportSeverity; needs_action: boolean; resolution?: unknown }): ImportTone {
  const spec = importCodeSpec(f.code, f.severity);
  if (f.severity === 'error') return 'error';
  if (f.needs_action) return f.resolution ? 'info' : 'action';
  return spec.tone === 'action' ? 'info' : spec.tone;
}

/** 预览行着色：错误 > 未处理的需处理警告 > 跳过 > 仅提示 */
export function rowTone(row: { status: string; findings: { code: string; severity: ImportSeverity; needs_action: boolean; resolution?: unknown }[] }): ImportTone | null {
  if (row.status === 'error') return 'error';
  const tones = row.findings.map(findingTone);
  if (tones.includes('error')) return 'error';
  if (tones.includes('action')) return 'action';
  if (row.status === 'skipped' || tones.includes('skip')) return 'skip';
  if (row.status === 'warning' || tones.includes('info')) return 'info';
  return null;
}

/** 确认写入 / 上传时 422 错误码的中文说明（契约 §7.2） */
export const IMPORT_422_TEXT: Record<string, string> = {
  IMPORT_FILE_ERRORS: '文件级错误未解决，无法导入。请按提示更换文件，或调整编码 / 解析器 / 列映射后重新解析。',
  IMPORT_ROW_ERRORS: '还有错误行。可以改为“只写入有效行”，错误行会被跳过并列入问题清单。',
  IMPORT_WARNINGS_UNACKNOWLEDGED: '有需处理的警告尚未逐项处理。请逐项选择处理方式，或勾选“对未处理的警告接受默认处理”。',
  IMPORT_NOTHING_TO_COMMIT: '没有可写入的行（全部为重复、跳过或错误）。',
};

/** 提示的中文正文：优先服务端 message，缺省时用契约模板 + params 渲染 */
export function findingText(f: { code: string; severity: ImportSeverity; message: string; params: Record<string, unknown> | null }): string {
  return f.message || renderTemplate(importCodeSpec(f.code, f.severity).template, f.params);
}
