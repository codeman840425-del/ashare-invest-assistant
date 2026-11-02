/** 评审 53468a5 m 级修复 + T-A10 P14 / P18（409 INVALID_STATE_TRANSITION 按 details.from 给文案） */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { ApiError } from '../api/client';
import { transitionText, stateErrorText } from '../lib/stateTransition';
import { uid } from '../mocks/fixtures';
import { draftsNow } from '../mocks/planHandlers';
import { patchSignal } from '../mocks/signalHandlers';
import { server } from '../mocks/server';
import { apiFetch } from '../test/apiFetch';

// 页面模块的冷加载放在等待窗口之外（评审 b23401a N8）
beforeAll(() => preloadRoutes(routes), 30_000);

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}
function captureKeys() {
  const keys: (string | null)[] = [];
  const on = ({ request }: { request: Request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname === `${API}/plan-drafts`) keys.push(request.headers.get('Idempotency-Key'));
  };
  server.events.on('request:start', on);
  return { keys, stop: () => server.events.removeListener('request:start', on) };
}
const bad = (from: string, to: string) => new ApiError(409, 'INVALID_STATE_TRANSITION', '示例', { from, to, allowed: [] }, null);

// 示例：uid 7701 条件已变草案；uid 1012 待确认草案
const STALE = uid(7701);
const PENDING = uid(1012);

describe('P18：按 details.from 区分文案', () => {
  it('信号', () => {
    expect(transitionText(bad('confirmed', 'drafted'), 'signal')).toBe('该信号已被确认为计划');
    expect(transitionText(bad('expired', 'drafted'), 'signal')).toBe('信号已失效（已过期）');
    expect(transitionText(bad('invalidated', 'drafted'), 'signal', { regen: true })).toBe('信号已失效（已失效），不能重新生成草案');
    expect(transitionText(bad('dismissed', 'dismissed'), 'signal')).toBe('该信号已忽略');
    expect(transitionText(bad('blocked', 'drafted'), 'signal')).toContain('暂不可执行');
  });
  it('草案', () => {
    expect(transitionText(bad('confirmed', 'discarded'), 'draft')).toBe('该草案已确认为计划');
    expect(transitionText(bad('discarded', 'confirmed'), 'draft')).toBe('该草案已放弃');
    expect(transitionText(bad('stale', 'confirmed'), 'draft')).toContain('条件已变');
  });
  it('未知 from / 其他错误码 → 回落通用文案', () => {
    expect(transitionText(bad('weird', 'x'), 'draft')).toBeNull();
    expect(transitionText(new ApiError(409, 'INVALID_STATE_TRANSITION', '示例', null, null), 'draft')).toBeNull();
    const other = new ApiError(500, 'INTERNAL', '示例', null, null);
    expect(transitionText(other, 'signal')).toBeNull();
    expect(stateErrorText(other, 'signal')).toBeTruthy();
  });
  it('mock 的 409 带契约要求的 {from, to, allowed}', async () => {
    const res = await apiFetch(`${API}/plan-drafts/${uid(7703)}/discard`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' });
    expect(res.status).toBe(409);
    const j = (await res.json()) as { error: { details: Record<string, unknown> } };
    expect(j.error.details).toEqual({ from: 'discarded', to: 'discarded', allowed: [] });
  });
  it('草案页：放弃已确认草案的 409 显示“该草案已确认为计划”', async () => {
    server.use(http.post(`${API}/plan-drafts/:id/discard`, () => HttpResponse.json({ error: { code: 'INVALID_STATE_TRANSITION', message: '示例', details: { from: 'confirmed', to: 'discarded', allowed: [] }, request_id: 'mock-x' } }, { status: 409 })));
    renderAt(`/plan-drafts/${PENDING}`);
    fireEvent.click(await screen.findByTestId('discard-btn'));
    fireEvent.click(await screen.findByTestId('discard-ok'));
    expect(await screen.findByTestId('discard-error')).toHaveTextContent('该草案已确认为计划');
  });
});

describe('53468a5 m1 / P14：重新生成草案', () => {
  it('原信号已失效 → 提示“信号已失效”；409 后换 Idempotency-Key，恢复后成功', async () => {
    const sig = draftsNow().find((d) => d.id === STALE)!.signal_ids[0];
    patchSignal(sig, { state: 'expired' });
    const cap = captureKeys();
    try {
      const router = renderAt(`/plan-drafts/${STALE}`);
      fireEvent.click(await screen.findByTestId('regen-btn'));
      expect(await screen.findByTestId('regen-error')).toHaveTextContent('信号已失效（已过期），不能重新生成草案');
      patchSignal(sig, { state: 'drafted' });
      fireEvent.click(screen.getByTestId('regen-btn'));
      await waitFor(() => expect(router.state.location.pathname).not.toBe(`/plan-drafts/${STALE}`));
      expect(cap.keys).toHaveLength(2);
      expect(cap.keys[0]).toBeTruthy();
      expect(cap.keys[1]).toBeTruthy();
      expect(cap.keys[1]).not.toBe(cap.keys[0]);
    } finally {
      cap.stop();
    }
  });
  it('网络错误后重试沿用同一个 Idempotency-Key', async () => {
    server.use(http.post(`${API}/plan-drafts`, () => HttpResponse.error(), { once: true }));
    const cap = captureKeys();
    try {
      const router = renderAt(`/plan-drafts/${STALE}`);
      fireEvent.click(await screen.findByTestId('regen-btn'));
      await screen.findByTestId('regen-error');
      fireEvent.click(screen.getByTestId('regen-btn'));
      await waitFor(() => expect(router.state.location.pathname).not.toBe(`/plan-drafts/${STALE}`));
      expect(cap.keys).toHaveLength(2);
      expect(cap.keys[1]).toBe(cap.keys[0]);
    } finally {
      cap.stop();
    }
  });
});
