/** T-F03：个股档案 /stocks/:code 与市场概览 /market（MSW 示例数据；未定契约的端点标 [待契约确认]） */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { HORIZON_ASSESSMENTS } from '../mocks/fixtures';
import { safeExternalUrl } from '../lib/url';
import { ANNOUNCEMENT_DISCLAIMER } from './stock/StockTabs';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

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

/** 记录所有请求，验证只走相对路径 /api/v1（不访问外部网络） */
function trackRequests() {
  const urls: string[] = [];
  server.events.on('request:start', ({ request }) => { urls.push(request.url); });
  return urls;
}
const onlyLocalApi = (urls: string[]) => urls.every((u) => new URL(u).origin === window.location.origin && new URL(u).pathname.startsWith('/api/v1/'));

describe('个股档案 /stocks/:code', () => {
  it('行情头、基本信息、周期分类、默认分时图', async () => {
    const urls = trackRequests();
    renderAt('/stocks/600000.SH');
    const head = await screen.findByTestId('stock-head');
    expect(within(head).getByText('示例银行')).toBeInTheDocument();
    expect(within(head).getByText('主板')).toBeInTheDocument();
    expect(await screen.findByTestId('intraday')).toBeInTheDocument();
    expect(within(screen.getByTestId('profile-panel')).getByText('上交所')).toBeInTheDocument();
    const hz = screen.getByTestId('horizon-panel');
    await waitFor(() => expect(within(hz).getByTestId('hz-long')).toBeInTheDocument());
    // 周期分类只描述持有周期，不出现动作类措辞
    expect(hz.textContent).not.toMatch(/买入|卖出|加仓|减仓/);
    expect(onlyLocalApi(urls)).toBe(true);
  });

  it('切换日K / 周K', async () => {
    renderAt('/stocks/600000.SH');
    await screen.findByTestId('intraday');
    fireEvent.click(screen.getByText('日K'));
    expect(await screen.findByTestId('kline')).toBeInTheDocument();
    fireEvent.click(screen.getByText('周K'));
    expect(await screen.findByText(/周线日期取该周最后交易日/)).toBeInTheDocument();
  });

  it('非画像封顶（IT0 等）在周期分类里显示为封顶；novice 只给提示不封顶', async () => {
    const code = Object.keys(HORIZON_ASSESSMENTS).find((c) => HORIZON_ASSESSMENTS[c].caps.length > 0) ?? Object.keys(HORIZON_ASSESSMENTS)[0];
    mockLoginAs('novice_user');
    renderAt(`/stocks/${code}`);
    const hz = await screen.findByTestId('horizon-panel');
    await waitFor(() => expect(within(hz).getByTestId('hint-short')).toBeInTheDocument());
    expect(within(hz).getByTestId('hint-intraday_t')).toBeInTheDocument();
    const a = HORIZON_ASSESSMENTS[code];
    for (const h of ['intraday_t', 'short', 'swing', 'long'] as const) {
      expect(!!within(hz).queryByTestId(`cap-${h}`)).toBe(a.caps.some((c) => c.horizon === h));
    }
    // novice 的 SH0C / IT0C 只是提示，不出现在封顶里
    expect(a.caps.some((c) => c.rule_id === 'SH0C' || c.rule_id === 'IT0C')).toBe(false);
  });

  it('财务 / 资金流 / 因子页签按 ?tab= 切换', async () => {
    const router = renderAt('/stocks/600000.SH');
    expect(await screen.findByTestId('tab-financials')).toBeInTheDocument();
    expect(screen.getByText('营业收入')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: '资金流' }));
    expect(await screen.findByTestId('tab-fund-flow')).toBeInTheDocument();
    expect(router.state.location.search).toBe('?tab=fund-flow');
    expect(screen.getByText('近 5 日主力净流入')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: '因子' }));
    expect(await screen.findByTestId('tab-factors')).toBeInTheDocument();
    expect(screen.getByText(/不代表方向判断/)).toBeInTheDocument();
  });

  it('公告只给外链：新窗口、noopener noreferrer，页面不请求外部地址', async () => {
    const urls = trackRequests();
    renderAt('/stocks/600000.SH?tab=announcements');
    const tab = await screen.findByTestId('tab-announcements');
    expect(within(tab).getByText(ANNOUNCEMENT_DISCLAIMER)).toBeInTheDocument();
    await waitFor(() => expect(tab.querySelectorAll('a.ext-link').length).toBeGreaterThan(0));
    for (const a of Array.from(tab.querySelectorAll<HTMLAnchorElement>('a.ext-link'))) {
      expect(a.target).toBe('_blank');
      expect(a.rel).toContain('noopener');
      expect(a.rel).toContain('noreferrer');
      expect(a.href).toMatch(/^https?:\/\//);
    }
    // v0.2.7：url 为 null 而 url_host 有值 = 原始链接不在白名单，只显示主机名、不给可点链接
    expect(within(tab).getByText('链接不在白名单（example.com）')).toBeInTheDocument();
    expect(onlyLocalApi(urls)).toBe(true);
  });

  it('外链只放行 http(s)', () => {
    expect(safeExternalUrl('javascript:alert(1)')).toBeNull();
    expect(safeExternalUrl('data:text/html,x')).toBeNull();
    expect(safeExternalUrl('not a url')).toBeNull();
    expect(safeExternalUrl('https://example.com/a.pdf')).toBe('https://example.com/a.pdf');
  });

  it('停牌证券显示停牌标记并默认日K', async () => {
    renderAt('/stocks/601001.SH');
    expect(await screen.findByTestId('suspended-tag')).toBeInTheDocument();
    expect(await screen.findByTestId('kline')).toBeInTheDocument();
  });

  it('代码格式错误 / 不存在', async () => {
    renderAt('/stocks/abc');
    expect(await screen.findByText('证券代码格式不正确')).toBeInTheDocument();
  });
  it('不存在的证券 → 404 提示', async () => {
    renderAt('/stocks/999999.SH');
    expect(await screen.findByText('未找到该证券')).toBeInTheDocument();
  });
});

describe('市场概览 /market', () => {
  it('指数卡、涨跌分布、大盘状态、板块资金', async () => {
    const urls = trackRequests();
    renderAt('/market');
    await screen.findByTestId('breadth-panel');
    const strip = screen.getByRole('list', { name: '主要指数' });
    expect(within(strip).getAllByRole('listitem')).toHaveLength(6);
    expect(within(strip).getByText('上证指数（示例）')).toBeInTheDocument();
    expect(within(screen.getByTestId('breadth-panel')).getByText('涨停')).toBeInTheDocument();
    expect(within(screen.getByTestId('regime-panel')).getByText(/参考仓位区间/)).toBeInTheDocument();
    const sector = screen.getByTestId('sector-panel');
    await waitFor(() => expect(within(sector).getByText('银行（示例）')).toBeInTheDocument());
    fireEvent.click(within(sector).getByText('概念'));
    await waitFor(() => expect(within(sector).getByText('人工智能（示例）')).toBeInTheDocument());
    expect(await screen.findByTestId('intraday')).toBeInTheDocument();
    expect(onlyLocalApi(urls)).toBe(true);
  });

  it('点击指数卡切换图表', async () => {
    renderAt('/market');
    const strip = await screen.findByRole('list', { name: '主要指数' });
    const card = within(strip).getByText('深证成指（示例）').closest('button')!;
    fireEvent.click(card);
    expect(card.getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText('399001.SZ')).toBeInTheDocument();
  });

  it('领涨股链接到个股档案', async () => {
    const router = renderAt('/market');
    const sector = await screen.findByTestId('sector-panel');
    await waitFor(() => expect(sector.querySelector('a[href^="/stocks/"]')).not.toBeNull());
    fireEvent.click(sector.querySelector('a[href^="/stocks/"]')!);
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/stocks\/\d{6}\.(SH|SZ|BJ)$/));
  });
});

describe('顶栏证券搜索', () => {
  it('输入简称 → 选中 → 跳到个股档案', async () => {
    const router = renderAt('/terminal');
    await screen.findByTestId('terminal');
    const input = screen.getByLabelText('证券搜索');
    fireEvent.change(input, { target: { value: '示例银行' } });
    const opt = await screen.findByText('600000.SH', { selector: '.search-opt .mono' }, { timeout: 3000 });
    fireEvent.click(opt);
    await waitFor(() => expect(router.state.location.pathname).toBe('/stocks/600000.SH'));
  });
  it('回车完整代码直接跳转', async () => {
    const router = renderAt('/terminal');
    await screen.findByTestId('terminal');
    const input = screen.getByLabelText('证券搜索');
    fireEvent.change(input, { target: { value: '000001.sz' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', keyCode: 13 });
    await waitFor(() => expect(router.state.location.pathname).toBe('/stocks/000001.SZ'));
  });
});
