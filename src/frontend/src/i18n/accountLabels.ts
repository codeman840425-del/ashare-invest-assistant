/** 账号与画像相关文案（v0.2.5：同意流程与风险测评已删除） */
import type { Effort, Experience } from '../api/accountTypes';

export const EFFORT: Record<Effort, { text: string; hint: string }> = {
  low: { text: '较少', hint: '每天看盘不超过 15 分钟' },
  medium: { text: '一般', hint: '每天 15–60 分钟' },
  high: { text: '较多', hint: '交易时段可以盯盘' },
};
export const EXPERIENCE: Record<Experience, { text: string; hint: string }> = {
  novice: { text: '新手', hint: '投资经验不足 1 年；短线与日内做T 周期会附提示，不影响分数（v0.2.5）' },
  intermediate: { text: '有一定经验', hint: '1–5 年' },
  advanced: { text: '经验丰富', hint: '5 年以上' },
};

export const ROLE_TEXT = { user: '普通用户', admin: '管理员' } as const;
