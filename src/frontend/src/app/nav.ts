/** 顶部导航（/reports 统一为 /daily-reports，见遗留问题 #2） */
export const NAV_MAIN = [
  { path: '/terminal', label: '交易终端' },
  { path: '/suggestions', label: '候选信号卡' },
  { path: '/daily-reports', label: '盘后日报' },
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
];
/** 管理后台入口只对 role=admin 显示（评审 M4；契约 §1.3：非管理员访问 /admin/* 一律 404） */
export const NAV_ADMIN = { path: '/admin', label: '管理后台' };
export const navMoreFor = (role: string | undefined) => (role === 'admin' ? [...NAV_MORE, NAV_ADMIN] : NAV_MORE);

