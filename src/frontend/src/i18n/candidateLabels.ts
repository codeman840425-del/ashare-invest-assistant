/** T-F23 研究候选文案（契约 v0.2.9 §7.7A） */
import type { CandidateDecision, ResearchCandidateOrigin, ResearchCandidateStatus, SourceKind } from '../api/enums';

export const RESEARCH_STATUS: Record<ResearchCandidateStatus, { text: string; color: string }> = {
  researching: { text: '研究中', color: 'blue' },
  watching: { text: '观察中', color: 'gold' },
  dropped: { text: '已放弃', color: 'default' },
  planned: { text: '已计划', color: 'green' },
};
export const RESEARCH_ORIGIN: Record<ResearchCandidateOrigin, string> = {
  manual: '手工新建', from_stock: '个股页', suggestion: '候选信号卡', strategy_screen: '策略筛选',
};
export const CANDIDATE_DECISION: Record<CandidateDecision, string> = { continue: '继续研究', watch: '转为观察', drop: '放弃' };
export const SOURCE_KIND: Record<SourceKind, string> = { market_data: '行情数据', disclosure: '公告披露', user_input: '用户填写', system_calc: '系统计算' };
/** 空反证时的固定文字（§7.7A） */
export const NO_COUNTER_EVIDENCE = '系统未列出反证，不代表没有风险';

/** 400 VALIDATION_ERROR 的 issue → 文案（§7.7A） */
export const CANDIDATE_ISSUE: Record<string, string> = {
  required: '必填',
  too_long: '超出长度上限',
  too_many: '成立条件至多 10 条',
  invalid: '取值不合法',
  not_supported: '本版不支持该来源',
  unknown_security: '证券代码不存在',
  security_type_not_supported: 'ETF、指数不能加入研究候选',
  not_found: '来源候选信号卡不存在',
  mismatch: '证券与来源候选信号卡不一致',
  verification_required: '验证日期与验证方式至少填一项',
  not_allowed: '不做决定时不能填写理由',
};
