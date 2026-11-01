/**
 * 账号、同意、风险测评、画像相关文案。
 * 风险测评题库不在这里：题目只从 GET /me/risk-assessment/questionnaire 取（评审 P1），示例题库只在 src/mocks/ 由 MSW 提供，不进生产包。
 * 条款版本号与哈希不在前端写死：取 GET /meta/consent-docs（契约 v0.2.4 #3，评审 s3）。
 */
import type { ConsentKey, Effort, Experience } from '../api/accountTypes';

/** 条款标题与摘要（正文与版本由 T-B15 / 合规提供；这里只是界面上的一句话说明） */
export const CONSENT_TEXT: Record<ConsentKey, { title: string; summary: string }> = {
  terms: { title: '用户协议', summary: '本工具仅供个人投资研究记录与复盘使用，不提供证券投资咨询服务，不代客下单。' },
  privacy: { title: '隐私政策', summary: '交割单与持仓数据只用于本人账户的持仓重建与对账；股东代码、资金账号脱敏存储。' },
  signal_risk_disclosure: {
    title: '规则信号风险揭示',
    summary:
      '“候选信号 / 规则信号”是按你选用的策略规则对公开数据计算的结果，不构成投资建议，不保证收益；数据可能延迟或缺失，计划条件需要你自行判断后决定是否执行，盈亏自负。',
  },
  sensitive_financial_info: {
    title: '个人敏感信息处理单独同意',
    summary:
      '导入交割单、持仓快照或手工录入成交时，会处理你的交易与持仓记录（属于个人敏感信息）。仅用于本人账户的持仓重建与对账，股东代码、资金账号脱敏存储，不向第三方提供；可随时删除导入批次。',
  },
};
/** 注册时必须勾选的三项（v0.2.4 #2：terms、privacy、signal_risk_disclosure；原 risk_disclosure 作废） */
export const AGREEMENT_ORDER: ConsentKey[] = ['terms', 'privacy', 'signal_risk_disclosure'];
/** 开通引导需要的同意项（契约 §1.3 合规门槛） */
export const CONSENT_ORDER: ConsentKey[] = ['terms', 'privacy', 'signal_risk_disclosure'];

export const EFFORT: Record<Effort, { text: string; hint: string }> = {
  low: { text: '较少', hint: '每天看盘不超过 15 分钟' },
  medium: { text: '一般', hint: '每天 15–60 分钟' },
  high: { text: '较多', hint: '交易时段可以盯盘' },
};
export const EXPERIENCE: Record<Experience, { text: string; hint: string }> = {
  novice: { text: '新手', hint: '投资经验不足 1 年；短线与日内做T 周期分数封顶 59（画像未填写同样处理；可在卡片上确认后覆盖）' },
  intermediate: { text: '有一定经验', hint: '1–5 年' },
  advanced: { text: '经验丰富', hint: '5 年以上' },
};
export const RISK_LEVEL_TEXT: Record<number, string> = { 1: '保守型（C1）', 2: '稳健型（C2）', 3: '平衡型（C3）', 4: '成长型（C4）', 5: '进取型（C5）' };

export const QUESTIONNAIRE_UNPUBLISHED = '风险测评题库尚未发布，暂不能开通候选信号与日报';

export const ROLE_TEXT = { user: '普通用户', admin: '管理员' } as const;
