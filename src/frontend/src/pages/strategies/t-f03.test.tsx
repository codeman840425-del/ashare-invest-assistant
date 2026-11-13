/**
 * F-03：我的策略实例独立页（编排者 2026-11-11 裁定 /strategy-instances 独立成页）。
 *
 * 覆盖：① 路由不再是占位页、页面按实例视角渲染；② 状态、范围、周期展示与后端返回一致（前端不重算）；
 * ③ 暂停/恢复/确认三种操作转发到正确的 §6.0A 端点；④ 空态文案；⑤ 归档实例默认收起。
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { routes } from '../../app/routes';
import type { StrategyInstance } from '../../api/strategyTypes';
import { errorBody } from '../../mocks/handlerUtils';
import { server } from '../../mocks/server';
import { mockLoginAs } from '../../mocks/session';
import { preloadRoutes } from '../../test/preloadRoutes';

vi.mock('../../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

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

const inst = (over: Partial<StrategyInstance>): StrategyInstance => ({
  id: 'i-1',
  strategy_id: 's-1',
  strategy_key: 'st_pullback_ma',
  strategy_name: '强势股短线回踩（示例）',
  strategy_version_id: 'v-1',
  version_no: 2,
  lifecycle: 'published',
  derived_strategy_version_id: null,
  risk_level: 'normal',
  status: 'active',
  origin: 'user',
  scope: 'account',
  account_id: 'a-1',
  security_code: null,
  name: null,
  horizon: 'short',
  param_overrides: null,
  budget_amount: null,
  auto_downweight: false,
  paused_by: null,
  pause_reason_code: null,
  paused_until: null,
  created_at: '2026-10-20T09:00:00+08:00',
  confirmed_at: null,
  updated_at: '2026-10-20T09:00:00+08:00',
  archived_at: null,
  ...over,
});

/** 用固定实例列表覆盖 /strategy-instances（含游标分页外壳） */
function serveInstances(items: StrategyInstance[]) {
  const calls: string[] = [];
  server.use(
    http.get(`${API}/strategy-instances`, ({ request }) => {
      calls.push(new URL(request.url).pathname + new URL(request.url).search);
      return HttpResponse.json({ items, next_cursor: null });
    }),
  );
  return calls;
}

describe('① 路由与页面', () => {
  it('/strategy-instances 不再是占位页，渲染真实页且不显示「功能开发中」', async () => {
    renderAt('/strategy-instances');
    expect(await screen.findByTestId('strategy-instances-page')).toBeInTheDocument();
    expect(screen.queryByTestId('route-pending')).toBeNull();
    expect(screen.getByText('我的策略实例')).toBeInTheDocument();
  });
});

describe('② 展示与后端一致（前端不重算）', () => {
  it('状态/范围/周期照后端返回展示；单只证券作用范围带出证券代码', async () => {
    serveInstances([
      inst({ id: 'i-active', status: 'active', scope: 'account', horizon: 'short' }),
      inst({ id: 'i-proposed', status: 'proposed', scope: 'security', security_code: '600000.SH', horizon: 'swing', strategy_name: '周期分类（示例）' }),
      inst({ id: 'i-paused', status: 'paused', scope: 'watch_group', horizon: 'long', strategy_name: '自选分组（示例）', paused_by: 'user' }),
    ]);
    renderAt('/strategy-instances');
    await screen.findByTestId('strategy-instances-page');

    expect(await screen.findByTestId('inst-status-i-active')).toHaveTextContent('运行中');
    expect(screen.getByTestId('inst-status-i-proposed')).toHaveTextContent('待确认');
    expect(screen.getByTestId('inst-status-i-paused')).toHaveTextContent('已暂停');
    expect(screen.getByText('单只证券 · 600000.SH')).toBeInTheDocument();
    expect(screen.getByText('自选分组')).toBeInTheDocument();
  });

  it('高风险实例带「高风险」标记（风险等级来自后端 risk_level，不由前端推断）', async () => {
    serveInstances([inst({ id: 'i-hi', risk_level: 'high' })]);
    renderAt('/strategy-instances');
    await screen.findByTestId('strategy-instances-page');
    await waitFor(() => expect(screen.getByText('高风险')).toBeInTheDocument());
  });

  it('正常返回时不出现误导性的错误框', async () => {
    serveInstances([inst({ id: 'i-x' })]);
    renderAt('/strategy-instances');
    await screen.findByTestId('strategy-instances-page');
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('③ 状态机操作转发到 §6.0A 端点', () => {
  const captureOp = () => {
    const ops: string[] = [];
    server.use(
      http.post(`${API}/strategy-instances/:id/:op`, ({ params }) => {
        ops.push(`${params.id}:${params.op}`);
        return HttpResponse.json(inst({ id: String(params.id), status: params.op === 'resume' ? 'active' : 'paused' }));
      }),
    );
    return ops;
  };

  it('运行中 → 关闭开关 = pause', async () => {
    serveInstances([inst({ id: 'i-a', status: 'active' })]);
    const ops = captureOp();
    renderAt('/strategy-instances');
    const sw = await screen.findByTestId('inst-enable-i-a');
    within(sw).getByRole('switch').click();
    await waitFor(() => expect(ops).toEqual(['i-a:pause']));
  });

  it('已暂停 → 打开开关 = resume', async () => {
    serveInstances([inst({ id: 'i-p', status: 'paused' })]);
    const ops = captureOp();
    renderAt('/strategy-instances');
    const sw = await screen.findByTestId('inst-enable-i-p');
    within(sw).getByRole('switch').click();
    await waitFor(() => expect(ops).toEqual(['i-p:resume']));
  });

  it('待确认（proposed）→ 打开开关 = confirm，不重复创建实例', async () => {
    serveInstances([inst({ id: 'i-pr', status: 'proposed', origin: 'classifier' })]);
    const ops = captureOp();
    const creates: string[] = [];
    server.use(
      http.post(`${API}/strategy-instances`, () => {
        creates.push('create');
        return HttpResponse.json({ id: 'x' }, { status: 201 });
      }),
    );
    renderAt('/strategy-instances');
    const sw = await screen.findByTestId('inst-enable-i-pr');
    within(sw).getByRole('switch').click();
    await waitFor(() => expect(ops).toEqual(['i-pr:confirm']));
    expect(creates).toEqual([]);
  });

  it('接口报错时展示错误框，不白屏', async () => {
    server.use(
      http.get(`${API}/strategy-instances`, () => HttpResponse.json(errorBody('INTERNAL_ERROR', 'boom'), { status: 500 })),
    );
    renderAt('/strategy-instances');
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});

describe('④ 空态', () => {
  it('没有实例时给出去策略库启用的引导，不报错', async () => {
    serveInstances([]);
    renderAt('/strategy-instances');
    expect(await screen.findByText(/还没有策略实例/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('⑤ 已归档实例默认收起', () => {
  it('有归档实例时出现筛选条；默认不展示归档实例', async () => {
    serveInstances([
      inst({ id: 'i-live', status: 'active' }),
      inst({ id: 'i-arch', status: 'archived', archived_at: '2026-11-01T09:00:00+08:00' }),
    ]);
    renderAt('/strategy-instances');
    expect(await screen.findByTestId('inst-status-i-live')).toBeInTheDocument();
    expect(screen.queryByTestId('inst-status-i-arch')).toBeNull();
    expect(screen.getByTestId('instances-status-filter')).toBeInTheDocument();
  });

  it('无归档实例时不显示筛选条', async () => {
    serveInstances([inst({ id: 'i-only', status: 'active' })]);
    renderAt('/strategy-instances');
    await screen.findByTestId('inst-status-i-only');
    expect(screen.queryByTestId('instances-status-filter')).toBeNull();
  });
});
