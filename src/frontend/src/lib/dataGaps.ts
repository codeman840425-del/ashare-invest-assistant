import type { Gap } from '../api/types';

/**
 * 契约 v0.2.8 gap_reason=not_applicable：该证券类型没有此类数据（如 ETF 的财务、资金流、因子、公告）。
 * gaps 全部为 not_applicable 时，界面显示“不适用”，不当作“数据不可用”或故障。
 */
export const isNotApplicable = (gaps?: readonly Gap[] | null) => !!gaps?.length && gaps.every((g) => g.reason === 'not_applicable');
export const NOT_APPLICABLE_TEXT = '不适用：该证券类型没有此类数据';
