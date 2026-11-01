import type {
  Action, CandidateSignalState, CheckOn, ConfidenceLevel, DataStatus, Dimension, DimensionView,
  EpistemicType, GapReason, Horizon, Lifecycle, MarketRegime, NotificationKind, ReasonCode,
  ReleaseKind, RiskControl, RiskLevel, Severity, SuggestionOrigin, RuleRole, StrategyEvalState, MarketSession, SignalKind,
  DataProvider, ExecutabilityStatus, ConsensusStatus, ReconciliationStatus, NotificationTargetType, PlanDraftStatus,
  SecurityType, Board, ListingStatus, SecurityRiskFlag, SecurityMatchKind, ReportPeriod, AnnouncementCategory, IndustryTaxonomy, InstanceOrigin,
  AlertStatus, AlertOrigin, PlanConditionKind, DataGapScope,
} from '../api/enums';

/** 动作：短标签（徽标用）与完整措辞（plan §2.5.0 措辞约定：规则信号 + 候选） */
export const ACTION_SHORT: Record<Action, string> = {
  buy: '买入', add: '加仓', hold: '持有', reduce: '减仓', sell: '卖出', wait: '等待',
};
export const ACTION_FULL: Record<Action, string> = {
  buy: '规则信号：买入条件满足（候选）',
  add: '规则信号：加仓条件满足（候选）',
  hold: '规则信号：持有条件维持',
  reduce: '规则信号：减仓条件满足（候选）',
  sell: '规则信号：卖出条件满足（候选）',
  wait: '规则信号：条件未满足，等待',
};
/** 红涨绿跌：偏多方向用红，偏空方向用绿 */
export const ACTION_COLOR: Record<Action, string> = {
  buy: '#f5384a', add: '#ff7a45', hold: '#3b82f6', reduce: '#36c47f', sell: '#14a35c', wait: '#7a8394',
};
export const HORIZON: Record<Horizon, string> = {
  intraday_t: '日内做T', short: '短线', swing: '波段', long: '中长线',
};
export const DIMENSION: Record<Dimension, string> = {
  technical: '技术', capital: '资金', fundamental: '基本面', sentiment: '情绪', sector_market: '板块与大盘', news: '消息',
};
export const VIEW: Record<DimensionView, { text: string; color: string }> = {
  bullish: { text: '偏多', color: '#f5384a' },
  bearish: { text: '偏空', color: '#22b573' },
  neutral: { text: '中性', color: '#a0a8b8' },
  unknown: { text: '未知', color: '#5a6170' },
};
export const CONF_LEVEL: Record<ConfidenceLevel, { text: string; color: string }> = {
  high: { text: '高', color: '#52c41a' }, medium: { text: '中', color: '#faad14' }, low: { text: '低', color: '#ff4d4f' },
};
export const DATA_STATUS: Record<DataStatus, { text: string; color: string }> = {
  fresh: { text: '最新', color: '#52c41a' },
  stale: { text: '已过期', color: '#8c8c8c' },
  pending: { text: '拉取中', color: '#1677ff' },
  partial: { text: '部分缺失', color: '#faad14' },
  unavailable: { text: '不可用', color: '#ff4d4f' },
};
export const SIGNAL_STATE: Record<CandidateSignalState, { text: string; color: string }> = {
  open: { text: '待检查', color: 'default' },
  drafted: { text: '可拟定草案', color: 'green' },
  blocked: { text: '暂不可执行', color: 'orange' },
  released: { text: '原因已解除', color: 'cyan' },
  confirmed: { text: '已确认为计划', color: 'blue' },
  dismissed: { text: '已忽略', color: 'default' },
  expired: { text: '已过期', color: 'default' },
  invalidated: { text: '已失效', color: 'red' },
  superseded: { text: '已被取代', color: 'default' },
};
export const LIFECYCLE: Record<Lifecycle, string> = {
  draft: '草稿', simulating: '模拟中', published: '已发布', observing: '观察中', retired: '已退役',
};
export const RISK_CONTROL: Record<RiskControl, string> = {
  stop_take: 'RC1 止损止盈', position_cap: 'RC2 单只仓位上限', total_exposure: 'RC3 总仓位',
  sector_concentration: 'RC4 板块集中度', loss_streak_drawdown: 'RC5 连亏与回撤', plan_violation: 'RC6 违反计划',
};
export const RISK_LEVEL: Record<RiskLevel, { text: string; color: string }> = {
  info: { text: '提示', color: 'blue' }, warning: { text: '警示', color: 'orange' }, critical: { text: '严重', color: 'red' },
};
export const REASON_CODE: Record<ReasonCode, string> = {
  DATA_STALE: '数据过期', KEY_DATA_MISSING: '关键数据缺失', LOW_CONFIDENCE: '置信度偏低', NON_TRADING_TIME: '非交易时段',
  SUSPENDED: '停牌', LIMIT_LOCKED: '一字涨跌停', ST_OR_DELISTING: 'ST/退市整理', NEW_LISTING: '上市不足 N 日',
  INSUFFICIENT_CASH: '可用资金不足', T1_NOT_SELLABLE: 'T+1 不可卖', NO_POSITION: '无持仓', POSITION_CAP_REACHED: '单只仓位已达上限',
  STRATEGY_BUDGET_EXHAUSTED: '策略预算用尽', SECTOR_EXPOSURE_EXCEEDED: '行业暴露超限', REGIME_MISMATCH: '大盘环境不符',
  SAME_DIRECTION_PLAN_EXISTS: '已有同向计划', CONFLICTS_CONFIRMED_PLAN: '与已确认计划相反', BLOCKLISTED: '在禁投名单',
  COOLING_OFF: '冷静期', LOSS_STREAK_PAUSE: '连亏暂停', STRATEGY_CONFLICT: '策略方向冲突', USER_MUTED: '已屏蔽',
};
export const CHECK_ON: Record<CheckOn, string> = {
  tick: '盘中每轮', daily_close: '每日收盘', schedule: '到点', holding_change: '持仓变化', cash_update: '资金更新',
  import: '导入后', plan_change: '计划变化', user_action: '用户操作',
};
export const RELEASE_KIND: Record<ReleaseKind, string> = {
  expr: '条件表达式', time: '到达时间', event: '事件', user_action: '用户操作',
};
export const EPISTEMIC: Record<EpistemicType, { text: string; color: string }> = {
  fact: { text: '事实', color: 'green' }, estimate: { text: '估计', color: 'gold' },
  hypothesis: { text: '假设', color: 'purple' }, execution: { text: '执行', color: 'blue' },
};
export const GAP_REASON: Record<GapReason, string> = {
  no_source: '无数据源', not_yet_published: '尚未发布', upstream_error: '上游错误', quota_deferred: '配额顺延', user_input_missing: '待用户录入', data_licence_unavailable: '你的数据证书不可用', not_applicable: '不适用',
};
export const ORIGIN: Record<SuggestionOrigin, string> = {
  daily_batch: '盘后批处理', intraday_event: '盘中事件', manual_refresh: '手动刷新',
};
export const REGIME: Record<MarketRegime, string> = { uptrend: '上行', range: '震荡', downtrend: '下行' };
export const NOTIFY_KIND: Record<NotificationKind, string> = {
  suggestion_change: '候选信号变化', invalidation: '失效条件触发', daily_report: '日报', alert: '提醒', import: '导入',
  system: '系统', reason_released: '原因已解除', plan_draft_ready: '计划草案待确认', plan_triggered: '计划条件已满足', strategy_health: '策略健康度', data_licence: '数据证书',
};
export const SEVERITY: Record<Severity, string> = { info: 'blue', attention: 'orange', important: 'red' };
export const RULE_ROLE: Record<RuleRole, string> = {
  entry: '入场', hold: '持有', weakening: '转弱', exit: '离场', filter: '过滤', veto: '否决', counter: '反证', invalidation: '失效',
};

export const EVAL_STATE: Record<StrategyEvalState, string> = {
  entry_ok: '入场条件满足', not_triggered: '未触发', hold_ok: '持有条件维持', weakening: '转弱', exit_signal: '离场条件满足',
  vetoed: '被否决', insufficient_data: '数据不足',
};
/** plan_draft_status（契约 §3；T-F08） */
export const PLAN_DRAFT_STATUS: Record<PlanDraftStatus, { text: string; color: string }> = {
  pending: { text: '待确认', color: 'gold' }, confirmed: { text: '已确认', color: 'green' }, discarded: { text: '已放弃', color: 'default' },
  expired: { text: '已过期', color: 'default' }, stale: { text: '条件已变', color: 'orange' },
};
export const SESSION: Record<MarketSession, string> = {
  non_trading_day: '非交易日', pre_open: '盘前', call_auction: '集合竞价', morning: '上午连续竞价', lunch_break: '午间休市',
  afternoon: '下午连续竞价', closing_auction: '收盘集合竞价', closed: '已收盘',
};
export const SIGNAL_KIND: Record<SignalKind, string> = {
  rule_flip: '规则翻转', breakout: '突破', breakdown: '跌破', vwap_deviation: '偏离均价', volume_spike: '放量',
  limit_up_touch: '触及涨停', limit_down_touch: '触及跌停', limit_open: '涨跌停打开', invalidation_near: '接近失效条件',
  stop_hit: '触及止损/止盈', suspended: '停牌', data_stale: '数据过期',
};
export const PROVIDER: Record<DataProvider, string> = {
  mairui: '麦蕊', user_import: '用户导入', user_input: '用户录入', system: '系统计算', exchange: '交易所公开信息',
};
export const EXECUTABILITY: Record<ExecutabilityStatus, { text: string; color: string }> = {
  executable: { text: '可执行', color: 'green' }, blocked: { text: '暂不可执行', color: 'orange' }, not_applicable: { text: '不适用', color: 'default' },
};
export const CONSENSUS: Record<ConsensusStatus, { text: string; color: string }> = {
  unanimous: { text: '一致', color: 'green' }, divergent: { text: '分歧', color: 'orange' }, single: { text: '单策略', color: 'blue' }, none: { text: '无策略', color: 'default' },
};
export const RECONCILIATION: Record<ReconciliationStatus, { text: string; color: string }> = {
  matched: { text: '已对账一致', color: 'green' }, diff: { text: '存在差异', color: 'orange' }, not_imported: { text: '未导入', color: 'default' },
};
export const TARGET_TYPE: Record<NotificationTargetType, string> = {
  suggestion: '候选信号卡', candidate_signal: '候选信号', plan_draft: '计划草案', plan: '交易计划', daily_report: '日报',
  import_batch: '导入批次', reconciliation: '对账', strategy_version: '策略版本', none: '无',
};

// ---- v0.2.7（T-A08）个股数据、策略实例、/today 新增枚举 ----
export const SECURITY_TYPE: Record<SecurityType, string> = { stock: '股票', cdr: 'CDR', etf: 'ETF', index: '指数' };
export const BOARD: Record<Board, string> = { main: '主板', chinext: '创业板', star: '科创板', bse: '北交所' };
export const LISTING_STATUS: Record<ListingStatus, string> = {
  listed: '上市', delisting_period: '退市整理期', delisted: '已退市', missing_from_list: '交易所列表未收录',
};
export const SECURITY_RISK_FLAG: Record<SecurityRiskFlag, string> = { st: 'ST', star_st: '*ST', delisting: '退市风险' };
export const MATCH_KIND: Record<SecurityMatchKind, string> = {
  code_exact: '代码', name_exact: '简称', initials_exact: '拼音首字母', code_prefix: '代码', name_prefix: '简称', initials_prefix: '拼音首字母',
  name_contains: '简称', former_name: '曾用名', former_code: '旧代码', fuzzy: '近似',
};
export const REPORT_PERIOD: Record<ReportPeriod, string> = { q1: '一季报', h1: '半年报', q3: '三季报', fy: '年报' };
export const ANNOUNCEMENT_CATEGORY: Record<AnnouncementCategory, string> = { periodic_report: '定期报告', other: '其他' };
export const INDUSTRY_TAXONOMY: Record<IndustryTaxonomy, string> = { sw_l1: '申万一级', sw_l2: '申万二级', csrc: '证监会行业' };
export const INSTANCE_ORIGIN: Record<InstanceOrigin, string> = { classifier: '周期分类生成', user: '自己添加', system: '系统内置' };
export const ALERT_STATUS: Record<AlertStatus, string> = { new: '未读', read: '已读', checked: '已核对', acted: '已处理', dismissed: '已忽略' };
export const ALERT_ORIGIN: Record<AlertOrigin, string> = { plan_condition: '计划条件', holding_event: '持仓事件', user_custom: '自定义提醒' };
export const PLAN_CONDITION_KIND: Record<PlanConditionKind, string> = { trigger: '计划条件', invalidation: '失效条件' };
export const DATA_GAP_SCOPE: Record<DataGapScope, string> = { user: '本人', account: '账户', security: '证券', market: '市场' };
/**
 * factor_category 键名【待 T003 补测】：已知的示例键给中文名，未知键原样显示
 */
export const FACTOR_CATEGORY_LABEL: Record<string, string> = {
  valuation: '估值', quality: '质量', growth: '成长', momentum: '动量', volatility: '波动', liquidity: '流动性',
};
export const factorCategoryLabel = (k: string) => FACTOR_CATEGORY_LABEL[k] ?? k;
export const SEVERITY_TEXT: Record<Severity, string> = { important: '重要', attention: '关注', info: '提示' };
