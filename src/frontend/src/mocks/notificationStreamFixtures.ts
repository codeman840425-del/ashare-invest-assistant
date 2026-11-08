/** 示例数据：DeepSeek先出版本/补读夹具草稿，已逐项按§7.11.4/§8复核。refs类型与route按T-A31。 */
import type { Notification } from '../api/types';
import { uid } from './fixtures';
export function exampleNotificationVersion(version: 1 | 2 | 3 = 1): Notification {
  const times = ['2026-11-02T10:40:00+08:00', '2026-11-02T10:41:00+08:00', '2026-11-02T10:42:00+08:00'];
  return {
    id: uid(9801), kind: 'suggestion_change', severity: 'important', title: `示例数据：候选信号事实变化（第${version}次变化）`,
    body: '示例数据：通知合并不改变候选信号计算，不自动执行计划条件。', created_at: times[0], updated_at: times[version - 1],
    read_at: null, security_code: '600000.SH', name: 'TEST示例证券', target: { type: 'none', id: null, route: null },
    // 示例预留中间已读变化版本；version不等于merged_count。
    version: version * 2 - 1, merged_count: version, refs: times.slice(0, version).map((at, i) => ({ type: 'plan_condition' as const, id: uid(9810 + i), at, route: `/plans/${uid(7301)}` })).reverse(),
  };
}

/** 示例数据：下一10分钟窗口应是新通知行；离线超窗仍靠列表补读，非第二次合并。 */
export function exampleOfflineNotification(): Notification {
  const at = '2026-11-02T10:50:00+08:00';
  return { ...exampleNotificationVersion(), id: uid(9898), title: '示例数据：离线新窗口的候选信号通知', created_at: at, updated_at: at,
    refs: [{ type: 'signal', id: uid(9897), at, route: null }] };
}
