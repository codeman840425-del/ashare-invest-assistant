/**
 * T-F33 自选股 /watchlist 的 MSW 处理器与会话内可变状态（契约 docs/contracts/watchlist.md，T-A129 4c89336）。
 * 示例数据全部虚构；鉴权（401/403 ACCOUNT_NOT_APPROVED）与 CSRF（403 CSRF_FAILED）由 accountHandlers 统一前置处理。
 * 校验顺序按 ⑩：请求体 400 → 代码 400 → 重复 409 → 上限 403 → 201；Idempotency-Key 重放先于业务判重（②）。
 * 骨架由 DeepSeek 起草（reports/deepseek/T-F33/draft.md），已按契约改正：401 码、指数按主数据判定、校验顺序、不 trim、按本人隔离。
 */
import { http, HttpResponse } from 'msw';
import type { WatchlistItem, WatchlistResponse } from '../api/types';
import { errorBody } from './handlerUtils';
import { WATCHLIST, uid } from './fixtures';
import { securityProfile } from './marketFixtures';
import { currentUser } from './session';

const API = '/api/v1';
const DEMO_UID = uid(2);
/** 示例上限：沿用 fixtures 的演示值（契约 U3：真实默认取 config/realtime.yaml，前端不写死） */
const DEFAULT_CAPS = { ...WATCHLIST.caps };
const GROUP_MAX = 32;
const NOTE_MAX = 500;
const ALLOWED_KEYS = new Set(['security_code', 'group', 'note']);
/** 与后端 SECURITY_CODE_PATTERN 同口径的写法：600000 / 600000.SH / SH600000，大小写均可 */
const CODE_RE = /^(?:(SH|SZ|BJ)(\d{6})|(\d{6})(?:\.(SH|SZ|BJ))?)$/i;

interface Row { id: string; item: WatchlistItem; removed: boolean }
interface Idem { body: string; status: number; json: WatchlistItem }

let store = new Map<string, Row[]>();
let idem = new Map<string, Idem>();
let caps = { ...DEFAULT_CAPS };
let seq = 0;

const rowId = (n: number) => `0b5e1000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const pad = (n: number) => String(n).padStart(2, '0');
/** 示例时间：每次写入在 2026-11-02 21:00 后加 1 分钟（北京时间） */
const nextTime = () => {
  const m = seq;
  return `2026-11-02T${pad(21 + Math.floor(m / 60))}:${pad(m % 60)}:00+08:00`;
};

function seedDemo(): Row[] {
  // ⑨：refresh_tier 本阶段恒为 null
  return WATCHLIST.items.map((x) => ({ id: rowId(++seq), item: { ...x, refresh_tier: null }, removed: false }));
}

export function resetWatchlist() {
  seq = 0;
  idem = new Map();
  caps = { ...DEFAULT_CAPS };
  store = new Map([[DEMO_UID, seedDemo()]]);
}
resetWatchlist();

/** 测试用：改当前示例上限（模拟权益覆盖 watchlist.per_user_cap） */
export function setMockWatchlistCap(n: number) {
  caps = { ...caps, watchlist: n };
}
/** 测试用：清空某用户（默认当前用户）的自选，演示空态 */
export function clearMockWatchlist(userId?: string) {
  const id = userId ?? currentUser()?.id;
  if (id) store.set(id, []);
}
export const watchlistNow = (userId: string = DEMO_UID): WatchlistItem[] => (store.get(userId) ?? []).filter((r) => !r.removed).map((r) => r.item);

const rowsOf = (userId: string) => {
  let rows = store.get(userId);
  if (!rows) store.set(userId, (rows = []));
  return rows;
};
const active = (userId: string) => rowsOf(userId).filter((r) => !r.removed);

const bad = (field: string, issue: string, extra: Record<string, unknown> = {}) =>
  HttpResponse.json(errorBody('VALIDATION_ERROR', '参数校验失败（示例）', { fields: [{ field, issue, ...extra }] }), { status: 400 });

type Qualified = { ok: true; code: string } | { ok: false; issue: string; extra?: Record<string, unknown> };
/** ⑤：格式 → 规范化（裸 6 位按主数据推断市场，排除指数）→ 旧代码 superseded → 主数据存在 → 类型 / 退市 */
function qualify(raw: unknown): Qualified {
  if (typeof raw !== 'string') return { ok: false, issue: 'invalid' };
  const m = CODE_RE.exec(raw);
  if (!m) return { ok: false, issue: 'invalid' };
  const digits = m[2] ?? m[3];
  const mkt = (m[1] ?? m[4])?.toUpperCase();
  let code: string | null = mkt ? `${digits}.${mkt}` : null;
  if (!code) {
    const hit = ['SH', 'SZ', 'BJ'].map((x) => `${digits}.${x}`).find((c) => { const p = securityProfile(c); return p && p.type !== 'index'; });
    if (!hit) return { ok: false, issue: 'invalid' };
    code = hit;
  }
  // 北交所旧代码（示例：43xxxx.BJ → 83xxxx.BJ，见 marketFixtures code_history）
  if (code.endsWith('.BJ') && code.startsWith('43')) {
    const successor = `83${code.slice(2)}`;
    if (securityProfile(successor)?.code_history.some((h) => h.security_code === code)) return { ok: false, issue: 'superseded', extra: { superseded_by: successor } };
  }
  const p = securityProfile(code);
  if (!p) return { ok: false, issue: 'unknown_security' };
  if (p.type === 'index') return { ok: false, issue: 'security_type_not_supported' };
  if (p.listing_status === 'delisted') return { ok: false, issue: 'delisted' };
  return { ok: true, code };
}

/** ⑥：类型须为字符串或 null；空串按 null；不 trim；按码点计长度 */
function textField(v: unknown, max: number): { ok: true; value: string | null } | { ok: false; issue: string } {
  if (v === undefined || v === null) return { ok: true, value: null };
  if (typeof v !== 'string') return { ok: false, issue: 'invalid' };
  if ([...v].length > max) return { ok: false, issue: 'too_long' };
  return { ok: true, value: v === '' ? null : v };
}

export const watchlistHandlers = [
  http.get(`${API}/watchlist`, () => {
    const u = currentUser()!;
    // ④：按 added_at、id 升序；只返回本人有效行；focus 按示例 focus 标记
    const items = active(u.id).slice().sort((a, b) => a.item.added_at.localeCompare(b.item.added_at) || a.id.localeCompare(b.id)).map((r) => r.item);
    const body: WatchlistResponse = { items, caps: { ...caps } };
    return HttpResponse.json(body);
  }),

  http.post(`${API}/watchlist`, async ({ request }) => {
    const u = currentUser()!;
    let raw: unknown;
    try {
      raw = await request.json();
    } catch {
      return bad('body', 'invalid');
    }
    const text = JSON.stringify(raw);
    const key = request.headers.get('Idempotency-Key');
    const idemKey = key ? `${u.id}|watchlist:add|${key}` : null;
    if (idemKey) {
      const hit = idem.get(idemKey);
      if (hit && hit.body !== text) return HttpResponse.json(errorBody('IDEMPOTENCY_CONFLICT', '同一 Idempotency-Key 的请求体不同（示例）', {}), { status: 409 });
      if (hit) return HttpResponse.json(hit.json, { status: hit.status });
    }
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return bad('body', 'invalid');
    const b = raw as Record<string, unknown>;
    const unknownKey = Object.keys(b).find((k) => !ALLOWED_KEYS.has(k));
    if (unknownKey) return bad(unknownKey, 'extra_forbidden');
    if (!('security_code' in b)) return bad('security_code', 'missing');
    const group = textField(b.group, GROUP_MAX);
    if (!group.ok) return bad('group', group.issue);
    const note = textField(b.note, NOTE_MAX);
    if (!note.ok) return bad('note', note.issue);
    const q = qualify(b.security_code);
    if (!q.ok) return bad('security_code', q.issue, q.extra);
    const mine = active(u.id);
    const existing = mine.find((r) => r.item.security_code === q.code);
    if (existing) {
      return HttpResponse.json(errorBody('CONFLICT', '该证券已在自选中（示例）', { field: 'security_code', existing_id: existing.id }), { status: 409 });
    }
    if (mine.length >= caps.watchlist) {
      return HttpResponse.json(
        errorBody('ENTITLEMENT_LIMIT_REACHED', '自选数量已达上限（示例）', { key: 'watchlist.per_user_cap', limit: caps.watchlist, current: mine.length }),
        { status: 403 },
      );
    }
    seq += 1;
    const item: WatchlistItem = {
      security_code: q.code, name: securityProfile(q.code)!.name, focus: false,
      group: group.value, note: note.value, added_at: nextTime(), refresh_tier: null,
    };
    rowsOf(u.id).push({ id: rowId(seq), item, removed: false });
    if (idemKey) idem.set(idemKey, { body: text, status: 201, json: item });
    return HttpResponse.json(item, { status: 201 });
  }),

  http.delete(`${API}/watchlist/:code`, ({ params }) => {
    const u = currentUser()!;
    const raw = String(params.code);
    const m = CODE_RE.exec(raw);
    if (!m) return bad('security_code', 'invalid');
    const q = qualify(raw);
    // ③：代码合法但本人没有有效行（含主数据没有、已删除、只在他人自选）一律 404
    const code = q.ok ? q.code : m[2] ? `${m[2]}.${m[1].toUpperCase()}` : m[4] ? `${m[3]}.${m[4].toUpperCase()}` : null;
    const row = code ? active(u.id).find((r) => r.item.security_code === code) : undefined;
    if (!row) return HttpResponse.json(errorBody('NOT_FOUND', '自选中没有该证券（示例）'), { status: 404 });
    row.removed = true;
    return new HttpResponse(null, { status: 204 });
  }),
];
