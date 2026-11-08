import { additionalSignalInstances } from '../../lib/signalEvents';
import { Tabs, Tag } from 'antd';
import { useNavigate } from 'react-router';
import { useDailyReports, useMarkNotificationRead, useNotifications, useSignals } from '../../api/queries';
import { NOTIFY_KIND, RECONCILIATION, REGIME, SEVERITY, SIGNAL_KIND } from '../../i18n/labels';
import { notificationRoute } from '../../lib/notificationTarget';
import { fmtTime } from '../../lib/format';

/** 底部面板：盘中规则事件（/signals，不含动作建议）、通知、日报 */
export function BottomPanel({ selected, onSelect }: { selected: string | null; onSelect: (code: string) => void }) {
  const navigate = useNavigate();
  const signals = useSignals();
  const notes = useNotifications();
  const reports = useDailyReports();
  const mark = useMarkNotificationRead();
  const unread = (notes.data?.items ?? []).filter((n) => !n.read_at).length;
  return (
    <section className="panel bottom-tabs" data-testid="bottom-panel">
      <Tabs
        size="small"
        items={[
          {
            key: 'signals',
            label: `盘中规则事件 (${signals.data?.items.length ?? 0})`,
            children: (
              <div className="bottom-scroll">
                {(signals.data?.items ?? []).map((e) => (
                  <div key={e.signal_event_id} className={`event-row ${e.security_code === selected ? 'hl' : ''}`} onClick={() => onSelect(e.security_code)}>
                    <span className="mono muted">{fmtTime(e.at).slice(11)}</span>
                    <span className="ev-name">{e.name}</span>
                    <Tag className="ev-kind">{SIGNAL_KIND[e.kind]}</Tag>
                    <span className="ev-text">{e.message}</span>
                    {additionalSignalInstances(e) ? <Tag data-testid={`signal-instances-${e.signal_event_id}`}>{additionalSignalInstances(e)}</Tag> : null}
                    {e.price ? <span className="mono muted">@ {e.price}</span> : null}
                  </div>
                ))}
              </div>
            ),
          },
          {
            key: 'notifications',
            label: `通知${unread ? ` (${unread})` : ''}`,
            children: (
              <div className="bottom-scroll">
                {(notes.data?.items ?? []).map((n) => (
                  <div
                    key={n.id}
                    className={`list-row ${n.read_at ? 'read' : ''}`}
                    onClick={() => {
                      if (!n.read_at) mark.mutate(n.id);
                      const route = notificationRoute(n.target);
                      if (route) navigate(route);
                    }}
                  >
                    <span className="mono muted">{fmtTime(n.created_at).slice(5, 16)}</span>
                    <Tag color={SEVERITY[n.severity]} className="ev-kind">{NOTIFY_KIND[n.kind]}</Tag>
                    <span className="ev-text">{n.title}</span>
                  </div>
                ))}
              </div>
            ),
          },
          {
            key: 'reports',
            label: '盘后日报',
            children: (
              <div className="bottom-scroll">
                {(reports.data?.items ?? []).map((r) => (
                  <div key={r.date} className="list-row" onClick={() => navigate(`/daily-reports/${r.date}`)}>
                    <span className="mono">{r.date}</span>
                    <span className="muted">生成 {fmtTime(r.generated_at).slice(11)}</span>
                    <span>大盘 {r.regime ? REGIME[r.regime] : '—'}</span>
                    <Tag color={RECONCILIATION[r.reconciliation_status].color}>{RECONCILIATION[r.reconciliation_status].text}</Tag>
                    <span className="muted">{r.stock_count} 只</span>
                  </div>
                ))}
              </div>
            ),
          },
        ]}
      />
    </section>
  );
}
