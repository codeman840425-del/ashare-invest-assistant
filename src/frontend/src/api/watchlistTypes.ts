/** T-F33：/watchlist 写接口的请求体与错误详情（契约 docs/contracts/watchlist.md，T-A129 4c89336；后端 T-B126 08e47de） */
export type { WatchlistItem, WatchlistResponse } from './types';

/** POST /watchlist 请求体（⑥：group、note 可省略，省略等同 null；未知键 400） */
export interface WatchlistCreate {
  security_code: string;
  group?: string | null;
  note?: string | null;
}

/** ② 409 CONFLICT 的 details；existing_id 在并发兜底分支里后端可能给 null */
export interface WatchlistConflictDetails {
  field: 'security_code';
  existing_id: string | null;
}

/** ⑩ 403 ENTITLEMENT_LIMIT_REACHED 的 details */
export interface WatchlistLimitDetails {
  key: 'watchlist.per_user_cap';
  limit: number;
  current: number;
}

/** ⑤/⑥ 400 VALIDATION_ERROR 里 security_code / group / note 的 issue 取值 */
export type WatchlistIssue =
  | 'invalid' | 'unknown_security' | 'security_type_not_supported' | 'delisted' | 'superseded' | 'too_long';
