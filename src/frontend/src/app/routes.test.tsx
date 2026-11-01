import { render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from './AppProviders';
import { makeQueryClient } from './queryClient';
import { routes } from './routes';
import { DISCLAIMER_TEXT } from '../components/RiskDisclosure';
import { REPORT_DATE, SUGGESTIONS } from '../mocks/fixtures';

// jsdom 没有 canvas：图表组件换成占位（图表本身在 Playwright 截图里验证）
vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

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

describe('路由与页面（MSW 示例数据）', () => {
  it('/ 重定向到 /terminal；外壳含免责提示、示例数据横幅', async () => {
    const router = renderAt('/');
    await waitFor(() => expect(router.state.location.pathname).toBe('/terminal'));
    expect(screen.getByTestId('risk-disclosure')).toHaveTextContent(DISCLAIMER_TEXT);
    expect(screen.getByTestId('sample-banner')).toHaveTextContent('示例数据');
    expect(await screen.findByTestId('terminal')).toBeInTheDocument();
  });

  it('终端：三栏 + 底部面板、分隔条、恢复默认布局按钮、候选信号卡共识条', async () => {
    renderAt('/terminal');
    expect(await screen.findByTestId('terminal')).toBeInTheDocument();
    for (const id of ['sep-left', 'sep-right', 'sep-bottom', 'reset-layout', 'watch-table', 'bottom-panel']) {
      expect(screen.getByTestId(id)).toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: /恢复默认布局/ })).toBeInTheDocument();
    expect(await screen.findByTestId('quote-head')).toBeInTheDocument();
    expect(await screen.findByTestId('consensus-bar')).toBeInTheDocument();
  });

  it('候选信号卡详情：分歧提示、并列策略卡、不可执行原因与解除条件', async () => {
    const sg = SUGGESTIONS.find((s) => s.consensus.status === 'divergent')!;
    renderAt(`/suggestions/${sg.id}`);
    const page = await screen.findByTestId('suggestion-detail');
    expect(within(page).getByText(/存在分歧，不合并为单一结论/)).toBeInTheDocument();
    expect(within(page).getAllByTestId('strategy-card')).toHaveLength(sg.strategies.length);
    if (sg.executability.reason_ids.length) expect((await within(page).findAllByText(/解除条件/)).length).toBeGreaterThan(0);
    // v0.2.2 周期分类：四个周期都有分数，理由按“支持 / 不支持”分组
    const hz = await within(page).findByTestId('horizon-panel');
    expect((await within(hz).findAllByText('支持')).length).toBeGreaterThanOrEqual(4);
    expect(within(hz).getAllByText('不支持').length).toBeGreaterThanOrEqual(4);
  });

  it('/reports 旧路径重定向到 /daily-reports/:date，并渲染日报', async () => {
    const router = renderAt('/reports');
    await waitFor(() => expect(router.state.location.pathname).toBe(`/daily-reports/${REPORT_DATE}`));
    const page = await screen.findByTestId('daily-report');
    expect(within(page).getByText('盘后日报')).toBeInTheDocument();
  });

  it('未实现页面为占位页，未知路径 404', async () => {
    renderAt('/plans');
    expect(await screen.findByTestId('placeholder')).toBeInTheDocument();
  });
  it('未知路径', async () => {
    renderAt('/no-such-page');
    expect(await screen.findByTestId('not-found')).toBeInTheDocument();
  });
});
