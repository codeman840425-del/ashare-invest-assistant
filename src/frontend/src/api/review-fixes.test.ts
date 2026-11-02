/** T-F01 评审 M1/M2 与契约 v0.2.3 同步项的单元测试 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { SUGGESTIONS, CANDIDATE_SIGNALS, REASONS } from '../mocks/fixtures';
import { ApiError, apiGet, clearEtagCache } from './client';
import { ERROR_CODES, isErrorCode } from './errorCodes';
import { ERROR_TEXT, errorText, globalErrorAction, handleGlobalError, onGlobalApiError, retryDelay, shouldRetry } from './errorPolicy';
import type { Evidence, MarketOverview, NonExecutableReason, Paged, SignalEvent, Suggestion, TerminalResponse, TodayResponse } from './types';
import { chartStops, markerSignals } from '../features/terminal/chartStops';
import { providerText, ruleCountText } from '../lib/format';
import { apiFetch } from '../test/apiFetch';

const CONTRACT = readFileSync(resolve(__dirname, '../../../../docs/api-contract.md'), 'utf8');
const err = (status: number, code: string, details: Record<string, unknown> | null = null) => new ApiError(status, code, 'x', details, 'req-1');

describe('M1：ETag / 304', () => {
  it('第二次 GET /terminal 带 If-None-Match，收到 304 时返回上一次的数据（不是 undefined）', async () => {
    const seen: (string | null)[] = [];
    const statuses: number[] = [];
    server.events.on('request:start', ({ request }) => {
      if (new URL(request.url).pathname === '/api/v1/terminal') seen.push(request.headers.get('If-None-Match'));
    });
    server.events.on('response:mocked', ({ request, response }) => {
      if (new URL(request.url).pathname === '/api/v1/terminal') statuses.push(response.status);
    });
    const a = await apiGet<TerminalResponse>('/terminal', { scope: 'all' });
    const b = await apiGet<TerminalResponse>('/terminal', { scope: 'all' });
    server.events.removeAllListeners();
    expect(seen[0]).toBeNull();
    expect(seen[1]).toMatch(/^W\/"[0-9a-f]+"$/);
    expect(statuses).toEqual([200, 304]);
    expect(b).toEqual(a);
    expect(b.rows.length).toBeGreaterThan(0);
  });

  it('/today 同样支持弱 ETag', async () => {
    const a = await apiGet<TodayResponse>('/today');
    const b = await apiGet<TodayResponse>('/today');
    expect(b).toEqual(a);
  });

  it('304 但本地无缓存 → NOT_MODIFIED 错误（不写入空值）', async () => {
    clearEtagCache();
    server.use(http.get('/api/v1/terminal', () => new HttpResponse(null, { status: 304 })));
    const e = (await apiGet('/terminal', { scope: 'all' }).catch((x: unknown) => x)) as ApiError;
    expect(e).toBeInstanceOf(ApiError);
    expect(e.code).toBe('NOT_MODIFIED');
  });
});

describe('M2：错误码类型与全局处理', () => {
  it('ERROR_CODES 与契约 §4 错误码表逐行一致（码与 HTTP 状态）', () => {
    const sec = CONTRACT.slice(CONTRACT.indexOf('## 4. 错误码表'), CONTRACT.indexOf('### 4.1'));
    const rows = [...sec.matchAll(/^\| (\d{3}) \| `([A-Z][A-Z0-9_]*)` \|/gm)].map((m) => [m[2], Number(m[1])]);
    expect(rows.length).toBeGreaterThan(50);
    expect(Object.entries(ERROR_CODES)).toEqual(rows);
    expect(isErrorCode('CONSENT_REQUIRED')).toBe(false); // v0.2.5 删除
    expect(isErrorCode('STRATEGY_FIT_ACK_REQUIRED')).toBe(false);
    expect(isErrorCode('IMPORT_ROW_COLUMN_MISMATCH')).toBe(false); // §4.1 提示码不在 error_codes
  });

  it('ApiError.code 带类型；known / contractStatus', () => {
    expect(err(404, 'NOT_FOUND').known).toBe(true);
    expect(err(404, 'NOT_FOUND').contractStatus).toBe(404);
    expect(err(418, 'TEAPOT').known).toBe(false);
  });

  it('文案按码：413 带上限、503 FRESH_DATA_REQUIRED 带等待秒数（T-F02 评审 m6/m7）；未知码回落', () => {
    expect(errorText(err(413, 'PAYLOAD_TOO_LARGE'))).toBe('文件过大，超过上传上限');
    expect(errorText(err(413, 'PAYLOAD_TOO_LARGE', { max_bytes: 27262976 }))).toBe('文件过大，超过单次上传上限 26 MB');
    expect(errorText(err(503, 'FRESH_DATA_REQUIRED', { retry_after_s: 8 }))).toBe('行情数据暂未更新，请 8 秒后再试');
    expect(errorText(err(503, 'FRESH_DATA_REQUIRED'))).toBe('行情数据暂未更新，请稍后再试');
    expect(errorText(new ApiError(502, 'HTTP_ERROR', 'HTTP 502', null, null))).toContain('服务暂时不可用');
    for (const k of Object.keys(ERROR_TEXT)) expect(isErrorCode(k) || ['HTTP_ERROR', 'NETWORK_ERROR', 'NOT_MODIFIED'].includes(k)).toBe(true);
  });

  it('全局动作：401 → login；405 → log；其他 403 → none（v0.2.5 无 consent 动作）', () => {
    expect(globalErrorAction(err(401, 'AUTH_REQUIRED'))).toBe('login');
    expect(globalErrorAction(err(401, 'INVALID_CREDENTIALS'))).toBe('none');
    expect(globalErrorAction(err(403, 'FORBIDDEN'))).toBe('none');
    expect(globalErrorAction(err(405, 'METHOD_NOT_ALLOWED', { allowed: ['GET'] }))).toBe('log');
    expect(globalErrorAction(new Error('x'))).toBe('none');
  });

  it('405 只写控制台，不通知订阅者；401 通知订阅者', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const got: string[] = [];
    const off = onGlobalApiError((a) => got.push(a));
    handleGlobalError(err(405, 'METHOD_NOT_ALLOWED'));
    handleGlobalError(err(401, 'AUTH_REQUIRED'));
    off();
    handleGlobalError(err(401, 'AUTH_REQUIRED'));
    expect(spy).toHaveBeenCalledTimes(1);
    expect(got).toEqual(['login']);
    spy.mockRestore();
  });

  it('重试策略：4xx 不重试；FRESH_DATA_REQUIRED 不自动重试（评审 m6）；5xx/网络 1 次；retry_after_s 优先', () => {
    expect(shouldRetry(0, err(404, 'NOT_FOUND'))).toBe(false);
    expect(shouldRetry(0, err(429, 'RATE_LIMITED'))).toBe(false);
    expect(shouldRetry(0, err(503, 'FRESH_DATA_REQUIRED'))).toBe(false);
    expect([0, 1].map((n) => shouldRetry(n, err(500, 'INTERNAL_ERROR')))).toEqual([true, false]);
    expect(shouldRetry(0, err(0, 'NETWORK_ERROR'))).toBe(true);
    expect(retryDelay(1, err(503, 'UPSTREAM_RATE_LIMITED', { retry_after_s: 5 }))).toBe(5000);
    expect(retryDelay(1, err(503, 'FRESH_DATA_REQUIRED'))).toBe(2000);
  });
});

describe('M5：日 K 止损/止盈线', () => {
  const base = SUGGESTIONS[0];
  const mk = (status: Suggestion['consensus']['status'], stops: [string | null, string | null][]): Suggestion => ({
    ...base,
    consensus: { ...base.consensus, status },
    strategies: stops.map(([sl, tp], i) => ({ ...base.strategies[0], strategy_name: `策略${i + 1}`, stops: { ...base.strategies[0].stops, stop_loss: sl, take_profit: tp } })),
  });
  it('分歧时不画', () => {
    expect(chartStops(mk('divergent', [['9.50', '11.00'], ['9.00', null]]))).toBeNull();
    const d = SUGGESTIONS.find((s) => s.consensus.status === 'divergent');
    if (d) expect(chartStops(d)).toBeNull();
  });
  it('单策略：画线并在图例写策略名', () => {
    expect(chartStops(mk('single', [['9.50', '11.00']]))).toEqual({ stopLoss: '9.50', takeProfit: '11.00', legend: '策略1' });
  });
  it('一致但价位不同：不挑选、不合并，不画', () => {
    expect(chartStops(mk('unanimous', [['9.50', '11.00'], ['9.40', '11.00']]))).toBeNull();
    expect(chartStops(mk('unanimous', [['9.50', '11.00'], ['9.50', '11.00']]))?.legend).toBe('策略1、策略2');
  });
  it('日 K 标记排除作废/过期/取代/驳回的候选信号（m8）', () => {
    const states = new Set(markerSignals(CANDIDATE_SIGNALS).map((c) => c.state));
    for (const s of ['expired', 'invalidated', 'superseded', 'dismissed']) expect(states.has(s as never)).toBe(false);
  });
});

describe('契约 v0.2.3 同步', () => {
  const endpointKeys = (path: string) => {
    const line = CONTRACT.split('\n').find((l) => l.startsWith(`| GET | \`${path}\``))!;
    const src = line.slice(line.indexOf('`{') + 1);
    let depth = 0;
    let cur = '';
    const keys: string[] = [];
    for (const c of src) {
      if ('{[('.includes(c) && ++depth === 1) continue;
      if ('}])'.includes(c) && --depth === 0) { keys.push(cur); break; }
      if (depth === 1 && c === ',') { keys.push(cur); cur = ''; continue; }
      if (depth >= 1) cur += c;
    }
    return keys.map((k) => k.trim().split(/[:\s]/)[0]).filter(Boolean)
      .flatMap((k) => (k === 'DataStatusBlock' ? ['data_status', 'data_as_of', 'gaps'] : [k])).sort();
  };

  it('#12 /today mock 顶层字段与契约 §7.3 一致；列表 ≤ 50 且带 more', async () => {
    const t = await apiGet<TodayResponse>('/today');
    // v0.2.7：§7.3 `/today` 补充新增 4 个顶层字段（写在补充小节的 text 块里，不在端点行的花括号内）
    const supplement = CONTRACT.slice(CONTRACT.indexOf('#### `/today` 补充'));
    const added = ['alerts', 'plan_triggers', 'data_gaps', 'evidence'];
    for (const k of added) expect(supplement).toMatch(new RegExp(`^${k}: `, 'm'));
    expect(Object.keys(t).sort()).toEqual([...endpointKeys('/today'), ...added].sort());
    for (const k of ['focus', 'pending_plan_drafts', 'released_reasons', 'risk_flags', 'invalidations_today'] as const) {
      expect(t[k].items.length).toBeLessThanOrEqual(50);
      expect(typeof t[k].more).toBe('boolean');
    }
  });

  it('#9 /market/overview 最小结构', async () => {
    const m = await apiGet<MarketOverview>('/market/overview');
    expect(Object.keys(m).sort()).toEqual(endpointKeys('/market/overview'));
    expect(m.breadth && Object.keys(m.breadth).sort()).toEqual(['down', 'flat', 'limit_down', 'limit_up', 'up']);
  });

  it('#17 /non-executable-reasons：suggestion_id / signal_ids 不分页返回 {items}；signal_ids > 100 → 400', async () => {
    const sg = SUGGESTIONS.find((s) => s.executability.reason_ids.length)!;
    const a = await apiGet<{ items: NonExecutableReason[] }>('/non-executable-reasons', { status: 'active', suggestion_id: sg.id });
    expect(Object.keys(a)).toEqual(['items']);
    expect(a.items.length).toBeGreaterThan(0);
    for (const r of a.items) expect(sg.candidate_signal_ids).toContain(r.signal_id);
    const ids = REASONS.slice(0, 2).map((r) => r.signal_id);
    const b = await apiGet<{ items: NonExecutableReason[] }>('/non-executable-reasons', { signal_ids: ids.join(',') });
    expect(b.items.every((r) => ids.includes(r.signal_id))).toBe(true);
    const tooMany = Array.from({ length: 101 }, (_, i) => `id${i}`).join(',');
    const e = (await apiGet('/non-executable-reasons', { signal_ids: tooMany }).catch((x: unknown) => x)) as ApiError;
    expect(e.status).toBe(400);
    expect(e.details).toEqual({ fields: [{ field: 'signal_ids', issue: expect.any(String) as unknown }] });
  });

  it('#6 /signals 按 security_code 与 since 过滤', async () => {
    const all = await apiGet<Paged<SignalEvent>>('/signals', { limit: 200 });
    const code = all.items[0].security_code;
    const since = all.items[0].at;
    const r = await apiGet<Paged<SignalEvent>>('/signals', { security_code: code, since, limit: 200 });
    expect(r.items.length).toBeGreaterThan(0);
    expect(r.items.every((e) => e.security_code === code && e.at >= since)).toBe(true);
  });

  it('m3 providerText 对未知数据源兜底显示原值；m4 纯离场单元格显示“离场 x/y”', () => {
    const ev = { provider: 'local', endpoint: null } as unknown as Evidence;
    expect(providerText(ev)).toBe('local');
    expect(ruleCountText({ rules_passed: 0, rules_total: 0, exit_hits: 1, exit_total: 2 })).toBe('离场 1/2');
    expect(ruleCountText({ rules_passed: 2, rules_total: 3, exit_hits: 0, exit_total: 0 })).toBe('规则 2/3');
    expect(ruleCountText({ rules_passed: 0, rules_total: 0, exit_hits: 0, exit_total: 0 })).toBe('规则 —');
  });
});

describe('m2：mock 兜底区分 404 / 405', () => {
  it('方法不对 → 405 METHOD_NOT_ALLOWED + Allow 头；路径不存在 → 404；/admin/* 一律 404', async () => {
    const r = await apiFetch(`${location.origin}/api/v1/terminal`, { method: 'DELETE' });
    expect(r.status).toBe(405);
    expect(r.headers.get('Allow')).toBe('GET');
    expect(((await r.json()) as { error: { code: string } }).error.code).toBe('METHOD_NOT_ALLOWED');
    expect((await apiFetch(`${location.origin}/api/v1/no-such-endpoint`)).status).toBe(404);
    expect((await apiFetch(`${location.origin}/api/v1/admin/users`, { method: 'DELETE' })).status).toBe(404);
  });
});
