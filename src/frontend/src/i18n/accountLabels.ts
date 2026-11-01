/**
 * 账号、同意、风险测评、画像相关文案。
 * 测评题库与条款版本号契约未给出，这里用前端本地常量，提交给后端的只有 q_id/choice 与版本号。 // [待契约确认]
 */
import type { ConsentKey, Effort, Experience } from '../api/accountTypes';

/** 条款版本号（POST /me/consents 的 version） // [待契约确认] 应由后端下发当前版本 */
export const CONSENT_VERSION = 'v1';

export const CONSENT_TEXT: Record<ConsentKey, { title: string; summary: string }> = {
  terms: { title: '用户协议', summary: '本工具仅供个人投资研究记录与复盘使用，不提供证券投资咨询服务，不代客下单。' },
  privacy: { title: '隐私政策', summary: '交割单与持仓数据只用于本人账户的持仓重建与对账；股东代码、资金账号脱敏存储。' },
  signal_risk_disclosure: {
    title: '规则信号风险揭示',
    summary:
      '“候选信号 / 规则信号”是按你选用的策略规则对公开数据计算的结果，不构成投资建议，不保证收益；数据可能延迟或缺失，计划条件需要你自行判断后决定是否执行，盈亏自负。',
  },
};
export const CONSENT_ORDER: ConsentKey[] = ['terms', 'privacy', 'signal_risk_disclosure'];

export const EFFORT: Record<Effort, { text: string; hint: string }> = {
  low: { text: '较少', hint: '每天看盘不超过 15 分钟' },
  medium: { text: '一般', hint: '每天 15–60 分钟' },
  high: { text: '较多', hint: '交易时段可以盯盘' },
};
export const EXPERIENCE: Record<Experience, { text: string; hint: string }> = {
  novice: { text: '新手', hint: '投资经验不足 1 年；短线周期分数封顶 59（可在卡片上确认后覆盖）' },
  intermediate: { text: '有一定经验', hint: '1–5 年' },
  advanced: { text: '经验丰富', hint: '5 年以上' },
};
export const RISK_LEVEL_TEXT: Record<number, string> = { 1: '保守型（C1）', 2: '稳健型（C2）', 3: '平衡型（C3）', 4: '成长型（C4）', 5: '进取型（C5）' };

export interface RiskQuestion { q_id: string; title: string; options: [string, string, string, string] }
/** 风险测评题库（示例，a→d 风险承受递增）。 // [待契约确认] 题库与计分规则应由后端提供 */
export const RISK_QUESTIONS: RiskQuestion[] = [
  { q_id: 'q1_age', title: '你的年龄段', options: ['60 岁以上', '50–60 岁', '35–50 岁', '35 岁以下'] },
  { q_id: 'q2_income_share', title: '计划用于股票投资的资金占家庭可投资资产的比例', options: ['10% 以下', '10%–30%', '30%–50%', '50% 以上'] },
  { q_id: 'q3_experience', title: '你的股票投资经验', options: ['没有经验', '1 年以内', '1–5 年', '5 年以上'] },
  { q_id: 'q4_loss_tolerance', title: '能承受的最大年度亏损', options: ['不能亏损', '5% 以内', '5%–20%', '20% 以上'] },
  { q_id: 'q5_reaction', title: '持仓一个月内下跌 15%，你通常会', options: ['全部卖出', '卖出一部分', '继续持有观察', '按计划条件再评估加入'] },
  { q_id: 'q6_horizon', title: '计划的投资期限', options: ['1 个月以内', '1–6 个月', '6 个月–2 年', '2 年以上'] },
];

export const ROLE_TEXT = { user: '普通用户', admin: '管理员' } as const;
