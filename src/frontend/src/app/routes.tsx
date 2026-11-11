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
  ['strategies/:id', '策略详情'],
  ['strategy-instances', '我的策略实例'],
  ['restrictions', '禁投 / 冷静期 / 屏蔽'],
  ['reviews', '复盘'],
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
      // 评审 T-F08 m1：首页落在“今日关注”
      { index: true, element: <Navigate to="/today" replace /> },
      { path: 'today', lazy: lazyPage(() => import('../pages/today/TodayPage'), (m) => m.TodayPage) },
      { path: 'terminal', lazy: lazyPage(() => import('../features/terminal/TerminalPage'), (m) => m.TerminalPage) },
      { path: 'suggestions', lazy: lazyPage(() => import('../pages/SuggestionIndex'), (m) => m.SuggestionIndex) },
      { path: 'suggestions/:id', lazy: lazyPage(() => import('../pages/SuggestionDetailPage'), (m) => m.SuggestionDetailPage) },
      { path: 'risk-controls', lazy: lazyPage(() => import('../pages/RiskControlsPage'), (m) => m.RiskControlsPage) },
      { path: 'daily-reports', lazy: lazyPage(() => import('../pages/DailyReportPage'), (m) => m.DailyReportIndex) },
      { path: 'daily-reports/:date', lazy: lazyPage(() => import('../pages/DailyReportPage'), (m) => m.DailyReportPage) },
      { path: 'reports', element: <ReportRedirect /> },
      { path: 'reports/:date', element: <ReportRedirect /> },
      { path: 'portfolio', lazy: lazyPage(() => import('../pages/portfolio/PortfolioPage'), (m) => m.PortfolioPage) },
      { path: 'portfolio/import', lazy: lazyPage(() => import('../pages/portfolio/ImportWizardPage'), (m) => m.ImportWizardPage) },
      { path: 'portfolio/import/:batchId', lazy: lazyPage(() => import('../pages/portfolio/ImportWizardPage'), (m) => m.ImportWizardPage) },
      { path: 'market/overview', lazy: lazyPage(() => import('../pages/market/MarketPage'), (m) => m.MarketPage) },
      { path: 'market', lazy: lazyPage(() => import('../pages/market/MarketPage'), (m) => m.MarketPage) },
      { path: 'stocks/:code', lazy: lazyPage(() => import('../pages/stock/StockPage'), (m) => m.StockPage) },
      { path: 'settings', element: <Navigate to="/settings/profile" replace /> },
      { path: 'settings/profile', lazy: lazyPage(() => import('../pages/settings/ProfilePage'), (m) => m.ProfilePage) },
      { path: 'settings/data-licence', lazy: lazyPage(() => import('../pages/settings/DataLicencePage'), (m) => m.DataLicencePage) },
      { path: 'strategies', lazy: lazyPage(() => import('../pages/strategies/StrategiesPage'), (m) => m.StrategiesPage) },
      // F-04：策略知识卡列表与详情（契约 §7.4 /strategy-cards）
      { path: 'strategy-cards', lazy: lazyPage(() => import('../pages/strategies/StrategyCardsPage'), (m) => m.StrategyCardsPage) },
      { path: 'strategy-cards/:id', lazy: lazyPage(() => import('../pages/strategies/StrategyCardDetailPage'), (m) => m.StrategyCardDetailPage) },
      { path: 'candidate-signals', lazy: lazyPage(() => import('../pages/signals/CandidateSignalsPage'), (m) => m.CandidateSignalsPage) },
      { path: 'candidate-signals/:id', lazy: lazyPage(() => import('../pages/signals/CandidateSignalDetailPage'), (m) => m.CandidateSignalDetailPage) },
      { path: 'candidates', lazy: lazyPage(() => import('../pages/research/CandidatesPage'), (m) => m.CandidatesPage) },
      { path: 'candidates/:id', lazy: lazyPage(() => import('../pages/research/CandidateDetailPage'), (m) => m.CandidateDetailPage) },
      { path: 'plan-drafts', lazy: lazyPage(() => import('../pages/plans/PlanDraftsPage'), (m) => m.PlanDraftsPage) },
      // T-F23 裁定跟进：§7.7B 计划页与提醒页（替换原占位页；/plans/{id} 是 Notification.target 与 /today 计划条件的跳转目标）
      { path: 'plans', lazy: lazyPage(() => import('../pages/plans/PlansPage'), (m) => m.PlansPage) },
      { path: 'plans/:id', lazy: lazyPage(() => import('../pages/plans/PlanDetailPage'), (m) => m.PlanDetailPage) },
      { path: 'alerts', lazy: lazyPage(() => import('../pages/alerts/AlertsPage'), (m) => m.AlertsPage) },
      { path: 'alerts/:id', lazy: lazyPage(() => import('../pages/alerts/AlertDetailPage'), (m) => m.AlertDetailPage) },
      { path: 'plan-drafts/:id', lazy: lazyPage(() => import('../pages/plans/PlanDraftDetailPage'), (m) => m.PlanDraftDetailPage) },
      { path: 'notifications', lazy: lazyPage(() => import('../pages/NotificationsPage'), (m) => m.NotificationsPage) },
      ...PLACEHOLDERS.map(([path, title]) => ({ path, element: <PlaceholderPage title={title} /> })),
      { path: 'admin', element: <AdminGate><Navigate to="/admin/users" replace /></AdminGate> },
      {
        path: 'admin/users',
        lazy: async () => {
          const { AdminUsersPage } = await import('../pages/admin/AdminUsersPage');
          return { element: <AdminGate><AdminUsersPage /></AdminGate> };
        },
      },
      {
        path: 'admin/ingest',
        lazy: async () => {
          const { AdminIngestPage } = await import('../pages/admin/AdminIngestPage');
          return { element: <AdminGate><AdminIngestPage /></AdminGate> };
        },
      },
      {
        path: 'admin/data-licences',
        lazy: async () => {
          const { AdminDataLicencesPage } = await import('../pages/admin/AdminDataLicencesPage');
          return { element: <AdminGate><AdminDataLicencesPage /></AdminGate> };
        },
      },
      {
        path: 'admin/securities/reconciliation',
        lazy: async () => {
          const { AdminSecurityReconciliationPage } = await import('../pages/admin/AdminSecurityReconciliationPage');
          return { element: <AdminGate><AdminSecurityReconciliationPage /></AdminGate> };
        },
      },
      { path: 'admin/strategy-gates', lazy: async () => { const { AdminStrategyGatesPage } = await import('../pages/admin/AdminStrategyGatesPage'); return { Component: () => <AdminGate><AdminStrategyGatesPage /></AdminGate> }; } },
      { path: 'admin/*', element: <AdminGate><PlaceholderPage title="管理后台" /></AdminGate> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];
