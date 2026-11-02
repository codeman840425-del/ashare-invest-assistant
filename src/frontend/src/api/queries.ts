import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';
import type {
  BarsResponse, CandidateSignal, DailyReport, DailyReportListItem, HorizonAssessment, Me, NonExecutableReason, Notification, Paged, Portfolio,
  SignalEvent, Suggestion, SuggestionListItem, TerminalResponse, TerminalScope, TodayResponse, UnreadCount,
} from './types';
import type { BarAdjust, BarFreq } from './enums';

/** 查询键集中定义，SSE 增量更新时按键失效 */
export const qk = {
  me: ['me'] as const,
  terminal: (scope: TerminalScope) => ['terminal', scope] as const,
  today: ['today'] as const,
  bars: (code: string, freq: BarFreq, adjust: BarAdjust) => ['bars', code, freq, adjust] as const,
  suggestion: (id: string) => ['suggestion', id] as const,
  candidateSignals: (code: string) => ['candidate-signals', code] as const,
  candidateSignal: (id: string) => ['candidate-signal', id] as const,
  reasons: (signalId: string) => ['non-executable-reasons', 'signal', signalId] as const,
  /** v0.2.3 #17：按建议卡批量取原因（失效时用前缀 ['non-executable-reasons']） */
  reasonsBySuggestion: (suggestionId: string) => ['non-executable-reasons', 'suggestion', suggestionId] as const,
  signals: ['signals'] as const,
  /** v0.2.3 #6：分时标记必须带 security_code（与 since） */
  signalsOf: (code: string, since: string) => ['signals', code, since] as const,
  suggestions: (status: string) => ['suggestions', status] as const,
  notifications: ['notifications'] as const,
  unread: ['notifications', 'unread-count'] as const,
  dailyReports: ['daily-reports'] as const,
  dailyReport: (date: string) => ['daily-report', date] as const,
  portfolio: (accountId?: string) => ['portfolio', accountId ?? 'all'] as const,
  horizon: (code: string) => ['horizon-assessments', code] as const,
};

/**
 * Me.data_licence_status 驱动全站证书横幅（契约 v0.2.6 #8）。SSE data_licence 事件接入前，
 * 用 60 秒低频轮询兜底，会话中途证书被判为额度用完/暂停时横幅也能出现（评审 T-F22a M1）。
 */
export const ME_POLL_MS = 60_000;
export const useMe = () =>
  useQuery({ queryKey: qk.me, queryFn: ({ signal }) => apiGet<Me>('/me', undefined, signal), refetchInterval: ME_POLL_MS });

export const useTerminal = (scope: TerminalScope) =>
  useQuery({
    queryKey: qk.terminal(scope),
    queryFn: ({ signal }) => apiGet<TerminalResponse>('/terminal', { scope }, signal),
    placeholderData: keepPreviousData,
    // SSE 未接入前的兜底轮询：契约 §8 要求 ≥ 15 秒
    refetchInterval: 15_000,
  });

/** 评审 T-F08 m6：收盘后与非交易日数据基本不变，轮询放慢到 60 秒；其余时段 15 秒（契约 §8 要求 ≥ 15 秒） */
export const todayPollMs = (session: TodayResponse['session'] | undefined) => (session === 'closed' || session === 'non_trading_day' ? 60_000 : 15_000);

/** T-F08：首页聚合 GET /today（契约 §7.3，弱 ETag；SSE 未接入前按 §8 带 If-None-Match 轮询） */
export const useToday = () =>
  useQuery({
    queryKey: qk.today,
    queryFn: ({ signal }) => apiGet<TodayResponse>('/today', undefined, signal),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => todayPollMs(query.state.data?.session),
  });

export const useBars = (code: string | undefined, freq: BarFreq) => {
  const adjust: BarAdjust = freq === '1m' ? 'none' : 'qfq';
  return useQuery({
    queryKey: qk.bars(code ?? '', freq, adjust),
    queryFn: ({ signal }) =>
      apiGet<BarsResponse>(`/securities/${encodeURIComponent(code!)}/bars`, { freq, adjust, limit: freq === '1m' ? 240 : 120 }, signal),
    enabled: !!code,
  });
};

export const useSuggestion = (id: string | undefined) =>
  useQuery({
    queryKey: qk.suggestion(id ?? ''),
    queryFn: ({ signal }) => apiGet<Suggestion>(`/suggestions/${encodeURIComponent(id!)}`, undefined, signal),
    enabled: !!id,
  });

export const useCandidateSignals = (code: string | undefined) =>
  useQuery({
    queryKey: qk.candidateSignals(code ?? ''),
    queryFn: ({ signal }) => apiGet<Paged<CandidateSignal>>('/candidate-signals', { security_code: code, limit: 50 }, signal),
    enabled: !!code,
  });

export const useReasons = (signalId: string | null | undefined) =>
  useQuery({
    queryKey: qk.reasons(signalId ?? ''),
    queryFn: ({ signal }) => apiGet<Paged<NonExecutableReason>>('/non-executable-reasons', { status: 'active', signal_id: signalId }, signal),
    enabled: !!signalId,
  });

/** 分时标记：只取本证券、本交易日以来的规则事件（v0.2.3 #6，不再拉全市场再过滤） */
export const useSecuritySignals = (code: string | undefined, tradeDate: string | null) => {
  const since = tradeDate ? `${tradeDate}T09:15:00+08:00` : '';
  return useQuery({
    queryKey: qk.signalsOf(code ?? '', since),
    queryFn: ({ signal }) => apiGet<Paged<SignalEvent>>('/signals', { security_code: code, since, limit: 200 }, signal),
    enabled: !!code && !!since,
    refetchInterval: 15_000,
  });
};

export const useSignals = () =>
  useQuery({ queryKey: qk.signals, queryFn: ({ signal }) => apiGet<Paged<SignalEvent>>('/signals', { limit: 50 }, signal), refetchInterval: 15_000 });

export const useNotifications = () =>
  useQuery({ queryKey: qk.notifications, queryFn: ({ signal }) => apiGet<Paged<Notification>>('/notifications', { limit: 50 }, signal) });

export const useUnreadCount = () =>
  useQuery({ queryKey: qk.unread, queryFn: ({ signal }) => apiGet<UnreadCount>('/notifications/unread-count', undefined, signal), refetchInterval: 30_000 });

export const useDailyReports = () =>
  useQuery({ queryKey: qk.dailyReports, queryFn: ({ signal }) => apiGet<Paged<DailyReportListItem>>('/daily-reports', { limit: 20 }, signal) });

/**
 * T-F13：日报日期列表按 §1.2 游标逐页加载（日期选择器里“加载更早”）。
 * 与 useDailyReports 分开缓存键，避免改变首页跳转所用的单页结构。
 */
export const useDailyReportPages = (limit = 20) =>
  useInfiniteQuery({
    queryKey: [...qk.dailyReports, 'pages', limit],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      apiGet<Paged<DailyReportListItem>>('/daily-reports', pageParam ? { limit, cursor: pageParam } : { limit }, signal),
    getNextPageParam: (last) => last.next_cursor,
  });

export const useDailyReport = (date: string | undefined) =>
  useQuery({
    queryKey: qk.dailyReport(date ?? ''),
    queryFn: ({ signal }) => apiGet<DailyReport>(`/daily-reports/${encodeURIComponent(date!)}`, undefined, signal),
    enabled: !!date,
  });

/** GET /portfolio?account_id=（v0.2.4 #14）：不传 account_id 时合并全部账户 */
export const usePortfolio = (accountId?: string) =>
  useQuery({ queryKey: qk.portfolio(accountId), queryFn: ({ signal }) => apiGet<Portfolio>('/portfolio', accountId ? { account_id: accountId } : undefined, signal) });

export function useMarkNotificationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiPost<void>(`/notifications/${encodeURIComponent(id)}/read`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.notifications });
    },
  });
}

/**
 * 一张建议卡下全部候选信号的原因：一次请求、不分页（v0.2.3 #17）。
 * v0.2.9 #12：建议卡原因列表要显示已解除的原因，传 status=all（默认只有 active）；终端右栏只取 active。
 */
export const useSuggestionReasons = (suggestionId: string | undefined) =>
  useQuery({
    queryKey: qk.reasonsBySuggestion(suggestionId ?? ''),
    queryFn: ({ signal }) => apiGet<{ items: NonExecutableReason[] }>('/non-executable-reasons', { status: 'all', suggestion_id: suggestionId }, signal),
    enabled: !!suggestionId,
  });

export const useSuggestions = () =>
  useQuery({
    queryKey: qk.suggestions('active'),
    queryFn: ({ signal }) => apiGet<Paged<SuggestionListItem>>('/suggestions', { status: 'active', limit: 100 }, signal),
  });

/** v0.2.2 周期分类结果（v0.2.3：evidence 取自本响应自带的 evidence[]） */
export const useHorizonAssessment = (code: string | undefined) =>
  useQuery({
    queryKey: qk.horizon(code ?? ''),
    queryFn: ({ signal }) => apiGet<HorizonAssessment>('/horizon-assessments', { security_code: code! }, signal),
    enabled: !!code,
  });
