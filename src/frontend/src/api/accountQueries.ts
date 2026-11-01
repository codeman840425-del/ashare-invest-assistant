/**
 * T-F02 / T-F02a / T-F04 的查询与变更（TanStack Query）。路径与请求体对齐契约 §7.1 / §7.2 / §7.9。
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, apiGet, clearEtagCache, apiPatch, apiPost, apiPut, apiUpload, buildUrl, fetchUrl, newIdempotencyKey, setCsrfToken } from './client';
import type {
  AdminUser, AdminUserPatch, BrokerAccount, BrokerAccountCreate, ConsentRequest, ImportBatch, ImportConfirmRequest, ImportConfirmResponse,
  ImportFinding, ImportKind, ImportOptions, ImportRow, ImportUploadResponse, LoginRequest, LoginResponse, Profile, ProfileInput, Reconciliation,
  RegisterRequest, RegisterResponse, ResolveFindingRequest, RiskAssessmentRequest, RiskAssessmentResult, Trade, TradeCreate,
} from './accountTypes';
import type { AccountStatus } from './enums';
import type { Paged, RegistrationMeta } from './types';
import { qk } from './queries';

export const ak = {
  registration: ['meta', 'registration'] as const,
  profile: ['me', 'profile'] as const,
  adminUsers: (status: string, q: string) => ['admin', 'users', status, q] as const,
  accounts: ['accounts'] as const,
  trades: (accountId: string) => ['trades', accountId] as const,
  imports: (accountId: string) => ['imports', accountId] as const,
  batch: (id: string) => ['import', id] as const,
  rows: (id: string, filter: string) => ['import', id, 'rows', filter] as const,
  reconciliation: (accountId: string) => ['reconciliation', accountId] as const,
};

// ---------------- §7.1 ----------------
export const useRegistrationMode = () =>
  useQuery({ queryKey: ak.registration, queryFn: ({ signal }) => apiGet<RegistrationMeta>('/meta/registration', undefined, signal), staleTime: 60_000 });

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: LoginRequest) => apiPost<LoginResponse>('/auth/login', b),
    onSuccess: (r) => {
      setCsrfToken(r.csrf_token);
      // 登录后整体刷新：其他用户的缓存（含 ETag 条件请求缓存）不能沿用
      clearEtagCache();
      qc.clear();
      qc.setQueryData(qk.me, r.user);
    },
  });
}
export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<void>('/auth/logout'),
    // 无论服务端是否成功，本地都清掉 CSRF、ETag 与查询缓存
    onSettled: () => {
      setCsrfToken(null);
      clearEtagCache();
      qc.clear();
    },
  });
}
export const useRegister = () => useMutation({ mutationFn: (b: RegisterRequest) => apiPost<RegisterResponse>('/auth/register', b) });

export function useConsent() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (b: ConsentRequest) => apiPost<void>('/me/consents', b), onSuccess: () => qc.invalidateQueries({ queryKey: qk.me }) });
}
export function useRiskAssessment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: RiskAssessmentRequest) => apiPost<RiskAssessmentResult>('/me/risk-assessment', b),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.me }),
  });
}

/** 还没有画像时后端返回 404，这里转为 null（// [待契约确认] 404 还是 200 null） */
export const useProfile = () =>
  useQuery({
    queryKey: ak.profile,
    queryFn: async ({ signal }) => {
      try {
        return await apiGet<Profile>('/me/profile', undefined, signal);
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
  });
export function useSaveProfile() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (b: ProfileInput) => apiPut<Profile>('/me/profile', b), onSuccess: (p) => qc.setQueryData(ak.profile, p) });
}

// ---------------- §7.9 管理端 ----------------
export const useAdminUsers = (status: AccountStatus | '', q: string) =>
  useQuery({
    queryKey: ak.adminUsers(status, q),
    queryFn: ({ signal }) => apiGet<Paged<AdminUser>>('/admin/users', { status, q, limit: 100 }, signal),
    retry: false,
  });
export function usePatchAdminUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...b }: AdminUserPatch & { id: string }) => apiPatch<AdminUser>(`/admin/users/${encodeURIComponent(id)}`, b),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'users'] }),
  });
}

// ---------------- §7.2 账户、成交 ----------------
export const useAccounts = () =>
  useQuery({ queryKey: ak.accounts, queryFn: ({ signal }) => apiGet<Paged<BrokerAccount>>('/accounts', { limit: 50 }, signal) });
export function useCreateAccount() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (b: BrokerAccountCreate) => apiPost<BrokerAccount>('/accounts', b), onSuccess: () => qc.invalidateQueries({ queryKey: ak.accounts }) });
}
export const useTrades = (accountId: string | undefined) =>
  useQuery({
    queryKey: ak.trades(accountId ?? ''),
    queryFn: ({ signal }) => apiGet<Paged<Trade>>('/trades', { account_id: accountId, limit: 200 }, signal),
    enabled: !!accountId,
  });
export function useCreateTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: TradeCreate) => apiPost<Trade>('/trades', b, { idempotencyKey: newIdempotencyKey() }),
    onSuccess: (t) => {
      void qc.invalidateQueries({ queryKey: ak.trades(t.account_id) });
      void qc.invalidateQueries({ queryKey: ak.reconciliation(t.account_id) });
    },
  });
}

// ---------------- §7.2 导入 ----------------
export const useImports = (accountId: string | undefined) =>
  useQuery({
    queryKey: ak.imports(accountId ?? ''),
    queryFn: ({ signal }) => apiGet<Paged<ImportBatch>>('/imports', { account_id: accountId, limit: 50 }, signal),
    enabled: !!accountId,
  });

export const useUploadImport = () =>
  useMutation({
    mutationFn: (v: { file: File; account_id: string; kind: ImportKind; snapshot_as_of: string | null }) => {
      const f = new FormData();
      f.append('file', v.file);
      f.append('account_id', v.account_id);
      f.append('kind', v.kind);
      if (v.snapshot_as_of) f.append('snapshot_as_of', v.snapshot_as_of);
      return apiUpload<ImportUploadResponse>('/imports', f);
    },
  });

/** 批次详情：uploaded/parsing 时每秒轮询，终态停止 */
export const useImportBatch = (id: string | null) =>
  useQuery({
    queryKey: ak.batch(id ?? ''),
    queryFn: ({ signal }) => apiGet<ImportBatch>(`/imports/${encodeURIComponent(id!)}`, undefined, signal),
    enabled: !!id,
    staleTime: 0,
    refetchInterval: (q) => (q.state.data && (q.state.data.status === 'uploaded' || q.state.data.status === 'parsing') ? 1000 : false),
  });

export interface RowFilter { status?: string; code?: string; dedup_status?: string }
export const useImportRows = (id: string | null, enabled: boolean, f: RowFilter) =>
  useQuery({
    queryKey: ak.rows(id ?? '', JSON.stringify(f)),
    queryFn: ({ signal }) => apiGet<Paged<ImportRow>>(`/imports/${encodeURIComponent(id!)}/rows`, { ...f, limit: 200 }, signal),
    enabled: !!id && enabled,
    staleTime: 0,
  });

function useBatchMutation<V, R>(fn: (id: string, v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, v }: { id: string; v: V }) => fn(id, v),
    onSettled: (_r, _e, { id }) => {
      void qc.invalidateQueries({ queryKey: ['import', id] });
      void qc.invalidateQueries({ queryKey: ['imports'] });
    },
  });
}
const p = (id: string, rest = '') => `/imports/${encodeURIComponent(id)}${rest}`;
export const useImportOptions = () => useBatchMutation((id, v: ImportOptions) => apiPut<{ status: 'parsing' }>(p(id, '/options'), v));
export const useResolveFinding = () =>
  useBatchMutation((id, v: ResolveFindingRequest & { finding_id: string }) =>
    apiPost<ImportFinding>(p(id, `/findings/${encodeURIComponent(v.finding_id)}/resolve`), { choice: v.choice, reason: v.reason }));
/** 确认写入：同一次确认的重试复用同一个 Idempotency-Key（调用方保存 key） */
export function useConfirmImport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body, key }: { id: string; body: ImportConfirmRequest; key: string }) => apiPost<ImportConfirmResponse>(p(id, '/confirm'), body, { idempotencyKey: key }),
    onSettled: (_r, _e, { id }) => {
      void qc.invalidateQueries({ queryKey: ['import', id] });
      void qc.invalidateQueries({ queryKey: ['imports'] });
      void qc.invalidateQueries({ queryKey: ['trades'] });
      void qc.invalidateQueries({ queryKey: ['reconciliation'] });
    },
  });
}
export const useDiscardImport = () => useBatchMutation<null, { status: 'discarded' }>((id) => apiPost<{ status: 'discarded' }>(p(id, '/discard')));
export function useRevertImport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiPost<{ status: 'reverted' }>(p(id, '/revert')),
    onSettled: () => {
      for (const k of ['imports', 'import', 'trades', 'reconciliation', 'portfolio']) void qc.invalidateQueries({ queryKey: [k] });
    },
  });
}

/** errors.csv：用 fetch 取回再存为文件（MSW 不拦截页面跳转，且这样能带上凭据与错误处理） */
export async function downloadErrorsCsv(batchId: string) {
  const res = await fetch(fetchUrl(buildUrl(p(batchId, '/errors.csv'))), { credentials: 'same-origin' });
  if (!res.ok) throw new ApiError(res.status, 'HTTP_ERROR', `下载失败（HTTP ${res.status}）`, null, res.headers.get('X-Request-Id'));
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `import-${batchId.slice(0, 8)}-errors.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------------- 对账 ----------------
export const useReconciliation = (accountId: string | undefined) =>
  useQuery({
    queryKey: ak.reconciliation(accountId ?? ''),
    queryFn: ({ signal }) => apiGet<Reconciliation>('/reconciliation', { account_id: accountId }, signal),
    enabled: !!accountId,
  });
