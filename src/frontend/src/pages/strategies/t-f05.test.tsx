/**
 * F-05：策略详情页（契约 §7.4 /strategies/{id}/versions/{vid}；通知路由 /strategies/{id}?version={vid}）。
 *
 * 覆盖：① 缺 version 参数时给出指引而非白屏；② 版本配置渲染（参数、规则、周期）；
 * ③ 内部检验按方案 A 只显示是否做过/方法/日期，不含数值或通过与否；④ 全站跟踪统计；⑤ 404 错误框。
 */
import { render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { routes } from '../../app/routes';
import { server } from '../../mocks/server';
import { mockLoginAs } from '../../mocks/session';
import { STRATEGY_TEMPLATES } from '../../mocks/strategyHandlers';
import { preloadRoutes } from '../../test/preloadRoutes';

vi.mock('../../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

beforeAll(() => preloadRoutes(routes), 60_000);
beforeEach(() => mockLoginAs('demo_user'));
afterEach(() => server.resetHandlers());

/** demo_trend 模板的 id / 版本 id（mock fixture 里固定生成） */
const tpl = STRATEGY_TEMPLATES.find((t) => t.key === 'demo_trend')!;
const SID = tpl.id;
const VID = tpl.current_version.id;

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

describe('① 缺版本参数', () => {
  it('未带 version 时给出「从策略库选择版本」的指引，不白屏', async () => {
    renderAt(`/strategies/${SID}`);
    expect(await screen.findByTestId('need-version')).toHaveTextContent('请从策略库选择具体版本');
    // 指引本身是 info 提示，不能是加载失败/错误框
    expect(screen.queryByText(/加载失败/)).toBeNull();
    expect(screen.queryByTestId('strategy-detail-page')?.textContent).not.toContain('参数定义');
  });
});

describe('② 版本配置展示', () => {
  it('渲染周期、参数定义与规则', async () => {
    renderAt(`/strategies/${SID}?version=${VID}`);
    expect(await screen.findByTestId('strategy-detail-page')).toBeInTheDocument();
    expect(screen.queryByTestId('route-pending')).toBeNull();

    const meta = screen.getByTestId('version-meta');
    expect(meta).toHaveTextContent('波段');      // HORIZON.swing
    expect(meta).toHaveTextContent('rule_template');

    const params = screen.getByTestId('params-schema');
    expect(params).toHaveTextContent('ma_fast');
    expect(params).toHaveTextContent('快线周期（合成示例）');
    expect(params).toHaveTextContent('5 ~ 60');

    expect(screen.getByText('close > ma(close, ma_fast)')).toBeInTheDocument();
    expect(screen.getByText('entry')).toBeInTheDocument();
  });

  it('止损与时间止损如实展示', async () => {
    renderAt(`/strategies/${SID}?version=${VID}`);
    const stops = await screen.findByTestId('stops');
    expect(stops).toHaveTextContent('entry - 2 * atr(14)');
    expect(stops).toHaveTextContent('10 个交易日');
    expect(stops).toHaveTextContent('未设置'); // take_profit 为 null
  });
});

describe('③ 内部检验（方案 A）', () => {
  it('只显示是否做过、方法类型与日期，不出现数值或“通过/失败”判定', async () => {
    renderAt(`/strategies/${SID}?version=${VID}`);
    const box = await screen.findByTestId('internal-check');
    expect(box).toHaveTextContent('做过');
    expect(box).toHaveTextContent('factor_ic');
    expect(box).toHaveTextContent('2026-10-28');
    // 不得出现通过与否的判定性文案
    expect(box.textContent).not.toMatch(/通过|失败|达标|不达标/);
  });
});

describe('④ 全站跟踪统计', () => {
  it('展示各周期统计并标注全站汇总', async () => {
    renderAt(`/strategies/${SID}?version=${VID}`);
    const table = await screen.findByTestId('tracking');
    expect(screen.getByText(/全站汇总/)).toBeInTheDocument();
    expect(table).toHaveTextContent('1 日');
    expect(table).toHaveTextContent('5 日');
    expect(table).toHaveTextContent('20 日');
  });
});

describe('⑤ 错误处理', () => {
  it('版本不存在 → 404 错误框，不白屏', async () => {
    renderAt(`/strategies/${SID}?version=00000000-0000-4000-8000-000000000000`);
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });

  it('不带 version 的同路径不再落到占位页（占位页已移除）', async () => {
    const router = renderAt(`/strategies/${SID}`);
    await screen.findByTestId('need-version');
    expect(router.state.location.pathname).toBe(`/strategies/${SID}`);
    await waitFor(() => expect(screen.queryByText('策略详情')).toBeNull());
  });
});
