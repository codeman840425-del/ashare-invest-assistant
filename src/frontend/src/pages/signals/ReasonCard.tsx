import { Button, Tag } from 'antd';
import type { NonExecutableReason } from '../../api/types';
import { REASON_CODE, RELEASE_KIND } from '../../i18n/labels';
import { REASON_STATUS } from '../../i18n/signalLabels';
import { manuallyReleasable, reevalText } from '../../lib/signals';
import { fmtTime } from '../../lib/format';

export function ReasonCard({ r, onRelease }: { r: NonExecutableReason; onRelease?: (r: NonExecutableReason) => void }) {
  const st = REASON_STATUS[r.status];
  const note = r.release_evidence && typeof r.release_evidence.note === 'string' ? r.release_evidence.note : null;
  return (
    <div className={`reason reason-${r.status}`} data-testid={`reason-${r.id}`}>
      <div>
        <Tag color={st.color}>{st.text}</Tag>
        <Tag color={r.status === 'active' ? 'orange' : 'default'}>{r.code}</Tag>
        <b>{REASON_CODE[r.code]}</b>：{r.description}
      </div>
      <div className="rc">
        解除条件（{RELEASE_KIND[r.release_condition.kind]}）：{r.release_condition.human_text}
        {r.release_condition.expr ? <code>{r.release_condition.expr}</code> : null}
        {r.release_condition.at ? <span className="mono small">　{fmtTime(r.release_condition.at)}</span> : null}
      </div>
      <div className="muted small" data-testid="reeval">
        自动重评状态：{reevalText(r)} · 检出 {fmtTime(r.detected_at)}{note ? ` · 备注：${note}` : ''}
      </div>
      {onRelease && manuallyReleasable(r) ? (
        <Button size="small" style={{ marginTop: 4 }} onClick={() => onRelease(r)} data-testid={`release-${r.id}`}>手动解除</Button>
      ) : null}
    </div>
  );
}
