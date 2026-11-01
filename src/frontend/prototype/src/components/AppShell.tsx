import { Badge, Button, Dropdown, Input, List, Popover, Tag } from 'antd';
import { BellOutlined, SearchOutlined } from '@ant-design/icons';
import type { ReactNode } from 'react';
import { NOTIFICATIONS, NOW } from '../mock/data';
import { NOTIFY_KIND, SEVERITY } from '../labels';
import { fmtTime, SampleWatermark } from './common';
import { go } from '../router';

export const NAV_MAIN = [
  { path: '/terminal', label: '交易终端' },
  { path: '/suggestions', label: '候选信号卡' },
  { path: '/reports', label: '盘后日报' },
  { path: '/today', label: '今日关注' },
  { path: '/portfolio', label: '账户持仓' },
  { path: '/strategies', label: '策略库' },
  { path: '/plans', label: '计划' },
  { path: '/risk-controls', label: '风控' },
];
export const NAV_MORE = [
  { path: '/market', label: '市场概览' },
  { path: '/candidate-signals', label: '候选信号列表' },
  { path: '/plan-drafts', label: '计划草案' },
  { path: '/strategy-instances', label: '我的策略实例' },
  { path: '/strategy-cards', label: '策略知识卡' },
  { path: '/restrictions', label: '禁投/冷静期/屏蔽' },
  { path: '/alerts', label: '提醒中心' },
  { path: '/reviews', label: '复盘' },
  { path: '/notifications', label: '通知中心' },
  { path: '/portfolio/import', label: '交割单导入' },
  { path: '/settings', label: '设置' },
  { path: '/admin', label: '管理后台' },
];

function NotificationPanel() {
  return (
    <div style={{ width: 380 }}>
      <List
        size="small"
        dataSource={NOTIFICATIONS}
        renderItem={(n) => (
          <List.Item
            className={`notif-item ${n.read ? 'read' : ''}`}
            onClick={() => n.link && (window.location.hash = n.link.slice(1))}
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
        <Button size="small" type="link" onClick={() => go('/notifications')}>通知中心 ›</Button>
      </div>
    </div>
  );
}

export function AppShell({ path, children }: { path: string; children: ReactNode }) {
  const unread = NOTIFICATIONS.filter((n) => !n.read).length;
  const active = (p: string) => path === p || path.startsWith(p + '/');
  const moreActive = NAV_MORE.some((n) => active(n.path));
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand" onClick={() => go('/terminal')}>
          <span className="logo">A</span>
          <span>投资研究与决策助手</span>
          <Tag color="gold" style={{ marginLeft: 8 }}>原型 · 示例数据</Tag>
        </div>
        <nav className="nav">
          {NAV_MAIN.map((n) => (
            <a key={n.path} className={active(n.path) ? 'active' : ''} href={`#${n.path}`}>{n.label}</a>
          ))}
          <Dropdown menu={{ items: NAV_MORE.map((n) => ({ key: n.path, label: n.label })), onClick: ({ key }) => go(key) }}>
            <a className={moreActive ? 'active' : ''}>更多 ▾</a>
          </Dropdown>
        </nav>
        <div className="topbar-right">
          <Input size="small" prefix={<SearchOutlined />} placeholder="代码/简称（示例）" style={{ width: 170 }} />
          <span className="market-clock mono">
            <span className="dot live" /> 盘中 {fmtTime(NOW)}
          </span>
          <Popover content={<NotificationPanel />} title="通知（示例）" trigger="click" placement="bottomRight">
            <Badge count={unread} size="small" offset={[-2, 2]}>
              <Button size="small" type="text" icon={<BellOutlined style={{ fontSize: 16 }} />} aria-label="通知" />
            </Badge>
          </Popover>
          <span className="user">示例用户</span>
        </div>
      </header>
      <div className="sample-banner">
        <b>示例数据</b>：本原型所有证券、行情、持仓、策略与信号均为虚构，仅用于确认界面风格与信息布局；不连接后端、不联网取数。
      </div>
      <main className="content">{children}</main>
      <footer className="risk-footer">
        本工具基于公开数据与您录入的信息、按透明规则生成<b>规则信号</b>，不构成投资建议，不保证收益；规则可能失效，交易决定与风险由您自行承担。
        <span className="muted"> · 图表由 TradingView Lightweight Charts 提供</span>
      </footer>
      <SampleWatermark />
      <div className="narrow-guard">请使用电脑端（宽度 ≥ 1280）访问</div>
    </div>
  );
}
