import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';
import type {
  BarsResponse, CandidateSignal, DailyReport, DailyReportListItem, HorizonAssessment, Me, NonExecutableReason, Notification, Paged, Portfolio,
  SignalEvent, Suggestion, SuggestionListItem, TerminalResponse, TerminalScope, UnreadCount,
} from './types';
import type { BarAdjust, BarFreq } from './enums';

/** 查询键集中定义，SSE 增量更新时按键失效 */
export const qk = {
  me: ['me'] as const,
  terminal: (scope: TerminalScope) => ['terminal', scope] as const,
  bars: (code: string, freq: BarFreq, adjust: BarAdjust) => ['bars', code, freq, adjust] as const,
  suggestion: (id: string) => ['suggestion', id] as const,
  candidateSignals: (code: string) => ['candidate-signals', code] as const,
  candidateSignal: (id: string) => ['candidate-signal', id] as const,
  reasons: (signalId: string) => ['non-executable-reasons', signalId] as const,
  signals: ['signals'] as const,
  notifications: ['notifications'] as const,
  unread: ['notifications', 'unread-count'] as const,
  dailyReports: ['daily-reports'] as const,
  dailyReport: (date: string) => ['daily-report', date] as const,
  portfolio: ['portfolio'] as const,
  horizon: (code: string) => ['horizon-assessments', code] as const,
};

export const useMe = () => useQuery({ queryKey: qk.me, queryFn: ({ signal }) => apiGet<Me>('/me', undefined, signal) });

export const useTerminal = (scope: TerminalScope) =>
  useQuery({
    queryKey: qk.terminal(scope),
    queryFn: ({ signal }) => apiGet<TerminalResponse>('/terminal', { scope }, signal),
    placeholderData: keepPreviousData,
    // SSE 未接入前的兜底轮询：契约 §8 要求 ≥ 15 秒
    refetchInterval: 15_000,
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

export const useSignals = () =>
  useQuery({ queryKey: qk.signals, queryFn: ({ signal }) => apiGet<Paged<SignalEvent>>('/signals', { limit: 50 }, signal), refetchInterval: 15_000 });

export const useNotifications = () =>
  useQuery({ queryKey: qk.notifications, queryFn: ({ signal }) => apiGet<Paged<Notification>>('/notifications', { limit: 50 }, signal) });

export const useUnreadCount = () =>
  useQuery({ queryKey: qk.unread, queryFn: ({ signal }) => apiGet<UnreadCount>('/notifications/unread-count', undefined, signal), refetchInterval: 30_000 });

export const useDailyReports = () =>
  useQuery({ queryKey: qk.dailyReports, queryFn: ({ signal }) => apiGet<Paged<DailyReportListItem>>('/daily-reports', { limit: 20 }, signal) });

export const useDailyReport = (date: string | undefined) =>
  useQuery({
    queryKey: qk.dailyReport(date ?? ''),
    queryFn: ({ signal }) => apiGet<DailyReport>(`/daily-reports/${encodeURIComponent(date!)}`, undefined, signal),
    enabled: !!date,
  });

export const usePortfolio = () => useQuery({ queryKey: qk.portfolio, queryFn: ({ signal }) => apiGet<Portfolio>('/portfolio', undefined, signal) });

export function useMarkNotificationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiPost<void>(`/notifications/${encodeURIComponent(id)}/read`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.notifications });
    },
  });
}

/** 全部 active 的不可执行原因（终端右栏按 signal_id 本地分组，避免逐条请求） */
export const useActiveReasons = () =>
  useQuery({
    queryKey: qk.reasons('*'),
    queryFn: ({ signal }) => apiGet<Paged<NonExecutableReason>>('/non-executable-reasons', { status: 'active', limit: 200 }, signal),
  });

export const useSuggestions = () =>
  useQuery({
    queryKey: ['suggestions', 'active'] as const,
    queryFn: ({ signal }) => apiGet<Paged<SuggestionListItem>>('/suggestions', { status: 'active', limit: 100 }, signal),
  });

/** v0.2.2 周期分类结果 */
export const useHorizonAssessment = (code: string | undefined) =>
  useQuery({
    queryKey: qk.horizon(code ?? ''),
    queryFn: ({ signal }) => apiGet<HorizonAssessment>('/horizon-assessments', { security_code: code! }, signal),
    enabled: !!code,
  });
