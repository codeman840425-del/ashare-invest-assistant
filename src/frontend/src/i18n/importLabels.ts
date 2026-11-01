/**
 * 导入 / 对账 / 账号相关的中文文案与着色。导入提示码本身的文案见 api/importCodes.ts。
 */
import type { AccountStatus, DedupStatus, ImportRowStatus, ImportStatus, ReconciliationItemKind, ReconciliationStatus, TradeSide } from '../api/enums';
import { TERM } from './statementTerms';

type L = { text: string; color: string };

export const IMPORT_STATUS: Record<ImportStatus, L> = {
  uploaded: { text: '已上传', color: 'default' },
  parsing: { text: '解析中', color: 'processing' },
  previewed: { text: '待确认', color: 'blue' },
  committed: { text: '已写入', color: 'green' },
  failed: { text: '解析失败', color: 'red' },
  discarded: { text: '已放弃', color: 'default' },
  reverted: { text: '已撤销', color: 'purple' },
};

/** 行状态着色与提示码 tone 对齐：error 红 / warning 金 / skipped 灰 */
export const IMPORT_ROW_STATUS: Record<ImportRowStatus, L> = {
  ok: { text: '正常', color: 'green' },
  warning: { text: '警告', color: 'gold' },
  error: { text: '错误', color: 'red' },
  skipped: { text: '跳过', color: 'default' },
};

export const DEDUP_STATUS: Record<DedupStatus, L> = {
  new: { text: '新成交', color: 'green' },
  duplicate_in_db: { text: '库内已有', color: 'default' },
  duplicate_in_file: { text: '文件内重复', color: 'default' },
  possible_duplicate_of_manual: { text: '疑似手动录入重复', color: 'orange' },
};

export const ACCOUNT_STATUS: Record<AccountStatus, L> = {
  pending: { text: '待审核', color: 'gold' },
  approved: { text: '已通过', color: 'green' },
  rejected: { text: '已驳回', color: 'red' },
  disabled: { text: '已停用', color: 'default' },
};

/**
 * 解析选项与处理选项的中文名。契约只规定 choice 须在 resolution_choices 中，没有列出取值，
 * 这里按 §4.1“处理”列的描述命名。 // [待契约确认]
 */
export const RESOLUTION_CHOICE: Record<string, string> = {
  confirm: '已核对，确认',
  import_as_is: '按原代码导入',
  skip_row: '跳过本行',
  use_master_data: '以证券主数据为准',
  keep_skipped: '保持跳过',
  manual_entry: '改为手动录入',
  force_import: '仍然导入（作为新成交）',
  skip_import_row: '跳过导入行（保留手动记录）',
  keep_import_void_manual: '保留导入并作废手动记录',
};
/** 覆盖类选择：契约要求必须填写理由，并写审计 // [待契约确认] 取值 */
export const OVERRIDE_CHOICES: ReadonlySet<string> = new Set(['force_import', 'keep_import_void_manual']);
export const choiceText = (c: string) => RESOLUTION_CHOICE[c] ?? c;

/** 标准化字段（列映射的目标字段）中文名，对齐 §7.2 预览行 normalized */
export const IMPORT_FIELDS: Record<string, string> = {
  trade_date: TERM.tradeDate,
  trade_time: '成交时间',
  security_code: TERM.securityCode,
  name: '证券名称',
  side: '买卖方向',
  qty: '成交数量',
  price: '成交价格',
  amount: '成交金额',
  fee_total: '费用合计',
  net_amount: TERM.netAmount,
  biz_type_raw: '业务类型',
  trade_no: TERM.tradeNo,
  balance: TERM.balance,
  shareholder_code: TERM.holderCode,
  cost_price: '成本价',
  market_value: '市值',
};

export const PARSERS: { id: string; text: string }[] = [
  { id: 'tdx_trades_v1', text: '通达信交割单 / 成交明细（tdx_trades_v1）' },
  { id: 'tdx_positions_v1', text: '通达信持仓快照（tdx_positions_v1）' },
];
export const ENCODINGS = ['GB18030', 'GBK', 'UTF-8', 'UTF-8-SIG', 'UTF-16'];

/**
 * 对账差异：数值是事实；“可能原因”是假设（固定文案），“建议操作”只是数据整理动作（plan 3.5A）。
 */
export const RECON_KIND: Record<ReconciliationItemKind, { text: string; color: string; cause: string; action: string; actionTo: string }> = {
  quantity_mismatch: {
    text: '数量不一致', color: 'red',
    cause: '可能缺少期初持仓，或有送转股、配股未导入（假设）', action: '补录期初持仓 / 补录分红送转', actionTo: 'trades',
  },
  missing_in_broker: {
    text: '券商无此持仓', color: 'orange',
    cause: '可能已在其他账户卖出，或快照时间早于成交（假设）', action: '导入最新持仓快照', actionTo: 'import',
  },
  missing_in_ours: {
    text: '我方无此持仓', color: 'orange',
    cause: '可能是导入前就已持有（缺期初持仓）（假设）', action: '补录期初持仓', actionTo: 'trades',
  },
  cost_differs: {
    text: '成本不一致', color: 'gold',
    cause: '可能是分红、红利税补缴或送转的成本口径不同（假设）', action: '确认成本口径 / 补录分红送转', actionTo: 'trades',
  },
  cash_gap: {
    text: '资金差额', color: 'gold',
    cause: '可能有银证转账、利息等非成交资金流水未导入（假设）', action: '导入资金流水', actionTo: 'import',
  },
  cash_chain_break: {
    text: '资金链断开', color: 'gold',
    cause: '交割单中间可能缺少某些日期或业务行（假设）', action: '导入缺失日期的交割单', actionTo: 'import',
  },
};

/** 对账成本口径说明（契约 §7.2 /reconciliation，v0.2.2 起已定，v0.2.3 未变） */
export const DILUTED_COST_NOTE =
  '我方成本按“摊薄成本”计算，分红计入成本：现金红利冲减成本，股息红利税补缴计入成本（与通达信口径一致）。比较容差为 max(0.01 元, 0.1%)，每次导入确认后重新对账。';

export const RECON_STATUS: Record<ReconciliationStatus, L> = {
  matched: { text: '一致', color: 'green' },
  diff: { text: '有差异', color: 'orange' },
  not_imported: { text: '尚未导入券商数据', color: 'default' },
};
export const TRADE_SIDE: Record<TradeSide, L> = {
  buy: { text: '买入', color: 'red' },
  sell: { text: '卖出', color: 'green' },
};
