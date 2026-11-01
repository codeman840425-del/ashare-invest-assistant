import { Navigate, type RouteObject } from 'react-router';
import { ReportRedirect } from '../pages/ReportRedirect';
import { AppShell } from '../components/AppShell';
import { TerminalPage } from '../features/terminal/TerminalPage';
import { SuggestionDetailPage } from '../pages/SuggestionDetailPage';
import { SuggestionIndex } from '../pages/SuggestionIndex';
import { DailyReportIndex, DailyReportPage } from '../pages/DailyReportPage';
import { NotFoundPage, PlaceholderPage } from '../pages/PlaceholderPage';
import { AdminGate } from './AdminGate';

/** 契约 §4 / plan 规划的页面；未实现的先给占位 */
export const PLACEHOLDERS: [string, string][] = [
  ['today', '今日关注'],
  ['portfolio', '账户持仓'],
  ['portfolio/import', '交割单导入'],
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
  ['settings', '设置'],
  ['candidates', '候选池'],
  ['discover', '发现'],
];

export const routes: RouteObject[] = [
  { path: '/login', element: <PlaceholderPage title="登录" /> },
  { path: '/register', element: <PlaceholderPage title="注册（邀请制）" /> },
  // 403 CONSENT_REQUIRED 的落点（风险测评 + 风险揭示同意，T-F02 实现）
  { path: '/onboarding', element: <PlaceholderPage title="开通引导：风险测评与风险揭示同意" /> },
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
      ...PLACEHOLDERS.map(([path, title]) => ({ path, element: <PlaceholderPage title={title} /> })),
      { path: 'admin/*', element: <AdminGate><PlaceholderPage title="管理后台" /></AdminGate> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];
