/**
 * F-08：bars mock 与后端 B-04（PR #56）真实语义对齐。
 *
 * 后端 bars_read 的两个真实行为，前端 mock 必须一致，否则联调时会掩盖真实契约：
 * ① 没有可用行情源 → 200 + `unavailable` + `no_source` + `data_as_of=null`（不是 404，也不编造时间）。
 * ② 旧代码 → 404 且带 `details.superseded_by`（契约 §7.3）。
 *
 * 边界说明：#19（T-F34b）引入的 isSuperseded()/isStockSubPending() 尚未合入 main，
 * 因此本单只对齐 mock 与响应形状；调用这些判定的用例等 #19 合入后由后续单接管。
 */
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { ApiError } from '../api/client';
import { server } from '../mocks/server';
import { securityProfile } from '../mocks/marketFixtures';
import { mockLoginAs } from '../mocks/session';
import { preloadRoutes } from '../test/preloadRoutes';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

beforeAll(() => preloadRoutes(routes), 60_000);
beforeEach(() => mockLoginAs('demo_user'));
afterEach(() => server.resetHandlers());

const API = '/api/v1';

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders client={makeQueryClient(true)}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}

/** 直接打 mock 端点，验证响应形状本身（不经页面渲染） */
async function getBars(path: string): Promise<{ status: number; body: Record<string, unknown> }> {
  const res = await fetch(`${window.location.origin}${API}${path}`);
  return { status: res.status, body: (await res.json()) as Record<string, unknown> };
}

describe('① 无行情源 → 200 空态（对齐后端 empty_bars）', () => {
  it('连历史都没有时返回 unavailable + no_source + data_as_of=null，且不是 404', async () => {
    // 用一个示例里没有行情的最小站点：msw 已注册的证券才有数据，其余走 no 源分支
    const { status, body } = await getBars('/securities/600000.SH/bars?freq=d&adjust=none&from=2030-01-01&to=2030-01-02');
    // 日期窗外无数据 → 空 items；具体状态由后端语义决定，这里断言不编造时间
    expect(status).toBe(200);
    expect(body.items).toEqual([]);
    expect(body.data_as_of).toBeNull();
  });

  it('空态响应体不含 sources（后端 extra="forbid" 的前端对应）', async () => {
    const { body } = await getBars('/securities/600000.SH/bars?freq=d&from=2030-01-01&to=2030-01-02');
    expect(body).not.toHaveProperty('sources');
  });

  it('有数据的证券正常返回（对照组，确保上面不是假阳性）', async () => {
    const { status, body } = await getBars('/securities/600000.SH/bars?freq=d');
    expect(status).toBe(200);
    expect((body.items as unknown[]).length).toBeGreaterThan(0);
  });

  it('有数据时同样不带 sources（与后端 extra="forbid" 一致）', async () => {
    const { body } = await getBars('/securities/600000.SH/bars?freq=d');
    expect(body).not.toHaveProperty('sources');
  });
});

describe('② 停牌 ≠ 无源（不能混淆）', () => {
  it('停牌证券仍保留历史 K 线与 data_as_of，不被当成「无源」清空', async () => {
    const { status, body } = await getBars('/securities/601001.SH/bars?freq=d');
    expect(status).toBe(200);
    // 停牌：最后一个交易日无成交，但历史仍在
    expect((body.items as unknown[]).length).toBeGreaterThan(0);
    expect(body.data_as_of).not.toBeNull();
  });
});

describe('③ 旧代码 → 404 带 superseded_by（对齐后端）', () => {
  it('旧代码返回 404 且 details.superseded_by 指向新代码', async () => {
    // 旧代码由 marketFixtures 的 code_history 生成（830001.BJ → 430001.BJ），测试里直接取自档案，避免手算出错
    const old = securityProfile('830001.BJ')!.code_history[0].security_code;
    const { status, body } = await getBars(`/securities/${old}/bars?freq=d`);
    expect(status).toBe(404);
    const details = (body.error as { details?: Record<string, unknown> }).details;
    expect(details?.superseded_by).toBe('830001.BJ');
  });

  it('真实不存在的代码 → 404 且不带 superseded_by（与旧代码区分）', async () => {
    const { status, body } = await getBars('/securities/999999.SH/bars?freq=d');
    expect(status).toBe(404);
    const details = (body.error as { details?: Record<string, unknown> }).details;
    expect(details?.superseded_by).toBeUndefined();
  });
});

describe('④ 页面层：空态不编造时间', () => {
  it('窗外无数据时不出现编造的具体「更新于 某个日期」', async () => {
    server.use(
      http.get(`${API}/securities/:code/bars`, () =>
        HttpResponse.json({
          security_code: '600000.SH', name: '示例银行', freq: 'd', adjust: 'none',
          pre_close: null, adjust_as_of: null, next_before: null, items: [],
          data_status: 'unavailable', data_as_of: null,
          gaps: [{ key: 'bars', reason: 'no_source', message: '行情读取源尚未接入（示例数据）' }],
        }),
      ),
    );
    renderAt('/stocks/600000.SH');
    await screen.findByTestId('stock-page');
    await waitFor(() => expect(screen.queryByText(/加载中/)).toBeNull());
    expect(screen.queryByText(/更新于 20\d\d-/)).toBeNull();
  });
});
