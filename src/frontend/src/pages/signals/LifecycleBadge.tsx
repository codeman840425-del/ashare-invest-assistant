import { Tag, Tooltip } from 'antd';
import type { Lifecycle } from '../../api/enums';
import { LIFECYCLE } from '../../i18n/labels';
import { LIFECYCLE_BADGE } from '../../i18n/signalLabels';

/** “模拟中 / 观察中”等非正式生命周期的徽标；已发布不显示 */
export function LifecycleBadge({ lifecycle }: { lifecycle: Lifecycle }) {
  const b = LIFECYCLE_BADGE[lifecycle];
  if (!b) return null;
  return (
    <Tooltip title={b.tip}>
      <Tag color={b.color} data-testid="lifecycle-badge">{LIFECYCLE[lifecycle]}</Tag>
    </Tooltip>
  );
}
