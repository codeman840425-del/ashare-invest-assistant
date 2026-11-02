/** T-A08 前端同步（契约 v0.2.7）：策略实例状态机与游标、证券搜索、复权基准日、“查看全部”目标页接住参数 */
import { render, screen } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { syncAdjustAsOf } from '../api/marketQueries';
import type { BarsResponse } from '../api/types';
import type { StrategyInstance } from '../api/strategyTypes';
import { mockAddInstance, STRATEGY_TEMPLATES } from '../mocks/strategyHandlers';
import { uid } from '../mocks/fixtures';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';
const post = (path: string, body?: unknown) => fetch(`${API}${path}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
const getJson = async <T,>(path: string) => (await (await fetch(`${API}${path}`)).json()) as T;
type InstancePage = { items: StrategyInstance[]; next_cursor: string | null };

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

describe('策略实例状态机（§6.0A）', () => {
  it('列表默认不含 archived；创建的实例 origin=user、直接 active', async () => {
    const list = await getJson<InstancePage>('/strategy-instances?limit=200');
    expect(list.items.length).toBeGreaterThan(0);
    expect(list.items.every((x) => x.status !== 'archived')).toBe(true);
    const tpl = (await getJson<{ items: { current_version: { id: string; lifecycle: string }; horizons: string[] }[] }>('/strategies?limit=200')).items
      .find((t) => ['published', 'observing'].includes(t.current_version.lifecycle))!;
    const res = await post('/strategy-instances', { strategy_version_id: tpl.current_version.id, horizon: tpl.horizons[0], scope: 'account' });
    expect(res.status).toBe(201);
    const { id, status } = (await res.json()) as { id: string; status: string };
    expect(status).toBe('active');
    const all = await getJson<InstancePage>('/strategy-instances?limit=200');
    expect(all.items.find((x) => x.id === id)).toMatchObject({ origin: 'user', status: 'active' });
  });

  it('pause 幂等 200；非法转换 409 INVALID_STATE_TRANSITION{from,to,allowed}', async () => {
    const x = (await getJson<InstancePage>('/strategy-instances?status=active&limit=200')).items.find((i) => i.origin !== 'system')!;
    let r = await post(`/strategy-instances/${x.id}/pause`);
    expect(r.status).toBe(200);
    expect(((await r.json()) as StrategyInstance).status).toBe('paused');
    r = await post(`/strategy-instances/${x.id}/pause`);
    expect(r.status).toBe(200);
    r = await post(`/strategy-instances/${x.id}/confirm`);
    expect(r.status).toBe(409);
    const body = (await r.json()) as { error: { code: string; details: { from: string; to: string; allowed: string[] } } };
    expect(body.error.code).toBe('INVALID_STATE_TRANSITION');
    expect(body.error.details).toEqual({ from: 'paused', to: 'active', allowed: ['active', 'archived'] });
  });

  it('system 实例不能归档', async () => {
    const t = STRATEGY_TEMPLATES[0];
    mockAddInstance({ id: uid(4990), strategy_version_id: t.current_version.id, status: 'active', horizon: t.horizons[0], origin: 'system' });
    const sys = (await getJson<InstancePage>('/strategy-instances?origin=system&limit=200')).items;
    expect(sys.map((x) => x.id)).toEqual([uid(4990)]);
    const r = await post(`/strategy-instances/${uid(4990)}/archive`);
    expect(r.status).toBe(409);
    expect(((await r.json()) as { error: { code: string } }).error.code).toBe('INVALID_STATE_TRANSITION');
  });

  it('游标与筛选/排序不一致 → 400 INVALID_CURSOR', async () => {
    const p1 = await getJson<InstancePage>('/strategy-instances?limit=1&order=created_at_desc');
    expect(p1.next_cursor).not.toBeNull();
    const ok = await fetch(`${API}/strategy-instances?limit=1&order=created_at_desc&cursor=${encodeURIComponent(p1.next_cursor!)}`);
    expect(ok.status).toBe(200);
    const bad = await fetch(`${API}/strategy-instances?limit=1&order=updated_at_desc&cursor=${encodeURIComponent(p1.next_cursor!)}`);
    expect(bad.status).toBe(400);
    expect(((await bad.json()) as { error: { code: string } }).error.code).toBe('INVALID_CURSOR');
  });
});

describe('证券搜索 /securities/search（v0.2.7）', () => {
  it('返回 {items: SecurityHit[]}，带匹配方式；q 越界 400', async () => {
    const r = await getJson<{ items: { security_code: string; match_kind: string; matched_text: string }[] }>('/securities/search?q=600000&limit=20');
    expect(r.items.length).toBeGreaterThan(0);
    expect(r.items[0].security_code).toMatch(/^600000\./);
    expect(r.items[0].match_kind).toBeTruthy();
    expect((await fetch(`${API}/securities/search?q=${'1'.repeat(21)}`)).status).toBe(400);
  });
});

describe('复权基准日 adjust_as_of（§7.3 v0.2.7）', () => {
  it('bars 带 is_final 与 adjust_as_of', async () => {
    const r = await getJson<BarsResponse>('/securities/600000.SH/bars?freq=d&adjust=qfq&limit=10');
    expect(r).toHaveProperty('adjust_as_of');
    for (const b of r.items) expect(typeof b.is_final).toBe('boolean');
  });

  it('基准日变化时丢弃同证券、同复权方式的其他缓存', () => {
    const qc = new QueryClient();
    const data = (asOf: string) => ({ adjust_as_of: asOf }) as BarsResponse;
    qc.setQueryData(['bars', '600000.SH', 'w', 'qfq', 500], data('2026-10-01'));
    qc.setQueryData(['bars', '600000.SH', 'd', 'hfq', 500], data('2026-10-01'));
    qc.setQueryData(['bars', '000001.SZ', 'w', 'qfq', 500], data('2026-10-01'));
    expect(syncAdjustAsOf(qc, '600000.SH', 'qfq', 'd', 500, '2026-10-30')).toBe(true);
    expect(qc.getQueryData(['bars', '600000.SH', 'w', 'qfq', 500])).toBeUndefined();
    expect(qc.getQueryData(['bars', '600000.SH', 'd', 'hfq', 500])).toBeDefined();
    expect(qc.getQueryData(['bars', '000001.SZ', 'w', 'qfq', 500])).toBeDefined();
    expect(syncAdjustAsOf(qc, '600000.SH', 'none', '1m', 500, null)).toBe(false);
  });
});

describe('“查看全部”目标页接住参数（页面未实现前用占位页）', () => {
  it.each([
    // /candidate-signals?tab=released 自 T-F17 起、/plan-drafts?status=pending,stale 自 T-F18 起由真实页面接住，见 t-f17 / t-f18.test.tsx
    ['/risk-controls?tab=events&event=x1', 'tab=events'],
    ['/plans?status=triggered', 'status=triggered'],
    ['/suggestions?status=invalidated', 'status=invalidated'],
  ])('%s', async (path, param) => {
    const router = renderAt(path);
    const ph = await screen.findByTestId('placeholder');
    expect(screen.getByTestId('placeholder-params')).toHaveTextContent(param);
    expect(router.state.location.pathname + router.state.location.search).toBe(path);
    expect(ph).toBeInTheDocument();
  });
});
