import { notificationRefRoute } from '../lib/notifications';
import { useEffect } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { resyncAfterReconnect } from '../app/streamEvents';
import { IS_MOCK } from '../lib/env';
import { Alert, Button, Segmented, Select, Space, Tabs, Tag } from 'antd';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { ENUMS, type NotificationKind } from '../api/enums';
import { useMarkAllNotificationsRead, useNotificationPages, type NotificationFilter } from '../api/notificationQueries';
import { useMarkNotificationRead, useUnreadCount } from '../api/queries';
import type { Notification } from '../api/types';
import { useNotificationSync, useStreamPolling, useStreamStatus, type StreamStatus } from '../app/streamContext';
import { CursorPager } from '../components/CursorPager';
import { ErrorBox } from '../components/common';
import { CardDisclaimer } from '../components/RiskDisclosure';
import { NOTIFY_KIND, SEVERITY, SEVERITY_TEXT, TARGET_TYPE } from '../i18n/labels';
import { fmtTime } from '../lib/format';
import { notificationRoute } from '../lib/notificationTarget';

const KINDS = ENUMS.notification_kind as readonly NotificationKind[];
const parseKind = (v: string | null): NotificationKind | null => (v && (KINDS as readonly string[]).includes(v) ? (v as NotificationKind) : null);

const STREAM_TEXT: Record<StreamStatus, { text: string; color: string; tip: string }> = {
  open: { text: '实时推送已连接', color: 'green', tip: '新通知通过 SSE 推送，未读数实时更新' },
  connecting: { text: '正在连接实时推送', color: 'blue', tip: '连续3次建流失败前不启动定时轮询' },
  retrying: { text: '实时推送已断开，正在重连', color: 'orange', tip: '连续3次建流失败后按15秒轮询未读数；重连时带上最后收到的事件 id 补发漏掉的事件' },
  closed: { text: '实时推送已停止', color: 'default', tip: '会话失效、接口未实现或已停止；未读数按 15 秒间隔轮询' },
  off: { text: '实时推送未启用', color: 'default', tip: '未读数按 15 秒间隔轮询' },
};

function StreamBadge() {
  const s = useStreamStatus(); const polling = useStreamPolling();
  const x = STREAM_TEXT[s];
  return <Tag color={x.color} title={`${x.tip}；${polling ? '15秒轮询已启用' : '轮询未启用：连接成功或连续失败未达3次'}`} data-testid="stream-status" data-state={s}>{x.text}</Tag>;
}

function NotificationRecovery() {
  const sync = useNotificationSync(); const qc = useQueryClient();
  const retry = useMutation({ mutationFn: () => resyncAfterReconnect(qc) }); const { reset } = retry;
  useEffect(() => { reset(); }, [sync, reset]);
  const failed = (sync === 'error' && !retry.isSuccess) || retry.isError;
  return <div data-testid="notification-recovery" className="small" style={{ marginBottom: 8 }}>
    {failed ? <Alert type="warning" title="离线补读失败，数据可能不完整" action={<Button size="small" loading={retry.isPending} onClick={() => retry.mutate()}>重新补读</Button>} /> : <span className="muted">{sync === 'loading' || retry.isPending ? '正在补读本人未读列表及权威未读数…' : sync === 'ready' || retry.isSuccess ? '已补读本人未读列表及未读数；一行一个未读单位，不按合并次数累加。' : '尚未完成离线补读；未读数来自 /notifications/unread-count。'}</span>}
  </div>;
}

function NotificationRow({ n }: { n: Notification }) {
  const mark = useMarkNotificationRead();
  const navigate = useNavigate();
  const route = notificationRoute(n.target);
  const open = () => {
    if (!n.read_at) mark.mutate(n.id);
    if (route) navigate(route);
  };
  return (
    <div className={`nc-item ${n.read_at ? 'read' : 'unread'}`} data-testid={`nc-item-${n.id}`}>
      <div className="nc-main" role={route ? 'link' : undefined} tabIndex={route ? 0 : undefined}
        onClick={route ? open : undefined} onKeyDown={route ? (e) => { if (e.key === 'Enter') open(); } : undefined}
        style={{ cursor: route ? 'pointer' : 'default' }}>
        <div className="nc-head">
          {!n.read_at ? <span className="nc-dot" aria-label="未读" /> : null}
          <Tag color={SEVERITY[n.severity]}>{SEVERITY_TEXT[n.severity]}</Tag>
          <Tag>{NOTIFY_KIND[n.kind]}</Tag>
          <Tag data-testid={`nc-merged-${n.id}`}>合并 {n.merged_count} 次变化</Tag>
          {n.name ? <span>{n.name} <span className="mono muted">{n.security_code}</span></span> : null}
          <span className="spacer" />
          <span className="mono muted small">{fmtTime(n.created_at)}</span>
        </div>
        <div className="nc-title">{n.title}</div>
        <div className="muted small" data-testid={`nc-updated-${n.id}`}>最近更新 {fmtTime(n.updated_at)}（北京时间）</div>
        {n.body ? <div className="muted small nc-body">{n.body}</div> : null}
        <details className="small" data-testid={`nc-refs-${n.id}`} onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
          <summary>合并引用（{n.refs.length} 条，最多20条）</summary>
          {n.refs.length ? <ul>{n.refs.slice(0, 20).map((ref) => <li key={`${ref.type}:${ref.id}`}>{notificationRefRoute(ref) ? <Link to={notificationRefRoute(ref)!}>计划条件引用 {ref.id}</Link> : <span>{ref.type}</span>} · {fmtTime(ref.at)}</li>)}</ul> : <p>旧记录或本条通知未附引用；不补造出处。</p>}
          <span className="muted">引用只跳转服务端提供的站内深链；route=null只显示类型与时间，不定位、不跳转。 </span><Link to="/signals">查看完整盘中规则事件</Link>
        </details>
        <div className="small nc-target">
          {route ? <span className="link" data-testid={`nc-go-${n.id}`}>查看{TARGET_TYPE[n.target.type]} ›</span>
            : n.target.type === 'none' ? null : <span className="muted" data-testid={`nc-noroute-${n.id}`}>{TARGET_TYPE[n.target.type]}（链接不可用）</span>}
          {n.read_at ? <span className="muted">　已读 {fmtTime(n.read_at).slice(5)}</span> : null}
        </div>
      </div>
      {!n.read_at ? (
        <Button size="small" type="link" loading={mark.isPending} onClick={() => mark.mutate(n.id)} data-testid={`nc-read-${n.id}`}>标为已读</Button>
      ) : null}
    </div>
  );
}

function NotificationList() {
  const [sp, setSp] = useSearchParams();
  const f: NotificationFilter = { unread: sp.get('unread') === '1', kind: parseKind(sp.get('kind')) };
  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v);
    else next.delete(k);
    setSp(next, { replace: true });
  };
  const list = useNotificationPages(f);
  const unread = useUnreadCount();
  const readAll = useMarkAllNotificationsRead();
  const count = unread.data?.count;
  return (
    <div data-testid="nc-list">
      <Space wrap style={{ marginBottom: 12 }}>
        <Segmented
          size="small"
          value={f.unread ? 'unread' : 'all'}
          onChange={(v) => setParam('unread', v === 'unread' ? '1' : '')}
          options={[{ value: 'all', label: '全部' }, { value: 'unread', label: `未读（${count ?? '—'}）` }]}
          data-testid="nc-filter-unread"
        />
        <Select<NotificationKind>
          size="small"
          allowClear
          style={{ width: 180 }}
          placeholder="全部类型"
          value={f.kind ?? undefined}
          onChange={(v) => setParam('kind', v ?? '')}
          options={KINDS.map((k) => ({ value: k, label: NOTIFY_KIND[k] }))}
          data-testid="nc-filter-kind"
        />
        <Button size="small" disabled={count === undefined || count === 0} loading={readAll.isPending} onClick={() => readAll.mutate()} data-testid="nc-read-all">全部标为已读</Button>
        {readAll.isError ? <span className="error-text small" role="alert">操作失败，请稍后重试</span> : null}
      </Space>
      {unread.isError ? <ErrorBox error={unread.error} /> : null}
      {list.isError ? <ErrorBox error={list.error} /> : null}
      {list.isPending ? <div className="muted small">加载中…</div> : !list.items.length && !list.isError ? (
        <div className="muted small" data-testid="nc-empty">{f.unread || f.kind ? '没有符合条件的通知' : '暂无通知'}</div>
      ) : (
        <div className="nc-items panel">{list.items.map((n) => <NotificationRow key={n.id} n={n} />)}</div>
      )}
      <CursorPager query={list} loaded={list.items.length} testId="nc-pager" />
    </div>
  );
}

/** 契约 §7.8 只列了路径，没有结构：前端不猜接口、不发请求 */
function PendingContract({ title, path, lines, testId }: { title: string; path: string; lines: string[]; testId: string }) {
  return (
    <div data-testid={testId}>
      <Alert
        type="info" showIcon
        title={<span>{title} <Tag color="gold">待契约</Tag></span>}
        description={
          <div className="small">
            <div>免打扰与渠道绑定的完整请求 / 响应结构尚未冻结（<code>{path}</code>）；已定的 intraday_cadence 只影响盘中推送节奏，本轮未提供设置入口，也不保存任何偏好。</div>
            <div style={{ marginTop: 6 }}>结构确定后这里将提供：</div>
            <ul style={{ margin: '4px 0 0 18px' }}>{lines.map((l) => <li key={l}>{l}</li>)}</ul>
          </div>
        }
      />
    </div>
  );
}

const CHANNEL_TEXT: Record<string, string> = { in_app: '站内（当前唯一生效的渠道）', email: '邮件', wecom_app: '企业微信应用（预留）' };

/** T-F14 通知中心（契约 §7.8、§8、§5.1） */
export function NotificationsPage() {
  const [sp, setSp] = useSearchParams();
  const tab = sp.get('tab') === 'preferences' || sp.get('tab') === 'channels' ? sp.get('tab')! : 'list';
  const setTab = (t: string) => {
    const next = new URLSearchParams(sp);
    if (t === 'list') next.delete('tab');
    else next.set('tab', t);
    setSp(next, { replace: true });
  };
  return (
    <div className="page-scroll page" data-testid="notifications-page">
      <h2 className="page-title">通知中心 <StreamBadge /></h2>
      <div className="muted small" style={{ marginBottom: 8 }}>
        候选信号变化、失效条件、计划条件、日报与系统消息都汇总在这里；点击通知跳到对应页面并标为已读。通知内容只是规则信号的提示，不替你做决定。
      </div>
      <Alert type="info" style={{ marginBottom: 8 }} title={IS_MOCK ? '示例数据 · 提醒流仅为MSW模拟，非真实通知' : '提醒流尚未真实联调，SSE仅在示例模式启用'} description="T-A31/T-A32：按version防重、reset全量补读；3秒起退避、45秒无字节断开、稳定60秒归零、连续3次建流失败转15秒轮询。本轮不提供外部渠道。" />
      <NotificationRecovery />
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          { key: 'list', label: '通知', children: <NotificationList /> },
          {
            key: 'preferences', label: '通知偏好 · 免打扰',
            children: (
              <PendingContract
                testId="nc-pref-placeholder" title="通知偏好与免打扰" path="GET/PUT /notification-preferences"
                lines={['按通知类型（候选信号变化、失效条件、计划条件、日报等）开关', '按重要程度（重要 / 关注 / 提示）选择是否提醒', '免打扰时段']}
              />
            ),
          },
          {
            key: 'channels', label: '通知渠道',
            children: (
              <div>
                <PendingContract
                  testId="nc-channel-placeholder" title="通知渠道绑定" path="GET/PUT /channels"
                  lines={['渠道绑定与验证', '各渠道接收哪些通知']}
                />
                <div className="small" style={{ marginTop: 12 }} data-testid="nc-channel-enum">
                  <div className="muted">契约 §3 已定义的渠道取值（仅展示，不可设置）：</div>
                  {ENUMS.channel.map((c) => <Tag key={c} style={{ marginTop: 4 }}>{c} · {CHANNEL_TEXT[c] ?? c}</Tag>)}
                </div>
              </div>
            ),
          },
        ]}
      />
      <CardDisclaimer />
    </div>
  );
}
