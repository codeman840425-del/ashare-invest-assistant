/** 评审 8249d6e / 7afbc06 m4：契约里出现的前端路由不落 404（Notification.target.route、/today 计划条件链接） */
import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { uid } from '../mocks/fixtures';

// 页面模块的冷加载放在等待窗口之外（评审 b23401a N8）
beforeAll(() => preloadRoutes(routes), 30_000);

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

describe('/plans/{id}', () => {
  it('计划详情页未实现前接占位页（标题“计划详情”），不是 404', async () => {
    renderAt(`/plans/${uid(7301)}`);
    expect(await screen.findByTestId('placeholder')).toBeInTheDocument();
    expect(screen.getByText('计划详情')).toBeInTheDocument();
    expect(screen.queryByTestId('not-found')).toBeNull();
  });
  it('真正不存在的路径仍是 404', async () => {
    renderAt('/no-such-page');
    expect(await screen.findByTestId('not-found')).toBeInTheDocument();
  });
});
