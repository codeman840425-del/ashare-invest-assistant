import { Alert, Badge, Button, Dropdown, List, Popover, Tag } from 'antd';
import { BellOutlined, DownOutlined } from '@ant-design/icons';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router';
import { useMe, useMarkNotificationRead, useNotifications, useUnreadCount } from '../api/queries';
import { NOTIFY_KIND, SEVERITY } from '../i18n/labels';
import { IS_MOCK } from '../lib/env';
import { CONTRACT_VERSION } from '../api/enums';
import { fmtTime } from '../lib/format';
import { RiskDisclosure } from './RiskDisclosure';
import { DesktopGuard } from './DesktopGuard';
import { SecuritySearch } from './SecuritySearch';
import { navMoreFor, NAV_MAIN } from '../app/nav';
import { useApiErrorRedirect } from '../app/useApiErrorRedirect';
import { useLogout } from '../api/accountQueries';
import { LicenceBanner } from './LicenceBanner';
import { StreamProvider } from '../app/StreamProvider';
import { notificationRoute } from '../lib/notificationTarget';

function NotificationPanel({ onNavigate }: { onNavigate: (route: string) => void }) {
  const { data } = useNotifications();
  const mark = useMarkNotificationRead();
  return (
    <div style={{ width: 400 }} data-testid="notification-panel">
      <List
        size="small"
        dataSource={data?.items ?? []}
        locale={{ emptyText: '暂无通知' }}
        renderItem={(n) => (
          <List.Item
            className={`notif-item ${n.read_at ? 'read' : ''}`}
            onClick={() => {
              if (!n.read_at) mark.mutate(n.id);
              // §5.1：按服务端 route 跳转；route 不是站内路径或与类型不符时按 type + id 拼（T-F14）
              const route = notificationRoute(n.target);
              if (route) onNavigate(route);
            }}
          >
            <div style={{ width: '100%' }}>
              <div className="notif-head">
                <Tag color={SEVERITY[n.severity]}>{NOTIFY_KIND[n.kind]}</Tag>
                <span className="muted mono">{fmtTime(n.created_at).slice(5)}</span>
              </div>
              <div className="notif-title">{n.title}</div>
            </div>
          </List.Item>
        )}
      />
      <div style={{ textAlign: 'right', paddingTop: 4 }}>
        <Button size="small" type="link" onClick={() => onNavigate('/notifications')}>通知中心 ›</Button>
      </div>
    </div>
  );
}

/** 登录后的外壳：挂 SSE 连接（契约 §8，T-F14），连接状态决定未读数 / 终端 / 首页是否轮询 */
export function AppShell() {
  return (
    <StreamProvider>
      <Shell />
    </StreamProvider>
  );
}

function Shell() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const unread = useUnreadCount();
  const me = useMe();
  const logout = useLogout();
  const { csrfExpired, dismissCsrf } = useApiErrorRedirect();
  const userMenu = [
    { key: '/settings/profile', label: '投资画像' },
    { key: '/settings/data-licence', label: '数据证书' },
    ...(me.data?.role === 'admin' ? [{ key: '/admin/users', label: '用户审核（管理）' }, { key: '/admin/ingest', label: '采集状态（管理）' }, { key: '/admin/data-licences', label: '数据证书（管理）' }] : []),
    { type: 'divider' as const },
    { key: 'logout', label: '退出登录', danger: true },
  ];
  const onUserMenu = ({ key }: { key: string }) => {
    if (key === 'logout') logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) });
    else navigate(key);
  };
  const navMore = navMoreFor(me.data?.role);
  const moreActive = navMore.some((n) => pathname === n.path || pathname.startsWith(n.path + '/'));
  return (
    <DesktopGuard>
      <div className="shell">
        <header className="topbar">
          <div className="brand" onClick={() => navigate('/terminal')}>
            <span className="logo">A</span>
            <span>投资研究与决策助手</span>
            {IS_MOCK ? <Tag color="gold" style={{ marginLeft: 8 }}>示例数据</Tag> : null}
          </div>
          <nav className="nav" aria-label="主导航">
            {NAV_MAIN.map((n) => (
              <NavLink key={n.path} to={n.path} className={({ isActive }) => (isActive ? 'active' : '')}>{n.label}</NavLink>
            ))}
            <Dropdown menu={{ items: navMore.map((n) => ({ key: n.path, label: n.label })), onClick: ({ key }) => navigate(key) }}>
              <a className={moreActive ? 'active' : ''}>更多 ▾</a>
            </Dropdown>
          </nav>
          <div className="topbar-right">
            <SecuritySearch />
            <Popover content={<NotificationPanel onNavigate={(r) => navigate(r)} />} title="通知" trigger="click" placement="bottomRight">
              <span data-testid="unread-badge" data-count={unread.data?.count ?? 0}>
                <Badge count={unread.data?.count ?? 0} size="small" offset={[-2, 2]}>
                  <Button size="small" type="text" icon={<BellOutlined style={{ fontSize: 16 }} />} aria-label="通知" />
                </Badge>
              </span>
            </Popover>
            <Dropdown menu={{ items: userMenu, onClick: onUserMenu }} trigger={['click']}>
              <a className="user" data-testid="user-menu">{me.data?.display_name ?? '—'} <DownOutlined style={{ fontSize: 10 }} /></a>
            </Dropdown>
          </div>
        </header>
        {IS_MOCK ? (
          <div className="sample-banner" data-testid="sample-banner">
            <b>示例数据</b>：当前由 MSW 返回虚构的证券、行情、持仓、策略与候选信号（按契约 {CONTRACT_VERSION} 结构），仅用于开发联调；不连接真实后端、不联网取数。
          </div>
        ) : null}
        <LicenceBanner status={me.data?.data_licence_status} onOpen={() => navigate('/settings/data-licence')} />
        {csrfExpired ? (
          <Alert
            type="warning" banner closable={{ onClose: dismissCsrf }} data-testid="csrf-refresh"
            title="页面已过期（安全令牌失效），刚才的操作没有提交。请刷新页面后重试。"
            action={<Button size="small" onClick={() => window.location.reload()} data-testid="csrf-refresh-btn">刷新页面</Button>}
          />
        ) : null}
        <main className="content">
          <Outlet />
        </main>
        <RiskDisclosure />
        {IS_MOCK ? <div className="watermark" aria-hidden>示例数据</div> : null}
      </div>
    </DesktopGuard>
  );
}
