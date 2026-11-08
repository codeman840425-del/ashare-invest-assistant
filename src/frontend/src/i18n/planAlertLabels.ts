/** T-F23 裁定跟进：操作计划与提醒的中文标签（契约 v0.2.9 §3 plan_status / plan_origin / plan_condition_type）。不含动作建议用语 */
import type { AlertStatus, PlanConditionType, PlanOrigin, PlanStatus } from '../api/enums';

export const PLAN_STATUS: Record<PlanStatus, { text: string; color: string }> = {
  active: { text: '进行中', color: 'blue' },
  triggered: { text: '条件已满足', color: 'orange' },
  done: { text: '已完成', color: 'default' },
  cancelled: { text: '已取消', color: 'default' },
};
export const PLAN_ORIGIN: Record<PlanOrigin, string> = { manual: '手工创建', plan_draft: '计划草案确认' };
export const PLAN_CONDITION_TYPE: Record<PlanConditionType, string> = {
  price_above: '价格高于或等于', price_below: '价格低于或等于', pct_change: '涨跌幅', indicator: '技术指标（本版不支持）', event: '事件（本版不支持）', date: '到达日期', custom: '自定义（只作文字记录）',
};
export const ALERT_STATUS_COLOR: Record<AlertStatus, string> = { new: 'red', read: 'blue', checked: 'cyan', acted: 'green', dismissed: 'default' };
/** 提醒状态按钮文字（PATCH 目标） */
export const ALERT_ACTION_TEXT: Record<Exclude<AlertStatus, 'new'>, string> = { read: '标为已读', checked: '标为已核对', acted: '标为已处理', dismissed: '忽略' };
