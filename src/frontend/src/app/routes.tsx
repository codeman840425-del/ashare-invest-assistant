import { Navigate, type RouteObject } from 'react-router';
import { ReportRedirect } from '../pages/ReportRedirect';
import { AppShell } from '../components/AppShell';
import { NotFoundPage, PlaceholderPage } from '../pages/PlaceholderPage';
import { AdminGate } from './AdminGate';
import { LoginPage } from '../pages/auth/LoginPage';

/**
 * 路由级懒加载（评审 T-F01/T-F02 m9）：终端（AG Grid）、详情 / 日报（图表）、持仓、导入向导、画像、管理端各自成块。
 * 登录页与外壳保持同步加载，保证首屏与 401 跳转不等网络。
 */
const lazyPage = <M,>(load: () => Promise<M>, pick: (m: M) => React.ComponentType) => async () => ({ Component: pick(await load()) });

/** 契约 §4 / plan 规划的页面；未实现的先给占位 */
export const PLACEHOLDERS: [string, string][] = [
  ['today', '今日关注'],
  ['strategies/:id', '策略详情'],
  ['strategy-cards', '策略知识卡'],
  ['strategy-instances', '我的策略实例'],
  ['candidate-signals', '候选信号列表'],
  ['candidate-signals/:id', '候选信号详情'],
  ['plan-drafts', '计划草案'],
  ['plan-drafts/:id', '计划草案详情'],
  ['plans', '计划'],
  ['risk-controls', '风控'],
  ['restrictions', '禁投 / 冷静期 / 屏蔽'],
  ['notifications', '通知中心'],
  ['alerts', '提醒中心'],
  ['reviews', '复盘'],
  ['candidates', '候选池'],
  ['discover', '发现'],
];

export const routes: RouteObject[] = [
  // 外壳之外：不挂全局 401/403 跳转，避免登录页自身循环
  { path: '/login', element: <LoginPage /> },
  { path: '/register', lazy: lazyPage(() => import('../pages/auth/RegisterPage'), (m) => m.RegisterPage) },
  { path: '/account-status', lazy: lazyPage(() => import('../pages/auth/AccountStatusPage'), (m) => m.AccountStatusPage) },
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/terminal" replace /> },
      { path: 'terminal', lazy: lazyPage(() => import('../features/terminal/TerminalPage'), (m) => m.TerminalPage) },
      { path: 'suggestions', lazy: lazyPage(() => import('../pages/SuggestionIndex'), (m) => m.SuggestionIndex) },
      { path: 'suggestions/:id', lazy: lazyPage(() => import('../pages/SuggestionDetailPage'), (m) => m.SuggestionDetailPage) },
      { path: 'daily-reports', lazy: lazyPage(() => import('../pages/DailyReportPage'), (m) => m.DailyReportIndex) },
      { path: 'daily-reports/:date', lazy: lazyPage(() => import('../pages/DailyReportPage'), (m) => m.DailyReportPage) },
      { path: 'reports', element: <ReportRedirect /> },
      { path: 'reports/:date', element: <ReportRedirect /> },
      { path: 'portfolio', lazy: lazyPage(() => import('../pages/portfolio/PortfolioPage'), (m) => m.PortfolioPage) },
      { path: 'portfolio/import', lazy: lazyPage(() => import('../pages/portfolio/ImportWizardPage'), (m) => m.ImportWizardPage) },
      { path: 'portfolio/import/:batchId', lazy: lazyPage(() => import('../pages/portfolio/ImportWizardPage'), (m) => m.ImportWizardPage) },
      { path: 'market', lazy: lazyPage(() => import('../pages/market/MarketPage'), (m) => m.MarketPage) },
      { path: 'stocks/:code', lazy: lazyPage(() => import('../pages/stock/StockPage'), (m) => m.StockPage) },
      { path: 'settings', element: <Navigate to="/settings/profile" replace /> },
      { path: 'settings/profile', lazy: lazyPage(() => import('../pages/settings/ProfilePage'), (m) => m.ProfilePage) },
      { path: 'settings/data-licence', lazy: lazyPage(() => import('../pages/settings/DataLicencePage'), (m) => m.DataLicencePage) },
      { path: 'strategies', lazy: lazyPage(() => import('../pages/strategies/StrategiesPage'), (m) => m.StrategiesPage) },
      ...PLACEHOLDERS.map(([path, title]) => ({ path, element: <PlaceholderPage title={title} /> })),
      { path: 'admin', element: <AdminGate><Navigate to="/admin/users" replace /></AdminGate> },
      {
        path: 'admin/users',
        lazy: async () => {
          const { AdminUsersPage } = await import('../pages/admin/AdminUsersPage');
          return { element: <AdminGate><AdminUsersPage /></AdminGate> };
        },
      },
      { path: 'admin/*', element: <AdminGate><PlaceholderPage title="管理后台" /></AdminGate> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];
