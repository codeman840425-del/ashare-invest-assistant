import type { SignalEvent } from '../api/types';
/** T-A34：只读服务端冻结集合，不重排/扇出事件或推算本人实例绑定。 */
export function additionalSignalInstances(event: Pick<SignalEvent, 'instance_ids'>): string | null {
  const count = Array.isArray(event.instance_ids) ? event.instance_ids.length : 0;
  return count > 1 ? `另 ${count - 1} 个实例` : null;
}
