import type { CardRiskLevel } from '../api/enums';

/** 是否为高风险模板：只看契约字段 card_risk_level，不按模板 key 判断（T-F22） */
export const isHighRisk = (riskLevel: CardRiskLevel | null | undefined) => riskLevel === 'high';
