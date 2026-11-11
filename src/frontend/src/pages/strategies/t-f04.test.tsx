/**
 * F-04：策略知识卡前端接入（契约 §7.4 /strategy-cards）。
 *
 * 覆盖：① 列表真实渲染、不再是占位页；② 筛选项转发为查询参数；③ 详情展示卡片内容；
 * ④ 门禁缺口原样展示、前端不做可用性判断；⑤ 历史版本切换；⑥ 外部验证信息缺失时的空态。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { routes } from '../../app/routes';
import { server } from '../../mocks/server';
import { mockLoginAs } from '../../mocks/session';
import { preloadRoutes } from '../../test/preloadRoutes';

vi.mock('../../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

beforeAll(() => preloadRoutes(routes), 60_000);
beforeEach(() => mockLoginAs('demo_user'));
afterEach(() => server.resetHandlers());

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

const CARD1 = '00000001-0000-4000-8000-000000000001';
const CARD2 = '00000002-0000-4000-8000-000000000002';

describe('① 列表页', () => {
  it('/strategy-cards 不再是占位页，展示三张合成卡片与完整度标签', async () => {
    renderAt('/strategy-cards');
    expect(await screen.findByTestId('strategy-cards-page')).toBeInTheDocument();
    expect(screen.queryByTestId('route-pending')).toBeNull();

    expect(await screen.findByTestId('card-link-sw_synthetic_trend')).toHaveTextContent('合成趋势跟随卡');
    expect(screen.getByTestId('card-completeness-sw_synthetic_trend')).toHaveTextContent('已晋级');
    expect(screen.getByTestId('card-completeness-st_synthetic_momo')).toHaveTextContent('可运行候选');
    expect(screen.getByTestId('card-completeness-lt_synthetic_value')).toHaveTextContent('草稿');
  });

  it('卡片名可点进详情', async () => {
    const router = renderAt('/strategy-cards');
    const link = await screen.findByTestId('card-link-sw_synthetic_trend');
    link.click();
    await waitFor(() => expect(router.state.location.pathname).toBe(`/strategy-cards/${CARD1}`));
  });
});

describe('② 筛选', () => {
  it('按完整度筛选只显示对应卡片', async () => {
    renderAt('/strategy-cards');
    await screen.findByTestId('card-link-sw_synthetic_trend');
    const combo = screen.getByTestId('filter-completeness');
    fireEvent.mouseDown(combo.querySelector('.ant-select') ?? combo);
    const opt = await screen.findByText('草稿', { selector: '.ant-select-item-option-content, [title="草稿"]' });
    fireEvent.click(opt);
    await waitFor(() => expect(screen.queryByTestId('card-link-sw_synthetic_trend')).toBeNull());
    expect(await screen.findByTestId('card-link-lt_synthetic_value')).toBeInTheDocument();
  });
});

describe('③ 详情页内容', () => {
  it('展示假设、维度、四段规则与数据需求', async () => {
    renderAt(`/strategy-cards/${CARD1}`);
    expect(await screen.findByTestId('strategy-card-detail')).toBeInTheDocument();

    expect(screen.getByTestId('hypothesis')).toHaveTextContent('趋势延续时顺势持有');
    expect(screen.getByTestId('hypothesis')).toHaveTextContent('连续两个周期趋势指标失效即证伪');
    expect(screen.getByTestId('dimensions')).toHaveTextContent('technical · 核心');

    // 四段规则都在（入场/反向/失效/离场），量化与待量化状态如实展示
    expect(screen.getByText('入场条件')).toBeInTheDocument();
    expect(screen.getByText('反向证据')).toBeInTheDocument();
    expect(screen.getByText('失效条件')).toBeInTheDocument();
    expect(screen.getByText('离场条件')).toBeInTheDocument();
    expect(screen.getAllByText('已量化').length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText('待量化').length).toBeGreaterThanOrEqual(1);

    expect(screen.getByText('close')).toBeInTheDocument();
    expect(screen.getByText('volume_ratio')).toBeInTheDocument();
  });

  it('详情 404 → 错误框，不白屏', async () => {
    renderAt('/strategy-cards/00000009-0000-4000-8000-000000000009');
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});

describe('④ 门禁缺口原样展示', () => {
  it('gates_missing 逐条展示，文案不把它说成"不可用"或"可用"', async () => {
    renderAt(`/strategy-cards/${CARD1}`);
    const alert = await screen.findByTestId('gates-missing');
    expect(alert).toHaveTextContent('G1:promotion_review_pending');
    expect(alert).toHaveTextContent('G7:promotion_review_pending');
    expect(alert).toHaveTextContent('不代表可用性判断');
    expect(alert.textContent).not.toContain('可以启用');
  });

  it('高风险的卡片带高风险标记（risk_level 来自后端）', async () => {
    renderAt(`/strategy-cards/${CARD2}`);
    await screen.findByTestId('strategy-card-detail');
    expect(screen.getByText('高风险')).toBeInTheDocument();
  });
});

describe('⑤ 历史版本', () => {
  it('切换版本后展示历史版本提示', async () => {
    renderAt(`/strategy-cards/${CARD1}`);
    await screen.findByTestId('strategy-card-detail');
    const combo = screen.getByTestId('card-version-select');
    fireEvent.mouseDown(combo.querySelector('.ant-select') ?? combo);
    const v1 = await screen.findByText('v1', { selector: '.ant-select-item-option-content, [title="v1"]' });
    fireEvent.click(v1);
    expect(await screen.findByTestId('viewing-history')).toBeInTheDocument();
  });
});

describe('⑥ 外部验证信息', () => {
  it('研究员未提供时显示空态，不显示假的验证结论', async () => {
    renderAt(`/strategy-cards/${CARD1}`);
    expect(await screen.findByTestId('no-validation-summary')).toHaveTextContent('研究员未提供外部验证信息');
    expect(screen.queryByTestId('validation-summary')).toBeNull();
  });
});
