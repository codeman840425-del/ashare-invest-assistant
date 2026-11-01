import { Navigate, type RouteObject } from 'react-router';
import { ReportRedirect } from '../pages/ReportRedirect';
import { AppShell } from '../components/AppShell';
import { TerminalPage } from '../features/terminal/TerminalPage';
import { SuggestionDetailPage } from '../pages/SuggestionDetailPage';
import { SuggestionIndex } from '../pages/SuggestionIndex';
import { DailyReportIndex, DailyReportPage } from '../pages/DailyReportPage';
import { NotFoundPage, PlaceholderPage } from '../pages/PlaceholderPage';
import { AdminGate } from './AdminGate';
import { LoginPage } from '../pages/auth/LoginPage';
import { RegisterPage } from '../pages/auth/RegisterPage';
import { AccountStatusPage } from '../pages/auth/AccountStatusPage';
import { OnboardingPage } from '../pages/auth/OnboardingPage';
import { ProfilePage } from '../pages/settings/ProfilePage';
import { AdminUsersPage } from '../pages/admin/AdminUsersPage';
import { PortfolioPage } from '../pages/portfolio/PortfolioPage';
import { ImportWizardPage } from '../pages/portfolio/ImportWizardPage';

/** 契约 §4 / plan 规划的页面；未实现的先给占位 */
export const PLACEHOLDERS: [string, string][] = [
  ['today', '今日关注'],
  ['market', '市场概览'],
  ['stocks/:code', '个股'],
  ['strategies', '策略库'],
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
  { path: '/register', element: <RegisterPage /> },
  { path: '/account-status', element: <AccountStatusPage /> },
  // 403 CONSENT_REQUIRED 的落点：风险揭示等条款同意 + 风险测评
  { path: '/onboarding', element: <OnboardingPage /> },
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/terminal" replace /> },
      { path: 'terminal', element: <TerminalPage /> },
      { path: 'suggestions', element: <SuggestionIndex /> },
      { path: 'suggestions/:id', element: <SuggestionDetailPage /> },
      { path: 'daily-reports', element: <DailyReportIndex /> },
      { path: 'daily-reports/:date', element: <DailyReportPage /> },
      { path: 'reports', element: <ReportRedirect /> },
      { path: 'reports/:date', element: <ReportRedirect /> },
      { path: 'portfolio', element: <PortfolioPage /> },
      { path: 'portfolio/import', element: <ImportWizardPage /> },
      { path: 'portfolio/import/:batchId', element: <ImportWizardPage /> },
      { path: 'settings', element: <Navigate to="/settings/profile" replace /> },
      { path: 'settings/profile', element: <ProfilePage /> },
      ...PLACEHOLDERS.map(([path, title]) => ({ path, element: <PlaceholderPage title={title} /> })),
      { path: 'admin', element: <AdminGate><Navigate to="/admin/users" replace /></AdminGate> },
      { path: 'admin/users', element: <AdminGate><AdminUsersPage /></AdminGate> },
      { path: 'admin/*', element: <AdminGate><PlaceholderPage title="管理后台" /></AdminGate> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];
